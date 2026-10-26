"""Pending actions are a contract. The payload shown to the user cannot change later."""

from __future__ import annotations

import frappe
from frappe.model.document import Document

from erpnext_ai_assistant.services.writes import payload_hash

LOCKED_FIELDS = (
	"payload_json",
	"payload_hash",
	"summary",
	"action_type",
	"target_doctype",
	"target_name",
	"user",
	"chat",
)

# executed/rejected/failed are terminal. pending may go straight to executed in one save.
TRANSITIONS = {
	"pending": {"approved", "rejected", "executed", "failed"},
	"approved": {"executed", "failed"},
	"executed": set(),
	"rejected": set(),
	"failed": set(),
}


class ERPAIPendingAction(Document):
	def validate(self):
		if self.is_new():
			self.payload_hash = payload_hash(self.payload_json)
			return
		before = self.get_doc_before_save()
		if not before:
			return
		if (self.status or "") != (before.status or "") and self.status not in TRANSITIONS.get(before.status or "pending", set()):
			frappe.throw(
				f"Cannot change status from {before.status} to {self.status}",
				frappe.ValidationError,
			)
		if frappe.flags.get("erp_ai_mutate_pending"):
			return
		for fieldname in LOCKED_FIELDS:
			if (self.get(fieldname) or "") != (before.get(fieldname) or ""):
				frappe.throw(
					f"Cannot change {fieldname} after the action was proposed",
					frappe.ValidationError,
				)
