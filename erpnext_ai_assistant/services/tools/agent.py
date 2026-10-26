"""The model chooses a tool. The server checks permission and schema, then runs it.

Writes never insert business documents here. propose_write only stores a pending action.
"""

from __future__ import annotations

import json

import frappe
from erpnext_ai_assistant.services.llm import provider as llm
from erpnext_ai_assistant.services.schema import describe_doctype, missing_message, prepare_payload
from erpnext_ai_assistant.services.tools import registry as tools

MAX_ROUNDS = 4

LABELS = {
	"describe_doctype": ("مخطط نوع المستند", "Read DocType"),
	"query_records": ("استعلام السجلات", "Query records"),
	"list_installed_apps": ("التطبيقات المثبتة", "Installed apps"),
	"lookup_field": ("مطابقة الحقل", "Match field"),
	"search_knowledge": ("استرجاع المعرفة", "Search knowledge"),
	"propose_write": ("تجهيز طلب", "Prepare request"),
}

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
			"description": "List records the current user can read. Filters are a JSON object of field to value.",
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
			"name": "lookup_field",
			"description": "Map a label, including Arabic, to a real fieldname before filtering.",
			"parameters": {
				"type": "object",
				"properties": {
					"query": {"type": "string"},
					"doctype": {"type": "string"},
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
		message_en = missing_message(doctype, prepared, "en") if prepared["missing"] else ""
		message_ar = missing_message(doctype, prepared, "ar") if prepared["missing"] else ""
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
		if name in ("describe_doctype", "query_records", "propose_write"):
			from erpnext_ai_assistant.services.targeting import canonical_doctype

			args = dict(args or {})
			args["doctype"] = canonical_doctype(args.get("doctype") or "", user_text)
		if name == "describe_doctype":
			return _compact_schema(args.get("doctype") or "")
		if name == "query_records":
			filters = args.get("filters") or {}
			if isinstance(filters, str):
				try:
					filters = json.loads(filters)
				except Exception:
					filters = {}
			rows = tools.tool_erp_query(
				args.get("doctype") or "",
				filters=filters if isinstance(filters, dict) else {},
				fields=args.get("fields") or ["name"],
				limit=min(int(args.get("limit") or 20), 50),
			)
			return {"doctype": args.get("doctype"), "count": len(rows), "rows": rows[:20]}
		if name == "list_installed_apps":
			return {"apps": tools.tool_list_installed_apps(args.get("query"))}
		if name == "lookup_field":
			return {"hits": tools.tool_rdf_lookup(args.get("query") or "", doctype=args.get("doctype"))[:12]}
		if name == "search_knowledge":
			from erpnext_ai_assistant.services.rag import service as rag

			hits = rag.retrieve(args.get("query") or "", limit=4)
			return {"passages": [{"content": (hit.get("content") or "")[:500]} for hit in hits]}
		if name == "propose_write":
			return _propose(args, chat_id, lang)
		return {"error": f"Unknown tool {name}"}
	except Exception as exc:
		return {"error": str(exc)}


def _detail(name: str, result: dict, lang: str) -> str:
	if result.get("error"):
		return str(result["error"])[:180]
	if name == "describe_doctype":
		labels = ", ".join(field["label"] or field["fieldname"] for field in result.get("required") or [])
		return labels[:180] or result.get("doctype") or ""
	if name == "query_records":
		return f"{result.get('count', 0)} rows"
	if name == "list_installed_apps":
		return ", ".join(row.get("app") or "" for row in (result.get("apps") or [])[:8])
	if name == "propose_write":
		if result.get("target_doctype"):
			return f"{result.get('action_type') or 'create'} {result.get('target_doctype')}"
		return (result.get("message_en") or result.get("summary") or "")[:180]
	if name == "search_knowledge":
		return f"{len(result.get('passages') or [])} passages"
	if lang == "ar" and name == "lookup_field":
		return f"{len(result.get('hits') or [])} حقول"
	return json.dumps(result, ensure_ascii=False, default=str)[:180]


def _targeted_turn(user: str, chat_id: str | None, lang: str, step) -> dict | None:
	"""Create or list the DocType the Arabic (or everyday) wording actually names."""
	from erpnext_ai_assistant.services.targeting import format_query, interpret, list_fields

	planned = interpret(user)
	if not planned:
		return None
	doctype = planned["doctype"]
	if planned["action"] == "create":
		step("target", "تحديد نوع المستند", "Choose DocType", "targeting", "done", detail=f"create {doctype}", detail_ar=f"إنشاء {doctype}")
		step("tool-1", "تجهيز طلب", "Prepare request", "propose_write", "running")
		result = dispatch(
			"propose_write",
			{"doctype": doctype, "action": "create", "values": planned.get("values") or {}},
			chat_id,
			lang,
			user_text=user,
		)
		detail = _detail("propose_write", result, lang)
		step("tool-1", "تجهيز طلب", "Prepare request", "propose_write", "done", detail=detail, detail_ar=detail)
		return {"answer": "", "pending": result}
	step("target", "تحديد نوع المستند", "Choose DocType", "targeting", "done", detail=f"query {doctype}", detail_ar=f"استعلام {doctype}")
	step("tool-1", "استعلام السجلات", "Query records", "query_records", "running")
	result = dispatch(
		"query_records",
		{"doctype": doctype, "fields": list_fields(doctype), "limit": 10},
		chat_id,
		lang,
		user_text=user,
	)
	detail = _detail("query_records", result, lang)
	step("tool-1", "استعلام السجلات", "Query records", "query_records", "done", detail=detail, detail_ar=detail)
	if result.get("error"):
		return {"answer": str(result["error"]), "pending": None}
	return {"answer": format_query(doctype, result.get("rows") or [], lang), "pending": None}


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

	rules = (
		"You direct the tools. Call a tool before you state live data or prepare a write. "
		"Use describe_doctype for the DocType the user named, not a similar one. "
		"propose_write does not save. If it returns missing fields, ask for those labels and stop. "
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
	for _round in range(MAX_ROUNDS):
		message = llm.chat_message(messages, tools=TOOL_SPECS)
		tool_calls = message.get("tool_calls") or []
		if not tool_calls:
			return {"answer": message.get("content") or "", "pending": pending}
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
			return {"answer": "", "pending": pending}
	final = llm.chat_message(messages, tools=None)
	return {"answer": final.get("content") or "", "pending": pending}
