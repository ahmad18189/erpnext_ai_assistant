"""Routes of whatever apps are installed on this site.

The assistant is not tied to one product. Each app declares its own screen
in hooks (`add_to_apps_screen` or `app_icon_route`).
"""

from __future__ import annotations

import frappe


def installed_app_routes() -> list[dict]:
	routes: list[dict] = []
	seen: set[str] = set()
	for app in frappe.get_installed_apps():
		title = app
		try:
			hook_title = frappe.get_hooks("app_title", app_name=app) or []
			if hook_title:
				title = hook_title[0] or app
		except Exception:
			pass
		candidates: list[str] = []
		try:
			for row in frappe.get_hooks("add_to_apps_screen", app_name=app) or []:
				if isinstance(row, dict) and row.get("route"):
					candidates.append(str(row["route"]))
					if row.get("title"):
						title = row["title"]
		except Exception:
			pass
		try:
			icon_route = frappe.get_hooks("app_icon_route", app_name=app) or []
			if icon_route:
				candidates.append(str(icon_route[0]))
		except Exception:
			pass
		for route in candidates:
			route = "/" + route.strip().lstrip("/")
			if route in seen or route in ("/", "/login"):
				continue
			seen.add(route)
			routes.append({"app": app, "title": title, "route": route})
	return routes
