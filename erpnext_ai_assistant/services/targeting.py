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
from erpnext_ai_assistant.services.arabic import normalize_arabic, strip_al
from erpnext_ai_assistant.services.doctype_catalog import match_catalog
from erpnext_ai_assistant.services.schema import DENIED_DOCTYPES

# Longer phrases are tried first. مهمة is handled before this list.
_PHRASES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
	(("عميل محتمل", "عملاء محتملين", "العملاء المحتملين", "crm lead"), ("CRM Lead", "Lead")),
	(("فاتوره مبيعات", "فواتير المبيعات", "فواتير مبيعات", "sales invoice"), ("Sales Invoice",)),
	(("فاتوره مشتريات", "فواتير المشتريات", "فواتير مشتريات", "purchase invoice"), ("Purchase Invoice",)),
	(("اوامر البيع", "اوامر بيع", "امر البيع", "امر بيع", "sales order"), ("Sales Order",)),
	(("اوامر الشراء", "اوامر شراء", "امر الشراء", "امر شراء", "purchase order"), ("Purchase Order",)),
	(("عروض الاسعار", "عروض اسعار", "عرض السعر", "عرض سعر", "quotation"), ("Quotation",)),
	(("سندات القبض", "سند قبض", "الدفعات", "دفعات", "payment entry", "payment entries", "payments"), ("Payment Entry",)),
	(("اذونات التسليم", "اذن تسليم", "delivery note"), ("Delivery Note",)),
	(("مشاريع", "مشروع", "project"), ("Project",)),
	(("موظف", "employee"), ("Employee",)),
	(("مورد", "supplier"), ("Supplier",)),
	(("صنف", "item"), ("Item",)),
	(("اجتماع", "اجتماعات", "meeting", "meetings"), ("Event",)),
	(("عميل", "عملاء", "customer", "customers"), ("Customer",)),
	(("ليد", "lead", "leads"), ("CRM Lead", "Lead")),
	# A bare "invoices" is a sales invoice; "فواتير المشتريات" above still wins on length.
	(("الفواتير", "فواتير", "فاتوره", "invoices", "invoice"), ("Sales Invoice",)),
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
_QUERY_WORDS = (
	"افتح",
	"اعرض",
	"قائمه",
	"ابحث",
	"list",
	"show",
	"open",
	"find",
	"صدر",
	"تصدير",
	"اصدر",
	"export",
	"excel",
	"xlsx",
	"csv",
	"اكسل",
	"chart",
	"graph",
	"مخطط",
	"image",
	"png",
	"صورة",
	"صوره",
	"text",
)
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
	"register",
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


# "invoices by customer" names the invoices; customer is how to group them.
_GROUPING = re.compile(r"\b(?:grouped\s+by|by|per|for\s+each)\s+[\w\-]+(?:\s+[\w\-]+)?|(?:بحسب|حسب|لكل)\s+\S+", re.I | re.UNICODE)


def without_grouping(text: str | None) -> str:
	return _GROUPING.sub(" ", text or "")


# "a quotation for Al-Ofuq company": the words after "for" describe the party, not the DocType.
_PARTY = re.compile(r"\b(?:for|to|from|with)\b|(?<!\w)(?:لشركة|لشركه|للشركة|للشركه|لعميل|للعميل|لمؤسسة|لمؤسسه|لمورد|للمورد|من\s+شركة|من\s+شركه)(?!\w)", re.I | re.UNICODE)


def doctype_text(text: str | None) -> str:
	"""The part of the message that names the DocType: no "by X", and nothing after "for/to"."""
	head = without_grouping(text)
	cut = _PARTY.split(head, 1)[0]
	return cut if cut.strip() else head


def grouping_words(text: str | None) -> list[str]:
	"""The words after "by"/"حسب" ("by customer" -> ["customer"])."""
	found = []
	for match in _GROUPING.finditer(text or ""):
		words = re.split(r"\s+", match.group(0).strip())
		found.extend(word for word in words[1:] if word.lower() not in ("by", "each"))
	return found


def match_doctype(text: str | None) -> str | None:
	"""The DocType the user named. Returns None when the match is not clear.

	The catalog and translated labels are the primary match. Phrase lists only
	raise the score of a known DocType; they never invent one.
	"""
	whole = without_grouping(text)
	head = doctype_text(text)
	if head != whole:
		found = _match_doctype_in(head)
		if found:
			return found
	return _match_doctype_in(whole)


