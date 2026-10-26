"""Deterministic work-only content gate (no LLM).

In scope: this site's ERP/CRM data, DocTypes, reports, and installed apps.
Out of scope: homework, poems, jokes, politics,
generic ChatGPT roleplay unrelated to this workplace.
"""

from __future__ import annotations

import re

import frappe
from erpnext_ai_assistant.services.arabic import normalize_arabic

OFF_WORK_PATTERNS = [
	r"\bhomework\b",
	r"\bpoem\b",
	r"\bjoke\b",
	r"\bjokes\b",
	r"\bpolitics\b",
	r"\bact as chatgpt\b",
	r"\byou are chatgpt\b",
	r"\bwrite (a |an )?(story|essay|song)\b",
	r"\bgeneral coding\b",
	r"واجب\s*منزلي",
	r"قصيدة",
	r"نكتة",
	r"نكات",
	r"سياسة",
	r"تشات\s*جي\s*بي\s*تي",
	r"اكتب\s*(قصة|شعر|اغنية)",
]

WORK_CUES = [
	r"\blead\b",
	r"\bcalls?\b",
	r"\bcalle\b",
	r"مكالم",
	r"\bcreate\b",
	r"\badd\b",
	r"إنشاء",
	r"أضف",
	r"\bdeal\b",
	r"\bcrm\b",
	r"\binvoice\b",
	r"\bcustomer\b",
	r"\bsupplier\b",
	r"\bemployee\b",
	r"\bsalary\b",
	r"\bitem\b",
	r"\bstock\b",
	r"\border\b",
	r"\bquotation\b",
	r"\bdoctype\b",
	r"\berp\b",
	r"\berpnext\b",
	r"\bfrappe\b",
	r"\bhrms\b",
	r"\binstalled app\b",
	r"\bcustom app\b",
	r"\bthis (site|system|bench)\b",
	r"\babout (the |this )?(app|module)\b",
	r"ما\s*هو",
	r"عرفني",
	r"عن\s*تطبيق",
	r"تطبيق",
	r"عميل",
	r"فاتورة",
	r"موظف",
	r"راتب",
	r"مخزون",
	r"صنف",
	r"عرض\s*سعر",
	r"صفقة",
	r"فرصة",
	r"عمولة",
	r"ضريبة",
]


def _installed_app_tokens() -> set[str]:
	"""Lowercased app names and title tokens from this site."""
	tokens: set[str] = set()
	try:
		for app in frappe.get_installed_apps():
			if not app:
				continue
			tokens.add(app.lower())
			tokens.add(app.replace("_", " ").lower())
			tokens.add(app.replace("_", "").lower())
			try:
				meta = frappe.get_hooks("app_title", app_name=app) or []
				# get_hooks without app may return dict; keep simple
			except Exception:
				pass
			try:
				title = frappe.get_attr(f"{app}.hooks.app_title")
				if isinstance(title, str) and title.strip():
					tokens.add(title.lower())
					for part in re.split(r"\W+", title.lower()):
						if len(part) >= 3:
							tokens.add(part)
			except Exception:
				pass
	except Exception:
		pass
	return tokens


def _on_installed_app(route: str) -> bool:
	if route.startswith("/desk") or route.startswith("/app"):
		return True
	try:
		from erpnext_ai_assistant.services.apps import installed_app_routes

		for row in installed_app_routes():
			pat = (row.get("route") or "").lower().rstrip("/")
			if pat and (route == pat or route.startswith(pat + "/")):
				return True
	except Exception:
		return False
	return False


def is_work_related(message: str, route: str | None = None) -> bool:
	text = normalize_arabic(message)
	raw = (message or "").lower()
	combined = f"{text} {raw}"
	for pat in OFF_WORK_PATTERNS:
		if re.search(pat, combined, re.I):
			return False

	# Questions about any installed / custom app on this site are workplace-scoped
	for token in _installed_app_tokens():
		if token and token in raw:
			return True
	if re.search(r"\b(app|module|addon|plugin)\b", raw) and re.search(
		r"\b(tell|about|what|explain|describe|how|installed|custom|site)\b", raw
	):
		return True

	route = (route or "").lower()
	if _on_installed_app(route):
		for pat in WORK_CUES:
			if re.search(pat, combined, re.I):
				return True
		if len((message or "").strip()) <= 120:
			return True
	for pat in WORK_CUES:
		if re.search(pat, combined, re.I):
			return True
	return False


def refusal_texts(settings) -> tuple[str, str]:
	ar = settings.refusal_text_ar or (
		"أنا مساعد عمل لهذا الموقع (ERP/CRM والتطبيقات المثبتة عليه) فقط. "
		"يرجى طرح سؤال متعلق بالعمل أو بتطبيقات النظام."
	)
	en = settings.refusal_text_en or (
		"I am a workplace assistant for this site only (ERP/CRM and its installed apps). "
		"Please ask about work data or the apps installed here."
	)
	return ar, en
