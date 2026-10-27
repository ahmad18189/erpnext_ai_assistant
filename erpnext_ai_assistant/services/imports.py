"""Match an uploaded table to Frappe Data Import templates.

Frappe import does not guess a DocType. A template is the target DocType's
importable columns (fieldname and label, including child-table columns). This
module scores the file header against those templates and reports what matches,
what is required but missing, and which file columns have no field. It does not
import rows.
"""

from __future__ import annotations

import csv
import io
import json
import re

import frappe
from erpnext_ai_assistant.services.schema import DENIED_DOCTYPES, LAYOUT

MAX_CANDIDATES = 40
SAMPLE_ROWS = 5


def _norm(value: str) -> str:
	text = (value or "").strip().lower()
	text = text.replace(" ", "_").replace("-", "_")
	return re.sub(r"[^a-z0-9_\u0600-\u06ff]", "", text)


def read_table(content: bytes, filename: str) -> tuple[list[str], list[list[str]]]:
	name = (filename or "").lower()
	if name.endswith(".xlsx") or name.endswith(".xlsm"):
		return _read_xlsx(content)
	text = content.decode("utf-8-sig", errors="replace")
	header: list[str] = []
	body: list[list[str]] = []
	for row in csv.reader(io.StringIO(text)):
		if not any((cell or "").strip() for cell in row):
			continue
		cells = [str(cell or "").strip()[:200] for cell in row[:80]]
		if not header:
			header = cells
			continue
		body.append(cells)
		if len(body) >= 20:
			break
	return header, body


def _read_xlsx(content: bytes) -> tuple[list[str], list[list[str]]]:
	import openpyxl

	book = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
	sheet = book.active
	rows = []
	for i, row in enumerate(sheet.iter_rows(values_only=True)):
		if i > 21:
			break
		values = ["" if cell is None else str(cell).strip()[:200] for cell in row[:80]]
		if any(values):
			rows.append(values)
	book.close()
	if not rows:
		return [], []
	width = max(len(row) for row in rows)
	rows = [row + [""] * (width - len(row)) for row in rows]
	return rows[0], rows[1:]


def _import_columns(doctype: str) -> list[dict]:
	meta = frappe.get_meta(doctype)
	columns = []
	for df in meta.fields:
		if not df.fieldname or df.fieldtype in LAYOUT or df.hidden:
			continue
		if df.fieldtype == "Table" and df.options:
			child = frappe.get_meta(df.options)
			for cdf in child.fields:
				if not cdf.fieldname or cdf.fieldtype in LAYOUT or cdf.hidden:
					continue
				columns.append(
					{
						"fieldname": cdf.fieldname,
						"label": cdf.label or cdf.fieldname,
						"reqd": int(cdf.reqd or 0),
						"parent_field": df.fieldname,
						"child_doctype": df.options,
					}
				)
			continue
		if df.read_only and df.fieldname != "name":
			continue
		columns.append(
			{
				"fieldname": df.fieldname,
				"label": df.label or df.fieldname,
				"reqd": int(df.reqd or 0),
				"parent_field": None,
				"child_doctype": None,
			}
		)
	return columns


def _template_index() -> list[dict]:
	key = f"erp_ai_import_templates:{frappe.session.user}"
	cached = frappe.cache().get_value(key)
	if cached:
		return cached
	names = frappe.get_all("DocType", filters={"istable": 0, "issingle": 0}, pluck="name")
	index = []
	for name in names:
		if name in DENIED_DOCTYPES or name.startswith("ERP AI "):
			continue
		if not frappe.has_permission(name, "read"):
			continue
		try:
			columns = _import_columns(name)
		except Exception:
			continue
		if not columns:
			continue
		index.append({"doctype": name, "columns": columns})
	frappe.cache().set_value(key, index, expires_in_sec=600)
	return index