def _match_doctype_in(text: str) -> str | None:
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
			# Clear the tie when Lead and CRM Lead share the same everyday word.
			scored[doctype] = scored.get(doctype, 0) + len(word) + 12
	if not scored:
		return None
	ranked = sorted(scored.items(), key=lambda item: (-item[1], -len(item[0])))
	# "سجل حضور الموظفين" matches Employee and Attendance. The register is the transaction.
	if wants_details(text) and ranked[0][0] in _PARTY_MASTERS:
		for name, score in ranked[1:]:
			if name not in _PARTY_MASTERS and score >= 4 and name not in DENIED_DOCTYPES:
				return name
	top_name, top_score = ranked[0]
	second_is_party = len(ranked) > 1 and ranked[1][0] in _PARTY_MASTERS
	# "attendance register for employees" names the register and the people. Keep the register.
	if len(ranked) > 1 and ranked[1][1] >= top_score - 2 and not (
		wants_details(text) and second_is_party and top_name not in _PARTY_MASTERS
	):
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
	# "أنشئ عرض سعر لعدد 3 كراسي": a create states quantities, not a counted number.
	head = " ".join(norm.split()[:3])
	if any(_has(head, word) for word in _CREATE_WORDS):
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
	# "do not count leave" is an exclusion, not a headcount.
	count_hit = any(_has(norm, word) for word in _COUNT_WORDS) or bool(re.search(r"\bhow many\b|\bcount\b", norm))
	if count_hit and re.search(r"don'?t\s+count|do\s+not\s+count|not\s+counting", norm):
		count_hit = bool(re.search(r"\bhow many\b", norm) or any(_has(norm, word) for word in ("كم", "عدد", "عددها", "كم عدد")))
	if count_hit:
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
	label = _tr(doctype, lang) or doctype
	if lang == "ar":
		return f"عدد سجلات {label} الظاهرة لك: {total}."
	return f"You can see {total} {label} records."


# Frappe list pages are limit_start + limit_page_length. Totals use count/sum, not the page.
_LIST_PAGE = 15
_GROUP_PAGE = 40


LIST_LIMIT = 10


def records_table(doctype: str, text: str | None, lang: str, limit: int = LIST_LIMIT) -> tuple[str, int]:
	"""The matching records themselves (number, who, date, amount, status), newest first.

	Uses the same filters as the count, so "4 overdue invoices" then "show them" lists those 4.
	Returns (markdown, total).
	"""
	meta = frappe.get_meta(doctype)
	plan = _summary_plan(meta)
	filters, note, problem, empty = _query_filters(doctype, plan, text, lang)
	if problem:
		return problem, 0
	label = _tr(doctype, lang) or doctype
	total = 0 if empty else _sql_total(doctype, filters)
	if not total:
		return (f"لا توجد سجلات {label} مطابقة." if lang == "ar" else f"No matching {label} records."), 0
	who = next((f for f in (plan.get("group_name"), plan.get("title"), "customer_name", "supplier_name", "party_name", plan.get("group")) if f and meta.has_field(f)), None)
	columns = list(dict.fromkeys(f for f in ("name", who, plan.get("date"), plan.get("amount"), plan.get("select")) if f))
	order = f"{plan['date']} desc" if plan.get("date") else "modified desc"
	rows = frappe.get_list(doctype, filters=filters, fields=columns, order_by=order, limit_page_length=limit)
	book = _translations(lang)
	header = [("الرقم" if lang == "ar" else "ID") if f == "name" else _tr(meta.get_field(f).label or f, lang, book) for f in columns]
	lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
	for row in rows:
		cells = []
		for f in columns:
			value = row.get(f)
			if value in (None, ""):
				value = "—"
			elif f == plan.get("amount"):
				value = frappe.utils.fmt_money(value)
			elif f == plan.get("select"):
				value = _tr(value, lang, book)
			cells.append(str(value).replace("|", "/").replace("\n", " "))
		lines.append("| " + " | ".join(cells) + " |")
	where = f" ({note})" if note else ""
	if lang == "ar":
		intro = f"{label}{where}: {total} سجلًا." + (f" يظهر أحدث {len(rows)}." if total > len(rows) else "")
	else:
		intro = f"{label}{where}: {total} records." + (f" Showing the newest {len(rows)}." if total > len(rows) else "")
	return intro + "\n\n" + "\n".join(lines) + "\n" + _list_link(doctype, filters, label, lang), total


def _list_link(doctype: str, filters: list, label: str, lang: str) -> str:
	"""An Open-list button for the same records; simple equal filters travel in the URL."""
	from urllib.parse import urlencode

	simple = {row[1]: row[3] for row in filters if isinstance(row, (list, tuple)) and len(row) == 4 and row[2] == "=" and isinstance(row[3], (str, int))}
	from erpnext_ai_assistant.services.desk_link import desk_path

	path = desk_path(frappe.scrub(doctype).replace("_", "-"))
	if simple:
		path += "?" + urlencode(simple)
	text = f"افتح قائمة {label}" if lang == "ar" else f"Open the {label} list"
	return f"[[open:{path}|{text}]]"


