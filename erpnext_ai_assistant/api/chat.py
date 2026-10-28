"""Whitelisted chat API — session user only, no allow_guest."""

from __future__ import annotations

import json
import re

import frappe
from erpnext_ai_assistant.services import run_chat as orch
from erpnext_ai_assistant.services.moderation import abuse as abuse_mod


@frappe.whitelist(methods=["POST"])
def run(
	message: str,
	route: str | None = None,
	chat_id: str | None = None,
	attachments: str | None = None,
	file_url: str | None = None,
):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	if not (message or "").strip() and not attachments and not file_url:
		frappe.throw("Empty message")
	images = _images_from_attachments(attachments)
	return orch.run_chat(
		message=(message or "Review the attached file.").strip(),
		route=route,
		chat_id=chat_id,
		images=images,
		file_url=file_url or None,
	)


@frappe.whitelist(methods=["POST"])
def upload_attachment():
	"""Store one private file for the current user and, for tables, review import templates."""
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	upload = (frappe.request.files or {}).get("file") if getattr(frappe, "request", None) else None
	if not upload:
		frappe.throw("No file")
	filename = (upload.filename or "upload").replace("/", "_").replace("\\", "_")
	content = upload.stream.read(5_000_001)
	if len(content) > 5_000_000:
		frappe.throw("File is larger than 5 MB")
	ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
	allowed = {"png", "jpg", "jpeg", "webp", "gif", "csv", "xlsx", "txt", "pdf"}
	if ext not in allowed:
		frappe.throw("File type is not supported")
	from frappe.utils.file_manager import save_file

	file_doc = save_file(filename, content, None, None, is_private=1)
	kind = "image" if ext in {"png", "jpg", "jpeg", "webp", "gif"} else "table" if ext in {"csv", "xlsx"} else "text"
	result = {"file_url": file_doc.file_url, "file_name": filename, "kind": kind}
	if kind == "table":
		from erpnext_ai_assistant.services.imports import read_table, review_table, review_text

		header, sample = read_table(content, filename)
		review = review_table(header, sample)
		result["review"] = review
		result["review_text"] = review_text(review, "ar" if _prefers_ar() else "en")
	elif kind == "text":
		result["excerpt"] = _text_excerpt(content, ext)
	return result


@frappe.whitelist()
def blank_import_template(doctype: str):
	"""CSV header row for a Frappe blank import template of this DocType."""
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	from erpnext_ai_assistant.services.imports import blank_template_csv

	return {"doctype": doctype, "filename": f"{doctype}.csv", "csv": blank_template_csv(doctype)}


def _app_routes() -> list:
	from erpnext_ai_assistant.services.apps import installed_app_routes

	try:
		return installed_app_routes()
	except Exception:
		return []


def _prefers_ar() -> bool:
	return "ar" in (frappe.local.lang or frappe.db.get_value("User", frappe.session.user, "language") or "")


def _text_excerpt(content: bytes, ext: str) -> str:
	if ext == "pdf":
		try:
			from pypdf import PdfReader
			import io

			reader = PdfReader(io.BytesIO(content))
			parts = []
			for page in reader.pages[:5]:
				parts.append(page.extract_text() or "")
			return "\n".join(parts)[:4000]
		except Exception:
			return ""
	return content.decode("utf-8", errors="replace")[:4000]


def _images_from_attachments(attachments) -> list[dict]:
	rows = frappe.parse_json(attachments) if isinstance(attachments, str) else attachments
	if not rows:
		return []
	images = []
	for row in rows:
		if not isinstance(row, dict) or row.get("kind") != "image":
			continue
		url = row.get("file_url") or ""
		if not url:
			continue
		file_doc = frappe.get_doc("File", {"file_url": url})
		if file_doc.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
			frappe.throw("Not your file", frappe.PermissionError)
		raw = file_doc.get_content()
		if not raw or len(raw) > 1_500_000:
			continue
		import base64

		ext = (file_doc.file_name or "").rsplit(".", 1)[-1].lower()
		mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/jpeg")
		images.append({"mime": mime, "b64": base64.b64encode(raw).decode()})
		if len(images) >= 2:
			break
	return images


