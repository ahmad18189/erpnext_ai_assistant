"""Guess the DocType, its app, and the action from one user message.

High confidence is a clear catalog margin plus a clear action word.
Anything else stays a candidate list for the model or a short clarification.
"""

from __future__ import annotations

import re

import frappe
from erpnext_ai_assistant.services.arabic import normalize_arabic
from erpnext_ai_assistant.services.doctype_catalog import match_catalog
from erpnext_ai_assistant.services.targeting import _action, _has, _is_howto

_UPDATE_WORDS = ("تعديل", "حدث", "تحديث", "update", "edit", "change")
# Record actions that need an existing record. They skip the Count/Show/Create menu.
_RECORD_ACTION_WORDS = (
	("submit", ("submit", "اعتمد", "اعتماد", "رحل", "ترحيل")),
	("cancel", ("cancel", "الغ", "الغي", "الغاء")),
	("delete", ("delete", "remove", "احذف", "حذف", "امسح")),
)
_DIGIT_INDEX = {"1": 0, "2": 1, "3": 2, "١": 0, "٢": 1, "٣": 2}


def infer_intent(message: str | None, route: str | None = None, user: str | None = None) -> dict:
	from erpnext_ai_assistant.services.targeting import doctype_text, without_grouping

	hits = match_catalog(doctype_text(message), limit=5) or match_catalog(without_grouping(message), limit=5)
	action = _action_name(message)
	installed = set()
	try:
		installed = set(frappe.get_installed_apps())
	except Exception:
		installed = set()
	candidates = []
	for row in hits:
		doctype = row["name"]
		module = ""
		app = ""
		try:
			module = frappe.db.get_value("DocType", doctype, "module") or ""
		except Exception:
			module = ""
		try:
			from erpnext_ai_assistant.services.rdf.graph import doctype_app

			app = doctype_app(doctype) or ""
		except Exception:
			app = ""
		if not app and module:
			try:
				app = frappe.get_doctype_app(doctype) or ""
			except Exception:
				app = ""
		if app and installed and app not in installed:
			continue
		candidates.append(
			{
				"doctype": doctype,
				"module": module,
				"app": app,
				"score": int(row.get("score") or 0),
				"labels": list(row.get("labels") or [])[:6],
			}
		)
	confidence = "low"
	margin = 0
	if candidates:
		top = candidates[0]["score"]
		second = candidates[1]["score"] if len(candidates) > 1 else 0
		margin = top - second
		if action != "unknown" and top >= 4 and (len(candidates) == 1 or margin >= 3):
			confidence = "high"
	from erpnext_ai_assistant.services.targeting import match_doctype

	named = match_doctype(message)
	close = len(candidates) > 1 and margin < 3
	if named and action not in ("unknown", "howto") and not close:
		confidence = "high"
		if not any(row.get("doctype") == named for row in candidates):
			candidates.insert(
				0,
				{"doctype": named, "module": "", "app": "", "score": 100, "labels": [named]},
			)
		else:
			candidates.sort(key=lambda row: 0 if row.get("doctype") == named else 1)
	app = ""
	if candidates and (confidence == "high" or len(candidates) == 1 or margin >= 3):
		app = candidates[0].get("app") or ""
		if not app and candidates[0].get("doctype"):
			try:
				app = frappe.get_doctype_app(candidates[0]["doctype"]) or ""
				candidates[0]["app"] = app
			except Exception:
				app = ""
	return {
		"candidates": candidates[:3],
		"app": app,
		"action": action,
		"confidence": confidence,
		"route": route or "",
		"user": user or "",
	}


def _action_name(message: str | None) -> str:
	if _is_howto(message or ""):
		return "howto"
	norm = normalize_arabic(message)
	for action, words in _RECORD_ACTION_WORDS:
		if any(_has(norm, word) for word in words):
			return action
	if any(_has(norm, word) for word in _UPDATE_WORDS):
		return "update"
	return _action(message or "") or "unknown"


def clarification_message(intent: dict | None, lang: str) -> str | None:
	intent = intent or {}
	if intent.get("confidence") == "high":
		return None
	if intent.get("action") == "howto":
		return None
	candidates = list(intent.get("candidates") or [])[:3]
	action = intent.get("action") or "unknown"
	if len(candidates) == 1 and action == "unknown":
		return _action_menu(candidates[0], lang)
	if len(candidates) < 2:
		return None
	if lang == "ar":
		lines = []
		for index, row in enumerate(candidates, start=1):
			lines.append(f"{index}. {_label(row, 'ar')} ({row.get('doctype')})")
		return "هل تقصد:\n" + "\n".join(lines) + "\n" + _next_step(action, "ar")
	lines = []
	for index, row in enumerate(candidates, start=1):
		lines.append(f"{index}. {_label(row, 'en')} ({row.get('doctype')})")
	return "Did you mean:\n" + "\n".join(lines) + "\n" + _next_step(action, "en")


