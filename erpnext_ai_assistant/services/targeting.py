"""Map Arabic and everyday words onto a real DocType.

The model must not invent a DocType name such as Meeting. مهمة is ToDo.
اجتماع is Event only when the user did not ask for a task. غدا is the next
calendar day on this site, not a guessed year.
"""

from __future__ import annotations

import re

import frappe
from erpnext_ai_assistant.services.arabic import normalize_arabic
from erpnext_ai_assistant.services.schema import DENIED_DOCTYPES

# Longer phrases are tried first. مهمة is handled before this list.
_PHRASES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
	(("عميل محتمل", "عملاء محتملين", "العملاء المحتملين", "crm lead"), ("CRM Lead", "Lead")),
	(("فاتوره مبيعات", "sales invoice"), ("Sales Invoice",)),
	(("فاتوره مشتريات", "purchase invoice"), ("Purchase Invoice",)),
	(("امر بيع", "sales order"), ("Sales Order",)),
	(("امر شراء", "purchase order"), ("Purchase Order",)),
	(("موظف", "employee"), ("Employee",)),
	(("مورد", "supplier"), ("Supplier",)),
	(("صنف", "item"), ("Item",)),
	(("اجتماع", "اجتماعات", "meeting", "meetings"), ("Event",)),
	(("عميل", "عملاء", "customer", "customers"), ("Customer",)),
	(("ليد", "lead", "leads"), ("CRM Lead", "Lead")),
)

_TASK_WORDS = ("مهمه", "مهام", "todo", "to-do", "to do", "task", "tasks")
_SYNONYMS = {
	"meeting": "Event",
	"meetings": "Event",
	"task": "ToDo",
	"tasks": "ToDo",
	"todo": "ToDo",
	"to-do": "ToDo",
	"to do": "ToDo",
}
_CREATE_WORDS = ("اعمل", "انشئ", "انشاء", "اضف", "اضيف", "سوي", "سو", "عمل", "create", "add", "make")
_QUERY_WORDS = ("افتح", "اعرض", "قائمه", "ابحث", "كم", "list", "show", "open", "find")
_LIST_FIELDS = {
	"ToDo": ["name", "description", "date", "status"],
	"Event": ["name", "subject", "starts_on", "event_category"],
	"Customer": ["name", "customer_name", "customer_type"],
	"CRM Lead": ["name", "lead_name", "status"],
	"Lead": ["name", "lead_name", "status"],
}


def match_doctype(text: str | None) -> str | None:
	"""The DocType the user named. Task words win over the word اجتماع."""
	norm = normalize_arabic(text)
	if not norm:
		return None
	if any(_has(norm, word) for word in _TASK_WORDS):
		return _first_existing(("ToDo",))
	found: list[tuple[int, tuple[str, ...]]] = []
	for phrases, names in _PHRASES:
		for phrase in phrases:
			if _has(norm, phrase):
				found.append((len(phrase), names))
	found.sort(key=lambda item: item[0], reverse=True)
	for _length, names in found:
		hit = _first_existing(names)
		if hit:
			return hit
	return None


def interpret(text: str | None) -> dict | None:
	"""Return {doctype, action, values} when the message clearly targets a DocType."""
	doctype = match_doctype(text)
	if not doctype:
		return None
	action = _action(text or "")
	if not action:
		return None
	return {"doctype": doctype, "action": action, "values": _values(doctype, text or "")}


def canonical_doctype(name: str | None, user_text: str | None = None) -> str:
	"""Prefer the DocType named in the user message over an invented tool argument."""
	planned = interpret(user_text or "")
	if planned:
		return planned["doctype"]
	cleaned = (name or "").strip()
	if cleaned and cleaned not in DENIED_DOCTYPES and frappe.db.exists("DocType", cleaned):
		return cleaned
	synonym = _SYNONYMS.get(cleaned.lower())
	if synonym and frappe.db.exists("DocType", synonym):
		return synonym
	return match_doctype(cleaned) or cleaned


def format_query(doctype: str, rows: list[dict], lang: str) -> str:
	if lang == "ar":
		lines = [f"وجدت {len(rows)} سجلًا من {doctype} ضمن صلاحياتك."]
		empty = f"لا توجد سجلات ظاهرة لك من {doctype}."
	else:
		lines = [f"Found {len(rows)} {doctype} records you can read."]
		empty = f"No {doctype} records are visible to you."
	if not rows:
		return empty
	for row in rows[:10]:
		bits = [str(row.get("name") or "")]
		for key, value in row.items():
			if key == "name" or value in (None, ""):
				continue
			bits.append(f"{key}: {str(value)[:80]}")
		lines.append("- " + " · ".join(bits))
	return "\n".join(lines)


def list_fields(doctype: str) -> list[str]:
	return list(_LIST_FIELDS.get(doctype) or ["name"])


