"""The five sentences a salesperson types on /crm.

Reads return an answer. Writes become one pending card whose summary is an
Arabic sentence: a name, a status, a task, a reminder, or a صفقة. The card
does not show fieldnames or DocType names.
"""

from __future__ import annotations

import re

import frappe
from erpnext_ai_assistant.services.arabic import normalize_arabic
from erpnext_ai_assistant.services.targeting import _clock, _relative_day, crm_sales_route

CONVERT_METHOD = "crm.fcrm.doctype.crm_lead.crm_lead.convert_to_deal"
REMINDER_METHOD = "yalla_theme.api.crm_reminder.create"

_STATUS_PHRASES = (
	("غير مؤهل", "Unqualified", "غير مؤهل"),
	("تم التواصل", "Contacted", "تم التواصل"),
	("مؤهل", "Qualified", "مؤهل"),
)
_SKIP = {
	"وريني",
	"ورييني",
	"عملائي",
	"عملاي",
	"خله",
	"الحين",
	"الان",
	"كلمت",
	"سجل",
	"مهمه",
	"مهمة",
	"مهام",
	"ارسل",
	"له",
	"العرض",
	"حط",
	"تذكير",
	"بكره",
	"بكرة",
	"الصباح",
	"صباح",
	"صباحا",
	"المساء",
	"مساء",
	"غدا",
	"حول",
	"لصفقة",
	"صفقة",
	"صفقه",
	"تم",
	"التواصل",
	"مؤهل",
	"هذا",
	"هذه",
	"العميل",
	"عميل",
	"العملاء",
	"المحتمل",
	"المحتملين",
	"المحتملة",
	"الصفقة",
	"ما",
	"حالة",
	"الحالة",
	"ارجع",
	"اعرض",
	"كم",
	"عدد",
}


def handle(message: str, route: str | None, chat: str, lang: str) -> dict | None:
	"""Return {answer, pending} when this is one of the CRM-day sentences, else None."""
	if not crm_sales_route(route):
		return None
	text = message or ""
	norm = normalize_arabic(text)
	if not norm:
		return None
	if _is_convert(norm):
		return _convert(text, route, chat, lang)
	if _is_reminder(norm):
		return _reminder(text, route, chat, lang)
	if _is_task(norm):
		return _task(text, route, chat, lang)
	if _status_phrase(norm):
		return _status(text, route, chat, lang)
	if _is_my_leads(norm):
		return {"answer": _my_leads_answer(), "pending": None}
	if _is_status_question(norm):
		return _status_question(text, route)
	return None


def _is_my_leads(norm: str) -> bool:
	return bool(re.search(r"عملائي|عملاي|my open leads|my leads", norm))


def _is_status_question(norm: str) -> bool:
	if "status of this lead" in norm or "status of this deal" in norm:
		return True
	return "حالة" in norm and ("عميل" in norm or "صفقة" in norm or "هذا" in norm or "هذه" in norm)


def _is_convert(norm: str) -> bool:
	return bool(re.search(r"حول|حوّل|convert", norm) and re.search(r"صفق", norm))


def _is_reminder(norm: str) -> bool:
	return "تذكير" in norm or "حط تذكير" in norm


def _is_task(norm: str) -> bool:
	if re.search(r"كم|عدد", norm):
		return False
	return bool(re.search(r"سجل\s+مهم|مهم[ةه]\s+\S", norm))


def _status_phrase(norm: str):
	for phrase, stored, shown in _STATUS_PHRASES:
		if normalize_arabic(phrase) in norm:
			return stored, shown
	return None


def _my_leads_answer() -> str:
	if not frappe.has_permission("CRM Lead", "read"):
		return "لا يمكنك قراءة العملاء المحتملين."
	filters: dict = {"lead_owner": frappe.session.user}
	open_names = _open_statuses()
	if open_names:
		filters["status"] = ["in", open_names]
	rows = frappe.get_list(
		"CRM Lead",
		filters=filters,
		fields=["name", "lead_name", "first_name", "status"],
		order_by="modified desc",
		limit_page_length=20,
	)
	if not rows:
		return "لا عملاء محتملين مفتوحين باسمك."
	lines = ["عملاؤك المفتوحون:"]
	for row in rows:
		lines.append(f"- {_display(row)} — {_status_ar(row.get('status'))}")
	return "\n".join(lines)


def _status_question(text: str, route: str | None) -> dict:
	found = _leads_named(text, route)
	if found.get("ambiguous"):
		return {"answer": found["answer"], "pending": None}
	lead = found.get("lead")
	if not lead:
		return {"answer": "لم أجد هذا العميل.", "pending": None}
	return {"answer": f"حالة {_display(lead)}: {_status_ar(lead.get('status'))}", "pending": None}