def summarize_doctype(doctype: str, text: str | None, lang: str) -> str:
	"""Plain-language rows for any DocType the user can read.

	Filtration is a Frappe filter list (between, is set, in, not in), including
	a linked party such as Employee.user_id. Aggregation is count/sum with
	group_by, so the totals cover every matching row. The lines are one page.
	"""
	from collections import Counter

	meta = frappe.get_meta(doctype)
	plan = _summary_plan(meta)
	filters, note, problem, empty = _query_filters(doctype, plan, text, lang)
	translations = _translations(lang)
	label = _tr(doctype, lang, translations)
	start, end = _month_window(text)
	if problem:
		return problem
	try:
		total = 0 if empty else _sql_total(doctype, filters)
		bounds = []
		if not empty and not start and plan["date"]:
			first, last = _sql_bounds(doctype, plan["date"], filters)
			if first:
				bounds = [{plan["date"]: first}, {plan["date"]: last}]
	except frappe.PermissionError:
		if lang == "ar":
			return f"لا صلاحية لقراءة {label}."
		return f"You cannot read {label}."
	period = _period_label(start, end, bounds, plan["date"], lang)
	if note:
		period = f"{period} ({note})".strip()
	head = f"{label} {period}".strip() if period else label
	if not total:
		if lang == "ar":
			return f"ما في سجلات {head} ظاهرة لك."
		return f"No {head} records are visible to you."
	group_it = bool(plan["group_name"]) and (total > _LIST_PAGE or (plan["select"] and total > 8))
	if lang == "ar":
		intro = f"{head}. يظهر لك {total} سجلاً."
	else:
		intro = f"{head}. You can see {total} records."
	lines = [intro]
	if group_it:
		grouped = _sql_groups(doctype, meta, plan, filters)
		buckets: dict[str, dict] = {}
		for row in grouped:
			key = row.get(plan["group"]) or "?"
			bucket = buckets.setdefault(
				key,
				{"name": row.get(plan["group_name"]) or key, "counts": Counter(), "amount": 0.0, "n": 0},
			)
			shown_name = row.get(plan["group_name"]) or bucket["name"]
			if shown_name:
				bucket["name"] = shown_name
			count = int(row.get("total") or 0)
			bucket["n"] += count
			if plan["select"]:
				bucket["counts"][row.get(plan["select"]) or ""] += count
			if plan["amount"] is not None and row.get("amount") not in (None, ""):
				bucket["amount"] += float(row.get("amount") or 0)
		ordered = sorted(buckets.values(), key=lambda item: str(item["name"] or ""))
		shown = ordered[:_GROUP_PAGE]
		for bucket in shown:
			lines.append("- " + _group_line(bucket, plan, lang, translations))
		if len(ordered) > len(shown):
			extra = len(ordered) - len(shown)
			lines.append(
				f"وهناك {extra} مجموعات أخرى. الأرقام فوق تشمل كل السجلات، وهذه صفحة المجموعات."
				if lang == "ar"
				else f"And {extra} more groups. The total above includes every record; these lines are one page of groups."
			)
	else:
		order = f"{plan['date']} asc" if plan["date"] else "modified desc"
		fields = ["name"]
		for key in ("date", "group", "group_name", "select", "amount", "title"):
			field = plan.get(key)
			if field and field not in fields and meta.has_field(field):
				fields.append(field)
		rows = frappe.get_list(
			doctype,
			filters=filters,
			fields=fields,
			order_by=order,
			limit_start=0,
			limit_page_length=_LIST_PAGE,
		)
		for row in rows:
			lines.append("- " + _row_line(row, plan, meta, lang, translations))
		if total > len(rows):
			extra = total - len(rows)
			lines.append(
				f"وهناك {extra} سجلات أخرى في الصفحات التالية."
				if lang == "ar"
				else f"And {extra} more records on later pages."
			)
	return "\n".join(lines)


def filtered_count(doctype: str, text: str | None, lang: str):
	"""Permission-scoped count after the same Frappe filters as the register."""
	meta = frappe.get_meta(doctype)
	plan = _summary_plan(meta)
	filters, note, problem, empty = _query_filters(doctype, plan, text, lang)
	if problem or empty:
		return 0, note, problem
	try:
		return _sql_total(doctype, filters), note, ""
	except frappe.PermissionError:
		if lang == "ar":
			return 0, "", f"لا صلاحية لقراءة {_tr(doctype, lang)}."
		return 0, "", f"You cannot read {_tr(doctype, lang)}."


def _agg(function: str, field: str, alias: str):
	"""One aggregate column for get_list.

	Frappe 16 refuses SQL functions written as strings and takes {"COUNT": "*", "as": "total"}.
	Frappe 15 only understands the string form, so the version-15 branch keeps working.
	"""
	if int(frappe.__version__.split(".")[0]) >= 16:
		return {function.upper(): field, "as": alias}
	return f"{function.lower()}({'name' if field == '*' else field}) as {alias}"


def _sql_total(doctype: str, filters: list) -> int:
	rows = frappe.get_list(doctype, fields=[_agg("count", "*", "total")], filters=filters, limit_page_length=0)
	if not rows:
		return 0
	return int(rows[0].get("total") or 0)


