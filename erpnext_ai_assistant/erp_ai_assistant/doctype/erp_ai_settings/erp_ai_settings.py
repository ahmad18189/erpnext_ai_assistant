import frappe
from frappe.model.document import Document


class ERPAISettings(Document):
	def validate(self):
		if not self.provider_base_url:
			self.provider_base_url = "https://api.openai.com/v1"
		if not self.model:
			self.model = "gpt-4o-mini"

	@frappe.whitelist()
	def rebuild_rdf(self):
		frappe.only_for("System Manager")
		from erpnext_ai_assistant.services.rdf.graph import rebuild_rdf_graph

		return rebuild_rdf_graph(force_ttl=True)

	@frappe.whitelist()
	def reindex_rag(self):
		frappe.only_for("System Manager")
		from erpnext_ai_assistant.services.rag.service import reindex_knowledge

		reindex_knowledge()
		return {"ok": True}

	@frappe.whitelist()
	def clear_user_block(self, user: str):
		frappe.only_for("System Manager")
		from frappe.utils import now_datetime

		changed = False
		for row in self.blocked_users or []:
			if row.user == user and not row.cleared_on:
				row.cleared_on = now_datetime()
				row.cleared_by = frappe.session.user
				changed = True
		if changed:
			self.save()
		return {"ok": changed}

	@frappe.whitelist()
	def clear_user_memory(self, user: str | None = None):
		frappe.only_for("System Manager")
		user = user or frappe.session.user
		frappe.db.delete("ERP AI Memory", {"user": user, "scope": "user"})
		return {"ok": True}
