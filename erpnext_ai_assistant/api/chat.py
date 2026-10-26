"""Whitelisted chat API — session user only, no allow_guest."""

from __future__ import annotations

import json

import frappe
from erpnext_ai_assistant.services import run_chat as orch
from erpnext_ai_assistant.services.moderation import abuse as abuse_mod


@frappe.whitelist()
def run(message: str, route: str | None = None, chat_id: str | None = None):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	if not (message or "").strip():
		frappe.throw("Empty message")
	return orch.run_chat(message=message.strip(), route=route, chat_id=chat_id)


@frappe.whitelist()
def approve_action(pending_action: str, acknowledgment_text: str, acknowledged: int | bool = 0):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	if not acknowledged:
		frappe.throw("Written acknowledgment required")
	if not (acknowledgment_text or "").strip():
		frappe.throw("Acknowledgment text required")
	if abuse_mod.is_user_blocked():
		frappe.throw(abuse_mod.blocked_message())

	doc = frappe.get_doc("ERP AI Pending Action", pending_action)
	if doc.user != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw("Not your pending action", frappe.PermissionError)
	if doc.status != "pending":
		frappe.throw(f"Action is {doc.status}")

	dt = doc.target_doctype
	action = doc.action_type
	perm_map = {
		"create": "create",
		"update": "write",
		"delete": "delete",
		"submit": "submit",
		"cancel": "cancel",
	}
	need = perm_map.get(action, "write")
	if not frappe.has_permission(dt, need):
		frappe.throw(f"No {need} permission for {dt}", frappe.PermissionError)

	doc.acknowledgment_text = acknowledgment_text.strip()
	doc.acknowledged = 1
	doc.status = "approved"
	doc.resolved_by = frappe.session.user
	doc.resolved_at = frappe.utils.now_datetime()

	payload = {}
	if doc.payload_json:
		payload = json.loads(doc.payload_json) if isinstance(doc.payload_json, str) else doc.payload_json

	try:
		result = _execute(action, dt, doc.target_name, payload)
		doc.status = "executed"
		doc.result_json = json.dumps(result, ensure_ascii=False, default=str)
	except Exception as e:
		doc.status = "failed"
		doc.result_json = json.dumps({"error": str(e)}, ensure_ascii=False)
		doc.save()
		raise
	doc.save()
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


@frappe.whitelist()
def reject_action(pending_action: str, reason: str | None = None):
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	doc = frappe.get_doc("ERP AI Pending Action", pending_action)
	if doc.user != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw("Not your pending action", frappe.PermissionError)
	doc.status = "rejected"
	doc.resolved_by = frappe.session.user
	doc.resolved_at = frappe.utils.now_datetime()
	doc.result_json = json.dumps({"reason": reason or ""}, ensure_ascii=False)
	doc.save()
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
def bootstrap():
	"""Panel boot: persona labels, overlay match, blocked state."""
	if frappe.session.user == "Guest":
		return {"allowed": False, "reason": "guest"}
	settings = frappe.get_single("ERP AI Settings")
	blocked = abuse_mod.is_user_blocked()
	persona = {"panel_label": "The ERPNext-AI-Assistant", "panel_label_ar": "مساعد ERPNext"}
	if settings.active_persona and frappe.db.exists("ERP AI Persona", settings.active_persona):
		p = frappe.get_doc("ERP AI Persona", settings.active_persona)
		persona = {
			"panel_label": p.panel_label or "The ERPNext-AI-Assistant",
			"panel_label_ar": p.panel_label_ar or "مساعد ERPNext",
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
		"overlay_pages": pages,
		"work_only": bool(settings.work_only),
		"provider": "openai",
		"model": settings.model or "gpt-4o-mini",
		"has_api_key": bool(settings.api_key or frappe.conf.get("erp_ai_openai_api_key")),
	}


@frappe.whitelist()
def clear_my_memory():
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	frappe.db.delete("ERP AI Memory", {"user": frappe.session.user, "scope": "user"})
	return {"ok": True}


def _record_link(doctype: str, name: str) -> dict:
	"""Desk route plus a CRM route when this DocType lives in the CRM SPA."""
	from urllib.parse import quote

	slug = frappe.scrub(doctype).replace("_", "-")
	safe = quote(name, safe="")
	crm_prefix = {
		"CRM Lead": "/crm/leads/",
		"CRM Deal": "/crm/deals/",
		"Contact": "/crm/contacts/",
		"CRM Organization": "/crm/organizations/",
	}.get(doctype)
	return {
		"doctype": doctype,
		"name": name,
		"label": f"{doctype} {name}",
		"desk_route": f"/desk/{slug}/{safe}",
		"crm_route": (crm_prefix + safe) if crm_prefix else None,
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


def _execute(action: str, doctype: str, name: str | None, payload: dict):
	if action == "create":
		payload = dict(payload or {})
		note_text = (payload.pop("_note_text", None) or "").strip()
		lead_name = payload.pop("_lead_name", None)
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
		if doctype == "CRM Call Log" and doc.get("reference_doctype") == "CRM Lead" and doc.get("reference_docname"):
			from urllib.parse import quote

			link["crm_route"] = "/crm/leads/" + quote(doc.reference_docname, safe="")
			link["label"] = f"Lead {lead_name or doc.reference_docname}"
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