def _status(text: str, route: str | None, chat: str, lang: str) -> dict:
	picked = _status_phrase(normalize_arabic(text))
	if not picked:
		return None
	stored, shown = picked
	found = _leads_named(text, route)
	if found.get("ambiguous"):
		return {"answer": found["answer"], "pending": None}
	lead = found.get("lead")
	if not lead:
		return {"answer": "لم أجد هذا العميل.", "pending": None}
	if not _status_exists(stored):
		return {"answer": f"لا توجد حالة باسم {shown}.", "pending": None}
	summary = f"{_display(lead)}: {shown}"
	pending = _propose(
		chat,
		"update",
		"CRM Lead",
		{"status": stored},
		summary,
		target_name=lead["name"],
		lang=lang,
	)
	return {"answer": None, "pending": pending}


def _task(text: str, route: str | None, chat: str, lang: str) -> dict:
	if not frappe.db.exists("DocType", "CRM Task"):
		return None
	found = _leads_named(text, route)
	if found.get("ambiguous"):
		return {"answer": found["answer"], "pending": None}
	lead = found.get("lead")
	if not lead:
		return {"answer": "لم أجد هذا العميل.", "pending": None}
	title = _task_title(text)
	if not title:
		return {"answer": "اكتب نص المهمة.", "pending": None}
	summary = f"{_display(lead)}، مهمة «{title}»"
	payload = {
		"title": title[:140],
		"reference_doctype": "CRM Lead",
		"reference_docname": lead["name"],
		"status": "Todo",
	}
	pending = _propose(chat, "create", "CRM Task", payload, summary, lang=lang)
	return {"answer": None, "pending": pending}


def _reminder(text: str, route: str | None, chat: str, lang: str) -> dict:
	if not frappe.db.exists("DocType", "Yalla CRM Reminder"):
		return {"answer": "التذكير غير متاح هنا.", "pending": None}
	when = _reminder_when(text)
	if not when:
		return {"answer": "اختر وقت التذكير.", "pending": None}
	ref = _reminder_reference(text, route)
	if ref.get("ambiguous"):
		return {"answer": ref["answer"], "pending": None}
	if not ref.get("doctype"):
		return {"answer": "لم أجد هذا العميل.", "pending": None}
	label = ref.get("label") or "هذا السجل"
	title = _reminder_title(text) or f"تذكير {label}"
	summary = f"تذكير {label} {when['label']}"
	pending = _propose_method(
		chat,
		"Yalla CRM Reminder",
		None,
		REMINDER_METHOD,
		{
			"title": title[:140],
			"remind_at": when["at"],
			"reference_doctype": ref["doctype"],
			"reference_name": ref["name"],
		},
		summary,
		done_ar=f"تم حفظ التذكير لـ {label}.",
	)
	return {"answer": None, "pending": pending}


def _convert(text: str, route: str | None, chat: str, lang: str) -> dict:
	found = _leads_named(text, route)
	if found.get("ambiguous"):
		return {"answer": found["answer"], "pending": None}
	lead = found.get("lead")
	if not lead:
		return {"answer": "لم أجد هذا العميل.", "pending": None}
	if _is_lost(lead):
		return {"answer": f"لا يمكن تحويل {_display(lead)} لأن حالته خاسرة.", "pending": None}
	summary = f"حوّل {_display(lead)} إلى صفقة"
	pending = _propose_method(
		chat,
		"CRM Lead",
		lead["name"],
		CONVERT_METHOD,
		{"lead": lead["name"]},
		summary,
		done_ar=f"تم تحويل {_display(lead)} إلى صفقة.",
	)
	return {"answer": None, "pending": pending}


def _propose(chat, action, doctype, payload, summary, target_name=None, lang="ar"):
	from erpnext_ai_assistant.services.tools.registry import propose_write

	return propose_write(
		chat,
		action,
		doctype,
		payload,
		summary=summary,
		target_name=target_name,
		lang=lang,
	)


def _propose_method(chat, doctype, target_name, method, args, summary, done_ar: str):
	from erpnext_ai_assistant.services.tools.registry import propose_write

	return propose_write(
		chat,
		"method",
		doctype,
		{"method": method, "args": args, "done_ar": done_ar},
		summary=summary,
		target_name=target_name,
		lang="ar",
	)


def _leads_named(text: str, route: str | None) -> dict:
	found: dict[str, dict] = {}
	for token in _name_tokens(text):
		rows = _search_leads(token)
		if not rows and token.startswith("ل") and len(token) > 3:
			rows = _search_leads(token[1:])
		for row in rows:
			found[row["name"]] = row
	if len(found) > 1:
		labels = "، ".join(_display(row) for row in found.values())
		return {"ambiguous": True, "answer": f"يوجد أكثر من نتيجة. أيهم تقصد؟ {labels}"}
	if len(found) == 1:
		return {"lead": next(iter(found.values()))}
	rec = _route_record(route)
	if rec and rec["doctype"] == "CRM Lead":
		lead = _load_lead(rec["name"])
		if lead:
			return {"lead": lead}
	return {}


