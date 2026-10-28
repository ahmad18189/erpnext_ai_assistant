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
	"target_modified",
)

# executed/rejected/failed are terminal. An import moves pending -> queued -> starting -> executed.
# A failed queue start returns to approved so the same Data Import can be started again.
# A pending card expires when it is too old or its record changed after it was proposed.
TRANSITIONS = {
	"pending": {"approved", "queued", "rejected", "expired", "executed", "failed"},
	"queued": {"starting", "approved", "failed"},
	"starting": {"executed", "approved", "failed"},
	"approved": {"starting", "executed", "failed"},
	"executed": set(),
	"rejected": set(),
	"expired": set(),
	"failed": set(),
}


def allow_card_insert():
	"""Only the server's proposal code may create a card (registry.propose_write, imports.propose_import)."""
	frappe.flags.erp_ai_propose = True


class ERPAIPendingAction(Document):
	def before_insert(self):
		# A card shown to a user must come from a proposal on the server, never from a REST insert
		# with a friendly summary and a different payload.
		if not frappe.flags.get("erp_ai_propose"):
			frappe.throw("Approval cards are created by the assistant only", frappe.PermissionError)
		frappe.flags.erp_ai_propose = False
		self.user = frappe.session.user

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
