"""Session-user tool registry. Never use ignore_permissions or get_all for ERP data."""

from __future__ import annotations

import inspect
import json
import re

import frappe
from erpnext_ai_assistant.services.arabic import normalize_arabic
from erpnext_ai_assistant.services.rdf import graph as rdf_graph

ALLOWED_RUN_METHODS = frozenset(
	{
		"frappe.auth.get_logged_user",
		"frappe.desk.query_report.run",
	}
)

NAME_HINT = re.compile(
	r"(اسم|الاسم|lead_name|first_name|last_name|who is|find|ابحث|\bname\b)",
	re.I,
)


def publish_step(chat_id: str, step: dict):
	if not chat_id:
		return
	frappe.publish_realtime(
		event="erp_ai_thinking",
		message=step,
		room=f"erp_ai_chat:{chat_id}",
		after_commit=False,
	)


def tool_rdf_lookup(query: str, doctype: str | None = None, module: str | None = None, app: str | None = None) -> list[dict]:
	return rdf_graph.lookup(query, doctype=doctype, module=module, app=app)


def tool_erp_query(
	doctype: str,
	filters=None,
	or_filters=None,
	fields=None,
	limit: int = 20,
	order_by: str | None = None,
) -> list[dict]:
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(f"No read permission for {doctype}", frappe.PermissionError)
	kwargs = {
		"doctype": doctype,
		"filters": filters or {},
		"fields": fields or ["name"],
		# Cap high enough for summaries/charts; still permission-scoped via get_list
		"limit_page_length": min(int(limit or 20), 500),
	}
	if or_filters:
		kwargs["or_filters"] = or_filters
	if order_by:
		kwargs["order_by"] = order_by
	# CRITICAL: get_list (not get_all) — respects permissions
	return frappe.get_list(**kwargs)


def tool_erp_count(doctype: str, filters=None) -> dict:
	"""Permission-scoped total. Uses DatabaseQuery, not frappe.db.count or get_all."""
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(f"No read permission for {doctype}", frappe.PermissionError)
	from frappe.model.db_query import DatabaseQuery

	rows = DatabaseQuery(doctype).execute(
		fields=["count(name) as total"],
		filters=filters or {},
		ignore_permissions=False,
		limit=None,
	)
	total = 0
	if rows:
		total = int(rows[0].get("total") or rows[0].get("count(name)") or 0)
	return {"doctype": doctype, "total": total}


def tool_erp_get_doc(doctype: str, name: str) -> dict:
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(f"No read permission for {doctype}", frappe.PermissionError)
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	doc.apply_fieldlevel_read_permissions()
	return doc.as_dict()


def tool_erp_report(report_name: str, filters=None) -> dict:
	if not frappe.has_permission("Report", "read"):
		# still try running via query report which checks report perms
		pass
	from frappe.desk.query_report import run

	return run(report_name, filters=filters or {})


def tool_get_doctype_meta(doctype: str) -> dict:
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(f"No read permission for {doctype}", frappe.PermissionError)
	meta = frappe.get_meta(doctype)
	return {
		"name": meta.name,
		"fields": [
			{
				"fieldname": df.fieldname,
				"label": df.label,
				"fieldtype": df.fieldtype,
				"options": df.options,
			}
			for df in meta.fields
			if df.fieldname
		],
	}


def tool_run_method(method: str, **kwargs):
	if method not in ALLOWED_RUN_METHODS:
		frappe.throw(f"Method not allowlisted: {method}", frappe.PermissionError)
	return frappe.call(method, **kwargs)


def tool_read_doctype_controller(doctype: str) -> dict:
	if "System Manager" not in frappe.get_roles():
		frappe.throw("System Manager only", frappe.PermissionError)
	controller = frappe.get_controller(doctype)
	path = inspect.getfile(controller)
	try:
		source = open(path, encoding="utf-8").read()
	except Exception as e:
		return {"path": path, "error": str(e)}
	return {"path": path, "source": source[:20000]}