def _reminder_reference(text: str, route: str | None) -> dict:
	named = _leads_named(text, route)
	if named.get("ambiguous"):
		return named
	if named.get("lead"):
		lead = named["lead"]
		return {"doctype": "CRM Lead", "name": lead["name"], "label": _display(lead)}
	rec = _route_record(route)
	if not rec:
		return {}
	if rec["doctype"] == "CRM Lead":
		lead = _load_lead(rec["name"])
		if not lead:
			return {}
		return {"doctype": "CRM Lead", "name": lead["name"], "label": _display(lead)}
	label = frappe.db.get_value(rec["doctype"], rec["name"], "title") if rec["doctype"] == "CRM Task" else None
	if rec["doctype"] == "CRM Deal":
		label = frappe.db.get_value("CRM Deal", rec["name"], "lead_name") or frappe.db.get_value(
			"CRM Deal", rec["name"], "organization_name"
		)
	return {"doctype": rec["doctype"], "name": rec["name"], "label": label or "هذا السجل"}


def _route_record(route: str | None) -> dict | None:
	match = re.search(r"/crm/(leads|deals|tasks)/([^/?#]+)", route or "")
	if not match:
		return None
	from urllib.parse import unquote

	kind = {"leads": "CRM Lead", "deals": "CRM Deal", "tasks": "CRM Task"}[match.group(1)]
	name = unquote(match.group(2))
	if not frappe.db.exists(kind, name):
		return None
	return {"doctype": kind, "name": name}


def _search_leads(token: str) -> list[dict]:
	if len(token) < 3 or not frappe.has_permission("CRM Lead", "read"):
		return []
	like = f"%{token}%"
	rows = frappe.get_list(
		"CRM Lead",
		or_filters=[
			["lead_name", "like", like],
			["first_name", "like", like],
			["last_name", "like", like],
		],
		fields=["name", "lead_name", "first_name", "status"],
		limit_page_length=5,
	)
	return rows


def _load_lead(name: str) -> dict | None:
	if not frappe.db.exists("CRM Lead", name):
		return None
	if not frappe.has_permission("CRM Lead", "read", doc=name):
		return None
	return frappe.db.get_value("CRM Lead", name, ["name", "lead_name", "first_name", "status"], as_dict=True)


def _name_tokens(text: str) -> list[str]:
	"""Keep ي and ى as typed so a name still matches the stored lead."""
	import unicodedata

	raw = unicodedata.normalize("NFKC", text or "")
	raw = re.sub(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]", "", raw)
	out = []
	for token in re.findall(r"[\u0600-\u06FFa-zA-Z]{3,}", raw):
		if normalize_arabic(token) in _SKIP or len(token) < 3:
			continue
		out.append(token)
	return out


def _task_title(text: str) -> str:
	match = re.search(r"مهم[ةه]\s+(.+)$", text or "", re.I)
	if not match:
		return ""
	title = re.sub(r"\s+", " ", match.group(1)).strip(" .،,")
	return title


def _reminder_title(text: str) -> str:
	norm = normalize_arabic(text)
	kept = [token for token in re.findall(r"[\u0600-\u06FF]{3,}", norm) if token not in _SKIP]
	return " ".join(kept)[:140]


def _reminder_when(text: str) -> dict | None:
	day = _relative_day(text)
	clock = _clock(text)
	norm = normalize_arabic(text)
	if not clock and "صباح" in norm:
		clock = "09:00"
	elif not clock and "مساء" in norm:
		clock = "17:00"
	if not day or not clock:
		return None
	label = "غداً ٩ صباحاً" if clock == "09:00" and day != str(frappe.utils.nowdate()) else clock
	if clock == "09:00" and day != str(frappe.utils.nowdate()):
		label = "غداً ٩ صباحاً"
	elif "صباح" in norm:
		label = f"الساعة {clock} صباحاً"
	elif "مساء" in norm:
		label = f"الساعة {clock} مساءً"
	return {"at": f"{day} {clock}:00", "label": label}


def _display(row: dict) -> str:
	return (row.get("lead_name") or row.get("first_name") or "").strip() or "هذا العميل"


def _status_ar(stored: str | None) -> str:
	wanted = {
		"New": "جديد",
		"Contacted": "تم التواصل",
		"Nurture": "رعاية",
		"Qualified": "مؤهل",
		"Converted": "محوّل",
		"Unqualified": "غير مؤهل",
		"Junk": "غير صالح",
	}
	return wanted.get(stored or "", stored or "")


def _status_exists(name: str) -> bool:
	return bool(frappe.db.exists("CRM Lead Status", name))


def _open_statuses() -> list[str]:
	if not frappe.db.exists("DocType", "CRM Lead Status"):
		return []
	return frappe.get_all(
		"CRM Lead Status",
		filters={"type": ["in", ["Open", "Ongoing"]]},
		pluck="name",
		limit_page_length=50,
	)


def _is_lost(lead: dict) -> bool:
	status = lead.get("status")
	if not status or not frappe.db.exists("DocType", "CRM Lead Status"):
		return False
	return frappe.db.get_value("CRM Lead Status", status, "type") == "Lost"
