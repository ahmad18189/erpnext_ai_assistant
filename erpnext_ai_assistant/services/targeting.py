"""Map Arabic and everyday words onto a real DocType.

The model must not invent a DocType name such as Meeting. مهمة is ToDo.
اجتماع is Event only when the user did not ask for a task. غدا is the next
calendar day on this site, not a guessed year.

When the match is unclear, return None so run_chat calls the AI with the
cached non-child DocType catalog available via list_doctypes.
"""

from __future__ import annotations

import re

import frappe
from erpnext_ai_assistant.services.arabic import normalize_arabic
from erpnext_ai_assistant.services.doctype_catalog import match_catalog
from erpnext_ai_assistant.services.schema import DENIED_DOCTYPES

# Longer phrases are tried first. مهمة is handled before this list.
_PHRASES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
	(("عميل محتمل", "عملاء محتملين", "العملاء المحتملين", "crm lead"), ("CRM Lead", "Lead")),
	(("فاتوره مبيعات", "فواتير المبيعات", "فواتير مبيعات", "sales invoice"), ("Sales Invoice",)),
	(("فاتوره مشتريات", "فواتير المشتريات", "فواتير مشتريات", "purchase invoice"), ("Purchase Invoice",)),
	(("امر بيع", "sales order"), ("Sales Order",)),
	(("امر شراء", "purchase order"), ("Purchase Order",)),
	(("موظف", "employee"), ("Employee",)),
	(("مورد", "supplier"), ("Supplier",)),
	(("صنف", "item"), ("Item",)),
	(("اجتماع", "اجتماعات", "meeting", "meetings"), ("Event",)),
	(("عميل", "عملاء", "customer", "customers"), ("Customer",)),
	(("ليد", "lead", "leads"), ("CRM Lead", "Lead")),
)

_TASK_WORDS = ("مهمه", "مهام", "todo", "todos", "to-do", "to do", "task", "tasks")
_SYNONYMS = {
	"meeting": "Event",
	"meetings": "Event",
	"task": "ToDo",
	"tasks": "ToDo",
	"todo": "ToDo",
	"todos": "ToDo",
	"to-do": "ToDo",
	"to do": "ToDo",
	"customer": "Customer",
	"customers": "Customer",
	"employee": "Employee",
	"employees": "Employee",
	"lead": "CRM Lead",
	"leads": "CRM Lead",
}
_CREATE_WORDS = ("اعمل", "انشئ", "انشاء", "اضف", "اضيف", "سوي", "سو", "عمل", "create", "add", "make")
_QUERY_WORDS = ("افتح", "اعرض", "قائمه", "ابحث", "list", "show", "open", "find")
_DETAIL_WORDS = (
	"جدول",
	"تفاصيل",
	"يظهر",
	"اظهر",
	"اعطيني",
	"اعطني",
	"سجل",
	"table",
	"details",
	"breakdown",
	"show me",
)
_COUNT_WORDS = ("كم", "عدد", "how many", "count", "عددها", "كم عدد")
# A register question that also names a person or company should use the transaction, not the master.
_PARTY_MASTERS = {"Employee", "Customer", "Supplier", "Item", "User", "Contact", "Company"}
_MONTHS_AR = (
	"يناير",
	"فبراير",
	"مارس",
	"أبريل",
	"مايو",
	"يونيو",
	"يوليو",
	"أغسطس",
	"سبتمبر",
	"أكتوبر",
	"نوفمبر",
	"ديسمبر",
)
_HOWTO_WORDS = (
	"كيف",
	"طريقه",
	"طريقة",
	"خطوات",
	"دليل",
	"شرح",
	"how to",
	"how do i",
	"how can i",
	"manual",
	"documentation",
	"docs",
	"instructions",
	"steps to",
)
_LIST_FIELDS = {
	"ToDo": ["name", "description", "date", "status"],
	"Event": ["name", "subject", "starts_on", "event_category"],
	"Customer": ["name", "customer_name", "customer_type"],
	"CRM Lead": ["name", "lead_name", "status"],
	"Lead": ["name", "lead_name", "status"],
}