def _sql_bounds(doctype: str, date_field: str, filters: list):
	rows = frappe.get_list(
		doctype,
		fields=[_agg("min", date_field, "first_on"), _agg("max", date_field, "last_on")],
		filters=filters,
		limit_page_length=0,
	)
	if not rows:
		return None, None
	return rows[0].get("first_on"), rows[0].get("last_on")


def _sql_groups(doctype: str, meta, plan: dict, filters: list) -> list:
	columns = []
	group_cols = []
	for field in (plan.get("group"), plan.get("group_name"), plan.get("select")):
		if field and meta.has_field(field) and field not in columns:
			columns.append(field)
			group_cols.append(field)
	if not group_cols:
		return []
	columns.append(_agg("count", "*", "total"))
	if plan.get("amount") and meta.has_field(plan["amount"]):
		columns.append(_agg("sum", plan["amount"], "amount"))
	order = group_cols[1] if plan.get("group_name") in group_cols else group_cols[0]
	return frappe.get_list(
		doctype,
		fields=columns,
		filters=filters,
		group_by=", ".join(group_cols),
		order_by=f"{order} asc",
		limit_page_length=0,
	)


_ROLE_WORD = r"(?:صلاحيه|صلاحيات|دور|role|permission)"
_NEG_HAVE = r"(?:ليس لديهم|ليس لديه|بدون|without|do not have|don't have|not have)"
_HAVE = r"(?:لديهم|لديه|who have|with)"
_NOT_A_TARGET = {"صلاحيه", "صلاحيات", "دور", "role", "permission"}


# استثتي is the usual misspelling of استثني. ة is already ه after normalize_arabic.
_EXCLUDE = (
	r"(?:لا\s*تحتسب|لا\s*تحسب|بدون\s*احتساب|باستثنا\w*|ما\s*عدا|استثن\w*|استثت\w*"
	r"|don'?t\s+count|do\s+not\s+count|excluding|exclude|except|not\s+counting|other\s+than)"
)


def _query_filters(doctype: str, plan: dict, text: str | None, lang: str):
	"""Frappe filter list: the date window, the linked party, then a status the user told us to skip."""
	filters = []
	start, end = _month_window(text)
	if start and end and plan.get("date"):
		filters.append([doctype, plan["date"], "between", [str(start), str(end)]])
	extra, note, problem, empty = _related_filters(doctype, plan, text, lang)
	if problem or empty:
		return filters + extra, note, problem, empty
	excluded, exclude_note = _select_exclusions(doctype, plan, text, lang)
	if excluded and plan.get("select"):
		filters.append([doctype, plan["select"], "not in", excluded])
	covered, covered_note, covered_problem = _covered_day_filters(doctype, plan, text, filters, lang)
	if covered_problem:
		return filters, "", covered_problem, False
	filters.extend(covered)
	state_filters, state_note = state_filters_for(doctype, text, lang)
	filters.extend(state_filters)
	notes = [part for part in (state_note, note, exclude_note, covered_note) if part]
	joiner = "، " if lang == "ar" else ", "
	return filters + extra, joiner.join(notes), "", False


# (words, docstatus, status option, English note, Arabic note). Longer phrases first: "غير مدفوعه" before "مدفوعه".
_STATE_WORDS = (
	(("not paid", "unpaid", "غير مدفوعه", "غير مدفوع", "غير المدفوعه"), None, "Unpaid", "unpaid", "غير مدفوعة"),
	(("partly paid", "مدفوعه جزئيا"), None, "Partly Paid", "partly paid", "مدفوعة جزئيًا"),
	(("overdue", "late", "متاخره", "متاخر", "متاخرات", "المتاخره"), None, "Overdue", "overdue", "متأخرة"),
	(("paid", "مدفوعه", "مدفوع", "المدفوعه"), None, "Paid", "paid", "مدفوعة"),
	(("completed", "done", "finished", "مكتمله", "مكتمل", "منجزه", "منجز"), None, "Completed", "completed", "مكتملة"),
	(("pending review", "قيد المراجعه"), None, "Pending Review", "pending review", "قيد المراجعة"),
	(("closed", "مغلقه", "مغلق"), None, "Closed", "closed", "مغلقة"),
	(("submitted", "approved", "confirmed", "معتمده", "معتمد", "المعتمده", "مرحله", "مرحل"), 1, None, "submitted", "معتمدة"),
	(("drafts", "draft", "مسودات", "مسوده"), 0, None, "draft", "مسودة"),
	(("cancelled", "canceled", "ملغاه", "ملغيه", "ملغي", "الملغاه"), 2, None, "cancelled", "ملغاة"),
	(("open", "مفتوحه", "مفتوح", "المفتوحه"), None, "Open", "open", "مفتوحة"),
)