@frappe.whitelist(methods=["POST"])
def approve_action(pending_action: str, acknowledgment_text: str, acknowledged: int | bool = 0):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	if not acknowledged:
		frappe.throw("Written acknowledgment required")
	if not (acknowledgment_text or "").strip():
		frappe.throw("Acknowledgment text required")
	if abuse_mod.is_user_blocked():
		frappe.throw(abuse_mod.blocked_message())

	# Lock the row so a second approval cannot execute the same proposal.
	frappe.db.sql("select name from `tabERP AI Pending Action` where name=%s for update", pending_action)
	doc = frappe.get_doc("ERP AI Pending Action", pending_action)
	# Only the person who asked approves. A manager can still reject a card, never run it.
	if doc.user != frappe.session.user:
		frappe.throw("Only the person who asked can approve this card", frappe.PermissionError)
	retry_import = doc.action_type == "import" and doc.status == "approved"
	if doc.status != "pending" and not retry_import:
		frappe.throw(f"Action is {doc.status}")
	settings = frappe.get_single("ERP AI Settings")
	# A pending card can still be approved when new chat turns are turned off.
	# Execution depends on allow_pending_writes, the payload hash, and permissions.
	if not settings.allow_pending_writes:
		frappe.throw("Writes are disabled in ERP AI Settings")
	from erpnext_ai_assistant.services.writes import payload_hash

	if (doc.payload_hash or "") != payload_hash(doc.payload_json):
		frappe.throw("This approval no longer matches the proposed payload", frappe.ValidationError)
	if doc.status == "pending":
		stale = _card_stale_reason(doc)
		if stale:
			doc.status = "expired"
			doc.result_json = json.dumps({"reason": stale}, ensure_ascii=False)
			_save_pending(doc)
			return {"status": "expired", "message": stale}

	dt = doc.target_doctype
	action = doc.action_type
	from erpnext_ai_assistant.services.schema import DENIED_DOCTYPES

	if dt in DENIED_DOCTYPES:
		frappe.throw(f"{dt} is not available for assistant writes", frappe.PermissionError)
	if action == "import":
		if doc.user != frappe.session.user:
			frappe.throw("Not your pending action", frappe.PermissionError)
		return _approve_import(doc, acknowledgment_text)

	perm_map = {
		"create": "create",
		"update": "write",
		"delete": "delete",
		"submit": "submit",
		"cancel": "cancel",
	}
	need = perm_map.get(action, "write")
	allowed = frappe.has_permission(dt, need) if action == "create" else frappe.has_permission(dt, need, doc=doc.target_name)
	if not allowed:
		frappe.throw(f"No {need} permission for {dt}", frappe.PermissionError)

	doc.acknowledgment_text = acknowledgment_text.strip()
	doc.acknowledged = 1
	doc.resolved_by = frappe.session.user
	doc.resolved_at = frappe.utils.now_datetime()

	payload = {}
	if doc.payload_json:
		payload = json.loads(doc.payload_json) if isinstance(doc.payload_json, str) else doc.payload_json

	from erpnext_ai_assistant.services.schema import prepare_payload

	if action == "create":
		checked = prepare_payload(dt, payload, "create", apply_defaults=False)
		if checked["missing"] or checked["errors"]:
			frappe.throw("Payload does not satisfy the DocType: " + "; ".join(checked["errors"]))
		payload = checked["payload"]
	elif action == "update":
		payload = {key: value for key, value in payload.items() if key not in _PROTECTED_KEYS}
		checked = prepare_payload(dt, payload, "update", apply_defaults=False)
		if checked["errors"]:
			frappe.throw("Payload does not satisfy the DocType: " + "; ".join(checked["errors"]))
		payload = checked["payload"]
	try:
		result = _execute(action, dt, doc.target_name, payload)
		doc.status = "executed"
		doc.result_json = json.dumps(result, ensure_ascii=False, default=str)
	except Exception as e:
		# The card stays pending, so the user can fix the cause and approve again.
		frappe.throw(_plain_error(e))
	_save_pending(doc)
	link = result.get("link") if isinstance(result, dict) else None
	message = _created_message(action, dt, result)
	if doc.chat and message:
		from erpnext_ai_assistant.services.naming import as_title

		frappe.get_doc(
			{
				"doctype": "ERP AI Message",
				"title": as_title("ERP AI Message", message[:80]),
				"chat": doc.chat,
				"role": "assistant",
				"content": message,
				"status": "complete",
			}
		).insert(ignore_permissions=True)
	return {
		"status": doc.status,
		"result": json.loads(doc.result_json or "{}"),
		"link": link,
		"message": message,
	}