def match_templates(header: list[str]) -> list[dict]:
	"""Rank DocType import templates by how many file columns they explain."""
	headers = [h for h in header if _norm(h)]
	if not headers:
		return []
	ranked = []
	for entry in _template_index():
		lookup = {}
		for column in entry["columns"]:
			lookup.setdefault(_norm(column["fieldname"]), column)
			lookup.setdefault(_norm(column["label"]), column)
		matched = []
		unmatched = []
		used = set()
		for title in headers:
			column = lookup.get(_norm(title))
			if column and column["fieldname"] not in used:
				matched.append({"file_column": title, "fieldname": column["fieldname"], "label": column["label"]})
				used.add(column["fieldname"])
			else:
				unmatched.append(title)
		if not matched:
			continue
		missing = [
			column
			for column in entry["columns"]
			if column["reqd"] and column["fieldname"] not in used and column["fieldname"] != "name"
		]
		score = len(matched) / max(len(headers), 1)
		if missing:
			score -= 0.05 * min(len(missing), 5)
		ranked.append(
			{
				"doctype": entry["doctype"],
				"score": round(score, 3),
				"matched": matched,
				"unmatched_columns": unmatched,
				"missing_required": [
					{"fieldname": column["fieldname"], "label": column["label"]} for column in missing[:12]
				],
			}
		)
	ranked.sort(key=lambda item: (-item["score"], item["doctype"]))
	return ranked[:3]


def blank_template_csv(doctype: str) -> str:
	"""One header row, the same columns Frappe would offer for a blank import."""
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(f"No read permission for {doctype}", frappe.PermissionError)
	columns = _import_columns(doctype)
	buffer = io.StringIO()
	writer = csv.writer(buffer)
	writer.writerow([column["fieldname"] for column in columns])
	return buffer.getvalue()


def review_table(header: list[str], sample: list[list[str]]) -> dict:
	matches = match_templates(header)
	return {
		"header": header,
		"sample_rows": sample[:SAMPLE_ROWS],
		"row_count_in_sample": len(sample),
		"templates": matches,
		"note": "Review only. Rows are not imported until you create a Data Import and start it.",
	}


INSERT_NEW = "Insert New Records"
UPDATE_EXISTING = "Update Existing Records"


def owned_import_file(file_url: str):
	"""Private file owned by the session user. Rejects Google Sheets and filesystem paths."""
	url = (file_url or "").strip()
	if (
		not url.startswith("/private/files/")
		or ".." in url
		or "docs.google.com" in url
		or "://" in url
	):
		frappe.throw("Import file must be a private file on this site", frappe.PermissionError)
	file_doc = frappe.get_doc("File", {"file_url": url})
	if file_doc.owner != frappe.session.user or not int(file_doc.is_private or 0):
		frappe.throw("Not your private file", frappe.PermissionError)
	return file_doc


def import_block_reason(doctype: str) -> str:
	"""Empty when this user may import the DocType. Otherwise a short reason."""
	if not doctype or doctype in DENIED_DOCTYPES or doctype.startswith("ERP AI "):
		return "blocked"
	from frappe.core.doctype.data_import.data_import import BLOCKED_DOCTYPES

	if doctype in BLOCKED_DOCTYPES or not frappe.db.exists("DocType", doctype):
		return "blocked"
	meta = frappe.get_meta(doctype)
	if meta.istable or meta.issingle or not int(meta.allow_import or 0):
		return "blocked"
	if not frappe.has_permission(doctype, "import") or not frappe.has_permission("Data Import", "create"):
		return "permission"
	return ""


def read_full_table(content: bytes, filename: str) -> tuple[list[str], list[list[str]]]:
	"""Every data row, capped at 5000. The 20-row sample is only for the first review."""
	name = (filename or "").lower()
	if name.endswith(".xlsx") or name.endswith(".xlsm"):
		return _read_xlsx_all(content)
	text = content.decode("utf-8-sig", errors="replace")
	header: list[str] = []
	body: list[list[str]] = []
	for row in csv.reader(io.StringIO(text)):
		cells = [str(cell or "").strip() for cell in row[:80]]
		if not any(cells):
			continue
		if not header:
			header = cells
			continue
		body.append(cells)
		if len(body) >= 5000:
			break
	return header, body


def _read_xlsx_all(content: bytes) -> tuple[list[str], list[list[str]]]:
	import openpyxl

	book = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
	sheet = book.active
	rows = []
	for i, row in enumerate(sheet.iter_rows(values_only=True)):
		if i > 5001:
			break
		values = ["" if cell is None else str(cell).strip() for cell in row[:80]]
		if any(values):
			rows.append(values)
	book.close()
	if not rows:
		return [], []
	width = max(len(row) for row in rows)
	rows = [row + [""] * (width - len(row)) for row in rows]
	return rows[0], rows[1:]