def state_filters_for(doctype: str, text: str | None, lang: str) -> tuple[list, str]:
	"""Turn "submitted", "overdue", "مسودة" into docstatus/status filters this DocType supports."""
	norm = normalize_arabic(text)
	if not norm:
		return [], ""
	meta = frappe.get_meta(doctype)
	status_df = meta.get_field("status")
	options = {line.strip() for line in ((status_df.options if status_df else "") or "").split("\n") if line.strip()}
	words = norm.split()
	filters, notes, used = [], [], set()
	for phrases, docstatus, option, note_en, note_ar in _STATE_WORDS:
		hit = next((p for p in phrases if _has(norm, p)), None)
		if not hit or any(hit in other for other in used):
			continue
		# "open the quotation list" is a navigation verb, not the Open status.
		if hit == "open" and words and words[0] == "open":
			continue
		if option == "Unpaid" and meta.has_field("outstanding_amount"):
			# People mean "still owes money": Unpaid, Overdue, and Partly Paid in ERPNext terms.
			filters += [[doctype, "docstatus", "=", 1], [doctype, "outstanding_amount", ">", 0]]
		elif docstatus is not None and meta.is_submittable:
			filters.append([doctype, "docstatus", "=", docstatus])
		elif option and option in options:
			filters.append([doctype, "status", "=", option])
		else:
			continue
		used.add(hit)
		notes.append(note_ar if lang == "ar" else note_en)
	return filters, ("، " if lang == "ar" else ", ").join(notes)


def _select_exclusions(doctype: str, plan: dict, text: str | None, lang: str):
	"""Match "لا تحتسب الإجازة" or "do not count cancelled" to a Select option on this DocType."""
	field = plan.get("select")
	df = frappe.get_meta(doctype).get_field(field) if field else None
	options = [line.strip() for line in ((df.options if df else "") or "").split("\n") if line.strip()]
	if not options:
		return [], ""
	phrases = _exclusion_phrases(text)
	if not phrases:
		return [], ""
	book = _translations("ar")
	try:
		from erpnext_ai_assistant.services.rdf.graph import select_option_labels
	except Exception:
		select_option_labels = None
	matched = []
	for option in options:
		extra = select_option_labels(doctype, field, option) if select_option_labels else []
		if any(_option_in_phrase(option, phrase, book, extra) for phrase in phrases):
			matched.append(option)
	if not matched:
		return [], ""
	labels = [_tr(option, lang, _translations(lang)) or option for option in matched]
	if lang == "ar":
		return matched, "بدون احتساب " + " و ".join(labels)
	return matched, "not counting " + " and ".join(labels)


def _exclusion_phrases(text: str | None) -> list[str]:
	norm = normalize_arabic(text)
	if not norm:
		return []
	phrases = []
	for match in re.finditer(rf"{_EXCLUDE}\s+(.+)", norm):
		phrases.append(" ".join(match.group(1).split()[:8]))
	return phrases


def _day_concepts(phrases: list[str]) -> list[str]:
	"""The thing after 'أيام' or 'days': إجازات، leave. Not the whole tail of the sentence."""
	found = []
	for phrase in phrases:
		for match in re.finditer(r"(?:ايام|يوم|days(?:\s+of)?)\s+([^\s،,.]+)", phrase):
			token = strip_al(match.group(1))
			if len(token) >= 4 and token not in found:
				found.append(token)
		for match in re.finditer(r"\b([a-z]{4,})\s+days\b", phrase):
			token = match.group(1)
			if token not in found and token not in ("these", "those", "other"):
				found.append(token)
	return found