# Fields a card may never set on an existing record.
_PROTECTED_KEYS = {"name", "owner", "creation", "modified", "modified_by", "docstatus", "doctype", "idx", "parent", "parenttype", "parentfield"}
CARD_TTL_HOURS = 24


def _card_stale_reason(doc) -> str:
	"""Why a pending card may no longer be approved, or "" when it is still current."""
	age = frappe.utils.time_diff_in_hours(frappe.utils.now_datetime(), doc.creation)
	if age > CARD_TTL_HOURS:
		return "This card is more than a day old. Ask again to prepare a fresh one."
	if doc.target_name and doc.get("target_modified"):
		current = frappe.db.get_value(doc.target_doctype, doc.target_name, "modified")
		if current is None:
			return f"{doc.target_doctype} {doc.target_name} no longer exists."
		if frappe.utils.get_datetime(current) != frappe.utils.get_datetime(doc.target_modified):
			return f"{doc.target_doctype} {doc.target_name} changed after this card was prepared. Ask again to prepare a fresh one."
	return ""


def _plain_error(exc: Exception) -> str:
	"""ERPNext validation messages are written for users; anything else is logged, not shown."""
	if isinstance(exc, frappe.ValidationError):
		from frappe.utils import strip_html

		text = strip_html(str(exc)).strip()
		if text:
			return text
	frappe.log_error(title="ERP AI approval failed")
	return "The change could not be saved. Your administrator can see the details in the Error Log."


def _save_pending(doc) -> None:
	# Users cannot write cards over REST; approve/reject change them here, with the lock flag set.
	frappe.flags.erp_ai_mutate_pending = True
	try:
		doc.save(ignore_permissions=True)
	finally:
		frappe.flags.erp_ai_mutate_pending = False


def _claim_import_start(name: str) -> bool:
	"""One caller marks the stored import as claimed. A second caller sees the same JSON and stops."""
	current = frappe.db.get_value("ERP AI Pending Action", name, "result_json") or ""
	try:
		data = json.loads(current) if current else {}
	except Exception:
		data = {}
	if not isinstance(data, dict) or data.get("start_claimed") or not data.get("data_import"):
		return False
	data["start_claimed"] = True
	frappe.db.sql(
		"""update `tabERP AI Pending Action`
		set result_json=%s
		where name=%s and status='approved' and result_json=%s""",
		(json.dumps(data, ensure_ascii=False), name, current),
	)
	return int(frappe.db.sql("select row_count()")[0][0] or 0) == 1


