"""Server-side write contract. Summaries are derived from the stored payload."""

from __future__ import annotations

import hashlib
import json

import frappe


def payload_hash(payload) -> str:
	if isinstance(payload, str):
		try:
			payload = json.loads(payload) if payload else {}
		except Exception:
			payload = {"_raw": payload}
	canonical = json.dumps(payload or {}, sort_keys=True, ensure_ascii=False, default=str)
	return hashlib.sha256(canonical.encode()).hexdigest()


_PERM = {"update": "write", "delete": "delete", "submit": "submit", "cancel": "cancel"}
_STATE_EN = {0: "draft", 1: "submitted", 2: "cancelled"}
_STATE_AR = {0: "مسودة", 1: "معتمد", 2: "ملغى"}
# Fields people use to point at a record: "the invoice for Delta Systems", "the task called Review".
_HINT_FIELDS = (
	"customer", "customer_name", "supplier", "supplier_name", "party_name", "party",
	"lead_name", "employee_name", "project", "project_name", "subject", "description", "title",
)
_MAX_CHOICES = 5


def resolve_write_target(action: str, doctype: str, target: str | None, payload: dict | None) -> dict:
	"""Find the one record a non-create card will change, before the card exists.

	The model may pass a party, a title, or an invented name as `target`. The card must
	point at a real record in the right state that this user may change, or say why not.
	Returns {"status": "ok", "name": ...}, or a need_input/failed result with message_en/message_ar.
	"""
	from erpnext_ai_assistant.services.targeting import _tr

	label_en, label_ar = doctype, _tr(doctype, "ar") or doctype
	if not target:
		return _no_target(action, doctype, "need_input", "missing_name", f"Which {label_en} should I {action}?", f"أي {label_ar} تقصد؟")
	meta = frappe.get_meta(doctype)
	if frappe.db.exists(doctype, target):
		return _check_record(action, doctype, meta, target, payload or {}, label_en, label_ar)
	rows = _find_by_hint(action, doctype, meta, target)
	if len(rows) == 1:
		return _check_record(action, doctype, meta, rows[0]["name"], payload or {}, label_en, label_ar)
	state_en, state_ar = _wanted_state(action, meta)
	if not rows:
		return _no_target(
			action, doctype, "failed", "target_not_found",
			f"I could not find a {state_en}{label_en} matching “{target}” that you can {action}. Nothing was prepared.",
			f"لم أجد {label_ar} {state_ar}يطابق “{target}” ويمكنك تنفيذ هذا عليه. لم يُجهَّز أي طلب.",
		)
	listing = "\n".join(f"{i}. {_describe(meta, row)}" for i, row in enumerate(rows[:_MAX_CHOICES], 1))
	more = len(rows) > _MAX_CHOICES
	result = _no_target(
		action, doctype, "need_input", "several_targets",
		f"Several {label_en} records match “{target}”. Which one?\n{listing}" + ("\n…and more. Add a detail to narrow it." if more else ""),
		f"يوجد أكثر من سجل {label_ar} يطابق “{target}”. أيها تقصد؟\n{listing}" + ("\n…وغيرها. أضف تفصيلًا لتضييق البحث." if more else ""),
	)
	result["choices"] = [row["name"] for row in rows[:_MAX_CHOICES]]
	return result


def _wanted_state(action: str, meta) -> tuple[str, str]:
	if not meta.is_submittable:
		return "", ""
	if action in ("submit", "update"):
		return "draft ", "مسودة "
	if action == "cancel":
		return "submitted ", "معتمد "
	return "", ""


def _state_filter(action: str, meta) -> dict:
	if not meta.is_submittable:
		return {}
	if action in ("submit", "update"):
		return {"docstatus": 0}
	if action == "cancel":
		return {"docstatus": 1}
	if action == "delete":
		return {"docstatus": ["!=", 1]}
	return {}


