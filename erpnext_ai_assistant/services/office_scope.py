"""A skill route answers as that office, not as the general ERP menu.

The generic assistant asks "count, list, or create" whenever a word looks like a
DocType. On a Feras screen that question contradicts the open file. A skill
whose description starts with `server_policy:` and whose route matches turns
that menu off and keeps the open record in front of the model.
"""

from __future__ import annotations

import json

import frappe


def activate(route: str | None, context=None) -> dict | None:
	ctx = _context(context)
	skill = _matching_skill(route, ctx)
	if not skill and not str(ctx.get("doctype") or "").startswith("FL "):
		frappe.flags.erp_ai_office = None
		frappe.flags.erp_ai_context = None
		return None
	policy = _policy(skill)
	doctypes = _doctype_lines(skill.get("doctypes") if skill else "")
	if not doctypes:
		# No list on the skill: stay inside the open record's module, never "everything".
		doctypes = _module_doctypes(ctx.get("doctype")) or list((policy.get("outbound") or {}).keys())
	ctx["allow"] = _server_allow(ctx)
	office = {"context": ctx, "policy": policy, "doctypes": doctypes}
	frappe.flags.erp_ai_office = office
	frappe.flags.erp_ai_context = ctx
	return office


def _module_doctypes(doctype: str | None) -> list[str]:
	if not doctype or not frappe.db.exists("DocType", doctype):
		return []
	module = frappe.db.get_value("DocType", doctype, "module")
	return frappe.get_all("DocType", filters={"module": module}, pluck="name") if module else [doctype]


def _server_allow(ctx: dict) -> list[dict]:
	"""Keep only the allow rows the user could do by hand. The browser does not decide what may be written."""
	kept = []
	for row in ctx.get("allow") or []:
		if not isinstance(row, dict):
			continue
		action, doctype = row.get("action") or "", row.get("doctype") or ""
		name, matter = row.get("name") or "", row.get("matter") or ""
		if not doctype or not frappe.db.exists("DocType", doctype):
			continue
		if action == "update":
			# Only the record that is open on screen, and only with write permission on it.
			if not name or name != ctx.get("name") or doctype != ctx.get("doctype"):
				continue
			if not frappe.db.exists(doctype, name) or not frappe.has_permission(doctype, "write", name):
				continue
		elif action == "create":
			if not frappe.has_permission(doctype, "create"):
				continue
			if matter and not (frappe.db.exists("FL Matter", matter) and frappe.has_permission("FL Matter", "write", matter)):
				continue
		else:
			continue
		kept.append({k: v for k, v in {"action": action, "doctype": doctype, "name": name, "matter": matter}.items() if v})
	return kept


def current() -> dict | None:
	office = getattr(frappe.flags, "erp_ai_office", None)
	return office if isinstance(office, dict) else None


def preflight(message: str) -> str:
	office = current() or {}
	if (office.get("policy") or {}).get("broken"):
		return "مساعد المكتب غير متاح الآن. أبلغ مدير النظام." if _arabic(message) else "The office assistant is unavailable. Tell your administrator."
	fn = (office.get("policy") or {}).get("preflight")
	if not callable(fn):
		return ""
	return fn(message) or ""


def note(lang: str = "ar") -> str:
	"""Instructions that keep the model on the open file."""
	office = current() or {}
	policy = office.get("policy") or {}
	ctx = office.get("context") or {}
	lines = [policy.get("addendum") or ""]
	name = ctx.get("name") or ""
	if name:
		lines.append(
			f"The open record is {ctx.get('doctype') or ''} {name} ({ctx.get('title') or ''}). "
			"Answer about that record. Do not ask whether to count, list, or create."
		)
	elif lang == "ar":
		lines.append("أنت على شاشة المكتب. أجب عن الملف المفتوح. لا تعرض قائمة عدد أو عرض أو إنشاء.")
	else:
		lines.append("You are on an office screen. Answer about the open record. Do not offer count, list, or create.")
	lines.append("Do not mention ERPNext, spreadsheets, or other apps.")
	return "\n".join(line for line in lines if line)