def _approve_import(doc, acknowledgment_text: str) -> dict:
	"""Create one Data Import, commit it, then start it. A failed start stays retryable."""
	from erpnext_ai_assistant.services.imports import execute_import, import_status_message

	payload = json.loads(doc.payload_json) if isinstance(doc.payload_json, str) else (doc.payload_json or {})
	doc.acknowledgment_text = acknowledgment_text.strip()
	doc.acknowledged = 1
	doc.resolved_by = frappe.session.user
	doc.resolved_at = frappe.utils.now_datetime()
	stored = json.loads(doc.result_json) if doc.result_json else {}
	if not isinstance(stored, dict):
		stored = {}
	created = stored if stored.get("data_import") else None
	if doc.status == "pending":
		try:
			created = execute_import(payload)
		except Exception as exc:
			doc.status = "failed"
			doc.result_json = json.dumps({"error": str(exc)}, ensure_ascii=False)
			_save_pending(doc)
			frappe.throw(str(exc))
		doc.status = "approved"
		doc.result_json = json.dumps(created, ensure_ascii=False)
		_save_pending(doc)
		frappe.db.commit()
	elif not created or not created.get("data_import"):
		frappe.throw("This import has no Data Import to resume")
	if not _claim_import_start(doc.name):
		current = frappe.db.get_value("ERP AI Pending Action", doc.name, "status")
		if current == "executed":
			report = import_status_message(created["data_import"], "en")
			return {
				"status": "executed",
				"result": created,
				"link": {"desk_route": f"/desk/data-import/{created['data_import']}", "label": created["data_import"]},
				"message": report["message"],
				"files": report.get("files") or [],
			}
		frappe.throw("Import start is already in progress")
	frappe.db.commit()
	data_import = frappe.get_doc("Data Import", created["data_import"])
	try:
		started = data_import.start_import()
	except Exception as exc:
		failed = dict(created)
		failed["start_claimed"] = False
		failed["startup_error"] = str(exc)
		frappe.db.set_value(
			"ERP AI Pending Action",
			doc.name,
			"result_json",
			json.dumps(failed, ensure_ascii=False),
		)
		frappe.db.commit()
		frappe.throw(str(exc))
	lang = "ar" if re.search(r"[\u0600-\u06FF]", doc.summary or "") else "en"
	report = import_status_message(data_import.name, lang)
	if started is False and report["status"] == "Pending" and not (data_import.template_warnings or "").strip():
		note = "الاستيراد في قائمة الانتظار.\n" if lang == "ar" else "The import is already queued.\n"
		report["message"] = note + report["message"]
	if doc.chat and report.get("message"):
		from erpnext_ai_assistant.services.naming import as_title

		frappe.get_doc(
			{
				"doctype": "ERP AI Message",
				"title": as_title("ERP AI Message", report["message"][:80]),
				"chat": doc.chat,
				"role": "assistant",
				"content": report["message"],
				"status": "complete",
			}
		).insert(ignore_permissions=True)
	frappe.db.set_value("ERP AI Pending Action", doc.name, "status", "executed")
	frappe.db.commit()
	return {
		"status": "executed",
		"result": created,
		"link": {"desk_route": f"/desk/data-import/{data_import.name}", "label": data_import.name},
		"message": report["message"],
		"files": report.get("files") or [],
	}


@frappe.whitelist(methods=["POST"])
def reject_action(pending_action: str, reason: str | None = None):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	frappe.db.sql("select name from `tabERP AI Pending Action` where name=%s for update", pending_action)
	doc = frappe.get_doc("ERP AI Pending Action", pending_action)
	if doc.user != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw("Not your pending action", frappe.PermissionError)
	if doc.status != "pending":
		frappe.throw(f"Cannot reject an action that is {doc.status}")
	doc.status = "rejected"
	doc.resolved_by = frappe.session.user
	doc.resolved_at = frappe.utils.now_datetime()
	doc.result_json = json.dumps({"reason": (reason or "")[:500]}, ensure_ascii=False)
	_save_pending(doc)
	return {"status": "rejected"}


@frappe.whitelist()
def list_chats(limit: int = 30):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	return frappe.get_list(
		"ERP AI Chat",
		filters={"user": frappe.session.user},
		fields=["name", "title", "route", "status", "language", "modified"],
		order_by="modified desc",
		limit_page_length=min(int(limit or 30), 100),
	)


@frappe.whitelist()
def get_chat_messages(chat_id: str):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	chat = frappe.get_doc("ERP AI Chat", chat_id)
	if chat.user != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw("Not your chat", frappe.PermissionError)
	return frappe.get_list(
		"ERP AI Message",
		filters={"chat": chat_id},
		fields=["name", "role", "content", "status", "reasoning_json", "creation"],
		order_by="creation asc",
		limit_page_length=200,
	)


