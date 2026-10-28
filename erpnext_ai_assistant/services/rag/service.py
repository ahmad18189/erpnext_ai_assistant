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


def backfill_content_norm() -> int:
	"""Fill normalized chunk text after the column exists. Safe to run more than once."""
	if not frappe.db.has_column("ERP AI Knowledge Chunk", "content_norm"):
		return 0
	rows = frappe.get_all("ERP AI Knowledge Chunk", fields=["name", "content"], limit_page_length=0)
	updated = 0
	for row in rows:
		frappe.db.set_value(
			"ERP AI Knowledge Chunk",
			row.name,
			"content_norm",
			normalize_arabic(row.content or ""),
			update_modified=False,
		)
		updated += 1
	return updated


def reindex_knowledge():
	"""Rebuild skill chunks. ERP AI Enhancement rows are never knowledge."""
	if not frappe.db.exists("DocType", "ERP AI Knowledge Document"):
		return
	if frappe.db.has_column("ERP AI Knowledge Document", "source_key"):
		for name in frappe.get_all(
			"ERP AI Knowledge Document",
			filters={"source_key": ["like", "enhancement:%"]},
			pluck="name",
		):
			_delete_document(name)
	for name in frappe.get_all("ERP AI Knowledge Document", filters={"source_type": "skill"}, pluck="name"):
		_delete_document(name)
	if frappe.db.exists("DocType", "ERP AI Skill"):
		for skill in frappe.get_all("ERP AI Skill", filters={"enabled": 1}, fields=["name", "title", "description"]):
			roles = frappe.get_all("ERP AI Skill Role", filters={"parent": skill.name}, pluck="role")
			_upsert_document(
				f"skill:{skill.name}",
				skill.title,
				skill.description or "",
				"skill",
				source_roles="\n".join(roles),
			)
	_upsert_document(
		"policy:work-only",
		"Work-only policy",
		"This assistant answers only workplace ERP/CRM questions on this site.",
		"policy",
		source_roles="",
	)
	for docname in frappe.get_all("ERP AI Knowledge Document", pluck="name"):
		_rechunk(docname)


def _upsert_document(key: str, title: str, content: str, source_type: str, source_roles: str = "") -> str:
	if (key or "").startswith("enhancement:") or title == "ERP AI Enhancement":
		return ""
	existing = _find_source(key, title if source_type != "skill" else None)
	if existing:
		doc = frappe.get_doc("ERP AI Knowledge Document", existing)
		doc.content = content
		doc.source_type = source_type
		if doc.title != title and not frappe.db.exists("ERP AI Knowledge Document", title):
			doc.title = title
		if frappe.db.has_column("ERP AI Knowledge Document", "source_roles"):
			doc.source_roles = source_roles or ""
		if frappe.db.has_column("ERP AI Knowledge Document", "source_key"):
			doc.source_key = key
		doc.save(ignore_permissions=True)
		return doc.name
	payload = {
		"doctype": "ERP AI Knowledge Document",
		"title": title,
		"content": content,
		"source_type": source_type,
	}
	if frappe.db.has_column("ERP AI Knowledge Document", "source_roles"):
		payload["source_roles"] = source_roles or ""
	if frappe.db.has_column("ERP AI Knowledge Document", "source_key"):
		payload["source_key"] = key
	doc = frappe.get_doc(payload)
	doc.insert(ignore_permissions=True)
	return doc.name


def _find_source(key: str, title: str | None = None) -> str | None:
	if key and frappe.db.has_column("ERP AI Knowledge Document", "source_key"):
		found = frappe.db.get_value("ERP AI Knowledge Document", {"source_key": key}, "name")
		if found:
			return found
	if title:
		return frappe.db.get_value("ERP AI Knowledge Document", {"title": title}, "name")
	return None


def _delete_document(name: str | None):
	if not name or not frappe.db.exists("ERP AI Knowledge Document", name):
		return
	frappe.db.delete("ERP AI Knowledge Chunk", {"document": name})
	frappe.delete_doc("ERP AI Knowledge Document", name, ignore_permissions=True, force=1)


def _delete_source(key: str, title: str | None = None):
	names = []
	found = _find_source(key, None)
	if found:
		names.append(found)
	if title:
		by_title = frappe.db.get_value(
			"ERP AI Knowledge Document", {"title": title, "source_type": "skill"}, "name"
		)
		if by_title:
			names.append(by_title)
	for name in dict.fromkeys(names):
		_delete_document(name)


