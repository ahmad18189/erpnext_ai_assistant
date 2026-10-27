"""Pick one enabled persona for this user, route, and inferred app.

Order: enabled, then roles (empty means every role), then affinity
(route, then the app inferred from the message, then the app that owns
the route, then a generic persona), then priority. Settings.active_persona
is only the fallback when nothing matches, and the tie-break when scores
are equal.
"""

from __future__ import annotations

import frappe
from erpnext_ai_assistant.services.apps import installed_app_routes


def resolve_persona(route: str | None = None, user: str | None = None, inferred_app: str | None = None) -> dict:
	user = user or getattr(frappe.session, "user", None) or ""
	settings = frappe.get_single("ERP AI Settings")
	active = getattr(settings, "active_persona", None) or ""
	roles = set(frappe.get_roles(user)) if user and user != "Guest" else set()
	installed = set()
	try:
		installed = set(frappe.get_installed_apps())
	except Exception:
		installed = set()
	route_app = _app_for_route(route)
	meta = frappe.get_meta("ERP AI Persona")
	fields = ["name", "persona_name", "panel_label", "panel_label_ar", "tone_instructions"]
	for extra in ("priority", "match_apps", "match_routes"):
		if meta.has_field(extra):
			fields.append(extra)
	rows = frappe.get_all("ERP AI Persona", filters={"enabled": 1}, fields=fields, limit_page_length=100)
	scored = []
	for row in rows:
		if not _role_ok(row.name, roles):
			continue
		apps = _lines(row.get("match_apps"))
		routes = _lines(row.get("match_routes"))
		if apps and installed and not any(app in installed for app in apps):
			continue
		generic = not apps and not routes
		score = 0
		if routes and _route_hit(routes, route):
			score = 300
		elif inferred_app and inferred_app in apps:
			score = 200
		elif route_app and route_app in apps:
			score = 150
		elif generic:
			score = 50
		if score == 0:
			continue
		try:
			priority = int(row.get("priority") or 0)
		except (TypeError, ValueError):
			priority = 0
		scored.append((score, priority, row))
	if scored:
		scored.sort(key=lambda item: (-item[0], -item[1], 0 if item[2].name == active else 1, item[2].name or ""))
		return _pack(scored[0][2])
	if active and frappe.db.exists("ERP AI Persona", active):
		doc = frappe.get_doc("ERP AI Persona", active)
		if int(doc.enabled or 0) and _role_ok(doc.name, roles):
			return _pack(doc)
	return _fallback()


def _role_ok(persona: str, roles: set[str]) -> bool:
	try:
		wanted = frappe.get_all("ERP AI Persona Role", filters={"parent": persona}, pluck="role")
	except Exception:
		return True
	wanted = [role for role in wanted if role]
	if not wanted:
		return True
	if "All" in wanted:
		return True
	return bool(set(wanted) & set(roles))


def _lines(value: str | None) -> list[str]:
	return [line.strip() for line in (value or "").splitlines() if line.strip()]


def _route_hit(patterns: list[str], route: str | None) -> bool:
	route = route or ""
	if not route:
		return False
	for pattern in patterns:
		if route == pattern or route.startswith(pattern.rstrip("/") + "/") or route.startswith(pattern):
			return True
	return False


def _app_for_route(route: str | None) -> str:
	route = route or ""
	best = ""
	best_len = -1
	try:
		rows = installed_app_routes()
	except Exception:
		rows = []
	for row in rows:
		pattern = row.get("route") or ""
		if not pattern:
			continue
		if route == pattern or route.startswith(pattern.rstrip("/") + "/"):
			if len(pattern) > best_len:
				best = row.get("app") or ""
				best_len = len(pattern)
	return best


def _pack(row) -> dict:
	name = row.get("persona_name") if isinstance(row, dict) else row.persona_name
	panel = row.get("panel_label") if isinstance(row, dict) else row.panel_label
	panel_ar = row.get("panel_label_ar") if isinstance(row, dict) else row.panel_label_ar
	tone = row.get("tone_instructions") if isinstance(row, dict) else row.tone_instructions
	key = row.get("name") if isinstance(row, dict) else row.name
	return {
		"name": key,
		"panel_label": panel or name or "Frappe helper",
		"panel_label_ar": panel_ar or name or "مساعد العمل",
		"tone_instructions": tone or "",
	}


def _fallback() -> dict:
	return {
		"name": "",
		"panel_label": "Frappe helper",
		"panel_label_ar": "مساعد العمل",
		"tone_instructions": "",
	}
