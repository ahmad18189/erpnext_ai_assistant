"""DocType schema for writes. Values come from the DocType meta (synced from JSON).

Nothing here invents business data. Mandatory fields that the user did not supply,
and that have no DocType default, stay missing so the assistant can ask.
"""

from __future__ import annotations

import re

import frappe

LAYOUT = {
	"Section Break",
	"Column Break",
	"Tab Break",
	"HTML",
	"Button",
	"Fold",
	"Heading",
}
# The assistant must not create accounts, roles, or files through chat.
DENIED_DOCTYPES = {
	"DocType",
	"DocField",
	"DocPerm",
	"User",
	"Role",
	"Has Role",
	"File",
	"Communication",
	"Error Log",
	"Activity Log",
	"Version",
	"Access Log",
	"Scheduled Job Log",
	"Server Script",
	"Client Script",
	"Custom Field",
	"Property Setter",
	"Module Def",
	"Page",
	"Report",
	"Workspace",
	"ERP AI Pending Action",
	"ERP AI Audit Log",
	"ERP AI Knowledge Chunk",
	"ERP AI Knowledge Document",
	"ERP AI Metadata Cache",
}


def _e164(number: str | None) -> str | None:
	import phonenumbers

	raw = (number or "").strip()
	if not raw:
		return None
	try:
		parsed = phonenumbers.parse(raw, "SA")
	except phonenumbers.NumberParseException:
		return None
	if not phonenumbers.is_valid_number(parsed):
		return None
	return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def describe_doctype(doctype: str) -> dict:
	"""Mandatory fields and child tables for a DocType the session user may create."""
	if doctype in DENIED_DOCTYPES or not frappe.db.exists("DocType", doctype):
		frappe.throw(f"DocType is not available for assistant writes: {doctype}", frappe.PermissionError)
	meta = frappe.get_meta(doctype)
	fields = []
	children = []
	for df in meta.fields:
		if not df.fieldname or df.fieldtype in LAYOUT:
			continue
		if df.fieldtype == "Table":
			child_meta = frappe.get_meta(df.options) if df.options else None
			child_fields = []
			if child_meta:
				for cdf in child_meta.fields:
					if not cdf.fieldname or cdf.fieldtype in LAYOUT:
						continue
					if cdf.reqd:
						child_fields.append(
							{"fieldname": cdf.fieldname, "label": cdf.label, "fieldtype": cdf.fieldtype}
						)
			children.append(
				{
					"fieldname": df.fieldname,
					"label": df.label,
					"child_doctype": df.options,
					"reqd": int(df.reqd or 0),
					"required_columns": child_fields,
				}
			)
			continue
		fields.append(
			{
				"fieldname": df.fieldname,
				"label": df.label,
				"fieldtype": df.fieldtype,
				"options": df.options,
				"reqd": int(df.reqd or 0),
				"default": df.default,
				"read_only": int(df.read_only or 0),
			}
		)
	return {"doctype": doctype, "fields": fields, "children": children}


def prepare_payload(doctype: str, raw: dict | None, action: str = "create", apply_defaults: bool = True) -> dict:
	"""Drop unknown fields, apply DocType defaults, and list what is still required."""
	described = describe_doctype(doctype)
	by_name = {f["fieldname"]: f for f in described["fields"]}
	cleaned: dict = {}
	errors: list[str] = []
	applied_defaults: list[str] = []
	for key, value in (raw or {}).items():
		if str(key).startswith("_"):
			cleaned[key] = value
			continue
		df = by_name.get(key)
		if not df:
			errors.append(f"Unknown field {key}")
			continue
		if df["read_only"]:
			errors.append(f"Read-only field {key}")
			continue
		if value in (None, ""):
			continue
		if df.get("fieldtype") == "Select" and df.get("options"):
			wanted = str(value).strip().lower()
			for option in str(df["options"]).split("\n"):
				if option.strip().lower() == wanted:
					value = option.strip()
					break
		if df.get("options") == "Phone":
			number = _e164(str(value))
			if not number:
				errors.append(f"{df['label']} is not a valid phone number")
				continue
			cleaned[key] = number
			continue
		cleaned[key] = value

	missing: list[dict] = []
	if action == "create":
		for df in described["fields"]:
			if df["read_only"]:
				continue
			if cleaned.get(df["fieldname"]) not in (None, ""):
				continue
			if apply_defaults and df.get("default") not in (None, ""):
				default = str(df["default"])
				# Today / __user are applied by Frappe on insert. Do not store those words.
				if default in {"Today", "Now", "now"} or default.startswith("__"):
					continue
				if df.get("options") == "Phone":
					default = _e164(default)
					if not default:
						missing.append(df)
						continue
				cleaned[df["fieldname"]] = default
				if df.get("fieldtype") != "Check":
					applied_defaults.append({"label": df.get("label") or df["fieldname"], "value": default})
			elif df["reqd"]:
				missing.append(df)
		for child in described["children"]:
			rows = cleaned.get(child["fieldname"])
			if child["reqd"] and not rows:
				missing.append(
					{
						"fieldname": child["fieldname"],
						"label": child["label"],
						"fieldtype": "Table",
						"child_doctype": child["child_doctype"],
						"required_columns": child["required_columns"],
					}
				)
			elif isinstance(rows, list):
				for row in rows:
					if not isinstance(row, dict):
						errors.append(f"{child['fieldname']} row is not an object")
						continue
					for col in child["required_columns"]:
						if row.get(col["fieldname"]) in (None, ""):
							missing.append(
								{
									"fieldname": f"{child['fieldname']}.{col['fieldname']}",
									"label": f"{child['label']} / {col['label']}",
									"fieldtype": col["fieldtype"],
								}
							)
	return {
		"payload": cleaned,
		"missing": missing,
		"errors": errors,
		"applied_defaults": applied_defaults,
		"children": described["children"],
	}