def _rechunk(docname: str):
	if not docname or not frappe.db.exists("ERP AI Knowledge Document", docname):
		return
	doc = frappe.get_doc("ERP AI Knowledge Document", docname)
	frappe.db.delete("ERP AI Knowledge Chunk", {"document": docname})
	from erpnext_ai_assistant.services.naming import as_title

	has_norm = frappe.db.has_column("ERP AI Knowledge Chunk", "content_norm")
	for i, chunk in enumerate(chunk_text(doc.content or "")):
		payload = {
			"doctype": "ERP AI Knowledge Chunk",
			"title": as_title("ERP AI Knowledge Chunk", f"{doc.title} {i + 1}"),
			"document": docname,
			"chunk_index": i,
			"content": chunk,
		}
		if has_norm:
			payload["content_norm"] = normalize_arabic(chunk)
		frappe.get_doc(payload).insert(ignore_permissions=True)


def on_skill_update(doc, method=None):
	try:
		key = f"skill:{doc.name}"
		_delete_source(key, doc.title)
		if not doc.enabled:
			return
		roles = [r.role for r in (doc.roles or []) if getattr(r, "role", None)]
		name = _upsert_document(key, doc.title, doc.description or "", "skill", source_roles="\n".join(roles))
		_rechunk(name)
	except Exception:
		frappe.log_error(title="ERP AI skill reindex")


def on_skill_trash(doc, method=None):
	try:
		_delete_source(f"skill:{doc.name}", doc.title)
	except Exception:
		frappe.log_error(title="ERP AI skill delete index")


def retrieve(query: str, limit: int = 5) -> list[dict]:
	"""Keyword overlap on a capped candidate set. Fail closed without source_roles."""
	if not frappe.db.has_column("ERP AI Knowledge Document", "source_roles"):
		return []
	q = normalize_arabic(query)
	tokens = [t for t in re.split(r"\W+", q) if len(t) >= 2]
	if not tokens:
		return []
	# Cap candidates: at most 200 chunks that contain at least one normalized token.
	column = "content_norm" if frappe.db.has_column("ERP AI Knowledge Chunk", "content_norm") else "content"
	or_filters = [[column, "like", f"%{t}%"] for t in tokens[:12]]
	chunks = frappe.get_all(
		"ERP AI Knowledge Chunk",
		fields=["name", "document", "content", "chunk_index"],
		or_filters=or_filters,
		limit_page_length=200,
	)
	scored = []
	for c in chunks:
		norm = normalize_arabic(c.content or "")
		score = sum(1 for t in tokens if t in norm)
		if score:
			scored.append({**c, "score": score})
	scored.sort(key=lambda x: -x["score"])
	allowed = _filter_by_source_roles(scored)
	top = allowed[: min(int(limit or 4), 4)]
	return [_enrich_hit(row) for row in top]


def _enrich_hit(row: dict) -> dict:
	"""Attach document title and source_key when the columns exist."""
	out = dict(row)
	docname = row.get("document")
	if not docname:
		return out
	fields = ["title"]
	if frappe.db.has_column("ERP AI Knowledge Document", "source_key"):
		fields.append("source_key")
	meta = frappe.db.get_value("ERP AI Knowledge Document", docname, fields, as_dict=True)
	if meta:
		out["document_title"] = meta.get("title") or ""
		out["source_key"] = meta.get("source_key") or ""
	else:
		out["document_title"] = ""
		out["source_key"] = out.get("source_key") or ""
	return out


def _filter_by_source_roles(chunks: list[dict]) -> list[dict]:
	"""Skill text is indexed with the skill's roles. Drop chunks the session user may not read."""
	if not chunks:
		return []
	if not frappe.db.has_column("ERP AI Knowledge Document", "source_roles"):
		# Without the role column, skill text cannot be filtered. Return nothing.
		return []
	names = list({c.get("document") for c in chunks if c.get("document")})
	rows = frappe.get_all(
		"ERP AI Knowledge Document",
		filters={"name": ("in", names)},
		fields=["name", "source_roles"],
	)
	roles_by_doc = {row.name: row.source_roles or "" for row in rows}
	user_roles = set(frappe.get_roles())
	kept = []
	for chunk in chunks:
		raw = roles_by_doc.get(chunk.get("document")) or ""
		required = {part.strip() for part in raw.splitlines() if part.strip()}
		if required and not (required & user_roles) and "All" not in required:
			continue
		kept.append(chunk)
	return kept