def match_doctype(text: str | None) -> str | None:
	"""The DocType the user named. Returns None when the match is not clear.

	The catalog and translated labels are the primary match. Phrase lists only
	raise the score of a known DocType; they never invent one.
	"""
	norm = normalize_arabic(text)
	if not norm:
		return None
	scored: dict[str, int] = {}
	for row in match_catalog(text, limit=8):
		scored[row["name"]] = int(row.get("score") or 0)
	if any(_has(norm, word) for word in _TASK_WORDS):
		if _first_existing(("ToDo",)):
			scored["ToDo"] = scored.get("ToDo", 0) + 30
	for phrases, names in _PHRASES:
		for phrase in phrases:
			if not _has(norm, phrase):
				continue
			boost = len(normalize_arabic(phrase)) + 6
			for name in names:
				if _first_existing((name,)):
					scored[name] = max(scored.get(name, 0), boost)
			break
	for word, doctype in _SYNONYMS.items():
		if _has(norm, word) and _first_existing((doctype,)):
			scored[doctype] = max(scored.get(doctype, 0), len(word) + 4)
	if not scored:
		return None
	ranked = sorted(scored.items(), key=lambda item: (-item[1], -len(item[0])))
	# "سجل حضور الموظفين" matches Employee and Attendance. The register is the transaction.
	if wants_details(text) and ranked[0][0] in _PARTY_MASTERS:
		for name, score in ranked[1:]:
			if name not in _PARTY_MASTERS and score >= 4 and name not in DENIED_DOCTYPES:
				return name
	top_name, top_score = ranked[0]
	if len(ranked) > 1 and ranked[1][1] >= top_score - 2:
		return None
	if top_name in DENIED_DOCTYPES:
		return None
	return top_name


def interpret(text: str | None) -> dict | None:
	"""Return {doctype, action, values} only when both are clear. Else None → AI."""
	# How-to / manual questions go to the model + search_manual, not create/count shortcuts.
	if _is_howto(text or ""):
		return None
	doctype = match_doctype(text)
	if not doctype:
		return None
	action = _action(text or "")
	if not action:
		return None
	return {"doctype": doctype, "action": action, "values": _values(doctype, text or "")}


def _is_howto(text: str) -> bool:
	norm = normalize_arabic(text)
	if not norm:
		return False
	if any(_has(norm, word) for word in _HOWTO_WORDS):
		return True
	return bool(re.search(r"\bhow\s+(do|can|to)\b|\bsteps?\b|\bmanual\b|\bdocs?\b", norm))


def canonical_doctype(name: str | None, user_text: str | None = None) -> str:
	"""Prefer the DocType named in the user message over an invented tool argument."""
	planned = interpret(user_text or "")
	if planned:
		return planned["doctype"]
	from_text = match_doctype(user_text or "")
	if from_text:
		return from_text
	cleaned = (name or "").strip()
	if cleaned and cleaned not in DENIED_DOCTYPES and frappe.db.exists("DocType", cleaned):
		# Must be a non-child DocType when possible
		if not frappe.db.get_value("DocType", cleaned, "istable"):
			return cleaned
	synonym = _SYNONYMS.get(cleaned.lower())
	if synonym and frappe.db.exists("DocType", synonym):
		return synonym
	# Last chance: catalog search on the tool argument itself
	hits = match_catalog(cleaned, limit=1)
	if hits:
		return hits[0]["name"]
	return match_doctype(cleaned) or cleaned


def format_query(doctype: str, rows: list[dict], lang: str, capped: bool = False) -> str:
	if lang == "ar":
		lines = [f"هذه الصفحة تعرض {len(rows)} سجلًا من {doctype} ضمن صلاحياتك."]
		if capped:
			lines.append("هذه ليست القائمة كاملة.")
		empty = f"لا توجد سجلات ظاهرة لك من {doctype}."
	else:
		lines = [f"This page shows {len(rows)} {doctype} records you can read."]
		if capped:
			lines.append("This is not the full list.")
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
	"""List columns: a known override, otherwise title_field plus in-list fields."""
	override = _LIST_FIELDS.get(doctype)
	if override:
		return list(override)
	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return ["name"]
	fields = ["name"]
	title = getattr(meta, "title_field", None)
	if title and title not in fields:
		fields.append(title)
	for df in meta.fields:
		if df.in_list_view and df.fieldname and df.fieldname not in fields:
			fields.append(df.fieldname)
		if len(fields) >= 6:
			break
	try:
		permitted = set(meta.get_permitted_fieldnames(permission_type="read") or [])
	except Exception:
		permitted = set()
	if permitted:
		fields = [field for field in fields if field in permitted or field == "name"]
	return fields or ["name"]


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