@frappe.whitelist()
def bootstrap(route: str | None = None):
	"""Panel boot: resolved persona, overlay match, blocked state."""
	if frappe.session.user == "Guest":
		return {"allowed": False, "reason": "guest"}
	settings = frappe.get_single("ERP AI Settings")
	blocked = abuse_mod.is_user_blocked()
	from erpnext_ai_assistant.services.persona import resolve_persona

	resolved = resolve_persona(route, frappe.session.user)
	persona = {
		"name": resolved.get("name") or "",
		"panel_label": resolved.get("panel_label") or "Frappe helper",
		"panel_label_ar": resolved.get("panel_label_ar") or "مساعد العمل",
	}
	pages = [
		{"path_pattern": r.path_pattern, "label": r.label, "host_hint": r.host_hint, "enabled": r.enabled}
		for r in (settings.overlay_pages or [])
		if r.enabled
	]
	return {
		"allowed": (not blocked) and bool(settings.enabled),
		"blocked": blocked,
		"persona": persona,
		"branding": {
			"title": (getattr(settings, "panel_title", None) or "").strip() or "ERP Assistant",
			"subtitle": (getattr(settings, "panel_subtitle", None) or "").strip() or "مساعد أعمالك",
			"hint": (getattr(settings, "panel_hint", None) or "").strip()
			or "يجيب من بيانات العمل المتاحة لك. لا يُنفَّذ أي تعديل قبل موافقتك.",
			"hint_en": (getattr(settings, "panel_hint_en", None) or "").strip()
			or "Answers from the business data you can access. Nothing changes until you approve.",
		},
		"overlay_pages": pages,
		"app_routes": _app_routes(),
		"work_only": bool(settings.work_only),
		"provider": "openai",
		"model": settings.model or "gpt-4o-mini",
		"has_api_key": bool(settings.api_key or frappe.conf.get("erp_ai_openai_api_key")),
		"has_erpnext": "erpnext" in set(frappe.get_installed_apps()),
	}


@frappe.whitelist(methods=["POST"])
def clear_my_memory():
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	frappe.db.delete("ERP AI Memory", {"user": frappe.session.user, "scope": "user"})
	return {"ok": True}


@frappe.whitelist()
def list_my_memory():
	"""List confirmed user-scope memory for the session user only."""
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	rows = frappe.get_all(
		"ERP AI Memory",
		filters={"user": frappe.session.user, "scope": "user", "enabled": 1},
		fields=["name", "key", "value", "modified"],
		order_by="modified desc",
		limit_page_length=50,
	)
	return {"items": rows}


@frappe.whitelist(methods=["POST"])
def save_my_memory(key: str, value: str, confirmed: int | bool | str = 0):
	"""Save only when the panel sends confirmed=1. The model cannot call this."""
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	ok = confirmed in (True, 1, "1", "true", "True")
	if not ok:
		frappe.throw("Confirm the fact before saving", frappe.ValidationError)
	key = (key or "").strip()[:80]
	value = (value or "").strip()[:500]
	if not key or not value:
		frappe.throw("Key and value are required")
	from erpnext_ai_assistant.services.naming import as_title

	title = as_title("ERP AI Memory", f"{frappe.session.user}:{key}")
	existing = frappe.db.get_value(
		"ERP AI Memory",
		{"user": frappe.session.user, "scope": "user", "key": key},
		"name",
	)
	if existing:
		doc = frappe.get_doc("ERP AI Memory", existing)
		doc.value = value
		doc.enabled = 1
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "ERP AI Memory",
				"title": title,
				"user": frappe.session.user,
				"scope": "user",
				"key": key,
				"value": value,
				"enabled": 1,
			}
		)
		doc.insert(ignore_permissions=True)
	return {"ok": True, "name": doc.name, "key": key}


