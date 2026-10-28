"""Export a filtered DocType, and its child rows, as CSV and Excel.

Frappe list calls are one page. The file walks limit_start until the filtered
count is covered, then flattens a child table (Purchase Invoice items, and the
same shape for any parent) onto those rows. The chat opens the private file.
"""

from __future__ import annotations

import csv
import io

import frappe
from erpnext_ai_assistant.services.arabic import normalize_arabic

_PAGE = 200
_CAP = 2000
_CHILD_FIELDS = ("item_code", "item_name", "description", "qty", "uom", "rate", "amount")
_SKIP_CHILDREN = {"links", "comments", "communications"}


def sheet_kinds(text: str | None) -> set[str]:
	"""Which files to build. A bare export asks for both CSV and Excel."""
	norm = normalize_arabic(text)
	if not norm:
		return set()
	kinds = set()
	if "csv" in norm:
		kinds.add("csv")
	if any(token in norm for token in ("اكسل", "excel", "xlsx")):
		kinds.add("xlsx")
	if kinds:
		return kinds
	if any(token in norm for token in ("تصدير", "اصدر", "صدر ملف", "download", "spreadsheet", "export")):
		return {"csv", "xlsx"}
	if "ملف" in norm and any(token in norm for token in ("صدر", "تصدير", "حمل", "جاهز")):
		return {"csv", "xlsx"}
	return set()


def wants_children(text: str | None) -> bool:
	norm = normalize_arabic(text)
	if not norm:
		return False
	return any(token in norm for token in ("بنود", "بند", "items", "line item", "child table", "الابناء", "الابنا"))


def build_export(doctype: str, text: str | None, lang: str) -> dict:
	"""Write the filtered register. Returns files, counts, and a short note."""
	from erpnext_ai_assistant.services.targeting import _query_filters, _summary_plan, _tr, _translations

	meta = frappe.get_meta(doctype)
	plan = _summary_plan(meta)
	filters, _note, problem, empty = _query_filters(doctype, plan, text, lang)
	if problem or empty:
		return {"files": [], "note": problem or "", "parents": 0, "children": 0}
	parent_fields = _parent_fields(meta, plan)
	child = _child_table(meta, text)
	child_fields = _child_fields(child) if child else []
	parents, truncated = _collect_parents(doctype, filters, parent_fields, plan)
	by_parent, child_total = _collect_children(doctype, child, child_fields, [row.get("name") for row in parents])
	translations = _translations(lang)
	header, matrix = _matrix(meta, parent_fields, child, child_fields, parents, by_parent, lang, translations, _tr)
	kinds = sheet_kinds(text)
	files = []
	stem = frappe.scrub(doctype)
	if "csv" in kinds:
		files.append(_save_csv(f"{stem}.csv", header, matrix, lang))
	if "xlsx" in kinds:
		files.append(_save_xlsx(f"{stem}.xlsx", header, matrix, lang))
	note = _note_text(lang, len(parents), child_total, child, truncated, bool(files))
	preview = _child_preview(parents, by_parent, child_fields, lang) if child and wants_children(text) else ""
	if preview:
		note = preview + "\n" + note
	return {"files": [item for item in files if item], "note": note, "parents": len(parents), "children": child_total}


def _parent_fields(meta, plan: dict) -> list[str]:
	fields = []
	for name in ("name", plan.get("date"), plan.get("group"), plan.get("group_name"), plan.get("select"), plan.get("amount"), plan.get("title")):
		if name and name not in fields and (name == "name" or meta.has_field(name)):
			fields.append(name)
	return fields or ["name"]


def _child_table(meta, text: str | None):
	tables = [
		df
		for df in meta.fields
		if df.fieldtype == "Table" and df.options and df.fieldname and df.fieldname not in _SKIP_CHILDREN
	]
	if not tables:
		return None
	for df in tables:
		if df.fieldname == "items":
			return df
	if wants_children(text):
		return tables[0]
	return None


def _child_fields(df) -> list[str]:
	child = frappe.get_meta(df.options)
	picked = []
	for name in _CHILD_FIELDS:
		if child.has_field(name):
			picked.append(name)
	if not picked:
		for cdf in child.fields:
			if cdf.in_list_view and cdf.fieldname and cdf.fieldtype not in ("Section Break", "Column Break", "Tab Break"):
				picked.append(cdf.fieldname)
			if len(picked) >= 6:
				break
	return picked[:6]


def _collect_parents(doctype: str, filters: list, fields: list[str], plan: dict):
	order = f"{plan['date']} asc, name asc" if plan.get("date") else "name asc"
	rows = []
	start = 0
	truncated = False
	while start < _CAP:
		page = frappe.get_list(
			doctype,
			filters=filters,
			fields=fields,
			order_by=order,
			limit_start=start,
			limit_page_length=_PAGE,
		)
		rows.extend(page)
		if len(page) < _PAGE:
			break
		start += _PAGE
		if start >= _CAP:
			truncated = True
			break
	return rows[:_CAP], truncated