def needs_live_check(text: str | None) -> bool:
	"""True when the reply must come from a tool result, not a model guess."""
	norm = normalize_arabic(text)
	if not norm:
		return False
	if any(_has(norm, word) for word in _COUNT_WORDS):
		return True
	if any(_has(norm, word) for word in _QUERY_WORDS):
		return True
	return bool(match_doctype(text) and re.search(r"\b(how many|list|show|open|find)\b|كم|عدد|قائمه|ابحث|اعرض|افتح", norm))


def wants_details(text: str | None) -> bool:
	"""A register, table, or breakdown. 'كم يوم حضور' is details, not a headcount."""
	norm = normalize_arabic(text)
	if not norm:
		return False
	if any(_has(norm, word) for word in _DETAIL_WORDS):
		return True
	return bool(re.search(r"\b(table|details|breakdown|show me)\b", norm))


def _action(text: str) -> str | None:
	norm = normalize_arabic(text)
	head = " ".join(norm.split()[:8])
	question = head.startswith(("ما ", "كيف", "هل ", "why ", "how ", "what "))
	# A table or register wins over كم. "كم يوم حضور وغياب" asks for the days, not a count of rows.
	if wants_details(text):
		return "query"
	# Count before create: "عمل" must not win inside "عملاء".
	if any(_has(norm, word) for word in _COUNT_WORDS) or re.search(r"\bhow many\b|\bcount\b", norm):
		return "count"
	create = any(_has(head, word) for word in _CREATE_WORDS)
	if question and not any(_has(norm, word) for word in ("انشئ", "اعمل", "اضف", "create", "add")):
		create = False
	if create:
		return "create"
	if any(_has(head, word) for word in _QUERY_WORDS):
		return "query"
	return None


def format_count(doctype: str, total: int, lang: str) -> str:
	if lang == "ar":
		return f"عدد سجلات {doctype} الظاهرة لك: {total}."
	return f"You can see {total} {doctype} records."


