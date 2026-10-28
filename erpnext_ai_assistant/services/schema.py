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
	"ERP AI Enhancement",
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
	if not (frappe.has_permission(doctype, "read") or frappe.has_permission(doctype, "create")):
		frappe.throw(f"No access to {doctype}", frappe.PermissionError)
	meta = frappe.get_meta(doctype)
	permitted = set(meta.get_permitted_fieldnames(permission_type="read") or [])
	# Create path still needs required fields the user can write.
	if frappe.has_permission(doctype, "create"):
		permitted.update(meta.get_permitted_fieldnames(permission_type="write") or [])
	fields = []
	children = []
	for df in meta.fields:
		if not df.fieldname or df.fieldtype in LAYOUT:
			continue
		if df.fieldtype == "Table":
			if permitted and df.fieldname not in permitted and int(df.permlevel or 0) > 0:
				continue
			child_meta = frappe.get_meta(df.options) if df.options else None
			child_fields = []
			if child_meta:
				for cdf in child_meta.fields:
					if not cdf.fieldname or cdf.fieldtype in LAYOUT:
						continue
					if cdf.reqd:
						child_fields.append(
							{"fieldname": cdf.fieldname, "label": cdf.label, "fieldtype": cdf.fieldtype, "read_only": int(cdf.read_only or 0)}
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
		if permitted and df.fieldname not in permitted:
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


_NUMERIC = {"Check": int, "Int": int, "Float": float, "Currency": float, "Percent": float}


def typed_default(fieldtype: str | None, default):
	"""A default as Frappe would store it. "0" for a Check is false in the DB but true in Python."""
	cast = _NUMERIC.get(fieldtype or "")
	if not cast or not isinstance(default, str):
		return default
	try:
		return cast(float(default)) if cast is int else cast(default)
	except ValueError:
		return default


def prepare_payload(doctype: str, raw: dict | None, action: str = "create", apply_defaults: bool = True) -> dict:
	"""Drop unknown fields, apply DocType defaults, and list what is still required."""
	described = describe_doctype(doctype)
	by_name = {f["fieldname"]: f for f in described["fields"]}
	tables = {child["fieldname"] for child in described["children"]}
	cleaned: dict = {}
	errors: list[str] = []
	applied_defaults: list[str] = []
	for key, value in (raw or {}).items():
		if str(key).startswith("_"):
			cleaned[key] = value
			continue
		if key in tables:
			# Item rows and other child tables: a list of row objects, checked below.
			if isinstance(value, dict):
				value = [value]
			if isinstance(value, list):
				cleaned[key] = value
			else:
				errors.append(f"{key} must be a list of rows")
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
	if action == "create" and apply_defaults:
		from erpnext_ai_assistant.services.autofill import fill_header, fill_rows

		applied_defaults.extend(fill_header(described["fields"], cleaned))
		errors.extend(fill_rows(described["children"], cleaned))
	if action == "create":
		for df in described["fields"]:
			if df["read_only"]:
				continue
			if cleaned.get(df["fieldname"]) not in (None, ""):
				continue
			# Frappe fills Today / Now / __user on insert, so they are never missing, even on the approval re-check.
			if str(df.get("default") or "") in {"Today", "Now", "now"} or str(df.get("default") or "").startswith("__"):
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
				cleaned[df["fieldname"]] = typed_default(df.get("fieldtype"), default)
				if df.get("fieldtype") != "Check":
					applied_defaults.append({"label": df.get("label") or df["fieldname"], "value": default})
			elif df["reqd"]:
				missing.append(df)
		from erpnext_ai_assistant.services.autofill import ASKED_DATES

		asked = ASKED_DATES.get(doctype)
		if asked and asked in by_name and cleaned.get(asked) in (None, ""):
			missing.append(by_name[asked])
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
						# Unit, factor and similar come from the Item; an unknown item is already an error.
						if col.get("read_only") or col["fieldname"] in _FILLED_ROW_FIELDS:
							continue
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


def next_step_payload(doctype: str, prepared: dict, lang: str = "en") -> dict:
	"""One missing field at a time, with labels the session user may write."""
	meta = None
	try:
		meta = frappe.get_meta(doctype)
		perm = "write" if frappe.has_permission(doctype, "create") else "read"
		permitted = set(meta.get_permitted_fieldnames(permission_type=perm) or [])
	except Exception:
		permitted = set()
	missing = []
	for item in prepared.get("missing") or []:
		fieldname = item.get("fieldname") or ""
		base = fieldname.split(".", 1)[0]
		if permitted and base and base not in permitted and "." not in fieldname:
			continue
		label_en = item.get("label") or fieldname
		label_ar = _label(label_en, "ar")
		options = item.get("options")
		if not options:
			try:
				df = meta.get_field(base) if base else None
				if df and df.fieldtype == "Select":
					options = df.options
			except Exception:
				options = None
		missing.append(
			{
				"fieldname": fieldname,
				"label_ar": label_ar,
				"label_en": label_en,
				"fieldtype": item.get("fieldtype"),
				"options": options or None,
			}
		)
	collected = {}
	for key, value in (prepared.get("payload") or {}).items():
		if str(key).startswith("_"):
			continue
		if isinstance(value, (str, int, float, bool)) or value is None:
			collected[key] = value
		elif isinstance(value, list) and all(isinstance(row, dict) for row in value):
			# Item rows already given ("5 monitors") must survive the turn that asks for the date.
			collected[key] = value
	next_ask = ""
	if missing:
		first = missing[0]
		label = first["label_ar"] if lang == "ar" else first["label_en"]
		next_ask = f"أرسل {label}." if lang == "ar" else f"Send {label}."
	return {"missing": missing, "next_ask": next_ask, "collected": collected}


def guided_message(doctype: str, prepared: dict, lang: str = "en") -> tuple[str, dict]:
	"""One-field ask plus a short list of the other missing labels."""
	step = next_step_payload(doctype, prepared, lang)
	missing = step.get("missing") or []
	if not missing:
		return missing_message(doctype, prepared, lang), step
	first = missing[0]
	label = first["label_ar"] if lang == "ar" else first["label_en"]
	options = []
	if first.get("fieldtype") == "Select" and first.get("options"):
		options = [opt.strip() for opt in str(first["options"]).split("\n") if opt.strip()][:8]
	names = []
	for item in missing[:8]:
		names.append(item["label_ar"] if lang == "ar" else item["label_en"])
	if lang == "ar":
		text = f"أرسل {label}."
		if options:
			text += " الخيارات: " + "، ".join(options) + "."
		text += "\nالحقول الناقصة: " + "، ".join(names)
		text += "\nلن أخمن القيم، ولن يُحفظ شيء قبل موافقتك."
	else:
		text = f"Send {label}."
		if options:
			text += " Options: " + ", ".join(options) + "."
		text += "\nStill missing: " + ", ".join(names)
		text += "\nI will not guess values, and nothing is saved until you approve."
	step["next_ask"] = text.split("\n", 1)[0]
	return text, step


# Row columns filled from the Item master or computed by ERPNext; never asked of the user.
_FILLED_ROW_FIELDS = {"uom", "stock_uom", "conversion_factor", "description", "rate", "amount"}


def typed_columns(columns: list[dict]) -> list[str]:
	"""Labels of the row values a person actually types: the item and the quantity."""
	labels = []
	for col in columns:
		if col.get("read_only") or col.get("fieldname") in _FILLED_ROW_FIELDS:
			continue
		labels.append("Item" if col.get("fieldname") in ("item_name", "item_code") else (col.get("label") or col.get("fieldname")))
	return list(dict.fromkeys(labels))


def missing_message(doctype: str, prepared: dict, lang: str = "en") -> str:
	lines = []
	for item in prepared.get("missing") or []:
		label = _label(item.get("label") or item.get("fieldname"), lang)
		if item.get("required_columns"):
			cols = ", ".join(_label(col, lang) for col in typed_columns(item["required_columns"]))
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
			return propose_write(chat_id, action, doctype, {}, target_name=target, lang=lang)
		values = extract_field_values(doctype, text or "")
		if not values:
			ask = f"Which fields of {doctype} {target} should change? Use Field Name: value."
			return {"error": "missing_required", "status": "need_input", "message_en": ask, "message_ar": ask}
		from erpnext_ai_assistant.services.tools.registry import propose_write

		if not chat_id:
			return {"error": "missing_chat", "status": "failed", "message_en": "No chat.", "message_ar": "لا توجد محادثة."}
		return propose_write(chat_id, "update", doctype, values, target_name=target, lang=lang)

	values = _values_for_create(doctype, text or "")
	prepared = prepare_payload(doctype, values, "create")
	if prepared["missing"] or prepared["errors"]:
		message_en, step_en = guided_message(doctype, prepared, "en")
		message_ar, step_ar = guided_message(doctype, prepared, "ar")
		step = step_ar if lang == "ar" else step_en
		return {
			"error": "missing_required",
			"status": "need_input",
			"target_doctype": doctype,
			"action_type": "create",
			"message_en": message_en,
			"message_ar": message_ar,
			"next_ask": step.get("next_ask"),
			"next_step": step,
		}
	if not chat_id:
		return {"error": "missing_chat", "status": "failed", "message_en": "No chat.", "message_ar": "لا توجد محادثة."}
	from erpnext_ai_assistant.services.tools.registry import propose_write

	return propose_write(chat_id, "create", doctype, prepared["payload"], lang=lang)


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
	"""Read field=value or label: value pairs, including Arabic labels.

	A label that matches more than one field is left absent so the caller asks.
	"""
	described = describe_doctype(doctype)
	try:
		from erpnext_ai_assistant.services.rdf.graph import field_aliases

		alias_map = field_aliases(doctype)
	except Exception:
		alias_map = {}
	from erpnext_ai_assistant.services.arabic import normalize_arabic

	raw = text or ""
	norm = normalize_arabic(raw)
	exact: dict[str, str] = {}
	by_label: dict[str, tuple[str, int]] = {}
	for df in described["fields"]:
		if df["read_only"]:
			continue
		fieldname = df["fieldname"]
		labels = [fieldname]
		if df.get("label"):
			labels.append(df["label"])
			translated = _label(df["label"], "ar")
			if translated:
				labels.append(translated)
		for alias in alias_map.get(fieldname) or []:
			labels.append(alias)
		seen = set()
		for key in labels:
			token = (key or "").strip()
			if not token or token in seen:
				continue
			seen.add(token)
			match = re.search(
				rf"(?i)(?<![A-Za-z0-9_]){re.escape(token)}\s*[:=]?\s+(\S[^\n,;]*)",
				raw,
			)
			value = match.group(1).strip() if match else ""
			strength = len(normalize_arabic(token))
			if not value and norm:
				alias = normalize_arabic(token)
				if alias and len(alias) >= 2:
					alias_match = re.search(
						rf"(?<!\w){re.escape(alias)}\s*[:=]?\s+(\S+)",
						norm,
					)
					if alias_match:
						value = alias_match.group(1).strip()
						strength = len(alias)
			if not value:
				continue
			if normalize_arabic(token) == normalize_arabic(fieldname):
				exact[fieldname] = value
				continue
			previous = by_label.get(fieldname)
			if not previous or strength > previous[1]:
				by_label[fieldname] = (value, strength)
	if len(by_label) == 1:
		fieldname, (value, _strength) = next(iter(by_label.items()))
		exact.setdefault(fieldname, value)
	elif len(by_label) > 1:
		ranked = sorted(by_label.items(), key=lambda item: item[1][1], reverse=True)
		if ranked[0][1][1] >= ranked[1][1][1] + 3:
			exact.setdefault(ranked[0][0], ranked[0][1][0])
	return exact