def _next_step(action: str, lang: str) -> str:
	ar = {
		"count": "اختر واحداً وسأعدّ السجلات الظاهرة لك.",
		"query": "اختر واحداً وسأعرض الصفحة الظاهرة لك.",
		"create": "اختر النوع ثم أرسل الحقول. لن يُحفظ شيء قبل موافقتك.",
		"update": "اختر النوع ثم أرسل اسم السجل والحقل المطلوب تعديله.",
		"submit": "اختر النوع ثم أرسل اسم السجل أو الطرف لاعتماده.",
		"cancel": "اختر النوع ثم أرسل اسم السجل أو الطرف لإلغائه.",
		"delete": "اختر النوع ثم أرسل اسم السجل المطلوب حذفه.",
		"howto": "اختر النوع وسأبحث عن الخطوات.",
	}
	en = {
		"count": "Say which one and I will count the records you can see.",
		"query": "Say which one and I will show the page you can read.",
		"create": "Say which one, then send the fields. Nothing is saved until you approve.",
		"update": "Say which one, then send the record name and the field to change.",
		"submit": "Say which one, then name the record or the party to submit.",
		"cancel": "Say which one, then name the record or the party to cancel.",
		"delete": "Say which one, then name the record to delete.",
		"howto": "Say which one and I will look up the steps.",
	}
	table = ar if lang == "ar" else en
	return table.get(action) or (
		"حدّد النوع والخطوة التالية (عرض أو عدد أو إنشاء)."
		if lang == "ar"
		else "Name the DocType and the next step (show, count, or create)."
	)


def _label(row: dict, lang: str) -> str:
	labels = row.get("labels") or []
	if lang == "ar":
		for label in labels:
			if label and re.search(r"[\u0600-\u06FF]", str(label)):
				return str(label)
	return str(row.get("doctype") or "")


def _action_menu(row: dict, lang: str) -> str:
	name = _label(row, lang)
	if lang == "ar":
		return (
			f"{name}. ماذا تريد؟\n"
			"1. عدد\n"
			"2. عرض\n"
			"3. إنشاء\n"
			"لن يُحفظ شيء قبل موافقتك."
		)
	return (
		f"{name}. What should I do?\n"
		"1. Count\n"
		"2. Show\n"
		"3. Create\n"
		"Nothing is saved until you approve."
	)


def _action_choices(row: dict) -> list[dict]:
	base = {
		"doctype": row.get("doctype"),
		"app": row.get("app") or "",
		"module": row.get("module") or "",
	}
	return [
		{**base, "action": "count", "label_ar": "عدد", "label_en": "Count"},
		{**base, "action": "query", "label_ar": "عرض", "label_en": "Show"},
		{**base, "action": "create", "label_ar": "إنشاء", "label_en": "Create"},
	]


def clarify_options(intent: dict | None) -> list[dict]:
	intent = intent or {}
	candidates = list(intent.get("candidates") or [])
	if len(candidates) == 1 and (intent.get("action") or "unknown") == "unknown":
		return _action_choices(candidates[0])
	options = []
	for row in candidates:
		options.append(
			{
				"doctype": row.get("doctype"),
				"app": row.get("app") or "",
				"module": row.get("module") or "",
				"label_ar": _label(row, "ar"),
				"label_en": _label(row, "en"),
			}
		)
	return options[:3]


def match_prior_choice(message: str | None, facts: dict | None) -> dict | None:
	"""The user picked one of the options offered on the previous turn."""
	options = list((facts or {}).get("clarify_options") or [])
	if not options:
		return None
	raw = (message or "").strip()
	if not raw:
		return None
	if raw in _DIGIT_INDEX and _DIGIT_INDEX[raw] < len(options):
		chosen = dict(options[_DIGIT_INDEX[raw]])
		chosen["action"] = chosen.get("action") or (facts or {}).get("clarify_action") or "unknown"
		return chosen
	norm = normalize_arabic(raw)
	hits = []
	for option in options:
		for label in (option.get("label_ar"), option.get("label_en"), option.get("doctype")):
			if label and _has(norm, str(label)):
				hits.append(option)
				break
	if len(hits) != 1:
		return None
	chosen = dict(hits[0])
	chosen["action"] = chosen.get("action") or (facts or {}).get("clarify_action") or "unknown"
	return chosen


def reuse_chosen(message: str | None, facts: dict | None) -> dict | None:
	"""Keep the DocType the user already picked when this turn only names an action."""
	facts = facts or {}
	doctype = facts.get("chosen_doctype")
	if not doctype:
		return None
	from erpnext_ai_assistant.services.targeting import match_doctype

	named = match_doctype(message)
	if named and named != doctype:
		return None
	action = _action_name(message)
	if action in ("unknown", "howto"):
		return None
	return {
		"doctype": doctype,
		"action": action,
		"app": facts.get("chosen_app") or "",
	}