def guard_doctype(doctype: str) -> dict | None:
	office = current()
	if not office or not doctype:
		return None
	allowed = set(office.get("doctypes") or [])
	if not allowed or doctype in allowed:
		return None
	message = (office.get("policy") or {}).get("outside_message") or "هذا الطلب خارج ملفات المكتب."
	return {"error": message, "status": "failed"}


def check_write(action: str, doctype: str, payload: dict, target_name: str | None = None) -> str:
	blocked = guard_doctype(doctype)
	if blocked:
		return blocked["error"]
	office = current() or {}
	fn = (office.get("policy") or {}).get("check_write")
	if not callable(fn):
		return ""
	message = getattr(frappe.flags, "erp_ai_user_text", "") or ""
	return fn(action, doctype, payload or {}, target_name, message) or ""


def allows(feature: str) -> bool:
	"""memory, knowledge, imports, attachments: off when the office policy says False."""
	office = current()
	if not office:
		return True
	policy = office.get("policy") or {}
	return not policy.get("broken") and policy.get(feature) is not False


def refusal(feature: str) -> str:
	policy = (current() or {}).get("policy") or {}
	key = {"attachments": "attachment_message", "imports": "import_message"}.get(feature, "outside_message")
	return policy.get(key) or policy.get("outside_message") or "هذا الطلب خارج ملفات المكتب."


def clamp_fields(doctype: str, fields):
	"""The fields the office lets the model read for this DocType."""
	office = current()
	fn = ((office or {}).get("policy") or {}).get("clamp_fields")
	return fn(doctype, fields) if office and callable(fn) else fields


def filter_rows(doctype: str, rows):
	office = current()
	outbound = ((office or {}).get("policy") or {}).get("outbound") or {}
	allowed = set(outbound.get(doctype) or ())
	if not office or not allowed:
		return rows
	allowed.add("name")
	return [{k: v for k, v in (row or {}).items() if k in allowed} for row in rows or []]


def _arabic(text: str) -> bool:
	return any("\u0600" <= ch <= "\u06ff" for ch in text or "")


def _matching_skill(route: str | None, ctx: dict):
	if not frappe.db.exists("DocType", "ERP AI Skill"):
		return None
	rows = frappe.get_all(
		"ERP AI Skill",
		filters={"enabled": 1},
		fields=["name", "routes", "doctypes", "description"],
		order_by="priority asc",
	)
	doctype = ctx.get("doctype") or ""
	for row in rows:
		if "server_policy:" not in (row.description or ""):
			continue
		listed = _doctype_lines(row.doctypes)
		if _route_hit(row.routes, route) or (doctype and doctype in listed):
			return row
	return None


def _policy(skill) -> dict:
	if not skill:
		return {}
	method = ""
	for line in (skill.get("description") or "").splitlines():
		if line.strip().lower().startswith("server_policy:"):
			method = line.split(":", 1)[1].strip()
			break
	if not method:
		return {}
	try:
		result = frappe.get_attr(method)() or {}
	except Exception:
		# Fail closed: a skill that names a policy but cannot load it refuses every turn.
		frappe.log_error(title=f"ERP AI office policy failed: {method}")
		return {"broken": True}
	return result if isinstance(result, dict) and result else {"broken": True}


def _route_hit(routes: str | None, route: str | None) -> bool:
	route = route or ""
	parts = [part for part in route.split("/") if part]
	for pattern in _doctype_lines(routes):
		if route == pattern or route.startswith(pattern.rstrip("/") + "/") or pattern in route:
			return True
		tail = pattern.strip("/").split("/")[-1]
		if tail and tail in parts:
			return True
	return False


def _doctype_lines(value: str | None) -> list[str]:
	text = (value or "").replace(",", "\n")
	return [line.strip() for line in text.splitlines() if line.strip()]


def _context(raw) -> dict:
	if isinstance(raw, str):
		try:
			raw = json.loads(raw) if raw.strip() else {}
		except Exception:
			raw = {}
	return raw if isinstance(raw, dict) else {}
