"""The model chooses a tool. The server checks permission and schema, then runs it.

Writes never insert business documents here. propose_write only stores a pending action.
"""

from __future__ import annotations

import json

import frappe
from erpnext_ai_assistant.services.llm import provider as llm
from erpnext_ai_assistant.services.schema import describe_doctype, guided_message, prepare_payload
from erpnext_ai_assistant.services.tools import registry as tools

MAX_ROUNDS = 4

LABELS = {
	"describe_doctype": ("مخطط نوع المستند", "Read DocType"),
	"query_records": ("استعلام السجلات", "Query records"),
	"count_records": ("عدد السجلات", "Count records"),
	"list_doctypes": ("أنواع المستندات", "List DocTypes"),
	"list_installed_apps": ("التطبيقات المثبتة", "Installed apps"),
	"list_modules": ("وحدات التطبيق", "App modules"),
	"lookup_field": ("مطابقة الحقل", "Match field"),
	"search_knowledge": ("استرجاع المعرفة", "Search knowledge"),
	"search_manual": ("دليل ERPNext", "ERPNext manual"),
	"propose_write": ("تجهيز طلب", "Prepare request"),
}

NOT_VERIFIED_AR = "لم أتحقق من السجلات، لذلك لن أذكر رقماً."
NOT_VERIFIED_EN = "I did not check the records, so I will not state a number."