def _column_picks(header: list[str], doctype: str) -> tuple[list[int], list[str]]:
	columns = _import_columns(doctype)
	try:
		from frappe.translate import get_all_translations

		arabic = get_all_translations("ar") or {}
	except Exception:
		arabic = {}
	lookup: dict[str, str] = {}
	for column in columns:
		lookup.setdefault(_norm(column["fieldname"]), column["fieldname"])
		label = column.get("label") or ""
		if label:
			lookup.setdefault(_norm(label), column["fieldname"])
			translated = arabic.get(label) or arabic.get(f"{label}:{doctype}")
			if translated:
				lookup.setdefault(_norm(str(translated)), column["fieldname"])
	indexes: list[int] = []
	names: list[str] = []
	used: set[str] = set()
	for index, title in enumerate(header):
		fieldname = lookup.get(_norm(title))
		if not fieldname or fieldname in used:
			continue
		used.add(fieldname)
		indexes.append(index)
		names.append(fieldname)
	return indexes, names


def _csv_text(header: list[str], rows: list[list[str]]) -> str:
	buffer = io.StringIO()
	writer = csv.writer(buffer)
	writer.writerow(header)
	for row in rows:
		writer.writerow(row)
	return buffer.getvalue()


def corrected_table(header: list[str], rows: list[list[str]], doctype: str) -> tuple[str, list[list[str]]]:
	"""Rename a header only when it matches one column. Cell values stay unchanged."""
	indexes, names = _column_picks(header, doctype)
	kept = []
	for row in rows:
		picked = [row[index] if index < len(row) else "" for index in indexes]
		if any(cell.strip() for cell in picked):
			kept.append(picked)
	return _csv_text(names, kept), kept


def preview_import(doctype: str, file_url: str) -> dict:
	"""In-memory Frappe preview. Does not insert a Data Import."""
	from frappe.core.doctype.data_import.importer import INSERT, ImportFile

	book = ImportFile(doctype, file_url, import_type=INSERT)
	preview = book.get_data_for_import_preview()
	messages = []
	warning_rows: set[int] = set()
	for warning in preview.get("warnings") or []:
		if (warning.get("type") or "") == "info":
			continue
		text = str(warning.get("message") or warning.get("title") or warning.get("type") or "")
		if text:
			messages.append(text[:180])
		if warning.get("row"):
			warning_rows.add(int(warning["row"]))
		for item in warning.get("invalid_value_items") or []:
			for row in item.get("rows") or []:
				warning_rows.add(int(row))
	for column in preview.get("columns") or []:
		for item in column.get("invalid_value_items") or []:
			for row in item.get("rows") or []:
				warning_rows.add(int(row))
	return {
		"total_number_of_rows": int(preview.get("total_number_of_rows") or 0),
		"warnings": messages[:12],
		"warning_rows": sorted(warning_rows),
	}


def warning_row_csv(header: list[str], rows: list[list[str]], warning_rows: list[int]) -> str:
	"""Preview warning rows. Sheet row 1 is the header, so data row i is sheet row i+2."""
	picked = [row for index, row in enumerate(rows) if (index + 2) in set(warning_rows)]
	return _csv_text(header, picked)


def save_private_csv(filename: str, text: str) -> str:
	from frappe.utils.file_manager import save_file

	doc = save_file(filename, text.encode("utf-8"), None, None, is_private=1)
	return doc.file_url


def failed_row_csv(data_import_name: str) -> str:
	"""Sheet rows tied to failed Data Import Log entries. Not the preview warning file."""
	data_import = frappe.get_doc("Data Import", data_import_name)
	data_import.check_permission("read")
	from frappe.core.doctype.data_import.importer import ImportFile

	book = ImportFile(
		data_import.reference_doctype,
		data_import.import_file,
		import_type=data_import.import_type,
		data_import_name=data_import.name,
	)
	logs = frappe.get_all(
		"Data Import Log",
		filters={"data_import": data_import.name, "success": 0},
		fields=["row_indexes"],
	)
	numbers: set[int] = set()
	for log in logs:
		raw = log.get("row_indexes") or "[]"
		try:
			parsed = json.loads(raw) if isinstance(raw, str) else raw
		except Exception:
			parsed = []
		for number in parsed or []:
			numbers.add(int(number))
	header = [col.header_title for col in book.columns]
	rows = [row.data for row in book.data if row.row_number in numbers]
	return _csv_text(header, rows)