def _label(text: str | None, lang: str) -> str:
	"""Field and DocType labels follow Frappe translations for the chat language."""
	source = text or ""
	if not source or lang in ("en", "en-US", "en-GB"):
		return source
	try:
		translated = (frappe.translate.get_all_translations(lang) or {}).get(source)
	except Exception:
		translated = None
	return translated or source


def missing_message(doctype: str, prepared: dict, lang: str = "en") -> str:
	lines = []
	for item in prepared.get("missing") or []:
		label = _label(item.get("label") or item.get("fieldname"), lang)
		if item.get("required_columns"):
			cols = ", ".join(_label(col.get("label") or col.get("fieldname"), lang) for col in item["required_columns"])
			child = _label(item.get("child_doctype"), lang)
			label = f"{label} ({child}: {cols})" if lang != "ar" else f"{label} ({child}: {cols})"
		lines.append(f"- {label}")
	defaults = []
	for item in prepared.get("applied_defaults") or []:
		if isinstance(item, dict):
			defaults.append(f"{_label(item.get('label'), lang)}: {_label(str(item.get('value') or ''), lang)}")
		else:
			defaults.append(str(item))
	doc_label = _label(doctype, lang)
	if lang == "ar":
		text = f"لا يمكن إنشاء {doc_label} بعد. الحقول الإلزامية الناقصة:\n" + "\n".join(lines)
		if defaults:
			text += "\nالقيم الافتراضية من نوع المستند:\n" + "\n".join(f"- {line}" for line in defaults)
		text += "\nأرسل القيم الناقصة. لن أخمنها."
		return text
	text = f"I cannot create {doc_label} yet. Required fields still missing:\n" + "\n".join(lines)
	if defaults:
		text += "\nDocType defaults that will be used:\n" + "\n".join(f"- {line}" for line in defaults)
	text += "\nSend the missing values. I will not guess them."
	return text


def resolve_doctype(text: str) -> str | None:
	"""Match a business DocType named in the message. Skips system DocTypes."""
	raw = text or ""
	lower = raw.lower()
	names = frappe.cache().get_value("erp_ai_writable_doctypes")
	if not names:
		names = frappe.get_all("DocType", filters={"istable": 0, "issingle": 0}, pluck="name")
		names = [n for n in names if n not in DENIED_DOCTYPES]
		frappe.cache().set_value("erp_ai_writable_doctypes", names, expires_in_sec=600)
	found = []
	for name in names:
		if len(name) < 4:
			continue
		if re.search(rf"(?i)(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", raw):
			found.append(name)
		elif name.lower() in lower and " " in name:
			found.append(name)
	if not found:
		return None
	found.sort(key=len, reverse=True)
	return found[0]


def action_from_text(text: str) -> str | None:
	raw = (text or "").lower()
	if re.search(r"\b(delete|remove)\b|حذف", raw):
		return "delete"
	if re.search(r"\b(submit)\b|اعتماد", raw):
		return "submit"
	if re.search(r"\bcancel\b|إلغاء", raw):
		return "cancel"
	if re.search(r"\b(update|edit|change)\b|تعديل", raw):
		return "update"
	if re.search(r"\b(create|add|new)\b|إنشاء|أضف", raw):
		return "create"
	return None