def _find_by_hint(action: str, doctype: str, meta, hint: str) -> list[dict]:
	fields = [f for f in _hint_fields(meta) if f != "name"]
	or_filters = [[doctype, "name", "like", f"%{hint}%"]] + [[doctype, f, "like", f"%{hint}%"] for f in fields]
	return frappe.get_list(
		doctype,
		filters=_state_filter(action, meta),
		or_filters=or_filters,
		fields=list(dict.fromkeys(["name", *(_shown_fields(meta))])),
		order_by="modified desc",
		limit_page_length=_MAX_CHOICES + 1,
	)


def _hint_fields(meta) -> list[str]:
	names = [meta.title_field] + [f.strip() for f in (meta.search_fields or "").split(",")] + list(_HINT_FIELDS)
	return [f for f in dict.fromkeys(names) if f and meta.has_field(f)]


def _shown_fields(meta) -> list[str]:
	wanted = [meta.title_field, "customer_name", "supplier_name", "party_name", "subject", "description", "grand_total", "posting_date", "transaction_date", "status"]
	return [f for f in dict.fromkeys(wanted) if f and meta.has_field(f)]


def _describe(meta, row: dict) -> str:
	from frappe.utils import strip_html

	bits = [row.get("name")]
	for field in _shown_fields(meta):
		value = row.get(field)
		if value in (None, ""):
			continue
		text = strip_html(str(value)) if field == "description" else str(value)
		if field == "grand_total":
			text = frappe.utils.fmt_money(value)
		bits.append(text[:60])
	return " — ".join(dict.fromkeys(bits))


def _check_record(action: str, doctype: str, meta, name: str, payload: dict, label_en: str, label_ar: str) -> dict:
	docstatus = frappe.db.get_value(doctype, name, "docstatus") or 0
	state_en, state_ar = _STATE_EN.get(docstatus, ""), _STATE_AR.get(docstatus, "")
	problem = None
	if meta.is_submittable:
		if action == "submit" and docstatus != 0:
			problem = (f"{name} is already {state_en}, so it cannot be submitted.", f"{name} حالته {state_ar}، فلا يمكن اعتماده.")
		elif action == "cancel" and docstatus != 1:
			problem = (f"{name} is {state_en}. Only a submitted {label_en} can be cancelled.", f"{name} حالته {state_ar}. لا يمكن إلغاء {label_ar} إلا بعد اعتماده.")
		elif action == "delete" and docstatus == 1:
			problem = (f"{name} is submitted. Cancel it before deleting it.", f"{name} معتمد. ألغه أولًا ثم احذفه.")
		elif action == "update" and docstatus != 0 and not all(
			(df := meta.get_field(key)) and df.allow_on_submit for key in payload
		):
			problem = (f"{name} is {state_en}, so these fields can no longer change.", f"{name} حالته {state_ar}، فلا يمكن تعديل هذه الحقول.")
	elif action in ("submit", "cancel"):
		problem = (f"{label_en} records are not submitted or cancelled.", f"سجلات {label_ar} لا تُعتمد ولا تُلغى.")
	if problem:
		return _no_target(action, doctype, "failed", "wrong_state", problem[0] + " Nothing was prepared.", problem[1] + " لم يُجهَّز أي طلب.")
	if not frappe.has_permission(doctype, _PERM.get(action, "write"), doc=name):
		return _no_target(
			action, doctype, "failed", "no_permission",
			f"You do not have permission to {action} {label_en} {name}. Nothing was prepared.",
			f"لا تملك صلاحية تنفيذ هذا على {label_ar} {name}. لم يُجهَّز أي طلب.",
		)
	return {"status": "ok", "name": name}


def _record_row(doctype: str, name: str) -> dict:
	fields = list(dict.fromkeys(["name", *_shown_fields(frappe.get_meta(doctype))]))
	return frappe.db.get_value(doctype, name, fields, as_dict=True) or {"name": name}


def _no_target(action: str, doctype: str, status: str, error: str, message_en: str, message_ar: str) -> dict:
	return {
		"status": status,
		"error": error,
		"target_doctype": doctype,
		"action_type": action,
		"message_en": message_en,
		"message_ar": message_ar,
	}