def summarize_doctype(doctype: str, text: str | None, lang: str) -> str:
	"""Plain-language rows for any DocType the user can read.

	The shape comes from the DocType itself: a date for "this month", a Link
	that has a companion name (employee / employee_name, customer / customer_name)
	to group a long register, a short Select such as status, and a currency total.
	"""
	from collections import Counter

	meta = frappe.get_meta(doctype)
	plan = _summary_plan(meta)
	start, end = _month_window(text)
	filters = {}
	if start and end and plan["date"]:
		filters[plan["date"]] = ["between", [str(start), str(end)]]
	fields = ["name"]
	for key in ("date", "group", "group_name", "select", "amount", "title"):
		field = plan.get(key)
		if field and field not in fields:
			fields.append(field)
	order = f"{plan['date']} asc" if plan["date"] else "modified desc"
	try:
		rows = frappe.get_list(
			doctype,
			filters=filters,
			fields=fields,
			order_by=order,
			limit_page_length=500,
		)
	except frappe.PermissionError:
		label = _tr(doctype, lang)
		if lang == "ar":
			return f"لا صلاحية لقراءة {label}."
		return f"You cannot read {label}."
	translations = _translations(lang)
	label = _tr(doctype, lang, translations)
	period = _period_label(start, end, rows, plan["date"], lang)
	group_field = plan["group"]
	# Group only when the DocType names a party (employee_name, customer_name). A master list stays a list.
	group_it = bool(plan["group_name"]) and (len(rows) > 15 or (plan["select"] and len(rows) > 8))
	if lang == "ar":
		if not rows:
			return f"ما في سجلات {label} ظاهرة لك {period}."
		if group_it:
			intro = f"{label} {period}. يظهر لك {len(rows)} سجلاً."
		else:
			intro = f"{label} {period}. يظهر لك {len(rows)} سجلاً."
	else:
		if not rows:
			return f"No {label} records are visible to you {period}."
		intro = f"{label} {period}. You can see {len(rows)} records."
	lines = [intro]
	if group_it:
		buckets: dict[str, dict] = {}
		for row in rows:
			key = row.get(group_field) or "?"
			bucket = buckets.setdefault(
				key,
				{"name": row.get(plan["group_name"]) or key, "counts": Counter(), "amount": 0.0, "n": 0},
			)
			shown_name = row.get(plan["group_name"]) or bucket["name"]
			if shown_name:
				bucket["name"] = shown_name
			bucket["n"] += 1
			if plan["select"]:
				bucket["counts"][row.get(plan["select"]) or ""] += 1
			if plan["amount"] is not None and row.get(plan["amount"]) not in (None, ""):
				bucket["amount"] += float(row.get(plan["amount"]) or 0)
		ordered = sorted(buckets.values(), key=lambda item: str(item["name"] or ""))
		shown = ordered[:40]
		for bucket in shown:
			lines.append("- " + _group_line(bucket, plan, lang, translations))
		if len(ordered) > len(shown):
			extra = len(ordered) - len(shown)
			lines.append(
				f"وهناك {extra} مجموعات أخرى في نفس الفترة." if lang == "ar" else f"And {extra} more groups in the same period."
			)
	else:
		shown = rows[:15]
		for row in shown:
			lines.append("- " + _row_line(row, plan, meta, lang, translations))
		if len(rows) > len(shown):
			extra = len(rows) - len(shown)
			lines.append(f"وهناك {extra} سجلات أخرى." if lang == "ar" else f"And {extra} more records.")
	if len(rows) >= 500:
		lines.append(
			"هذه أول 500 سجلات فقط، والقائمة أطول من ذلك."
			if lang == "ar"
			else "This is the first 500 rows. The list is longer."
		)
	return "\n".join(lines)


def _summary_plan(meta) -> dict:
	"""Pick the date, the party link, a short status, and a money field from meta."""
	skip = {"amended_from", "company", "owner", "naming_series"}
	fields = [df for df in meta.fields if df.fieldname and df.fieldtype not in ("Section Break", "Column Break", "Tab Break", "HTML", "Fold")]
	try:
		permitted = set(meta.get_permitted_fieldnames(permission_type="read") or [])
	except Exception:
		permitted = set()

	def allowed(fieldname: str | None) -> bool:
		return bool(fieldname) and (not permitted or fieldname in permitted or fieldname == "name")

	by_name = {df.fieldname: df for df in fields if allowed(df.fieldname)}
	date = None
	for preferred in ("posting_date", "transaction_date", "attendance_date", "date"):
		df = by_name.get(preferred)
		if df and df.fieldtype == "Date":
			date = preferred
			break
	if not date:
		for df in fields:
			if df.fieldname in by_name and df.fieldtype == "Date" and df.in_list_view:
				date = df.fieldname
				break
	if not date:
		for df in fields:
			if df.fieldname in by_name and df.fieldtype == "Date":
				date = df.fieldname
				break

	group = group_name = None
	for df in fields:
		if df.fieldtype not in ("Link", "Dynamic Link") or df.fieldname not in by_name or df.fieldname in skip:
			continue
		companion = f"{df.fieldname}_name"
		if companion in by_name:
			group, group_name = df.fieldname, companion
			break
	if not group:
		for df in fields:
			if df.fieldtype == "Link" and df.fieldname in by_name and df.fieldname not in skip and df.in_list_view:
				group = df.fieldname
				break

	select = None
	status = by_name.get("status")
	if status and status.fieldtype == "Select":
		select = "status"
	else:
		for df in fields:
			if df.fieldname not in by_name or df.fieldtype != "Select" or df.fieldname in skip:
				continue
			options = [line for line in (df.options or "").split("\n") if line.strip()]
			if 1 < len(options) <= 8:
				select = df.fieldname
				break

	amount = None
	for preferred in ("grand_total", "net_total", "total", "base_grand_total", "paid_amount"):
		df = by_name.get(preferred)
		if df and df.fieldtype in ("Currency", "Float"):
			amount = preferred
			break
	if not amount:
		for df in fields:
			if df.fieldname in by_name and df.fieldtype == "Currency" and df.in_list_view:
				amount = df.fieldname
				break

	title = meta.title_field if meta.title_field and meta.title_field != "name" and allowed(meta.title_field) else None
	if title == group or title == group_name:
		title = None
	return {
		"date": date,
		"group": group,
		"group_name": group_name,
		"select": select,
		"amount": amount,
		"title": title,
	}