def propose_schema_write(
	text: str,
	chat_id: str | None = None,
	lang: str = "en",
	pending_intent: str | None = None,
) -> dict | None:
	"""Propose a create/update/delete for any permitted business DocType.

	Returns None when the message does not name a DocType. Missing mandatory
	fields produce a question instead of a pending action.
	"""
	action = action_from_text(text)
	doctype = resolve_doctype(text or "")
	if not doctype and pending_intent and str(pending_intent).startswith("create:"):
		doctype = pending_intent.split(":", 1)[1]
		action = action or "create"
	if not action or not doctype:
		return None
	perm = {"create": "create", "update": "write", "delete": "delete", "submit": "submit", "cancel": "cancel"}.get(action, "write")
	if not frappe.has_permission(doctype, perm):
		return {
			"error": "no_create_permission",
			"status": "failed",
			"message_en": f"You do not have permission to {action} {doctype}.",
			"message_ar": f"لا تملك صلاحية {action} على {doctype}.",
		}
	if action in ("update", "delete", "submit", "cancel"):
		match = re.search(r"(?:name|id)\s*[:=]?\s*([A-Za-z0-9][A-Za-z0-9._\-/]{1,80})", text or "", re.I)
		if not match:
			ask = f"Which {doctype} name should I {action}?"
			return {"error": "missing_name", "status": "need_input", "message_en": ask, "message_ar": ask}
		target = match.group(1)
		if action != "update":
			from erpnext_ai_assistant.services.tools.registry import propose_write

			if not chat_id:
				return {"error": "missing_chat", "status": "failed", "message_en": "No chat.", "message_ar": "لا توجد محادثة."}
			return propose_write(chat_id, action, doctype, {}, target_name=target)
		values = extract_field_values(doctype, text or "")
		if not values:
			ask = f"Which fields of {doctype} {target} should change? Use Field Name: value."
			return {"error": "missing_required", "status": "need_input", "message_en": ask, "message_ar": ask}
		from erpnext_ai_assistant.services.tools.registry import propose_write

		if not chat_id:
			return {"error": "missing_chat", "status": "failed", "message_en": "No chat.", "message_ar": "لا توجد محادثة."}
		return propose_write(chat_id, "update", doctype, values, target_name=target)

	values = _values_for_create(doctype, text or "")
	prepared = prepare_payload(doctype, values, "create")
	if prepared["missing"] or prepared["errors"]:
		return {
			"error": "missing_required",
			"status": "need_input",
			"target_doctype": doctype,
			"action_type": "create",
			"message_en": missing_message(doctype, prepared, "en"),
			"message_ar": missing_message(doctype, prepared, "ar"),
		}
	if not chat_id:
		return {"error": "missing_chat", "status": "failed", "message_en": "No chat.", "message_ar": "لا توجد محادثة."}
	from erpnext_ai_assistant.services.tools.registry import propose_write

	return propose_write(chat_id, "create", doctype, prepared["payload"])


def _values_for_create(doctype: str, text: str) -> dict:
	values = extract_field_values(doctype, text)
	if doctype == "Customer":
		if not values.get("customer_name"):
			match = re.search(
				r"(?i)\bcustomer\s+([A-Za-z0-9][\w .'-]{0,80}?)(?:\s+as\b|\s+type\b|$)",
				text or "",
			)
			if match:
				name = match.group(1).strip(" .")
				if name.lower() not in {"name", "as", "type", "a", "the"}:
					values["customer_name"] = name
		if re.search(r"(?i)\bcompan", text or ""):
			values.setdefault("customer_type", "Company")
		elif re.search(r"(?i)\bindividual\b", text or ""):
			values.setdefault("customer_type", "Individual")
	return values


def extract_field_values(doctype: str, text: str) -> dict:
	"""Read field=value or label: value pairs. Unmentioned fields stay absent."""
	described = describe_doctype(doctype)
	found: dict = {}
	for df in described["fields"]:
		if df["read_only"]:
			continue
		keys = [df["fieldname"]]
		if df.get("label"):
			keys.append(df["label"])
		for key in keys:
			match = re.search(
				rf"(?i)(?<![A-Za-z0-9_]){re.escape(key)}\s*[:=]?\s+(\S[^\n,;]*)",
				text or "",
			)
			if match:
				found[df["fieldname"]] = match.group(1).strip()
				break
	return found