def tool_list_installed_apps(query: str | None = None) -> list[dict]:
	"""Describe apps installed on this site (custom + standard). Session-safe."""
	q = (query or "").lower().strip()
	out = []
	for app in frappe.get_installed_apps():
		title = app
		description = ""
		try:
			title = frappe.get_attr(f"{app}.hooks.app_title") or app
		except Exception:
			pass
		try:
			description = frappe.get_attr(f"{app}.hooks.app_description") or ""
		except Exception:
			pass
		row = {
			"app": app,
			"title": title,
			"description": description,
		}
		if app == "erpnext_ai_assistant":
			row["notes"] = "The ERPNext-AI-Assistant panel."
		elif app == "hrms":
			row["notes"] = "HRMS — Employee, Salary Slip, leave, attendance."
		elif app == "erpnext":
			row["notes"] = "ERPNext — accounts, stock, buying, selling."
		hay = f"{app} {title} {description} {row.get('notes') or ''}".lower()
		if q and q not in hay and not any(part in hay for part in q.replace("_", " ").split() if len(part) > 2):
			continue
		out.append(row)
	return out


def read_skill(title: str | None = None, route: str | None = None) -> list[dict]:
	roles = set(frappe.get_roles())
	filters = {"enabled": 1}
	skills = frappe.get_all(
		"ERP AI Skill",
		filters=filters,
		fields=["name", "title", "description", "routes", "doctypes", "priority"],
		order_by="priority asc",
	)
	out = []
	for s in skills:
		role_rows = frappe.get_all(
			"ERP AI Skill Role", filters={"parent": s.name}, pluck="role"
		)
		if role_rows and not (roles & set(role_rows)):
			continue
		if title and s.title != title:
			continue
		if route and s.routes:
			patterns = [p.strip() for p in (s.routes or "").splitlines() if p.strip()]
			if patterns and not any(route.startswith(p) or p in route for p in patterns):
				# still include high-priority CRM skill when route matches loosely
				if not any(p.rstrip("/") in route for p in patterns):
					continue
		out.append(s)
	return out


def propose_write(chat: str, action_type: str, target_doctype: str, payload: dict, summary: str | None = None, target_name: str | None = None, message: str | None = None) -> dict:
	settings = frappe.get_single("ERP AI Settings")
	if not settings.allow_pending_writes:
		frappe.throw("Writes are disabled in ERP AI Settings")
	from erpnext_ai_assistant.services.naming import as_title
	from erpnext_ai_assistant.services.schema import prepare_payload
	from erpnext_ai_assistant.services.writes import payload_hash, summary_from_payload

	if action_type == "create":
		prepared = prepare_payload(target_doctype, payload or {}, "create")
		if prepared["missing"] or prepared["errors"]:
			frappe.throw(
				"Refusing to propose an incomplete write: "
				+ ", ".join(item.get("fieldname") or "" for item in prepared["missing"])
				+ " "
				+ "; ".join(prepared["errors"])
			)
		payload = prepared["payload"]
	body = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True, default=str)
	card = summary_from_payload(action_type, target_doctype, payload or {}, target_name)
	doc = frappe.get_doc(
		{
			"doctype": "ERP AI Pending Action",
			"title": as_title("ERP AI Pending Action", card[:80] or f"{action_type} {target_doctype}"),
			"chat": chat,
			"message": message,
			"user": frappe.session.user,
			"action_type": action_type,
			"target_doctype": target_doctype,
			"target_name": target_name,
			"payload_json": body,
			"payload_hash": payload_hash(payload or {}),
			"summary": card,
			"status": "pending",
		}
	)
	doc.insert()
	return {
		"pending_action": doc.name,
		"summary": card,
		"status": "pending",
		"payload_hash": doc.payload_hash,
		"target_doctype": target_doctype,
		"action_type": action_type,
	}