def _covered_day_filters(doctype: str, plan: dict, text: str | None, filters: list, lang: str):
	"""Drop register rows whose date sits in an approved leave (or similar) for that party.

	Employee.user_id is the user, and the role lives on that user. A leave day is
	the On Leave status, handled above, and also a date inside a submitted
	document such as Leave Application. Allocation and ledger rows are balances,
	not days off, so they are not used here.
	"""
	concepts = _day_concepts(_exclusion_phrases(text))
	date_field = plan.get("date")
	party_field = plan.get("group")
	if not concepts or not date_field or not party_field:
		return [], "", ""
	party_df = frappe.get_meta(doctype).get_field(party_field)
	if not party_df or party_df.fieldtype != "Link" or not party_df.options:
		return [], "", ""
	start, end = _filter_bounds(doctype, date_field, filters)
	if not start or not end:
		return [], "", ""
	spans = [row for row in _span_doctypes(party_df.options) if _span_matches(row, concepts)]
	if not spans:
		return [], "", ""
	party_names = _filter_in(doctype, party_field, filters)
	drop: list[str] = []
	used = ""
	for span in spans:
		readable, reason, detail = _span_access(span["doctype"], [span["link"], "from_date", "to_date", "status"])
		if not readable:
			label = strip_al(_tr(span["doctype"], lang)) or span["doctype"]
			if lang == "ar":
				if reason == "field":
					text = f"ما أقدر أتحقق من أيام {label} لأن الحقول {detail} فوق مستوى صلاحيتك."
				elif reason == "missing":
					text = f"ما أقدر أتحقق من أيام {label} لأن {span['doctype']} غير مثبت."
				else:
					text = f"ما أقدر أتحقق من أيام {label} لأنك لا تستطيع قراءة {span['doctype']}."
			elif reason == "field":
				text = f"The {label} filter cannot be verified because {detail} on {span['doctype']} is above your permission level."
			elif reason == "missing":
				text = f"The {label} filter cannot be verified because {span['doctype']} is not installed."
			else:
				text = f"The {label} filter cannot be verified because you cannot read {span['doctype']}."
			return [], "", text
		span_filters: dict = {"docstatus": 1, "from_date": ["<=", str(end)], "to_date": [">=", str(start)]}
		if party_names is not None:
			if not party_names:
				continue
			span_filters[span["link"]] = ["in", party_names]
		status = frappe.get_meta(span["doctype"]).get_field("status")
		options = [line.strip() for line in ((status.options if status else "") or "").split("\n") if line.strip()]
		if "Approved" in options:
			span_filters["status"] = "Approved"
		ranges = frappe.get_list(
			span["doctype"],
			filters=span_filters,
			fields=[span["link"], "from_date", "to_date"],
			limit_page_length=0,
		)
		if not ranges:
			continue
		by_party: dict[str, list] = {}
		for rng in ranges:
			by_party.setdefault(rng.get(span["link"]), []).append((rng.get("from_date"), rng.get("to_date")))
		rows = frappe.get_list(
			doctype,
			filters=filters,
			fields=["name", party_field, date_field],
			limit_page_length=0,
		)
		for row in rows:
			day = frappe.utils.getdate(row.get(date_field)) if row.get(date_field) else None
			for left, right in by_party.get(row.get(party_field)) or []:
				if left and right and day and frappe.utils.getdate(left) <= day <= frappe.utils.getdate(right):
					drop.append(row.get("name"))
					break
		if not used:
			used = span["doctype"]
	drop = list(dict.fromkeys(name for name in drop if name))
	if not drop:
		return [], "", ""
	label = strip_al(_tr(used, lang)) or used
	if lang == "ar":
		return [[doctype, "name", "not in", drop]], f"باستثناء أيام {label}", ""
	return [[doctype, "name", "not in", drop]], f"excluding days covered by {label}", ""


def _span_access(doctype: str, fields: list[str]) -> tuple[bool, str, str]:
	"""True only when this user may read the source DocType and every date field used to exclude rows."""
	if not frappe.db.exists("DocType", doctype):
		return False, "missing", doctype
	if not frappe.has_permission(doctype, "read"):
		return False, "read", doctype
	meta = frappe.get_meta(doctype)
	permitted = set(meta.get_permitted_fieldnames(parenttype=doctype))
	hidden = [
		field
		for field in fields
		if field != "name" and meta.get_field(field) and field not in permitted
	]
	if hidden:
		return False, "field", ", ".join(hidden)
	return True, "", ""


def _filter_bounds(doctype: str, field: str, filters: list):
	for item in filters:
		if len(item) >= 4 and item[0] == doctype and item[1] == field and item[2] == "between":
			window = item[3] or []
			if len(window) == 2:
				return window[0], window[1]
	return None, None


def _filter_in(doctype: str, field: str, filters: list):
	for item in filters:
		if len(item) >= 4 and item[0] == doctype and item[1] == field and item[2] == "in":
			return list(item[3] or [])
	return None


def _span_doctypes(party: str) -> list[dict]:
	"""Submitted from/to documents linked to this party. Not allocations or ledgers."""
	key = f"erp_ai_span_v1:{party}"
	cached = frappe.cache().get_value(key)
	if isinstance(cached, list):
		return cached
	rows = frappe.db.sql(
		"""
		select a.parent as doctype, c.fieldname as link_field
		from `tabDocField` a
		join `tabDocField` b on b.parent = a.parent and b.fieldname = 'to_date' and b.fieldtype = 'Date'
		join `tabDocField` c on c.parent = a.parent and c.fieldtype = 'Link' and c.options = %s
		join `tabDocType` d on d.name = a.parent and ifnull(d.istable, 0) = 0 and ifnull(d.issingle, 0) = 0
		where a.fieldname = 'from_date' and a.fieldtype = 'Date'
		""",
		(party,),
		as_dict=True,
	)
	book = _translations("ar")
	out = []
	for row in rows:
		name = row.doctype
		if any(word in (name or "").lower() for word in ("allocation", "ledger", "withholding")):
			continue
		meta = frappe.get_meta(name)
		if not int(meta.get("is_submittable") or 0):
			continue
		labels = [label for label in (name, book.get(name) or "") if label]
		out.append({"doctype": name, "link": row.link_field, "labels": labels})
	frappe.cache().set_value(key, out, expires_in_sec=3600)
	return out


