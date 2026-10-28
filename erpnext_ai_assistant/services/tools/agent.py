"""The model chooses a tool. The server checks permission and schema, then runs it.

Writes never insert business documents here. propose_write only stores a pending action.
"""

from __future__ import annotations

import json
import re

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
			"description": "One permission-checked page plus the filtered total. Ask only for fields the answer needs. Never request password, token, bank, IBAN, national ID, or salary component fields. returned_count is the page, total is every matching row.",
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
			"description": "Permission-scoped total after filters. Use for how many / كم / عدد. Pass the same user, role, date, and status filters as the list. Call once per DocType when the question needs several totals. Never invent SQL.",
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
			"description": (
				"Prepare a create, update, delete, submit, or cancel. Does not save; the user approves a card. "
				"System fields (series, company, currency, price list, exchange rates) are filled automatically: never ask for them. "
				"Item rows go in values.items as [{\"item_name\" or \"item_code\": ..., \"qty\": ...}]; unit and price come from the Item. "
				"For update/delete/submit/cancel pass target_name as the record name. If query results show several records that could fit, "
				"list them and ask which one; never pick one yourself. If required fields are missing, the result lists them and you must ask the user. "
				"Never invent values."
			),
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
	from erpnext_ai_assistant.services.autofill import fill_header

	full = describe_doctype(doctype)
	automatic = {row["fieldname"] for row in fill_header(full["fields"], {})}
	required = [
		{
			"fieldname": field["fieldname"],
			"label": field["label"],
			"fieldtype": field["fieldtype"],
			"options": field.get("options") if field["fieldtype"] == "Select" else None,
		}
		for field in full["fields"]
		if field.get("reqd") and not field.get("read_only") and field["fieldname"] not in automatic
	][:25]
	return {"doctype": doctype, "required": required, "filled_automatically": sorted(automatic), "children": full["children"][:6]}


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
		return tools.propose_write(chat_id, "create", doctype, values, lang=lang)
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
	return tools.propose_write(chat_id, action, doctype, values if action == "update" else {}, target_name=target, lang=lang)


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
		from erpnext_ai_assistant.services.autofill import sentence_values

		values = dict(planned.get("values") or {})
		values.update(extract_field_values(doctype, user) or {})
		values.update(sentence_values(doctype, user))
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
			"signals": [{"kind": "had_data", "action": "count_records", "doctype": doctype, "total": int(total or 0)}],
		}
	step("target", "تحديد نوع المستند", "Choose DocType", "targeting", "done", detail=f"query {doctype}", detail_ar=f"استعلام {doctype}")
	step("tool-1", "تفاصيل السجلات", "Record details", "query_records", "running")
	from erpnext_ai_assistant.services.present import chart_for, chart_marker, image_file, output_formats, table_markdown
	from erpnext_ai_assistant.services.sheets import build_export

	formats = output_formats(user)
	if "list" in formats:
		from erpnext_ai_assistant.services.targeting import records_table

		listed, total = records_table(doctype, user, lang)
		step("tool-1", "تفاصيل السجلات", "Record details", "query_records", "done", detail=str(total), detail_ar=str(total))
		return {
			"answer": listed,
			"pending": None,
			"signals": [{"kind": "had_data", "action": "query_records", "doctype": doctype, "total": total, "shown": sorted(formats)}],
		}
	full = summarize_doctype(doctype, user, lang)
	intro = (full or "").split("\n", 1)[0]
	answer = full if "text" in formats else intro
	charts = []
	if "table" in formats:
		table = table_markdown(doctype, user, lang)
		if table:
			answer = (answer or intro) + "\n\n" + table
	if "chart" in formats or "image" in formats:
		chart = chart_for(doctype, user, lang)
		if chart and "chart" in formats:
			charts.append(chart)
			answer = (answer or intro) + "\n" + chart_marker(chart)
		if chart and "image" in formats:
			picture = image_file(chart, lang)
			if picture:
				files_ready = [picture]
			else:
				files_ready = []
		else:
			files_ready = []
	else:
		files_ready = []
	if "csv" in formats or "xlsx" in formats:
		exported = build_export(doctype, user, lang)
		if exported.get("note"):
			answer = (answer or "") + "\n" + exported["note"]
		files_ready.extend(exported.get("files") or [])
	step("tool-1", "تفاصيل السجلات", "Record details", "query_records", "done", detail=doctype, detail_ar=doctype)
	return {
		"answer": answer,
		"pending": None,
		"files": [item for item in files_ready if item],
		"charts": charts,
		"signals": [{"kind": "had_data", "action": "query_records", "doctype": doctype, "shown": sorted(formats)}],
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
	if err and name in ("count_records", "query_records") and _permission_error(err):
		# No "action" key: a permission answer is complete, not a gap for ERP AI Enhancement.
		signals.append({"kind": "no_access", "doctype": result.get("doctype") or args.get("doctype") or ""})
		return
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
		elif name == "count_records" and result.get("total") is not None:
			signals.append(
				{
					"kind": "had_data",
					"action": name,
					"doctype": result.get("doctype") or args.get("doctype") or "",
					"total": result.get("total"),
					"filters": args.get("filters") or {},
					"live": True,
				}
			)
		elif name == "query_records" and result.get("rows") is not None:
			signals.append(
				{
					"kind": "had_data",
					"action": name,
					"doctype": result.get("doctype") or args.get("doctype") or "",
					"rows": result.get("rows") or [],
					"live": True,
				}
			)
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
	from erpnext_ai_assistant.services.autofill import sentence_values

	extracted = extract_field_values(doctype, user) or {}
	extracted.update(sentence_values(doctype, user))
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


DRAFT_KEYS = ("pending_intent", "collected", "next_field")
_DROP_DRAFT = (
	"cancel", "stop", "never mind", "nevermind", "forget it", "drop it", "no thanks",
	"الغ", "الغي", "الغاء", "توقف", "خلاص", "انس", "لا شكرا", "بلاش",
)
_QUESTION_START = (
	"what", "what's", "how", "which", "who", "when", "where", "why", "show", "list",
	"ما", "ماذا", "كم", "كيف", "هل", "اين", "متى", "لماذا", "اعرض", "وش",
)


def leave_draft(user: str, prior_facts: dict | None) -> str | None:
	"""How this message relates to a create still waiting for fields.

	"cancel": the user dropped it ("cancel", "إلغاء").
	"aside": the user moved on — a question, or another action or DocType.
	None: no draft, or the message reads like the value the draft asked for.
	"""
	intent = str((prior_facts or {}).get("pending_intent") or "")
	if not intent.startswith("create:"):
		return None
	from erpnext_ai_assistant.services.arabic import normalize_arabic
	from erpnext_ai_assistant.services.intent import _action_name
	from erpnext_ai_assistant.services.targeting import _has, match_doctype

	norm = normalize_arabic(user)
	words = norm.split()
	if not words:
		return None
	named = match_doctype(user)
	# "cancel invoice ACC-SINV-1" is a record action, not "drop my draft".
	if len(words) <= 4 and not named and not any(ch.isdigit() for ch in norm):
		if any(_has(norm, phrase) for phrase in _DROP_DRAFT):
			return "cancel"
	if norm.endswith(("?", "؟")) or words[0] in _QUESTION_START:
		return "aside"
	action = _action_name(user)
	if action not in ("unknown", "create"):
		return "aside"
	if named and named != intent.split(":", 1)[1].strip() and action == "create":
		return "aside"
	return None


def draft_note(doctype: str, kind: str, lang: str) -> str:
	from erpnext_ai_assistant.services.targeting import _tr

	label = _tr(doctype, lang) or doctype
	if kind == "cancel":
		if lang == "ar":
			return f"تمام، ألغيت مسودة {label}. لم يُحفظ شيء."
		return f"Okay, I dropped the {label} draft. Nothing was saved."
	if lang == "ar":
		return f"(تركت مسودة {label} جانبًا ولم يُحفظ منها شيء. اطلب إنشاءها من جديد متى شئت.)"
	return f"(I set the {label} draft aside. Nothing was saved. Ask to create it again any time.)"


def _has_live_evidence(signals: list) -> bool:
	"""A successful count or query in this turn. A failed call or a knowledge search is not evidence."""
	return any(row.get("live") and row.get("kind") == "had_data" for row in signals)


def _finish_with_evidence(content: str, user: str, lang: str, pending, signals: list) -> dict:
	from erpnext_ai_assistant.services.targeting import needs_live_check

	text = content or ""
	if needs_live_check(user) and not _has_live_evidence(signals):
		denied = next((row for row in signals if row.get("kind") == "no_access" and row.get("doctype")), None)
		if denied:
			from erpnext_ai_assistant.services.targeting import _tr

			label = _tr(denied["doctype"], lang) or denied["doctype"]
			text = f"لا تملك صلاحية قراءة {label}." if lang == "ar" else f"You cannot read {label}."
		else:
			text = NOT_VERIFIED_AR if lang == "ar" else NOT_VERIFIED_EN
	elif re.search(r"[0-9\u0660-\u0669]", text):
		checked = _checked_line(signals, lang)
		if checked:
			text = text.rstrip() + "\n\n" + checked
	return {"answer": text, "pending": pending, "signals": signals}


def _checked_line(signals: list, lang: str) -> str:
	"""What the tools really counted, so a number in the model's wording can be checked against it."""
	from erpnext_ai_assistant.services.targeting import _tr

	parts = []
	for row in signals:
		if row.get("action") != "count_records" or not row.get("live"):
			continue
		label = _tr(row.get("doctype") or "", lang) or row.get("doctype") or ""
		where = _filters_text(row.get("filters"))
		if lang == "ar":
			parts.append(f"{row.get('total')} من {label}" + (f" ({where})" if where else ""))
		else:
			parts.append(f"{row.get('total')} {label}" + (f" ({where})" if where else ""))
	if not parts:
		return ""
	if lang == "ar":
		return "تم التحقق: " + "؛ ".join(parts)
	return "Checked: " + "; ".join(parts)


def _filters_text(filters) -> str:
	if isinstance(filters, str):
		try:
			filters = json.loads(filters)
		except Exception:
			return ""
	bits = []
	if isinstance(filters, dict):
		for key, value in filters.items():
			if isinstance(value, (list, tuple)) and len(value) == 2:
				bits.append(f"{key} {value[0]} {value[1]}")
			else:
				bits.append(f"{key} = {value}")
	elif isinstance(filters, list):
		for row in filters:
			if isinstance(row, (list, tuple)) and len(row) >= 3:
				bits.append(" ".join(str(part) for part in row[-3:]))
	return ", ".join(bits)[:160]


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
		"Call a tool before you state live data or prepare a write. "
		"If the DocType is unclear, call list_doctypes, then use only a returned name. "
		"A quantity (كم عدد / how many / count) is count_records with filters applied. "
		"A register, table, or details (سجل، جدول، اعطيني، يظهر، تفاصيل) is query_records, then plain language. Use query_records.total, not returned_count. "
		"A question about several DocTypes is several tool calls in this turn, then one answer. "
		"Use list_modules and lookup_field before a filter label. Pass module or app. Bind a fieldname only when exactly one hit comes back. "
		"Exclude a status with not in before the count. Exclude leave days before an attendance total. "
		"If the tool returns a permission error, say so and stop. Do not write SQL. "
		"Leave passwords, tokens, bank accounts, IBAN, national IDs, and salary lines out of the answer. "
		"A register can be shown as text, a table, a chart, CSV, Excel, or an image. "
		"Never say a file is ready unless the answer contains a private-file link. "
		+ manual_rule
		+ "Use describe_doctype for the DocType the user named. "
		"propose_write does not save. If fields are missing, ask for the next_ask label and stop. "
		"On a follow-up, pass every value already given, plus the new one. "
		"مهمة is ToDo. اجتماع is Event only when the user did not ask for a مهمة. "
		"There is no DocType named Meeting. غدا is the next calendar day. "
		"Do not answer a create request with a menu click-path. "
		"After tools return, answer in the language of the latest user message. Do not paste tool JSON."
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
			return _finish_with_evidence(message.get("content") or "", user, lang, pending, signals)
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
	return _finish_with_evidence(final.get("content") or "", user, lang, pending, signals)