def _record_link(doctype: str, name: str) -> dict:
	"""Open the record on Desk. Any installed app can show this same link."""
	from urllib.parse import quote

	from erpnext_ai_assistant.services.apps import installed_app_routes

	slug = frappe.scrub(doctype).replace("_", "-")
	safe = quote(name, safe="")
	app_route = None
	try:
		module = frappe.db.get_value("DocType", doctype, "module")
		app = frappe.local.module_app.get(frappe.scrub(module)) if module else None
	except Exception:
		app = None
	if app:
		for row in installed_app_routes():
			if row.get("app") == app and row.get("route"):
				app_route = row["route"]
				break
	return {
		"doctype": doctype,
		"name": name,
		"label": f"{doctype} {name}",
		"desk_route": f"/desk/{slug}/{safe}",
		"crm_route": app_route,
		"route": ["desk", slug, name],
	}


def _created_message(action: str, doctype: str, result: dict) -> str:
	link = (result or {}).get("link") or {}
	name = (result or {}).get("name") or link.get("name") or ""
	path = link.get("desk_route") or ""
	if action == "delete":
		return f"Deleted {doctype} {result.get('deleted') or name}."
	verb = {"create": "Created", "update": "Updated", "submit": "Submitted", "cancel": "Cancelled"}.get(
		action, "Saved"
	)
	# Marker is turned into an Open button in the panel, including chat history.
	crm = link.get("crm_route") or ""
	marker = f"[[open:{path}|{doctype} {name}|{crm}]]" if path else ""
	return f"{verb} {doctype} {name}.\n{marker}".strip()


def _e164(number: str | None, default_region: str = "SA") -> str | None:
	"""Return a valid E.164 number, or None. Local 05… numbers are read as SA."""
	import phonenumbers

	raw = (number or "").strip()
	if not raw:
		return None
	try:
		parsed = phonenumbers.parse(raw, default_region)
	except phonenumbers.NumberParseException:
		return None
	if not phonenumbers.is_valid_number(parsed):
		return None
	return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def _execute(action: str, doctype: str, name: str | None, payload: dict):
	if action == "create":
		payload = dict(payload or {})
		note_text = (payload.pop("_note_text", None) or "").strip()
		lead_name = payload.pop("_lead_name", None)
		if doctype == "CRM Call Log":
			for key in ("from", "to"):
				number = _e164(payload.get(key))
				if not number:
					frappe.throw(f"{doctype} field {key} needs a real phone number. It was not guessed.")
				payload[key] = number
		doc = frappe.get_doc({"doctype": doctype, **payload})
		doc.insert()
		if doctype == "CRM Call Log" and doc.get("reference_doctype") and doc.get("reference_docname"):
			if hasattr(doc, "link_with_reference_doc"):
				doc.link_with_reference_doc(doc.reference_doctype, doc.reference_docname)
				doc.save()
		if doctype == "CRM Call Log" and note_text:
			note = frappe.get_doc(
				{
					"doctype": "FCRM Note",
					"title": "Call note",
					"content": note_text,
					"reference_doctype": "CRM Call Log",
					"reference_docname": doc.name,
				}
			)
			note.insert()
			doc.note = note.name
			doc.save()
		link = _record_link(doctype, doc.name)
		if lead_name:
			link["label"] = f"{doctype} {lead_name}"
		return {"name": doc.name, "link": link}
	if action == "update":
		doc = frappe.get_doc(doctype, name)
		doc.update(payload or {})
		doc.save()
		return {"name": doc.name, "link": _record_link(doctype, doc.name)}
	if action == "delete":
		frappe.delete_doc(doctype, name)
		return {"deleted": name}
	if action == "submit":
		doc = frappe.get_doc(doctype, name)
		doc.submit()
		return {"name": doc.name, "docstatus": doc.docstatus, "link": _record_link(doctype, doc.name)}
	if action == "cancel":
		doc = frappe.get_doc(doctype, name)
		doc.cancel()
		return {"name": doc.name, "docstatus": doc.docstatus, "link": _record_link(doctype, doc.name)}
	frappe.throw(f"Unknown action {action}")