def _values(doctype: str, text: str) -> dict:
	day = _relative_day(text)
	clock = _clock(text)
	if doctype == "ToDo":
		values = {}
		description = _todo_description(text, clock)
		if description:
			values["description"] = description
		if day:
			values["date"] = day
		return values
	if doctype == "Event":
		values = {"event_category": "Meeting"}
		subject = _event_subject(text)
		if subject:
			values["subject"] = subject
		if day and clock:
			values["starts_on"] = f"{day} {clock}:00"
		return values
	return {}


def _action(text: str) -> str | None:
	norm = normalize_arabic(text)
	head = " ".join(norm.split()[:8])
	question = head.startswith(("ما ", "كيف", "هل ", "why ", "how ", "what "))
	create = any(_has(head, word) for word in _CREATE_WORDS)
	if question and not any(_has(norm, word) for word in ("انشئ", "اعمل", "اضف", "create", "add")):
		create = False
	if create:
		return "create"
	if any(_has(head, word) for word in _QUERY_WORDS):
		return "query"
	return None


def _relative_day(text: str) -> str | None:
	norm = normalize_arabic(text)
	if "بعد غد" in norm or "بعد بكر" in norm:
		days = 2
	elif re.search(r"غدا|(?<!\S)غد(?!\S)|بكر|tomor+ow|tomoro|tmrw", norm):
		days = 1
	elif "اليوم" in norm or re.search(r"(?<![a-z])today(?![a-z])", norm):
		days = 0
	else:
		return None
	return str(frappe.utils.add_days(frappe.utils.nowdate(), days))


def _clock(text: str) -> str | None:
	norm = normalize_arabic(text)
	match = re.search(r"(?<!\d)(\d{1,2})(?::(\d{2}))?\s*(صباح\S*|مساء\S*|(?<![a-z])am(?![a-z])|(?<![a-z])pm(?![a-z]))", norm)
	if not match:
		return None
	hour = int(match.group(1))
	minute = match.group(2) or "00"
	mark = match.group(3) or ""
	if mark.startswith("مساء") or mark == "pm":
		if hour < 12:
			hour += 12
	elif hour == 12:
		hour = 0
	if hour > 23 or int(minute) > 59:
		return None
	return f"{hour:02d}:{minute}"


def _todo_description(text: str, clock: str | None) -> str:
	norm = normalize_arabic(text)
	base = _remainder(text)
	if not base and "اجتماع" in norm:
		base = "اجتماع"
	elif not base and "meeting" in norm:
		base = "Meeting"
	if clock and base and not re.search(r"\d", base):
		shown = _clock_label(text, clock)
		joiner = "الساعة" if re.search(r"[\u0600-\u06FF]", text or "") else "at"
		return f"{base} {joiner} {shown}".strip()
	return base


def _event_subject(text: str) -> str:
	remainder = _remainder(text)
	if remainder:
		return remainder[:140]
	if "اجتماع" in normalize_arabic(text):
		return "اجتماع"
	if "meeting" in normalize_arabic(text):
		return "Meeting"
	return ""


def _clock_label(text: str, clock: str) -> str:
	match = re.search(r"(\d{1,2}(?::\d{2})?\s*(?:صباح\S*|مساء\S*|am|pm))", text or "", re.I)
	if match:
		return match.group(1).strip()
	return clock


def _remainder(text: str) -> str:
	cleaned = (text or "").strip()
	cleaned = re.sub(r"^(?:من فضلك|اريد|أبي|ابي|ابغى|نعم)\s+", "", cleaned, flags=re.I)
	cleaned = re.sub(
		r"^(?:اعمل|أعمل|أنشئ|انشئ|إنشاء|انشاء|أضف|اضف|سوي|سوّ|سو|عمل|make|create|add)\s+",
		"",
		cleaned,
		flags=re.I,
	)
	cleaned = re.sub(r"^(?:مهمة|مهمه|مهام|todo|task|to-do)\s+", "", cleaned, flags=re.I)
	cleaned = re.sub(r"(?:غدًا|غدا|بكرة|بكره|بعد غد|اليوم|tomor+ow|tomoro|tmrw|today)", "", cleaned, flags=re.I)
	cleaned = re.sub(r"(?i)\b(?:for|fro|at|on)\b", "", cleaned)
	cleaned = re.sub(r"(?:على\s*)?\d{1,2}(?::\d{2})?\s*(?:صباح\S*|مساء\S*|am|pm)", "", cleaned, flags=re.I)
	cleaned = re.sub(r"\s+", " ", cleaned).strip(" .،,-")
	return cleaned


def _first_existing(names: tuple[str, ...]) -> str | None:
	for name in names:
		if name in DENIED_DOCTYPES:
			continue
		if frappe.db.exists("DocType", name):
			return name
	return None


def _has(norm: str, phrase: str) -> bool:
	phrase = normalize_arabic(phrase)
	if not phrase:
		return False
	if " " in phrase or re.search(r"[\u0600-\u06FF]", phrase):
		return phrase in norm
	return bool(re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", norm))