TOOL_SPECS = [
	{
		"type": "function",
		"function": {
			"name": "describe_doctype",
			"description": "Read a DocType schema: required fields, labels, types, and child tables. Call this before any create.",
			"parameters": {
				"type": "object",
				"properties": {"doctype": {"type": "string"}},
				"required": ["doctype"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "query_records",
			"description": "List records the current user can read. Filters are a JSON object of field to value. returned_count is a page, not the total.",
			"parameters": {
				"type": "object",
				"properties": {
					"doctype": {"type": "string"},
					"filters": {"type": "object"},
					"fields": {"type": "array", "items": {"type": "string"}},
					"limit": {"type": "integer"},
				},
				"required": ["doctype"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "count_records",
			"description": "Return the permission-scoped total number of records for a DocType. Use this for quantity questions (how many / كم / عدد).",
			"parameters": {
				"type": "object",
				"properties": {
					"doctype": {"type": "string"},
					"filters": {"type": "object"},
				},
				"required": ["doctype"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "list_doctypes",
			"description": "Search the cached list of non-child DocTypes on this site (name + Arabic labels). Call this when you are unsure which DocType the user meant. Never invent a DocType name.",
			"parameters": {
				"type": "object",
				"properties": {
					"query": {"type": "string", "description": "Arabic or English words from the user message"},
				},
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "list_installed_apps",
			"description": "List apps installed on this site. Use this for questions about an app, not a guess.",
			"parameters": {
				"type": "object",
				"properties": {"query": {"type": "string"}},
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "list_modules",
			"description": "List modules from the site RDF graphs, optionally for one installed app.",
			"parameters": {
				"type": "object",
				"properties": {"app": {"type": "string"}},
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "lookup_field",
			"description": "Map a label, including Arabic, to a real fieldname before filtering. Pass module or app to stay inside that RDF graph.",
			"parameters": {
				"type": "object",
				"properties": {
					"query": {"type": "string"},
					"doctype": {"type": "string"},
					"module": {"type": "string"},
					"app": {"type": "string"},
				},
				"required": ["query"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "search_knowledge",
			"description": "Search role-filtered help text. Not a source of live record counts.",
			"parameters": {
				"type": "object",
				"properties": {"query": {"type": "string"}},
				"required": ["query"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "search_manual",
			"description": "Fetch how-to instructions from the official ERPNext user manual (docs.frappe.io). Use when the user asks how to do something in ERPNext, needs steps, or wants documentation. Not for live record counts.",
			"parameters": {
				"type": "object",
				"properties": {
					"query": {"type": "string", "description": "Topic in English or Arabic, e.g. sales invoice, إنشاء فاتورة مبيعات"},
				},
				"required": ["query"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "propose_write",
			"description": "Prepare a create, update, or delete. Does not save. If required fields are missing, the result lists them and you must ask the user. Never invent values.",
			"parameters": {
				"type": "object",
				"properties": {
					"doctype": {"type": "string"},
					"action": {"type": "string", "enum": ["create", "update", "delete", "submit", "cancel"]},
					"values": {"type": "object"},
					"target_name": {"type": "string"},
				},
				"required": ["doctype", "action"],
			},
		},
	},
]


def _compact_schema(doctype: str) -> dict:
	full = describe_doctype(doctype)
	required = [
		{
			"fieldname": field["fieldname"],
			"label": field["label"],
			"fieldtype": field["fieldtype"],
			"options": field.get("options") if field["fieldtype"] == "Select" else None,
		}
		for field in full["fields"]
		if field.get("reqd") and not field.get("read_only")
	][:25]
	return {"doctype": doctype, "required": required, "children": full["children"][:6]}


def _propose(args: dict, chat_id: str | None, lang: str) -> dict:
	doctype = args.get("doctype") or ""
	action = args.get("action") or "create"
	values = args.get("values") or {}
	if isinstance(values, str):
		try:
			values = json.loads(values)
		except Exception:
			values = {}
	if not isinstance(values, dict):
		values = {}
	target = args.get("target_name") or None
	prepared = prepare_payload(doctype, values, "create" if action == "create" else "update")
	if prepared["errors"] or (action == "create" and prepared["missing"]):
		message_en, step_en = guided_message(doctype, prepared, "en") if prepared["missing"] else ("", {})
		message_ar, step_ar = guided_message(doctype, prepared, "ar") if prepared["missing"] else ("", {})
		step = step_ar if lang == "ar" else step_en
		if prepared["errors"]:
			extra = "\n".join(prepared["errors"])
			message_en = (message_en + "\n" + extra).strip() if message_en else extra
			message_ar = (message_ar + "\n" + extra).strip() if message_ar else extra
		return {
			"status": "need_input",
			"target_doctype": doctype,
			"action_type": action,
			"message_en": message_en,
			"message_ar": message_ar,
			"next_ask": (step or {}).get("next_ask"),
			"next_step": step or {},
		}
	values = prepared["payload"]
	if action == "create":
		if not chat_id:
			return {"error": "no chat", "status": "failed"}
		return tools.propose_write(chat_id, "create", doctype, values)
	if not target:
		return {
			"status": "need_input",
			"target_doctype": doctype,
			"action_type": action,
			"message_en": f"Which {doctype} name should I {action}?",
			"message_ar": f"ما اسم سجل {doctype} المطلوب لـ {action}؟",
		}
	if not chat_id:
		return {"error": "no chat", "status": "failed"}
	return tools.propose_write(chat_id, action, doctype, values if action == "update" else {}, target_name=target)


def dispatch(name: str, args: dict, chat_id: str | None, lang: str, user_text: str | None = None) -> dict:
	try:
		if name in ("describe_doctype", "query_records", "count_records", "propose_write"):
			from erpnext_ai_assistant.services.targeting import canonical_doctype

			args = dict(args or {})
			args["doctype"] = canonical_doctype(args.get("doctype") or "", user_text)
		if name == "describe_doctype":
			return _compact_schema(args.get("doctype") or "")
		if name == "query_records":
			filters = _ready_filters(args.get("doctype") or "", args.get("filters"), lang)
			if isinstance(filters, dict) and filters.get("_error"):
				return {"error": filters["_error"], "candidates": filters.get("_candidates") or []}
			page_length = min(int(args.get("limit") or 20), 50)
			rows = tools.tool_erp_query(
				args.get("doctype") or "",
				filters=filters,
				fields=args.get("fields") or ["name"],
				limit=page_length,
			)
			page = rows[:page_length]
			counted = tools.tool_erp_count(args.get("doctype") or "", filters=filters)
			return {
				"doctype": args.get("doctype"),
				"returned_count": len(page),
				"total": counted.get("total"),
				"limit_start": 0,
				"limit_page_length": page_length,
				"capped": int(counted.get("total") or 0) > len(page),
				"note": "rows are one page (limit_page_length). total is the filtered count of every matching row.",
				"rows": page,
			}
		if name == "count_records":
			filters = _ready_filters(args.get("doctype") or "", args.get("filters"), lang)
			if isinstance(filters, dict) and filters.get("_error"):
				return {"error": filters["_error"], "candidates": filters.get("_candidates") or []}
			return tools.tool_erp_count(args.get("doctype") or "", filters=filters)
		if name == "list_doctypes":
			from erpnext_ai_assistant.services.doctype_catalog import search_catalog

			return {"doctypes": search_catalog(args.get("query"), limit=20)}
		if name == "list_installed_apps":
			return {"apps": tools.tool_list_installed_apps(args.get("query"))}
		if name == "list_modules":
			from erpnext_ai_assistant.services.rdf.graph import list_modules

			return {"modules": list_modules(args.get("app") or None)}
		if name == "lookup_field":
			hits = tools.tool_rdf_lookup(
				args.get("query") or "",
				doctype=args.get("doctype"),
				module=args.get("module"),
				app=args.get("app"),
			)[:12]
			if len(hits) == 1:
				return {"fieldname": hits[0].get("fieldname"), "doctype": hits[0].get("doctype"), "hits": hits}
			return {"candidates": hits, "hits": hits}
		if name == "search_knowledge":
			from erpnext_ai_assistant.services.rag import service as rag

			hits = rag.retrieve(args.get("query") or "", limit=4)
			return {
				"passages": [
					{
						"source": hit.get("document_title") or hit.get("document") or "",
						"source_key": hit.get("source_key") or "",
						"chunk_index": hit.get("chunk_index"),
						"content": (hit.get("content") or "")[:500],
					}
					for hit in hits
				]
			}
		if name == "search_manual":
			if not _erpnext_installed():
				return {"error": "The ERPNext manual is not available on this site.", "passages": []}
			from erpnext_ai_assistant.services.manual_docs import search_manual

			return {"passages": search_manual(args.get("query") or "", limit=3)}
		if name == "propose_write":
			return _propose(args, chat_id, lang)
		return {"error": f"Unknown tool {name}"}
	except Exception as exc:
		return {"error": str(exc)}


def _parse_filters(raw):
	"""A Frappe filter dict or a list of [doctype, field, operator, value]."""
	filters = raw or {}
	if isinstance(filters, str):
		try:
			filters = json.loads(filters)
		except Exception:
			filters = {}
	if isinstance(filters, dict):
		return filters
	if isinstance(filters, list):
		return filters
	return {}


def _ready_filters(doctype: str, raw, lang: str):
	filters = _parse_filters(raw)
	if isinstance(filters, dict):
		return _resolve_filter_keys(doctype, filters, lang)
	return filters


def _resolve_filter_keys(doctype: str, filters: dict, lang: str) -> dict:
	"""Map label-like filter keys to fieldnames the session may read. Iteration 3."""
	if not filters or not doctype:
		return filters
	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return filters
	known = {df.fieldname for df in meta.fields if df.fieldname}
	known.update({"name", "owner", "creation", "modified", "docstatus", "idx"})
	permitted = set(meta.get_permitted_fieldnames(permission_type="read") or [])
	resolved = {}
	for key, value in filters.items():
		if key in known:
			if permitted and key not in permitted and key not in ("name", "owner", "creation", "modified", "docstatus", "idx"):
				msg = (
					f"لا صلاحية لقراءة الحقل {key}."
					if lang == "ar"
					else f"No permission to read field {key}."
				)
				return {"_error": msg}
			resolved[key] = value
			continue
		hits = tools.tool_rdf_lookup(str(key), doctype=doctype)
		readable = [h for h in hits if h.get("fieldname") in permitted or not permitted]
		candidates = [
			{"fieldname": hit.get("fieldname"), "label": hit.get("label"), "doctype": hit.get("doctype")}
			for hit in (readable or hits)[:8]
			if hit.get("fieldname")
		]
		if len(readable) == 1:
			resolved[readable[0]["fieldname"]] = value
			continue
		if len(readable) > 1:
			msg = (
				f"«{key}» يطابق أكثر من حقل. اختر واحداً من القائمة."
				if lang == "ar"
				else f"«{key}» matches more than one field. Choose one from the list."
			)
			return {"_error": msg, "_candidates": candidates}
		if hits and not readable:
			msg = (
				f"الحقل «{key}» فوق مستوى صلاحيتك."
				if lang == "ar"
				else f"Field «{key}» is above your permission level."
			)
			return {"_error": msg, "_candidates": []}
		msg = (
			f"لم أجد حقلاً باسم «{key}». أعطِ تسمية الحقل الصحيحة."
			if lang == "ar"
			else f"No field matched «{key}». Provide the correct field label."
		)
		return {"_error": msg, "_candidates": []}
	return resolved


def _erpnext_installed() -> bool:
	try:
		return "erpnext" in set(frappe.get_installed_apps())
	except Exception:
		return False


def active_tool_specs() -> list[dict]:
	if _erpnext_installed():
		return TOOL_SPECS
	return [spec for spec in TOOL_SPECS if (spec.get("function") or {}).get("name") != "search_manual"]


def _detail(name: str, result: dict, lang: str) -> str:
	if result.get("error"):
		return str(result["error"])[:180]
	if name == "describe_doctype":
		labels = ", ".join(field["label"] or field["fieldname"] for field in result.get("required") or [])
		return labels[:180] or result.get("doctype") or ""
	if name == "query_records":
		shown = result.get("returned_count", result.get("count", 0))
		return f"{shown} rows" + (" (page, not a total)" if result.get("capped") else "")
	if name == "count_records":
		return f"total {result.get('total', 0)}"
	if name == "list_doctypes":
		names = [row.get("name") or "" for row in (result.get("doctypes") or [])[:8]]
		return ", ".join(n for n in names if n) or "none"
	if name == "list_installed_apps":
		return ", ".join(row.get("app") or "" for row in (result.get("apps") or [])[:8])
	if name == "propose_write":
		if result.get("target_doctype"):
			return f"{result.get('action_type') or 'create'} {result.get('target_doctype')}"
		return (result.get("message_en") or result.get("summary") or "")[:180]
	if name == "search_knowledge":
		return f"{len(result.get('passages') or [])} passages"
	if name == "search_manual":
		titles = [p.get("title") or "" for p in (result.get("passages") or [])[:3]]
		return ", ".join(t for t in titles if t) or f"{len(result.get('passages') or [])} pages"
	if lang == "ar" and name == "lookup_field":
		return f"{len(result.get('hits') or [])} حقول"
	return json.dumps(result, ensure_ascii=False, default=str)[:180]


def _targeted_turn(user: str, chat_id: str | None, lang: str, step, planned: dict | None = None) -> dict | None:
	"""Create, count, or list the DocType the Arabic (or everyday) wording actually names."""
	from erpnext_ai_assistant.services.schema import extract_field_values
	from erpnext_ai_assistant.services.targeting import (
		filtered_count,
		format_count,
		interpret,
		summarize_doctype,
	)

	planned = planned or interpret(user)
	if not planned:
		return None
	doctype = planned["doctype"]
	if planned["action"] == "create":
		values = dict(planned.get("values") or {})
		values.update(extract_field_values(doctype, user) or {})
		step("target", "تحديد نوع المستند", "Choose DocType", "targeting", "done", detail=f"create {doctype}", detail_ar=f"إنشاء {doctype}")
		step("tool-1", "تجهيز طلب", "Prepare request", "propose_write", "running")
		result = dispatch(
			"propose_write",
			{"doctype": doctype, "action": "create", "values": values},
			chat_id,
			lang,
			user_text=user,
		)
		detail = _detail("propose_write", result, lang)
		step("tool-1", "تجهيز طلب", "Prepare request", "propose_write", "done", detail=detail, detail_ar=detail)
		return {"answer": "", "pending": result}
	if planned["action"] == "count":
		step("target", "تحديد نوع المستند", "Choose DocType", "targeting", "done", detail=f"count {doctype}", detail_ar=f"عدد {doctype}")
		step("tool-1", "عدد السجلات", "Count records", "count_records", "running")
		total, note, problem = filtered_count(doctype, user, lang)
		step("tool-1", "عدد السجلات", "Count records", "count_records", "done", detail=str(total), detail_ar=str(total))
		if problem:
			return {"answer": problem, "pending": None, "signals": []}
		answer = format_count(doctype, int(total or 0), lang)
		if note:
			answer = answer[:-1] + f" ({note})."
		return {
			"answer": answer,
			"pending": None,
			"signals": [{"kind": "had_data", "action": "count_records", "doctype": doctype}],
		}
	step("target", "تحديد نوع المستند", "Choose DocType", "targeting", "done", detail=f"query {doctype}", detail_ar=f"استعلام {doctype}")
	step("tool-1", "تفاصيل السجلات", "Record details", "query_records", "running")
	answer = summarize_doctype(doctype, user, lang)
	files = []
	from erpnext_ai_assistant.services.sheets import build_export, sheet_kinds, wants_children

	if sheet_kinds(user) or wants_children(user):
		exported = build_export(doctype, user, lang)
		if exported.get("note"):
			answer = answer + "\n" + exported["note"]
		files = exported.get("files") or []
	step("tool-1", "تفاصيل السجلات", "Record details", "query_records", "done", detail=doctype, detail_ar=doctype)
	return {
		"answer": answer,
		"pending": None,
		"files": files,
		"signals": [{"kind": "had_data", "action": "query_records", "doctype": doctype}],
	}


def _permission_error(text: str) -> bool:
	raw = text or ""
	lower = raw.lower()
	phrases = (
		"لا صلاحية",
		"فوق مستوى صلاحيتك",
		"لا تملك صلاحية",
		"no permission",
		"no read permission",
		"no access",
		"not available for assistant writes",
		"within_permissions",
		"no_create_permission",
	)
	return any(phrase in raw or phrase in lower for phrase in phrases)


def _error_signal(name: str, doctype: str, result: dict) -> list:
	if result.get("candidates") or _permission_error(str(result.get("error") or "")):
		return []
	return [{"kind": "tool_error", "action": name, "doctype": doctype, "surfaced": True}]


def _note_signal(signals: list, name: str, args: dict, result: dict) -> None:
	err = str(result.get("error") or "")
	if err.startswith("Unknown tool "):
		signals.append({"kind": "unknown_capability", "action": name, "doctype": "", "app": ""})
		return
	if name == "search_manual" and not err and not (result.get("passages") or []):
		query = str(args.get("query") or "").strip()
		if len(query) >= 2:
			signals.append(
				{
					"kind": "manual_miss",
					"action": "search_manual",
					"topic": query[:40],
					"doctype": "",
					"app": "",
				}
			)
		return
	if not err and name in ("query_records", "count_records", "search_knowledge", "search_manual"):
		if name == "search_manual" or name == "search_knowledge":
			if result.get("passages"):
				signals.append({"kind": "had_data", "action": name, "doctype": args.get("doctype") or ""})
		else:
			signals.append({"kind": "had_data", "action": name, "doctype": args.get("doctype") or ""})
		return
	if name == "propose_write" and result.get("status") == "failed" and not _permission_error(err):
		signals.append(
			{
				"kind": "tool_error",
				"action": "propose_write",
				"doctype": result.get("target_doctype") or args.get("doctype") or "",
				"surfaced": True,
			}
		)


def continue_guided_create(
	user: str,
	prior_facts: dict | None,
	chat_id: str | None,
	lang: str,
	step,
) -> dict | None:
	"""Merge a follow-up value into the create that is already in progress."""
	facts = prior_facts or {}
	intent = str(facts.get("pending_intent") or "")
	if not intent.startswith("create:"):
		return None
	from erpnext_ai_assistant.services.schema import extract_field_values
	from erpnext_ai_assistant.services.targeting import _action, _is_howto, match_doctype

	if _is_howto(user) or _action(user) in ("count", "query"):
		return None
	doctype = intent.split(":", 1)[1].strip()
	named = match_doctype(user)
	# A bare answer to the missing field can contain a DocType word ("اجتماع غدا").
	# Switch DocTypes only when the user also names an action.
	if named and named != doctype and _action(user):
		return None
	if not doctype or not frappe.db.exists("DocType", doctype):
		return None
	collected = facts.get("collected") or {}
	if not isinstance(collected, dict):
		collected = {}
	extracted = extract_field_values(doctype, user) or {}
	merged = dict(collected)
	for key, value in extracted.items():
		if value not in (None, ""):
			merged[key] = value
	nxt = facts.get("next_field")
	if nxt and not extracted:
		bare = (user or "").strip()
		if bare and len(bare) <= 180 and "\n" not in bare and not _action(user):
			merged[str(nxt)] = bare
	if merged == collected:
		return None
	step("tool-1", "تجهيز طلب", "Prepare request", "propose_write", "running")
	result = dispatch(
		"propose_write",
		{"doctype": doctype, "action": "create", "values": merged},
		chat_id,
		lang,
		user_text=None,
	)
	detail = _detail("propose_write", result, lang)
	step("tool-1", "تجهيز طلب", "Prepare request", "propose_write", "done", detail=detail, detail_ar=detail)
	return {"answer": "", "pending": result}


def run_tool_loop(
	system: str,
	user: str,
	history: list[dict],
	chat_summary: str,
	images: list[dict] | None,
	chat_id: str | None,
	lang: str,
	step,
) -> dict:
	"""Return {answer, pending}. Raises if the provider call fails."""
	from erpnext_ai_assistant.services.conversation import build_messages

	manual_rule = ""
	if _erpnext_installed():
		manual_rule = "For how-to / steps / manual questions, call search_manual and cite the returned url. "
	rules = (
		"You direct the tools. Call a tool before you state live data or prepare a write. "
		"If the DocType is unclear, call list_doctypes with words from the user message, "
		"then use only a name from that cached non-child list. Never invent a DocType. "
		"For a pure quantity question (كم عدد / how many / count) call count_records after you know the DocType. "
		"If the user asks for a register, table, list, or details (سجل، جدول، اعطيني، يظهر، تفاصيل), "
		"call query_records and describe the rows in plain language, using field labels. Do not answer those with only a count. "
		"A register that also names a person or company uses that transaction DocType, not the master list. "
		"An employee reaches a user through user_id. A role (صلاحية) is a Has Role row on that user; match the Role name exactly, so CEO is not Deputy CEO. "
		"Apply has-user and has-role or lacks-role before you total the rows. "
		"Leave days (أيام الإجازة / on leave) are the On Leave status and any date inside an approved Leave Application for that employee. Exclude both before you count or group. "
		"query_records returns one page. Its total is the filtered count of every row, from count/group, not the length of the page. "
		"If the user says not to count a status (إجازة / leave, ملغاة / cancelled), filter that status out with not in before you count or group. "
		"Use list_modules and lookup_field for labels. Pass module or app so the match stays in that module graph. "
		+ manual_rule
		+ "Use describe_doctype for the DocType the user named, not a similar one. "
		"lookup_field and filter labels bind a fieldname only when exactly one readable hit comes back. "
		"Otherwise ask using the returned candidates. Never invent a fieldname. "
		"propose_write does not save. If it returns missing fields, ask for the next_ask label and stop. "
		"On a follow-up, pass every value the user already gave, plus the new one. "
		"Do not invent field values, dates, or phone numbers. "
		"مهمة is ToDo. اجتماع is Event only when the user did not ask for a مهمة. "
		"There is no DocType named Meeting. غدا is the next calendar day. "
		"Do not answer a create request with a menu click-path. "
		"After tools return, answer in the language of the latest user message."
	)
	messages = build_messages(
		system=system + "\n" + rules,
		tool_context="",
		history=history,
		user_message=user,
		chat_summary=chat_summary or "",
		images=images or [],
	)
	pending = None
	call_no = 0
	signals: list = []
	llm.begin_turn_deadline()
	for _round in range(MAX_ROUNDS):
		try:
			message = llm.chat_message(messages, tools=active_tool_specs(), chat_id=chat_id, lang=lang)
		except (llm.CallLimitExceeded, llm.TurnDeadlineExceeded) as exc:
			return {"answer": str(exc), "pending": pending, "signals": signals}
		tool_calls = message.get("tool_calls") or []
		if not tool_calls:
			from erpnext_ai_assistant.services.targeting import needs_live_check

			if needs_live_check(user):
				return {
					"answer": NOT_VERIFIED_AR if lang == "ar" else NOT_VERIFIED_EN,
					"pending": pending,
					"signals": signals,
				}
			return {"answer": message.get("content") or "", "pending": pending, "signals": signals}
		messages.append(
			{
				"role": "assistant",
				"content": message.get("content") or "",
				"tool_calls": tool_calls,
			}
		)
		for call in tool_calls:
			fn = call.get("function") or {}
			name = fn.get("name") or ""
			try:
				args = json.loads(fn.get("arguments") or "{}")
			except Exception:
				args = {}
			if not isinstance(args, dict):
				args = {}
			call_no += 1
			label_ar, label_en = LABELS.get(name, (name, name))
			step(f"tool-{call_no}", label_ar, label_en, name, "running")
			result = dispatch(name, args, chat_id, lang, user_text=user)
			_note_signal(signals, name, args, result)
			if name == "propose_write" and result.get("status") in ("pending", "need_input", "failed"):
				pending = result
			detail = _detail(name, result, lang)
			step(f"tool-{call_no}", label_ar, label_en, name, "done", detail=detail, detail_ar=detail)
			messages.append(
				{
					"role": "tool",
					"tool_call_id": call.get("id") or name,
					"content": json.dumps(result, ensure_ascii=False, default=str)[:8000],
				}
			)
			if pending and pending.get("status") in ("pending", "need_input", "failed"):
				break
		if pending and pending.get("status") in ("pending", "need_input", "failed"):
			return {"answer": "", "pending": pending, "signals": signals}
	try:
		final = llm.chat_message(messages, tools=None, chat_id=chat_id, lang=lang)
	except (llm.CallLimitExceeded, llm.TurnDeadlineExceeded) as exc:
		return {"answer": str(exc), "pending": pending, "signals": signals}
	return {"answer": final.get("content") or "", "pending": pending, "signals": signals}
