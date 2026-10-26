"""Cached list of non-child DocTypes for targeting and the model.

Child tables (`istable=1`) are excluded. The cache is per site and rebuilt
on miss, migrate, or an explicit clear.
"""

from __future__ import annotations

import re

import frappe
from erpnext_ai_assistant.services.arabic import normalize_arabic
from erpnext_ai_assistant.services.schema import DENIED_DOCTYPES

CACHE_KEY = "erp_ai_doctype_catalog"
CACHE_TTL = 60 * 60 * 6


def _cache_key() -> str:
	return f"{CACHE_KEY}:{getattr(frappe.local, 'site', '')}"


def clear_doctype_catalog(doc=None, method=None):
	frappe.cache().delete_value(_cache_key())


def get_doctype_catalog(force: bool = False) -> list[dict]:
	"""Return [{name, name_norm, labels}] for every non-child DocType on this site."""
	if not force:
		cached = frappe.cache().get_value(_cache_key())
		if cached:
			return cached
	rows = frappe.get_all(
		"DocType",
		filters={"istable": 0},
		fields=["name"],
		order_by="name asc",
		limit_page_length=5000,
	)
	catalog = []
	for row in rows:
		name = row.name
		if not name or name in DENIED_DOCTYPES:
			continue
		labels = _labels_for(name)
		catalog.append(
			{
				"name": name,
				"name_norm": normalize_arabic(name),
				"labels": labels,
			}
		)
	frappe.cache().set_value(_cache_key(), catalog, expires_in_sec=CACHE_TTL)
	return catalog


# Extra Arabic / everyday labels merged into the cache for common DocTypes.
_EXTRA_LABELS: dict[str, tuple[str, ...]] = {
	"ToDo": ("مهمه", "مهام", "مهمة", "todo", "task", "tasks"),
	"Event": ("اجتماع", "اجتماعات", "meeting", "meetings"),
	"Customer": ("عميل", "عملاء", "customer", "customers"),
	"Supplier": ("مورد", "موردين", "supplier", "suppliers"),
	"Employee": ("موظف", "موظفين", "employee", "employees"),
	"Item": ("صنف", "اصناف", "item", "items"),
	"Sales Invoice": ("فاتوره مبيعات", "sales invoice"),
	"Purchase Invoice": ("فاتوره مشتريات", "purchase invoice"),
	"Sales Order": ("امر بيع", "sales order"),
	"Purchase Order": ("امر شراء", "purchase order"),
	"CRM Lead": ("عميل محتمل", "ليد", "lead", "leads"),
	"Lead": ("عميل محتمل", "ليد", "lead", "leads"),
}


def _labels_for(name: str) -> list[str]:
	"""English name plus Arabic translations and known everyday labels."""
	labels = [name]
	try:
		ar = frappe.db.get_value(
			"Translation",
			{"source_text": name, "language": "ar"},
			"translated_text",
		)
		if ar and ar not in labels:
			labels.append(ar)
	except Exception:
		pass
	try:
		# Current language translation (often Arabic on this site)
		translated = frappe._(name)
		if translated and translated not in labels:
			labels.append(translated)
	except Exception:
		pass
	for extra in _EXTRA_LABELS.get(name) or ():
		if extra not in labels:
			labels.append(extra)
	return labels


def match_catalog(text: str | None, limit: int = 5) -> list[dict]:
	"""Score catalog entries that appear in the user text. Longest label wins."""
	norm = normalize_arabic(text)
	raw = (text or "").strip()
	if not norm and not raw:
		return []
	hits: list[tuple[int, dict]] = []
	for row in get_doctype_catalog():
		name = row["name"]
		score = 0
		# Exact DocType name token (ASCII)
		if re.search(rf"(?i)(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", raw):
			score = max(score, len(name) + 20)
		for label in row.get("labels") or []:
			lab = normalize_arabic(label)
			if not lab or len(lab) < 2:
				continue
			if " " in lab:
				if lab in norm:
					score = max(score, len(lab) + 5)
			elif re.search(rf"(?<!\w)(?:ال)?{re.escape(lab)}(?!\w)", norm, re.UNICODE):
				score = max(score, len(lab) + (2 if re.search(r"[\u0600-\u06FF]", lab) else 0))
			elif lab in norm and len(lab) >= 4:
				# Substring only for longer labels (avoid عمل ⊂ عملاء)
				score = max(score, len(lab) - 2)
		if score:
			hits.append((score, row))
	hits.sort(key=lambda item: (-item[0], -len(item[1]["name"])))
	out = []
	seen = set()
	for score, row in hits:
		if row["name"] in seen:
			continue
		seen.add(row["name"])
		out.append({**row, "score": score})
		if len(out) >= limit:
			break
	return out


def search_catalog(query: str | None, limit: int = 20) -> list[dict]:
	"""Filter the cached catalog by a free-text query for the model tool."""
	q = normalize_arabic(query)
	if not q:
		rows = get_doctype_catalog()
		return [{"name": r["name"], "labels": r.get("labels") or []} for r in rows[:limit]]
	# Prefer scored matches (includes Arabic everyday labels)
	scored = match_catalog(query, limit=limit)
	if scored:
		return [{"name": r["name"], "labels": r.get("labels") or []} for r in scored]
	# Fallback: token overlap on name + labels
	matched = []
	tokens = [tok for tok in q.split() if len(tok) >= 2]
	for row in get_doctype_catalog():
		blob = normalize_arabic(" ".join([row["name"]] + (row.get("labels") or [])))
		if q in blob or any(tok in blob for tok in tokens):
			matched.append({"name": row["name"], "labels": row.get("labels") or []})
		if len(matched) >= limit:
			break
	return matched


def candidate_hint(text: str | None, limit: int = 8) -> str:
	"""Short hint block for the model when targeting was unclear."""
	hits = match_catalog(text, limit=limit)
	if not hits:
		return ""
	parts = []
	for row in hits:
		labels = ", ".join((row.get("labels") or [])[:4])
		parts.append(f"{row['name']} ({labels})" if labels else row["name"])
	return "Candidate non-child DocTypes from site catalog: " + "; ".join(parts)