def detect_and_query_leads(message: str, chat_id: str | None = None) -> dict | None:
	"""For name questions on CRM Lead: RDF first, then get_list with lead_name fields."""
	if not NAME_HINT.search(message or ""):
		# still try extracting a bare Arabic/Latin token as person name on CRM routes
		pass
	doctype = "CRM Lead" if frappe.db.exists("DocType", "CRM Lead") else "Lead"
	if not frappe.db.exists("DocType", doctype):
		return None
	if not frappe.has_permission(doctype, "read"):
		return {"error": "within_permissions", "rows": []}

	publish_step(
		chat_id or "",
		{
			"id": "rdf",
			"label_ar": "البحث في مخطط الحقول",
			"label_en": "RDF field lookup",
			"tool": "tool_rdf_lookup",
			"status": "running",
		},
	)
	rdf_hits = tool_rdf_lookup(message, doctype=doctype if doctype == "CRM Lead" else None)
	# Force lead name fields for person search
	name_fields = ["lead_name", "first_name", "last_name"]
	if doctype == "Lead":
		name_fields = ["lead_name", "first_name", "last_name"]
	for h in rdf_hits:
		if h.get("fieldname") in name_fields or normalize_arabic(h.get("label") or "") in (
			normalize_arabic("اسم"),
			normalize_arabic("الاسم الكامل"),
		):
			if h["fieldname"] not in name_fields:
				name_fields.append(h["fieldname"])

	publish_step(
		chat_id or "",
		{
			"id": "rdf",
			"label_ar": "البحث في مخطط الحقول",
			"label_en": "RDF field lookup",
			"tool": "tool_rdf_lookup",
			"status": "done",
			"ms": 0,
		},
	)

	# Extract search token: quoted, or Arabic word, or Latin word after "find"
	token = _extract_name_token(message)
	if not token:
		return {"rdf": rdf_hits, "rows": [], "fields_used": name_fields}

	or_filters = [[f, "like", f"%{token}%"] for f in name_fields]
	publish_step(
		chat_id or "",
		{
			"id": "erp_query",
			"label_ar": "استعلام عن العملاء المحتملين",
			"label_en": "Query CRM leads",
			"tool": "tool_erp_query",
			"status": "running",
		},
	)
	rows = tool_erp_query(
		doctype,
		or_filters=or_filters,
		fields=["name", "lead_name", "first_name", "last_name", "status", "lead_owner", "mobile_no", "organization", "email"]
		if doctype == "CRM Lead"
		else ["name", "lead_name", "status"],
		limit=20,
	)
	publish_step(
		chat_id or "",
		{
			"id": "erp_query",
			"label_ar": "استعلام عن العملاء المحتملين",
			"label_en": "Query CRM leads",
			"tool": "tool_erp_query",
			"status": "done",
		},
	)
	return {
		"doctype": doctype,
		"token": token,
		"fields_used": name_fields,
		"rdf": rdf_hits,
		"rows": rows,
	}


_AR_SKIP = {
	normalize_arabic(w)
	for w in (
		"اسم",
		"الاسم",
		"من",
		"عن",
		"ابحث",
		"هل",
		"ما",
		"هي",
		"هو",
		"في",
		"على",
		"هذا",
		"هذه",
		"العميل",
		"عميل",
		"البحث",
		"اعثر",
		"وجد",
		"لدي",
		"عندي",
		"ممكن",
		"أريد",
		"اريد",
	)
}


def _extract_name_token(message: str) -> str | None:
	if not message:
		return None
	m = re.search(r"[«\"']([^\"'»]+)[»\"']", message)
	if m:
		return m.group(1).strip()
	# Walk Arabic tokens; skip question words.
	for token in re.findall(r"[\u0600-\u06FF]{2,}", message):
		token = re.sub(r"[؟?!,.،؛:]+$", "", token)
		if len(token) < 2:
			continue
		if normalize_arabic(token) not in _AR_SKIP:
			return token
	for token in re.findall(r"\b([A-Za-z]{2,})\b", message):
		if token.lower() not in {
			"find",
			"lead",
			"name",
			"who",
			"is",
			"the",
			"about",
			"show",
			"list",
			"search",
			"for",
			"please",
			"crm",
		}:
			return token
	return None
