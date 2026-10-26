"""Keyword RAG with Arabic normalization (Qdrant optional)."""

from __future__ import annotations

import re

import frappe
from erpnext_ai_assistant.services.arabic import normalize_arabic

CHUNK_SIZE = 900
CHUNK_OVERLAP = 100


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
	text = text or ""
	if len(text) <= size:
		return [text] if text.strip() else []
	chunks = []
	i = 0
	while i < len(text):
		chunks.append(text[i : i + size])
		i += size - overlap
	return chunks


def reindex_knowledge():
	if not frappe.db.exists("DocType", "ERP AI Knowledge Document"):
		return
	# Seed from skills
	if frappe.db.exists("DocType", "ERP AI Skill"):
		for skill in frappe.get_all("ERP AI Skill", filters={"enabled": 1}, fields=["name", "title", "description"]):
			_upsert_document(f"skill:{skill.name}", skill.title, skill.description or "", "skill")
	# Policy stub
	_upsert_document(
		"policy:work-only",
		"Work-only policy",
		"This assistant answers only workplace ERP/CRM questions on this site.",
		"policy",
	)
	# Rebuild chunks
	for docname in frappe.get_all("ERP AI Knowledge Document", pluck="name"):
		doc = frappe.get_doc("ERP AI Knowledge Document", docname)
		frappe.db.delete("ERP AI Knowledge Chunk", {"document": docname})
		for i, chunk in enumerate(chunk_text(doc.content or "")):
			frappe.get_doc(
				{
					"doctype": "ERP AI Knowledge Chunk",
					"document": docname,
					"chunk_index": i,
					"content": chunk,
				}
			).insert(ignore_permissions=True)


def _upsert_document(key: str, title: str, content: str, source_type: str):
	existing = frappe.db.get_value("ERP AI Knowledge Document", {"title": title}, "name")
	if existing:
		doc = frappe.get_doc("ERP AI Knowledge Document", existing)
		doc.content = content
		doc.source_type = source_type
		doc.save(ignore_permissions=True)
	else:
		frappe.get_doc(
			{
				"doctype": "ERP AI Knowledge Document",
				"title": title,
				"content": content,
				"source_type": source_type,
			}
		).insert(ignore_permissions=True)


def on_skill_update(doc, method=None):
	try:
		_upsert_document(f"skill:{doc.name}", doc.title, doc.description or "", "skill")
		frappe.db.delete("ERP AI Knowledge Chunk", {"document": frappe.db.get_value("ERP AI Knowledge Document", {"title": doc.title})})
		reindex_knowledge()
	except Exception:
		frappe.log_error(title="ERP AI skill reindex")


def retrieve(query: str, limit: int = 5) -> list[dict]:
	q = normalize_arabic(query)
	tokens = [t for t in re.split(r"\W+", q) if len(t) >= 2]
	if not tokens:
		return []
	chunks = frappe.get_all(
		"ERP AI Knowledge Chunk",
		fields=["name", "document", "content", "chunk_index"],
		limit_page_length=500,
	)
	scored = []
	for c in chunks:
		norm = normalize_arabic(c.content)
		score = sum(1 for t in tokens if t in norm)
		if score:
			scored.append({**c, "score": score})
	scored.sort(key=lambda x: -x["score"])
	return scored[:limit]