def import_status_message(data_import_name: str, lang: str) -> dict:
	from frappe.core.doctype.data_import.data_import import get_import_status

	data_import = frappe.get_doc("Data Import", data_import_name)
	data_import.check_permission("read")
	status = get_import_status(data_import_name)
	state = data_import.status or "Pending"
	success = int(status.get("success") or 0)
	failed = int(status.get("failed") or 0)
	warnings = (data_import.template_warnings or "").strip()
	link = f"[[open:/desk/data-import/{data_import.name}|{data_import.name}]]"
	files = []
	if lang == "ar":
		if state == "Success":
			text = f"اكتمل الاستيراد. نجح {success} صفًا.\n{link}"
		elif state in ("Partial Success", "Error", "Timed Out"):
			text = f"حالة الاستيراد: {state}. نجح {success}. فشل {failed}.\n{link}"
		elif state == "Pending" and warnings:
			text = f"توقف الاستيراد بسبب تحذيرات في الملف. راجع {data_import.name}.\n{link}"
		else:
			text = f"الاستيراد لم يكتمل بعد. الحالة: {state}.\n{link}"
	else:
		if state == "Success":
			text = f"Import finished. {success} rows succeeded.\n{link}"
		elif state in ("Partial Success", "Error", "Timed Out"):
			text = f"Import status: {state}. Succeeded {success}. Failed {failed}.\n{link}"
		elif state == "Pending" and warnings:
			text = f"Import is blocked by file warnings. Open {data_import.name}.\n{link}"
		else:
			text = f"Import has not finished. Status: {state}.\n{link}"
	if state in ("Partial Success", "Error", "Timed Out") and failed:
		try:
			csv_text = failed_row_csv(data_import.name)
			if csv_text.strip():
				url = save_private_csv(f"failed-{data_import.name}.csv", csv_text)
				files.append({"label": "صفوف الفشل" if lang == "ar" else "Failed rows", "url": url})
		except Exception:
			frappe.log_error(title="ERP AI failed-row csv")
	return {"message": text, "files": files, "status": state}


def propose_import(chat: str, file_url: str, doctype: str, import_type: str, lang: str) -> dict:
	"""Build the corrected file and a pending import card. Does not start the import."""
	reason = import_block_reason(doctype)
	if reason:
		message = (
			f"لا يمكن استيراد {doctype}."
			if lang == "ar"
			else f"Cannot import {doctype}."
		)
		return {"message": message, "files": [], "pending": None}
	file_doc = owned_import_file(file_url)
	content = file_doc.get_content() or b""
	header, rows = read_full_table(content, file_doc.file_name or "")
	corrected, kept = corrected_table(header, rows, doctype)
	corrected_url = save_private_csv(f"corrected-{frappe.scrub(doctype)}.csv", corrected)
	try:
		preview = preview_import(doctype, corrected_url)
	except Exception:
		preview = {"total_number_of_rows": len(kept), "warnings": [], "warning_rows": []}
	files = [{"label": "الملف المصحح" if lang == "ar" else "Corrected file", "url": corrected_url}]
	if preview["warning_rows"]:
		warning_csv = warning_row_csv(
			_column_picks(header, doctype)[1],
			kept,
			preview["warning_rows"],
		)
		if warning_csv.count("\n") > 0:
			warning_url = save_private_csv(f"warnings-{frappe.scrub(doctype)}.csv", warning_csv)
			files.append({"label": "صفوف التحذير" if lang == "ar" else "Warning rows", "url": warning_url})
	row_count = len(kept)
	payload = {
		"reference_doctype": doctype,
		"import_type": import_type,
		"file_url": corrected_url,
		"row_count": row_count,
	}
	from erpnext_ai_assistant.services.naming import as_title
	from erpnext_ai_assistant.services.writes import payload_hash

	if lang == "ar":
		summary = f"استيراد {row_count} صفًا إلى {doctype} ({import_type}). لن يبدأ قبل موافقتك."
	else:
		summary = f"Import {row_count} rows into {doctype} ({import_type}). Nothing starts until you approve."
	if preview["warnings"]:
		summary += "\n" + "\n".join(f"- {line}" for line in preview["warnings"][:8])
	body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
	doc = frappe.get_doc(
		{
			"doctype": "ERP AI Pending Action",
			"title": as_title("ERP AI Pending Action", f"import {doctype}"),
			"chat": chat,
			"user": frappe.session.user,
			"action_type": "import",
			"target_doctype": doctype,
			"payload_json": body,
			"payload_hash": payload_hash(payload),
			"summary": summary[:2000],
			"status": "pending",
		}
	)
	doc.insert()
	return {
		"message": summary,
		"files": files,
		"pending": {
			"pending_action": doc.name,
			"summary": summary,
			"status": "pending",
			"target_doctype": doctype,
			"action_type": "import",
		},
	}