def _span_matches(span: dict, concepts: list[str]) -> bool:
	phrase = " ".join(span.get("labels") or [])
	return any(_option_in_phrase(concept, phrase, {}) for concept in concepts)


def _option_in_phrase(option: str, phrase: str, book: dict, extra_labels: list | None = None) -> bool:
	phrase_n = normalize_arabic(phrase)
	labels = [option, book.get(option) or "", book.get(option.upper()) or "", book.get(option.lower()) or ""]
	labels.extend(extra_labels or [])
	tokens = [strip_al(token) for token in phrase_n.split()]
	tokens = [token for token in tokens if len(token) >= 4]
	for label in labels:
		norm = normalize_arabic(label)
		if not norm:
			continue
		bare = strip_al(norm)
		if len(bare) >= 4 and bare in phrase_n:
			return True
		for word in norm.split():
			word = strip_al(word)
			if len(word) < 4:
				continue
			if word in phrase_n:
				return True
			for token in tokens:
				if word.startswith(token[:3]) and token.startswith(word[:3]) and len(word) >= 4 and len(token) >= 4:
					return True
	return False


def _related_filters(doctype: str, plan: dict, text: str | None, lang: str):
	"""Turn "has a user and not the CEO role" into Frappe filters before the query.

	The party is resolved with is/set and not in, then the register is filtered
	with employee in (...). Aggregation therefore sees every matching row, not
	one page filtered afterwards.
	"""
	constraints = _related_constraints(text)
	if not constraints:
		return [], "", "", False
	for item in constraints:
		if item["kind"] == "role":
			item["role"] = _role_named(item["token"])
			item["target"] = "User"
			if not item["role"]:
				if lang == "ar":
					return [], "", f"ما لقيت صلاحية باسم {item['token']}.", False
				return [], "", f"No role is named {item['token']}.", False
		else:
			item["target"] = _doctype_named(item["token"])
			if not item["target"]:
				if lang == "ar":
					return [], "", f"ما لقيت مستند يطابق «{item['token']}» عشان أطبق الشرط.", False
				return [], "", f"No DocType matches “{item['token']}” for that filter.", False
	anchor, row_field = _constraint_anchor(doctype, plan, constraints)
	if not anchor:
		targets = "، ".join(dict.fromkeys(item["target"] for item in constraints))
		if lang == "ar":
			return [], "", f"ما في ربط بين {doctype} و {targets} يخليني أطبق هذا الشرط.", False
		return [], "", f"There is no link from {doctype} to {targets} for that filter.", False
	clauses = []
	try:
		for item in constraints:
			df = _pick_link(frappe.get_meta(anchor), item["target"])
			if not df:
				if lang == "ar":
					return [], "", f"ما في حقل على {anchor} يربط بـ {item['target']}.", False
				return [], "", f"{anchor} has no link to {item['target']}.", False
			if item["kind"] == "link":
				clauses.append([anchor, df.fieldname, "is", "not set" if item["negate"] else "set"])
				continue
			holders = frappe.get_list(
				"Has Role",
				filters={"parenttype": "User", "role": item["role"]},
				pluck="parent",
				limit_page_length=0,
			)
			if item["negate"]:
				if holders:
					clauses.append([anchor, df.fieldname, "not in", holders])
			elif holders:
				clauses.append([anchor, df.fieldname, "in", holders])
			else:
				return [], _constraint_note(constraints, lang), "", True
		if row_field == "name":
			return clauses, _constraint_note(constraints, lang), "", False
		names = frappe.get_list(anchor, filters=clauses, pluck="name", limit_page_length=0)
	except frappe.PermissionError:
		if lang == "ar":
			return [], "", f"لا صلاحية لقراءة {anchor} لتطبيق الشرط.", False
		return [], "", f"You cannot read {anchor} to apply that filter.", False
	if not names:
		return [], _constraint_note(constraints, lang), "", True
	return [[doctype, row_field, "in", names]], _constraint_note(constraints, lang), "", False


