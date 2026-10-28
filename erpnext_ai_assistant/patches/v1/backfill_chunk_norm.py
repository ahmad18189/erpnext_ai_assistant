"""Store normalized Arabic chunk text so retrieval and scoring use the same letters."""

import frappe


def execute():
	from erpnext_ai_assistant.services.rag.service import backfill_content_norm

	if not frappe.db.table_exists("ERP AI Knowledge Chunk"):
		return
	if not frappe.db.has_column("ERP AI Knowledge Chunk", "content_norm"):
		return
	backfill_content_norm()