_VERB_EN = {"create": "New", "update": "Change", "delete": "Delete", "submit": "Submit", "cancel": "Cancel"}
_VERB_AR = {"create": "إنشاء", "update": "تعديل", "delete": "حذف", "submit": "اعتماد", "cancel": "إلغاء"}
# Plumbing the user never chose; ERPNext needs it, the card does not show it.
_CARD_HIDDEN = {
	"naming_series", "conversion_rate", "plc_conversion_rate", "price_list_currency",
	"apply_discount_on", "order_type", "quotation_to", "docstatus",
}
# Filled automatically, shown on one short line so nothing is hidden.
_CARD_AUTO = ("company", "currency", "selling_price_list", "buying_price_list")


def summary_from_payload(action: str, doctype: str, payload: dict, target_name: str | None = None, lang: str = "en") -> str:
	"""What the card says: which record, what changes, in the user's words. Built only from the payload and the record."""
	from frappe.utils import fmt_money, strip_html

	from erpnext_ai_assistant.services.targeting import _tr

	ar = lang == "ar"
	meta = frappe.get_meta(doctype)
	title = (_VERB_AR if ar else _VERB_EN).get(action, action)
	lines = [f"{title} {_tr(doctype, lang) or doctype}" + (f" {target_name}" if target_name else "")]
	exists = bool(target_name and frappe.db.exists(doctype, target_name))
	if exists:
		described = _describe(meta, _record_row(doctype, target_name))
		if described != target_name:
			lines.append(described)
	payload = payload or {}
	plain = [key for key in payload if not str(key).startswith("_") and meta.get_field(key) and meta.get_field(key).fieldtype != "Table"]
	before = frappe.db.get_value(doctype, target_name, plain, as_dict=True) if exists and action == "update" and plain else {}
	currency = payload.get("currency") or ""
	auto, rows_text = [], []
	for key in sorted(payload):
		value = payload[key]
		df = meta.get_field(key) if not str(key).startswith("_") else None
		if not df:
			continue
		if df.fieldtype == "Table":
			rows_text.extend(_row_lines(value, currency))
			continue
		if action == "create" and key in _CARD_AUTO:
			auto.append(str(value))
			continue
		if key in _CARD_HIDDEN or (action == "create" and df.fieldtype == "Check" and not value):
			continue
		if action == "create" and df.default not in (None, "") and str(value) == str(df.default):
			continue
		label = _tr(df.label or key, lang) or key
		if df.fieldtype == "Dynamic Link" and payload.get(df.options):
			label = _tr(payload[df.options], lang) or label  # "Party" on a Quotation to a Customer reads "Customer"
		shown = strip_html(str(value)) if isinstance(value, str) else value
		if action == "update" and before is not None:
			old = (before or {}).get(key)
			lines.append(f"{label}: {old if old not in (None, '') else '—'} → {shown}")
		else:
			lines.append(f"{label}: {shown}")
	if rows_text:
		lines.extend(rows_text)
		total = sum(float(row.get("qty") or 0) * float(row.get("rate") or 0) for rows in (v for v in payload.values() if isinstance(v, list)) for row in rows if isinstance(row, dict))
		if total:
			lines.append(("الإجمالي: " if ar else "Total: ") + fmt_money(total, currency=currency or None))
	if auto:
		lines.append(("تُملأ تلقائيًا: " if ar else "Filled automatically: ") + " · ".join(auto))
	return "\n".join(lines)[:2000]


def _row_lines(rows, currency: str) -> list[str]:
	from frappe.utils import fmt_money

	out = []
	for row in rows if isinstance(rows, list) else []:
		if not isinstance(row, dict):
			continue
		name = row.get("item_name") or row.get("item_code") or ""
		qty = row.get("qty")
		rate = row.get("rate")
		line = f"• {qty} × {name}" if qty not in (None, "") else f"• {name}"
		if rate not in (None, ""):
			line += f" @ {fmt_money(rate, currency=currency or None)}"
		out.append(line)
	return out