def _group_line(bucket: dict, plan: dict, lang: str, translations: dict) -> str:
	parts = []
	if plan["select"]:
		for status, total in bucket["counts"].most_common():
			if not total:
				continue
			parts.append(f"{_tr(status, lang, translations)} {int(total)}")
	elif bucket["n"]:
		parts.append(f"{int(bucket['n'])} سجل" if lang == "ar" else f"{int(bucket['n'])} records")
	if plan["amount"] and bucket["amount"]:
		parts.append(_money(bucket["amount"]))
	joiner = "، " if lang == "ar" else ", "
	body = joiner.join(parts) if parts else str(bucket["n"])
	return f"{bucket['name']}: {body}"


def _row_line(row, plan: dict, meta, lang: str, translations: dict) -> str:
	title = row.get(plan["title"]) or row.get(plan["group_name"]) or row.get("name")
	parts = []
	for key in ("date", "group", "select", "amount"):
		field = plan.get(key)
		if not field or key == "group" and plan.get("group_name"):
			continue
		value = row.get(field)
		if value in (None, ""):
			continue
		df = meta.get_field(field)
		shown = _tr(value, lang, translations) if key == "select" else (_money(value) if key == "amount" else value)
		caption = _tr(df.label, lang, translations) if df and df.label else field
		parts.append(f"{caption} {shown}")
	joiner = "، " if lang == "ar" else ", "
	if parts:
		return f"{title}: " + joiner.join(parts)
	return str(title)


def _money(value) -> str:
	try:
		return frappe.utils.fmt_money(value)
	except Exception:
		return str(value)


def _translations(lang: str) -> dict:
	try:
		return frappe.translate.get_all_translations(lang) or {}
	except Exception:
		return {}


def _tr(text, lang: str, translations: dict | None = None) -> str:
	raw = "" if text is None else str(text)
	if not raw:
		return ""
	book = translations if translations is not None else _translations(lang)
	return str(book.get(raw) or raw)


def _month_window(text: str | None):
	norm = normalize_arabic(text)
	if not any(token in norm for token in ("للشهر", "هذا الشهر", "this month")):
		return None, None
	today = frappe.utils.getdate()
	return frappe.utils.get_first_day(today), frappe.utils.get_last_day(today)


def _period_label(start, end, rows, date_field: str | None, lang: str) -> str:
	if start:
		if lang == "ar":
			return f"لشهر {_MONTHS_AR[start.month - 1]} {start.year}"
		return f"for {start.strftime('%B %Y')}"
	dates = [row.get(date_field) for row in rows if date_field and row.get(date_field)]
	if not dates:
		return "في الفترة المطلوبة" if lang == "ar" else "for the requested period"
	first, last = min(dates), max(dates)
	if lang == "ar":
		return f"من {first} إلى {last}"
	return f"from {first} to {last}"


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
	if " " in phrase:
		return phrase in norm
	# Arabic tokens may appear with the definite article ال (المهام، العملاء).
	if re.search(r"[\u0600-\u06FF]", phrase):
		return bool(re.search(rf"(?<!\w)(?:ال)?{re.escape(phrase)}(?!\w)", norm, re.UNICODE))
	return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", norm, re.UNICODE))