def _collect_children(doctype: str, child, fields: list[str], names: list[str]):
	if not child or not names or not fields:
		return {}, 0
	found = {}
	total = 0
	wanted = ["parent", "idx", *fields]
	for offset in range(0, len(names), 200):
		chunk = [name for name in names[offset : offset + 200] if name]
		if not chunk:
			continue
		# Child columns such as parent and item_code are dropped when the child
		# table is queried with its own permissions. These rows belong to parents
		# the user was already allowed to list.
		rows = frappe.get_all(
			child.options,
			filters={"parent": ["in", chunk], "parenttype": doctype},
			fields=wanted,
			order_by="parent asc, idx asc",
			limit_page_length=0,
		)
		for row in rows:
			found.setdefault(row.get("parent"), []).append(row)
			total += 1
	return found, total


def _matrix(meta, parent_fields, child, child_fields, parents, by_parent, lang, translations, translate):
	header = [_caption(meta, field, lang, translations, translate) for field in parent_fields]
	if child:
		child_meta = frappe.get_meta(child.options)
		header.append("idx")
		header.extend(_caption(child_meta, field, lang, translations, translate) for field in child_fields)
	matrix = []
	for parent in parents:
		base = [_cell(parent.get(field)) for field in parent_fields]
		kids = by_parent.get(parent.get("name")) or [None]
		for kid in kids:
			extra = []
			if child:
				extra.append("" if not kid else _cell(kid.get("idx")))
				extra.extend("" if not kid else _cell(kid.get(field)) for field in child_fields)
			matrix.append(base + extra)
	return header, matrix


def _caption(meta, field: str, lang: str, translations: dict, translate) -> str:
	if field == "name":
		return "ID" if lang != "ar" else "المعرف"
	df = meta.get_field(field)
	label = df.label if df and df.label else field
	return translate(label, lang, translations) or field


def _cell(value) -> str:
	if value in (None, ""):
		return ""
	text = str(value)
	if "<" in text and ">" in text:
		from frappe.utils import strip_html

		text = strip_html(text)
	return " ".join(text.split())


def _save_csv(filename: str, header: list[str], matrix: list[list[str]], lang: str) -> dict | None:
	buffer = io.StringIO()
	writer = csv.writer(buffer)
	writer.writerow(header)
	writer.writerows(matrix)
	return _store(filename, buffer.getvalue().encode("utf-8-sig"), "CSV" if lang != "ar" else "فتح CSV")


def _save_xlsx(filename: str, header: list[str], matrix: list[list[str]], lang: str) -> dict | None:
	import openpyxl

	book = openpyxl.Workbook()
	sheet = book.active
	sheet.title = "Export"
	sheet.append(header)
	for row in matrix:
		sheet.append(row)
	buffer = io.BytesIO()
	book.save(buffer)
	return _store(filename, buffer.getvalue(), "Excel" if lang != "ar" else "فتح Excel")


def _store(filename: str, content: bytes, label: str) -> dict | None:
	from frappe.utils.file_manager import save_file

	# site_config sometimes stores this limit as text, and Frappe then compares int > str.
	size = frappe.conf.get("max_file_size")
	if isinstance(size, str) and size.isdigit():
		frappe.conf.max_file_size = int(size)
	doc = save_file(filename, content, None, None, is_private=1)
	url = doc.file_url or ""
	if not url.startswith("/private/files/"):
		return None
	return {"label": label, "url": url}


def _child_preview(parents, by_parent, child_fields, lang: str) -> str:
	lines = []
	for parent in parents:
		for kid in by_parent.get(parent.get("name")) or []:
			bits = [str(parent.get("name") or "")]
			for field in child_fields:
				value = _cell(kid.get(field))
				if value:
					bits.append(value)
			lines.append("- " + " · ".join(bits))
			if len(lines) >= 8:
				break
		if len(lines) >= 8:
			break
	if not lines:
		return ""
	title = "أول البنود:" if lang == "ar" else "First child rows:"
	return title + "\n" + "\n".join(lines)


def _note_text(lang: str, parents: int, children: int, child, truncated: bool, has_file: bool) -> str:
	if not has_file:
		return ""
	if lang == "ar":
		text = f"الملف جاهز للفتح: {parents} سجلاً"
		if child and children:
			text += f" و {children} بنداً من {child.options}"
		text += "."
		if truncated:
			text += " هذه أول 2000 سجل."
		return text
	text = f"The file is ready to open: {parents} records"
	if child and children:
		text += f" and {children} {child.options} rows"
	text += "."
	if truncated:
		text += " This is the first 2000 records."
	return text