def execute_import(payload: dict) -> dict:
	"""Insert one Data Import after the card checks, commit, then start it."""
	doctype = payload.get("reference_doctype") or ""
	import_type = payload.get("import_type") or INSERT_NEW
	file_url = payload.get("file_url") or ""
	if import_type not in (INSERT_NEW, UPDATE_EXISTING):
		frappe.throw("Import type is not allowed")
	reason = import_block_reason(doctype)
	if reason == "permission":
		frappe.throw(f"No import permission for {doctype}", frappe.PermissionError)
	if reason:
		frappe.throw(f"Importing {doctype} is not allowed")
	file_doc = owned_import_file(file_url)
	content = file_doc.get_content() or b""
	_header, rows = read_full_table(content, file_doc.file_name or "")
	if int(payload.get("row_count") or -1) != len(rows):
		frappe.throw("This approval no longer matches the file")
	from frappe.utils.scheduler import is_scheduler_inactive

	if is_scheduler_inactive() and not frappe.in_test and not frappe.conf.developer_mode:
		frappe.throw("Scheduler is inactive. Cannot import data.")
	data_import = frappe.get_doc(
		{
			"doctype": "Data Import",
			"reference_doctype": doctype,
			"import_type": import_type,
			"import_file": file_url,
			"mute_emails": 1,
			"submit_after_import": 0,
		}
	)
	data_import.insert()
	return {"data_import": data_import.name, "doctype": doctype}


def review_text(review: dict, lang: str = "en") -> str:
	lines = []
	if lang == "ar":
		lines.append("مراجعة ملف الاستيراد. لم يُستورد أي صف.")
	else:
		lines.append("Import file review. No rows were imported.")
	header = ", ".join(review.get("header") or [])
	lines.append(("الأعمدة: " if lang == "ar" else "Columns: ") + header)
	templates = review.get("templates") or []
	if not templates:
		lines.append("لا يوجد قالب DocType مطابق." if lang == "ar" else "No DocType import template matches these columns.")
		return "\n".join(lines)
	for item in templates:
		lines.append(
			f"{item['doctype']} — {int(item['score'] * 100)}% "
			+ ("تطابق" if lang == "ar" else "match")
		)
		from erpnext_ai_assistant.services.schema import _label

		mapped = ", ".join(
			f"{pair['file_column']} → {_label(pair.get('label') or pair['fieldname'], lang)}"
			for pair in item["matched"][:12]
		)
		lines.append(("يطابق: " if lang == "ar" else "Maps: ") + mapped)
		if item["missing_required"]:
			missing = ", ".join(_label(field.get("label") or field["fieldname"], lang) for field in item["missing_required"])
			lines.append(("إلزامي ناقص: " if lang == "ar" else "Required but missing: ") + missing)
		if item["unmatched_columns"]:
			extra = ", ".join(item["unmatched_columns"][:8])
			lines.append(("أعمدة بلا حقل: " if lang == "ar" else "Columns with no field: ") + extra)
	lines.append(
		"يمكن تنزيل قالب فراب فارغ لنوع المستند المقترح من زر القالب."
		if lang == "ar"
		else "Download the blank Frappe template for a suggested DocType from the template button."
	)
	return "\n".join(lines)
