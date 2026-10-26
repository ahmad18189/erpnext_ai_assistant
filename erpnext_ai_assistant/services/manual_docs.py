"""Fetch ERPNext user-manual pages from docs.frappe.io when the chat needs how-to text.

Public wiki APIs only. Results are cached per site. Content is returned as quoted
data for the model — never as a new system policy. Not a source of live counts.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

import frappe
from erpnext_ai_assistant.services.arabic import normalize_arabic

DOCS_BASE = "https://docs.frappe.io"
SEARCH_METHOD = "/api/method/wiki.frappe_wiki.doctype.wiki_document.search.search"
PAGE_METHOD = "/api/method/wiki.frappe_wiki.doctype.wiki_document.wiki_document.get_page_data"
CACHE_TTL = 60 * 60 * 12
MAX_PASSAGES = 3
MAX_CHARS = 3500

# Arabic / everyday → English search terms (docs are mostly English).
_QUERY_EXPAND: tuple[tuple[tuple[str, ...], str], ...] = (
	(("فاتوره مبيعات", "فاتورة مبيعات", "sales invoice"), "sales invoice"),
	(("فاتوره مشتريات", "فاتورة مشتريات", "purchase invoice"), "purchase invoice"),
	(("امر بيع", "أمر بيع", "sales order"), "sales order"),
	(("امر شراء", "أمر شراء", "purchase order"), "purchase order"),
	(("عميل محتمل", "ليد", "crm lead"), "lead"),
	(("عميل", "عملاء", "customer"), "customer"),
	(("مورد", "supplier"), "supplier"),
	(("موظف", "employee"), "employee"),
	(("راتب", "مسير رواتب", "salary slip"), "salary slip"),
	(("صنف", "item"), "item"),
	(("مخزون", "stock"), "stock entry"),
	(("مهمه", "مهام", "todo", "task"), "to do"),
	(("اجتماع", "meeting"), "event"),
)


def search_manual(query: str, limit: int = 3) -> list[dict]:
	"""Search the ERPNext manual and return short passages with source URLs."""
	q = (query or "").strip()
	if len(q) < 2:
		return []
	limit = max(1, min(int(limit or 3), MAX_PASSAGES))
	search_q = _expand_query(q)
	cache_key = f"erp_ai_manual:{getattr(frappe.local, 'site', '')}:{normalize_arabic(search_q)[:80]}:{limit}"
	cached = frappe.cache().get_value(cache_key)
	if cached:
		return cached

	hits = _search_remote(search_q)
	hits = _rank_hits(hits, search_q)
	passages = []
	for hit in hits:
		if len(passages) >= limit:
			break
		route = hit.get("route") or ""
		if not _is_erpnext_manual(route):
			continue
		page = _fetch_page(route)
		if not page:
			body = _strip_html(hit.get("content") or "")
			if not body:
				continue
			passages.append(
				{
					"title": _strip_html(hit.get("title") or route),
					"route": route,
					"url": f"{DOCS_BASE}/{route}",
					"content": body[:MAX_CHARS],
				}
			)
			continue
		passages.append(page)

	frappe.cache().set_value(cache_key, passages, expires_in_sec=CACHE_TTL)
	return passages


def _expand_query(query: str) -> str:
	"""Map Arabic topics to English search terms. Docs search is English-first."""
	norm = normalize_arabic(query)
	for phrases, english in _QUERY_EXPAND:
		for phrase in phrases:
			if normalize_arabic(phrase) in norm:
				return english
	# Strip Arabic letters so a mixed query still searches English tokens.
	latin = re.sub(r"[\u0600-\u06FF]+", " ", query)
	latin = re.sub(r"\s+", " ", latin).strip()
	return latin or query


def _rank_hits(hits: list[dict], query: str) -> list[dict]:
	tokens = [t for t in re.split(r"\W+", normalize_arabic(query).lower()) if len(t) >= 3]
	slug = "-".join(tokens)

	def score(row: dict) -> tuple:
		route = (row.get("route") or "").lower()
		title = normalize_arabic(_strip_html(row.get("title") or "")).lower()
		exact_title = 1 if title == " ".join(tokens) or all(t in title for t in tokens) else 0
		route_exact = 1 if route.endswith("/" + slug) or route.endswith(slug) else 0
		token_hits = sum(1 for t in tokens if t in route or t in title)
		versioned = 1 if re.search(r"/v\d+/", route) else 0
		return (-exact_title, -route_exact, -token_hits, versioned, len(route))

	return sorted(hits, key=score)


def _is_erpnext_manual(route: str) -> bool:
	route = (route or "").strip().lstrip("/")
	if not route.startswith("erpnext/"):
		return False
	# Prefer current docs; still allow versioned if that is all search returned.
	return True


def _search_remote(query: str) -> list[dict]:
	url = DOCS_BASE + SEARCH_METHOD + "?" + urllib.parse.urlencode({"query": query})
	try:
		data = _http_json(url)
	except Exception:
		frappe.log_error(title="ERP AI manual search failed")
		return []
	results = ((data or {}).get("message") or {}).get("results") or []
	erp = [r for r in results if isinstance(r, dict) and _is_erpnext_manual(r.get("route") or "")]
	return erp[:20]


def _fetch_page(route: str) -> dict | None:
	route = (route or "").strip().lstrip("/")
	page_key = f"erp_ai_manual_page:{getattr(frappe.local, 'site', '')}:{route}"
	cached = frappe.cache().get_value(page_key)
	if cached:
		return cached
	url = DOCS_BASE + PAGE_METHOD + "?" + urllib.parse.urlencode({"route": route})
	try:
		data = _http_json(url)
	except Exception:
		return None
	message = (data or {}).get("message")
	if not isinstance(message, dict):
		return None
	body = (message.get("raw_markdown") or "").strip()
	if not body:
		body = _strip_html(message.get("rendered_content") or "")
	if not body:
		return None
	out = {
		"title": message.get("title") or route,
		"route": message.get("route") or route,
		"url": f"{DOCS_BASE}/{message.get('route') or route}",
		"content": body[:MAX_CHARS],
	}
	frappe.cache().set_value(page_key, out, expires_in_sec=CACHE_TTL)
	return out


def _http_json(url: str) -> dict:
	req = urllib.request.Request(
		url,
		headers={"User-Agent": "ERPNext-AI-Assistant/1.0 (workplace manual fetch)", "Accept": "application/json"},
		method="GET",
	)
	with urllib.request.urlopen(req, timeout=20) as resp:
		return json.loads(resp.read().decode("utf-8", errors="replace"))


def _strip_html(text: str) -> str:
	text = re.sub(r"(?is)<script.*?>.*?</script>", " ", text or "")
	text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
	text = re.sub(r"<mark>|</mark>", "", text)
	text = re.sub(r"<[^>]+>", " ", text)
	text = re.sub(r"&nbsp;", " ", text)
	text = re.sub(r"&amp;", "&", text)
	text = re.sub(r"&lt;", "<", text)
	text = re.sub(r"&gt;", ">", text)
	text = re.sub(r"\s+", " ", text).strip()
	return text
