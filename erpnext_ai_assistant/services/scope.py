"""DocType scope from an ERP AI Skill.

A skill whose DocTypes field is filled, and whose route matches, is an
allow-list. The registry enforces it. A `server_policy:` line in the skill
description names a function that returns outbound fields, write rules, and
retention. That line is stripped before the description reaches the model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import frappe


@dataclass
class Scope:
	doctypes: set[str]
	policy: dict = field(default_factory=dict)
	outside_message: str = "هذا الطلب خارج ملفات المكتب."

	def preflight(self, message: str) -> str:
		fn = self.policy.get("preflight")
		if not callable(fn):
			return ""
		return fn(message) or ""


def policy_method_from_text(text: str | None) -> str:
	for line in (text or "").splitlines():
		if line.strip().lower().startswith("server_policy:"):
			return line.split(":", 1)[1].strip()
	return ""


def prompt_text(text: str | None) -> str:
	kept = [line for line in (text or "").splitlines() if not line.strip().lower().startswith("server_policy:")]
	return "\n".join(kept).strip()


def load_policy(method: str) -> dict:
	method = (method or "").strip()
	if not method or method.count(".") < 1:
		return {}
	try:
		fn = frappe.get_attr(method)
	except Exception:
		return {}
	try:
		result = fn() or {}
	except Exception:
		return {}
	return result if isinstance(result, dict) else {}


def scope_for_route(route: str | None) -> Scope | None:
	if not (route or "").strip():
		return None
	from erpnext_ai_assistant.services.tools.registry import read_skill

	names: set[str] = set()
	policy: dict = {}
	for skill in read_skill(route=route):
		listed = _doctype_lines(skill.get("doctypes") if isinstance(skill, dict) else skill.doctypes)
		if not listed:
			continue
		names.update(listed)
		description = skill.get("description") if isinstance(skill, dict) else skill.description
		method = policy_method_from_text(description)
		if method and not policy:
			policy = load_policy(method)
	if not names:
		return None
	message = (policy or {}).get("outside_message") or "هذا الطلب خارج ملفات المكتب."
	return Scope(doctypes=names, policy=policy or {}, outside_message=message)


def bind(route: str | None, context=None) -> Scope | None:
	scope = scope_for_route(route)
	frappe.flags.erp_ai_scope = scope
	frappe.flags.erp_ai_context = _context(context)
	return scope


def current() -> Scope | None:
	scope = getattr(frappe.flags, "erp_ai_scope", None)
	return scope if isinstance(scope, Scope) else None


def guard_doctype(doctype: str) -> dict | None:
	scope = current()
	if not scope or not doctype:
		return None
	if doctype in scope.doctypes:
		return None
	return {"error": scope.outside_message, "status": "failed"}


def filter_catalog(rows: list[dict]) -> list[dict]:
	scope = current()
	if not scope:
		return rows
	return [row for row in rows if (row.get("name") or "") in scope.doctypes]


def clamp_fields(doctype: str, fields):
	scope = current()
	fn = (scope.policy.get("clamp_fields") if scope else None)
	if not callable(fn):
		return fields or ["name"]
	return fn(doctype, fields)


def filter_rows(doctype: str, rows: list[dict]) -> list[dict]:
	scope = current()
	outbound = (scope.policy.get("outbound") if scope else None) or {}
	if not outbound or doctype not in outbound:
		return rows
	allowed = set(outbound[doctype]) | {"name"}
	return [{key: value for key, value in (row or {}).items() if key in allowed} for row in rows]


def assert_write(action: str, doctype: str, payload: dict, target_name: str | None = None) -> str:
	"""Empty when the proposal may be stored."""
	blocked = guard_doctype(doctype)
	if blocked:
		return blocked["error"]
	scope = current()
	fn = (scope.policy.get("check_write") if scope else None)
	if not callable(fn):
		return ""
	message = getattr(frappe.flags, "erp_ai_user_text", "") or ""
	return fn(action, doctype, payload or {}, target_name, message) or ""


def knowledge_enabled_text(description: str | None) -> bool:
	method = policy_method_from_text(description)
	if not method:
		return True
	policy = load_policy(method)
	return policy.get("knowledge") is not False


def import_blocked(doctype: str) -> bool:
	"""True when any enabled scoped skill refuses imports of this DocType."""
	if not doctype or not frappe.db.exists("DocType", "ERP AI Skill"):
		return False
	skills = frappe.get_all("ERP AI Skill", filters={"enabled": 1}, fields=["description", "doctypes"])
	for skill in skills:
		listed = _doctype_lines(skill.doctypes)
		if doctype not in listed:
			continue
		method = policy_method_from_text(skill.description)
		policy = load_policy(method) if method else {}
		if policy.get("imports") is False:
			return True
	return False


def memory_blocked_for_user() -> bool:
	"""True when this user's latest chat sits on a scope that keeps no memory."""
	if not frappe.db.exists("DocType", "ERP AI Chat"):
		return False
	route = frappe.db.get_value(
		"ERP AI Chat",
		{"user": frappe.session.user},
		"route",
		order_by="modified desc",
	)
	scope = scope_for_route(route)
	return bool(scope and scope.policy.get("memory") is False)


def retention_routes() -> list[tuple[str, int]]:
	"""Route prefix and day count for skills that set retention_days."""
	if not frappe.db.exists("DocType", "ERP AI Skill"):
		return []
	found = []
	skills = frappe.get_all("ERP AI Skill", filters={"enabled": 1}, fields=["description", "routes"])
	for skill in skills:
		method = policy_method_from_text(skill.description)
		if not method:
			continue
		days = int(load_policy(method).get("retention_days") or 0)
		if days <= 0:
			continue
		for pattern in _lines(skill.routes):
			found.append((pattern, days))
	return found


def _doctype_lines(value: str | None) -> list[str]:
	text = (value or "").replace(",", "\n")
	return [line.strip() for line in text.splitlines() if line.strip()]


def _lines(value: str | None) -> list[str]:
	return [line.strip() for line in (value or "").splitlines() if line.strip()]


def _context(raw) -> dict:
	if isinstance(raw, str):
		try:
			raw = json.loads(raw) if raw.strip() else {}
		except Exception:
			raw = {}
	if not isinstance(raw, dict):
		return {}
	return raw
