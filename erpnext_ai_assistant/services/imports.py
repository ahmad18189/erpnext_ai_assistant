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
	rows = list(csv.reader(io.StringIO(text)))
	rows = [row for row in rows if any((cell or "").strip() for cell in row)]
	if not rows:
		return [], []
	header = [str(cell or "").strip() for cell in rows[0]]
	body = [[str(cell or "").strip() for cell in row] for row in rows[1:21]]
	return header, body


def _read_xlsx(content: bytes) -> tuple[list[str], list[list[str]]]:
	import openpyxl

	book = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
	sheet = book.active
	rows = []
	for i, row in enumerate(sheet.iter_rows(values_only=True)):
		if i > 21:
			break
		values = ["" if cell is None else str(cell).strip() for cell in row]
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
