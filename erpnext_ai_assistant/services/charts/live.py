"""A chart from records the session user can read. No invented numbers."""

from __future__ import annotations

import frappe
from erpnext_ai_assistant.services.arabic import normalize_arabic, strip_al
from erpnext_ai_assistant.services.charts.build import build_chart
from erpnext_ai_assistant.services.targeting import _has, match_doctype
from erpnext_ai_assistant.services.tools import registry as tools

_CHART_WORDS = ("chart", "graph", "مخطط", "رسم بياني", "بياني")


def wants_chart(message: str | None) -> bool:
	norm = normalize_arabic(message)
	raw = (message or "").lower()
	if any(_has(norm, word) for word in _CHART_WORDS):
		return True
	return "chart" in raw or "graph" in raw


def live_chart(message: str | None, lang: str) -> dict | None:
	"""Return {answer, charts} or None when this is not a chart question."""
	if not wants_chart(message):
		return None
	doctype = _chart_doctype(message)
	if not doctype:
		return None
	if not frappe.has_permission(doctype, "read"):
		text = (
			f"لا تملك صلاحية قراءة {doctype}."
			if lang == "ar"
			else f"You cannot read {doctype}."
		)
		return {"answer": text, "charts": []}
	field = _group_field(doctype, message)
	counted = tools.tool_erp_count(doctype)
	if counted.get("error"):
		return {"answer": str(counted["error"]), "charts": []}
	total = int(counted.get("total") or 0)
	if not field or total == 0:
		from erpnext_ai_assistant.services.targeting import format_count

		return {"answer": format_count(doctype, total, lang), "charts": []}
	try:
		rows = tools.tool_erp_query(doctype, fields=[field], limit=200)
	except Exception as exc:
		return {"answer": str(exc), "charts": []}
	if isinstance(rows, dict) and rows.get("error"):
		return {"answer": str(rows["error"]), "charts": []}
	groups: dict[str, int] = {}
	for row in rows or []:
		label = row.get(field) or ("غير معيّن" if lang == "ar" else "Unassigned")
		groups[str(label)] = groups.get(str(label), 0) + 1
	from erpnext_ai_assistant.services.targeting import _tr

	df = frappe.get_meta(doctype).get_field(field)
	field_label = _tr(df.label if df else field, lang) or field
	doctype_label = _tr(doctype, lang) or doctype
	title = f"{doctype_label} by {field_label}" if lang != "ar" else f"{doctype_label} حسب {field_label}"
	chart = build_chart("pie" if len(groups) <= 6 else "bar", title, list(groups), [float(v) for v in groups.values()])
	shown = sum(groups.values())
	bits = ", ".join(f"{name}: {count}" for name, count in list(groups.items())[:8])
	if lang == "ar":
		answer = f"يمكنك رؤية {total} سجلًا من {doctype_label}. المخطط يجمّع {shown} سجلًا حسب {field_label}. {bits}"
	else:
		answer = f"You can see {total} {doctype_label} records. The chart groups {shown} of them by {field_label}. {bits}"
	if total > shown:
		note = " هذه ليست كل السجلات." if lang == "ar" else " This is not every record."
		answer += note
	return {"answer": answer, "charts": [chart]}


def _chart_doctype(message: str | None) -> str | None:
	found = match_doctype(message)
	if found:
		return found
	norm = normalize_arabic(message)
	raw = (message or "").lower()
	if _has(norm, "lead") or _has(norm, "leads") or "lead" in raw:
		for name in ("CRM Lead", "Lead"):
			if frappe.db.exists("DocType", name):
				return name
	return None


def _group_field(doctype: str, message: str | None) -> str | None:
	norm = normalize_arabic(message)
	raw = (message or "").lower()
	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return None
	names = {df.fieldname for df in meta.fields if df.fieldname}
	picked = _named_group_field(meta, message)
	if picked:
		return picked
	if any(word in norm or word in raw for word in ("owner", "مالك", "مسؤول")):
		for candidate in ("lead_owner", "owner"):
			if candidate in names:
				return candidate
	if "status" in names and any(word in norm or word in raw for word in ("status", "حالة", "الحالة")):
		return "status"
	if "status" in names:
		return "status"
	return None


_GROUPABLE = ("Link", "Select", "Data", "Dynamic Link")


def _named_group_field(meta, message: str | None) -> str | None:
	"""The field after "by"/"حسب": "invoices by customer" -> customer."""
	from erpnext_ai_assistant.services.targeting import _tr, grouping_words

	words = [normalize_arabic(word) for word in grouping_words(message)]
	if not words:
		return None
	for df in meta.fields:
		if df.fieldtype not in _GROUPABLE or not df.fieldname:
			continue
		names = {normalize_arabic(df.fieldname.replace("_", " ")), normalize_arabic(df.label or ""), normalize_arabic(_tr(df.label or "", "ar"))}
		names |= {name.rstrip("s") for name in names}
		if any(word in names or word.rstrip("s") in names or strip_al(word) in names for word in words):
			return df.fieldname
	return None