def _related_constraints(text: str | None) -> list[dict]:
	norm = normalize_arabic(text)
	if not norm:
		return []
	found = []
	spans: list[tuple[int, int]] = []

	def covered(start: int) -> bool:
		return any(left <= start < right for left, right in spans)

	article = r"(?:(?:a|an|the)\s+)?"
	# "do not have the CEO role" puts the role name before the word role.
	for match in re.finditer(rf"{_NEG_HAVE}\s+{article}([^\s،,.]+)\s+{_ROLE_WORD}\b", norm):
		found.append({"kind": "role", "negate": True, "token": match.group(1)})
		spans.append(match.span())
	for match in re.finditer(rf"{_HAVE}\s+{article}([^\s،,.]+)\s+{_ROLE_WORD}\b", norm):
		if covered(match.start()):
			continue
		found.append({"kind": "role", "negate": False, "token": match.group(1)})
		spans.append(match.span())
	for match in re.finditer(rf"{_NEG_HAVE}\s+{article}{_ROLE_WORD}\s+([^\s،,.]+)", norm):
		found.append({"kind": "role", "negate": True, "token": match.group(1)})
		spans.append(match.span())
	for match in re.finditer(rf"{_HAVE}\s+{article}{_ROLE_WORD}\s+([^\s،,.]+)", norm):
		if covered(match.start()):
			continue
		found.append({"kind": "role", "negate": False, "token": match.group(1)})
		spans.append(match.span())
	for match in re.finditer(rf"{_NEG_HAVE}\s+{article}([^\s،,.]+)", norm):
		if covered(match.start()):
			continue
		token = match.group(1)
		if token in _NOT_A_TARGET:
			continue
		found.append({"kind": "link", "negate": True, "token": token})
		spans.append(match.span())
	for match in re.finditer(rf"{_HAVE}\s+{article}([^\s،,.]+)", norm):
		if covered(match.start()):
			continue
		before = norm[max(0, match.start() - 5) : match.start()]
		if before.endswith("ليس ") or before.rstrip().endswith("ليس"):
			continue
		token = match.group(1)
		if token in _NOT_A_TARGET:
			continue
		found.append({"kind": "link", "negate": False, "token": token})
	return found


def _constraint_anchor(doctype: str, plan: dict, constraints: list[dict]):
	targets = [item["target"] for item in constraints if item.get("target")]

	def can(meta) -> bool:
		return all(_pick_link(meta, target) for target in targets)

	if can(frappe.get_meta(doctype)):
		return doctype, "name"
	field = plan.get("group")
	linked = frappe.get_meta(doctype).get_field(field) if field else None
	if linked and linked.fieldtype == "Link" and linked.options and can(frappe.get_meta(linked.options)):
		return linked.options, field
	return None, None


def _pick_link(meta, target: str):
	links = [df for df in meta.fields if df.fieldtype == "Link" and df.options == target and df.fieldname]
	if not links:
		return None
	preferred = [df for df in links if df.fieldname in (f"{target.lower()}_id", target.lower(), "user_id" if target == "User" else "")]
	if preferred:
		return preferred[0]
	plain = [df for df in links if "approver" not in (df.fieldname or "")]
	return (plain or links)[0]


def _doctype_named(token: str) -> str | None:
	"""DocType the word names, including ones the chat catalog refuses to list."""
	raw = (token or "").strip()
	wanted = strip_al(raw)
	if not wanted:
		return None
	real = frappe.db.get_value("DocType", raw, ["name", "istable"], as_dict=True)
	if real and not real.istable:
		return real.name
	if wanted.isascii():
		found = [
			name
			for name in frappe.get_all("DocType", filters={"istable": 0, "name": ["like", wanted]}, pluck="name", limit_page_length=8)
			if str(name).lower() == wanted.lower()
		]
		if len(found) == 1:
			return found[0]
	matches = []
	for source, translated in _translations("ar").items():
		if strip_al(translated) != wanted and strip_al(source) != wanted:
			continue
		if not source or " " in source or len(source) > 80:
			continue
		real = frappe.db.get_value("DocType", source, ["name", "istable"], as_dict=True)
		if not real or real.istable or real.name in matches:
			continue
		matches.append(real.name)
	if len(matches) == 1:
		return matches[0]
	titled = [name for name in matches if strip_al(_tr(name, "ar")) == wanted or name.lower() == wanted.lower()]
	if len(titled) == 1:
		return titled[0]
	return None


def _role_named(token: str) -> str | None:
	wanted = (token or "").strip().lower()
	if not wanted:
		return None
	try:
		names = frappe.get_all("Role", filters={"disabled": 0}, pluck="name", limit_page_length=300)
	except frappe.PermissionError:
		return None
	exact = [name for name in names if str(name).lower() == wanted]
	return exact[0] if len(exact) == 1 else None


def _constraint_note(constraints: list[dict], lang: str) -> str:
	parts = []
	ordered = [item for item in constraints if item["kind"] == "link"] + [item for item in constraints if item["kind"] == "role"]
	for item in ordered:
		if item["kind"] == "link":
			label = strip_al(_tr(item["target"], lang)) or item["target"]
			if lang == "ar":
				parts.append(f"ليس لديهم {label}" if item["negate"] else f"لديهم {label}")
			else:
				parts.append(f"without a {label}" if item["negate"] else f"with a {label}")
		else:
			role = item["role"]
			if lang == "ar":
				parts.append(f"بدون صلاحية {role}" if item["negate"] else f"لديهم صلاحية {role}")
			else:
				parts.append(f"without the {role} role" if item["negate"] else f"with the {role} role")
	joiner = "، " if lang == "ar" else ", "
	return joiner.join(parts)


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
		from frappe.translate import get_all_translations

		return get_all_translations(lang) or {}
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
	if not date_field:
		return ""
	dates = [row.get(date_field) for row in rows if row.get(date_field)]
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
