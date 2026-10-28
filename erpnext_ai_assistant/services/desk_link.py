"""Same-site Desk links. The model never supplies the path."""

from __future__ import annotations

import re

import frappe
from erpnext_ai_assistant.services.arabic import normalize_arabic
from erpnext_ai_assistant.services.doctype_catalog import match_catalog
from erpnext_ai_assistant.services.schema import DENIED_DOCTYPES
from erpnext_ai_assistant.services.targeting import _COUNT_WORDS, _CREATE_WORDS, _has

# Frappe v15 serves Desk at /app. The v16 app uses /desk.
DESK_ROOT = "/app"


def desk_path(*parts: str) -> str:
	"""Same-site Desk path. Parts are scrubbed route segments, never a full URL."""
	cleaned = [str(part).strip("/") for part in parts if part]
	if not cleaned:
		return DESK_ROOT
	return DESK_ROOT + "/" + "/".join(cleaned)


_NAV_WORDS = (
	"افتح",
	"خذني",
	"وديني",
	"وين",
	"روح",
	"open",
	"go to",
	"take me",
	"where is",
	"where",
)

# Phrase -> DocType. Used only when that DocType exists on this site.
_TOOLS = (
	(("اداة الاستيراد", "أداة الاستيراد", "استيراد", "data import", "import tool", "import"), "Data Import"),
	(("تخصيص النموذج", "customize form"), "Customize Form"),
)


def desk_link(message: str | None, lang: str = "en") -> dict | None:
	"""Return {reply} for one readable screen, {ambiguous: True}, or None."""
	if not _is_nav(message):
		return None
	norm = normalize_arabic(message)
	tool_hits = []
	for phrases, doctype in _TOOLS:
		if any(_has(norm, phrase) for phrase in phrases) and _readable(doctype):
			tool_hits.append(doctype)
	if len(tool_hits) == 1:
		return _payload(tool_hits[0], message, lang, create=False)
	catalog = match_catalog(message, limit=3)
	if tool_hits and not catalog:
		return {"ambiguous": True}
	if not catalog and not tool_hits:
		return None
	if catalog and (len(catalog) == 1 or catalog[0]["score"] > catalog[1]["score"] + 2):
		doctype = catalog[0]["name"]
		if doctype in DENIED_DOCTYPES or not _readable(doctype):
			return None
		create = _wants_new(norm) and bool(frappe.has_permission(doctype, "create"))
		return _payload(doctype, message, lang, create=create)
	if len(catalog) > 1:
		return {"ambiguous": True}
	return None


def _is_nav(message: str | None) -> bool:
	norm = normalize_arabic(message)
	if not norm:
		return False
	if any(_has(norm, word) for word in _COUNT_WORDS):
		return False
	return any(_has(norm, word) for word in _NAV_WORDS)


def _wants_new(norm: str) -> bool:
	return any(_has(norm, word) for word in _CREATE_WORDS)


def _readable(doctype: str) -> bool:
	if not doctype or doctype in DENIED_DOCTYPES:
		return False
	if not frappe.db.exists("DocType", doctype):
		return False
	try:
		return bool(frappe.has_permission(doctype, "read"))
	except Exception:
		return False


def _slug(doctype: str) -> str:
	return frappe.scrub(doctype).replace("_", "-")


def _payload(doctype: str, message: str | None, lang: str, create: bool) -> dict:
	slug = _slug(doctype)
	path = desk_path(slug, "new") if create else desk_path(slug)
	label = _label(doctype, message, lang)
	if lang == "ar" or re.search(r"[\u0600-\u06FF]", message or ""):
		sentence = f"هذا رابط {label} في هذا الموقع."
	else:
		sentence = f"This opens {label} on this site."
	marker = f"[[open:{path}|{label}]]"
	return {"reply": f"{sentence}\n{marker}", "doctype": doctype, "path": path}


def _label(doctype: str, message: str | None, lang: str) -> str:
	if doctype == "Data Import" and (lang == "ar" or re.search(r"[\u0600-\u06FF]", message or "")):
		return "أداة الاستيراد"
	if doctype == "Customize Form" and (lang == "ar" or re.search(r"[\u0600-\u06FF]", message or "")):
		return "تخصيص النموذج"
	try:
		translated = frappe._(doctype)
	except Exception:
		translated = doctype
	if lang == "ar" and translated and translated != doctype:
		return translated
	return doctype
