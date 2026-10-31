"""Delete old chats that were opened on a scoped screen."""

from __future__ import annotations

import frappe
from frappe.utils import add_days, now_datetime


def purge_scoped_chats():
	"""Daily. Skills set retention_days. Messages go with the chat."""
	from erpnext_ai_assistant.services.scope import retention_routes

	if not frappe.db.exists("DocType", "ERP AI Chat"):
		return 0
	removed = 0
	for pattern, days in retention_routes():
		cutoff = add_days(now_datetime(), -int(days))
		names = frappe.get_all(
			"ERP AI Chat",
			filters={"route": ["like", f"%{pattern}%"], "creation": ["<", cutoff]},
			pluck="name",
			limit_page_length=500,
		)
		for name in names:
			frappe.db.delete("ERP AI Message", {"chat": name})
			frappe.delete_doc("ERP AI Chat", name, ignore_permissions=True, force=True)
			removed += 1
	return removed
