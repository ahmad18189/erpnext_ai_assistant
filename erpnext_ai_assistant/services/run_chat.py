"""Canonical run_chat orchestrator for The ERPNext-AI-Assistant."""

from __future__ import annotations

import json
import re
import time

import frappe
from erpnext_ai_assistant.services import detectors
from erpnext_ai_assistant.services.llm import provider as llm
from erpnext_ai_assistant.services.moderation import abuse as abuse_mod
from erpnext_ai_assistant.services.moderation import work_gate
from erpnext_ai_assistant.services.rag import service as rag
from erpnext_ai_assistant.services.tools import registry as tools


def run_chat(message: str, route: str | None = None, chat_id: str | None = None) -> dict:
	t0 = time.time()
	user = frappe.session.user
	if user == "Guest" or not user:
		frappe.throw("Login required", frappe.PermissionError)

	settings = frappe.get_single("ERP AI Settings")
	lang = "ar" if re.search(r"[\u0600-\u06FF]", message or "") else "en"

	def _abuse_payload(abuse: dict | None = None) -> dict:
		abuse = abuse or {}
		return {
			"contains_abuse": bool(abuse.get("contains_abuse") or abuse.get("hit")),
			"abuse": {
				"hit": bool(abuse.get("hit")),
				"category": abuse.get("category"),
				"score": abuse.get("score") or 0,
				"matched": abuse.get("matched") or [],
				"event_name": abuse.get("event_name"),
				"blocked_now": bool(abuse.get("blocked_now")),
			},
		}

	if abuse_mod.is_user_blocked(user):
		text = abuse_mod.blocked_message(lang)
		chat = _ensure_chat(chat_id, route, lang, message)
		_save_msg(chat.name, "user", message, "blocked")
		asst = _save_msg(chat.name, "assistant", text, "blocked")
		return {
			"chat_id": chat.name,
			"message": text,
			"status": "blocked",
			"message_id": asst.name,
			**_abuse_payload({"hit": True, "contains_abuse": True, "category": "blocked", "score": 0}),
		}

	chat = _ensure_chat(chat_id, route, lang, message)
	_save_msg(chat.name, "user", message, "complete")
	steps: list[dict] = []

	def step(sid, label_ar, label_en, tool, status, **extra):
		s = {"id": sid, "label_ar": label_ar, "label_en": label_en, "tool": tool, "status": status, **extra}
		steps.append(s)
		tools.publish_step(chat.name, s)
		return s

	step("abuse", "فحص المحتوى", "Abuse scan", "abuse_scan", "running")
	abuse = abuse_mod.scan_abuse(message, chat=chat.name)
	step(
		"abuse",
		"فحص المحتوى",
		"Abuse scan",
		"abuse_scan",
		"done",
		contains_abuse=bool(abuse.get("contains_abuse")),
		matched=abuse.get("matched") or [],
	)
	if abuse.get("blocked_now"):
		text = abuse_mod.blocked_message(lang)
		asst = _save_msg(chat.name, "assistant", text, "blocked", steps)
		return {
			"chat_id": chat.name,
			"message": text,
			"status": "blocked",
			"message_id": asst.name,
			"steps": steps,
			**_abuse_payload(abuse),
		}
	if abuse.get("hit"):
		warn = (
			"تم تسجيل هذه الرسالة المسيئة. تكرار الإساءة يؤدي إلى الحظر."
			if lang == "ar"
			else "This disrespectful message was registered. Repeated abuse will block access."
		)
		asst = _save_msg(chat.name, "assistant", warn, "refused_abuse", steps)
		return {
			"chat_id": chat.name,
			"message": warn,
			"status": "refused_abuse",
			"message_id": asst.name,
			"steps": steps,
			"abuse_event": abuse.get("event_name"),
			**_abuse_payload(abuse),
		}

	recent_user = [
		r.content
		for r in frappe.get_all(
			"ERP AI Message",
			filters={"chat": chat.name, "role": "user"},
			fields=["content"],
			order_by="creation desc",
			limit=6,
		)
		if r.content and r.content != message
	]
	step("work", "بوابة نطاق العمل", "Work-scope gate", "work_gate", "running")
	work_blob = " ".join([message, *recent_user])
	if settings.work_only and not (
		work_gate.is_work_related(message, route) or work_gate.is_work_related(work_blob, route or "/crm")
	):
		ar, en = work_gate.refusal_texts(settings)
		text = ar if lang == "ar" else en
		step("work", "بوابة نطاق العمل", "Work-scope gate", "work_gate", "done")
		asst = _save_msg(chat.name, "assistant", text, "refused_work", steps)
		return {
			"chat_id": chat.name,
			"message": text,
			"status": "refused_work",
			"message_id": asst.name,
			"steps": steps,
			**_abuse_payload(abuse),
		}
	step("work", "بوابة نطاق العمل", "Work-scope gate", "work_gate", "done")

	step("skills", "تحميل المهارات", "Load skills", "read_skill", "running")
	skills = tools.read_skill(route=route)
	step("skills", "تحميل المهارات", "Load skills", "read_skill", "done")
	memory_bits = _load_memory(settings)
	persona = _load_persona(settings)

	step("rag", "استرجاع المعرفة", "RAG retrieve", "retrieve", "running")
	chunks = rag.retrieve(message)
	step("rag", "استرجاع المعرفة", "RAG retrieve", "retrieve", "done")

	from erpnext_ai_assistant.services import conversation as conv

	conv.maybe_set_chat_title(chat.name, message)
	history_msgs = conv.load_openai_history(chat.name, exclude_last_user=True)
	chat_summary = conv.get_chat_summary(chat.name)
	# Prior session facts BEFORE detectors so follow-ups ("by owner instead") can reuse topic
	prior_facts: dict = {}
	if chat_summary and "SESSION_FACTS:" in chat_summary:
		try:
			prev_line = [ln for ln in chat_summary.splitlines() if ln.startswith("SESSION_FACTS:")][0]
			prior_facts = json.loads(prev_line.split(":", 1)[1].strip())
		except Exception:
			prior_facts = {}

	# Detectors: live CRM / invoices / orgs / charts / apps
	step("detect", "تحليل الطلب", "Detect intent", "detectors", "running")
	detected = detectors.gather_context(
		message,
		route,
		lang,
		chat_id=chat.name,
		session_facts=prior_facts,
		recent_user_texts=recent_user,
	)
	steps.extend(detected.get("steps") or [])
	step("detect", "تحليل الطلب", "Detect intent", "detectors", "done")

	tool_parts = list(detected.get("tool_parts") or [])
	charts = list(detected.get("charts") or [])
	pending = detected.get("pending")

	if chunks:
		tool_parts.append("RAG:\n" + "\n---\n".join(c.get("content", "")[:500] for c in chunks))
	if skills:
		# Strip the stock permission one-liner from skills so the model stops parroting it
		skill_blob = "\n\n".join(f"## {s.title}\n{(s.description or '')[:1800]}" for s in skills[:4])
		skill_blob = skill_blob.replace("«ضمن صلاحياتك»", "").replace("within your permissions", "")
		tool_parts.append("Skills:\n" + skill_blob)

	session_facts = conv.extract_session_facts(message, charts=charts, tool_parts=tool_parts)
	for k, v in prior_facts.items():
		session_facts.setdefault(k, v)
	if pending and (pending.get("status") == "pending" or pending.get("error") == "missing_name"):
		session_facts["pending_intent"] = "create_lead"
		if pending.get("pending_action"):
			session_facts["pending_action"] = pending.get("pending_action")
	if session_facts:
		tool_parts.append("Session facts for follow-ups:\n" + json.dumps(session_facts, ensure_ascii=False))

	step("model", "كتابة الإجابة", "Writing answer", "llm", "running")
	system = _base_system(persona, memory_bits, lang)
	# Deterministic replies for write proposals / permission failures — don't trust the model alone
	answer = _answer_for_pending(pending, lang)
	if not answer:
		answer = llm.complete(
			system,
			message,
			tool_context="\n\n".join(tool_parts),
			history=history_msgs,
			chat_summary=chat_summary,
		)
	step("model", "كتابة الإجابة", "Writing answer", "llm", "done", ms=int((time.time() - t0) * 1000))

	answer = _sanitize_answer(answer, lang, has_data=bool(tool_parts or charts or pending))

	# If a chart was produced, nudge the answer to mention it (model often denies chart ability)
	if charts and answer and not re.search(r"chart|مخطط|رسم", answer, re.I):
		note = (
			"\n\nتم إرفاق مخطط تفاعلي أسفل هذه الرسالة."
			if lang == "ar"
			else "\n\nAn interactive chart is attached below this message."
		)
		answer = answer.rstrip() + note

	asst = _save_msg(chat.name, "assistant", answer, "complete", steps)
	for ch in charts:
		from erpnext_ai_assistant.services.naming import as_title

		frappe.get_doc(
			{
				"doctype": "ERP AI Generated Chart",
				"message": asst.name,
				"chart_type": ch.get("type"),
				"title": as_title("ERP AI Generated Chart", ch.get("title") or ch.get("type") or "Chart"),
				"payload_json": json.dumps(ch, ensure_ascii=False),
			}
		).insert(ignore_permissions=True)

	# Update rolling conversation memory after the turn
	new_summary = conv.merge_summary(chat_summary, message, answer, session_facts)
	conv.set_chat_summary(chat.name, new_summary)
	if frappe.db.has_column("ERP AI Chat", "session_facts_json"):
		frappe.db.set_value(
			"ERP AI Chat",
			chat.name,
			"session_facts_json",
			json.dumps(session_facts, ensure_ascii=False),
			update_modified=False,
		)

	_audit("chat_complete", chat.name, {"ms": int((time.time() - t0) * 1000)})

	pending_name = None
	pending_summary = None
	if isinstance(pending, dict) and pending.get("pending_action"):
		pending_name = pending.get("pending_action")
		pending_summary = pending.get("summary") or answer

	return {
		"chat_id": chat.name,
		"message": answer,
		"status": "complete",
		"message_id": asst.name,
		"steps": steps,
		"charts": charts,
		"pending_action": pending_name,
		"pending_summary": pending_summary,
		"persona": persona.get("panel_label_ar") if lang == "ar" else persona.get("panel_label"),
		**_abuse_payload(abuse),
	}


def _answer_for_pending(pending: dict | None, lang: str) -> str | None:
	if not pending:
		return None
	if pending.get("status") == "pending" and pending.get("pending_action"):
		if lang == "ar":
			return (
				"تم تجهيز الطلب. راجع الملخص، فعّل خانة التأكيد، ثم اضغط موافقة. "
				"لن يُحفظ شيء قبل موافقتك.\n\n"
				+ (pending.get("summary") or "")
			)
		return (
			"I prepared this request. Review the summary, check the box, then Approve. "
			"Nothing is saved until you approve.\n\n"
			+ (pending.get("summary") or "")
		)
	if pending.get("message_ar") or pending.get("message_en"):
		return pending.get("message_ar") if lang == "ar" else pending.get("message_en")
	if pending.get("error") == "missing_name":
		if lang == "ar":
			return (
				"نعم، أقدر أجهّز إنشاء العميل المحتمل. أرسل الاسم والبريد بهذا الشكل:\n"
				"إنشاء عميل اسمه أحمد البريد name@example.com\n"
				"سأعرض بطاقة موافقة ولن يُحفظ شيء قبل أن تضغط موافقة."
			)
		return (
			"Yes. I can prepare the new lead for you. Send the name and email like this:\n"
			"create lead name Ahmed email name@example.com\n"
			"I will show an approval card. Nothing is saved until you press Approve."
		)
	if pending.get("status") == "failed":
		err = pending.get("error") or "failed"
		return (
			f"تعذّر اقتراح الإنشاء: {err}"
			if lang == "ar"
			else f"Could not propose the create action: {err}"
		)
	return None


def _sanitize_answer(answer: str | None, lang: str, has_data: bool = False) -> str:
	text = (answer or "").strip()
	stub = {"ضمن صلاحياتك", "ضمن صلاحياتك.", "within your permissions", "within your permissions."}
	if text in stub or (has_data and text in stub):
		return (
			"وجدت بيانات لهذا الطلب، لكن تعذّر صياغة إجابة أوضح. أعد صياغة السؤال أو حدّد العميل/التقرير المطلوب."
			if lang == "ar"
			else "I have data for this request but could not form a clear answer. Please rephrase or name the lead/report you need."
		)
	# Model often refuses creates with this phrase instead of the approval card
	if ("ضمن صلاحياتك" in text or "within your permissions" in text.lower()) and (
		len(text) < 220 or re.search(r"create|إنشاء|lead|عميل", text, re.I)
	):
		if lang == "ar":
			return (
				"أقدر أجهّز إنشاء العميل المحتمل لك. أرسل الاسم والبريد، ثم وافق على البطاقة. "
				"لن يُحفظ السجل قبل موافقتك."
			)
		return (
			"I can prepare the lead for you. Send the name and email, then Approve the card. "
			"Nothing is saved before you approve."
		)
	return answer or ""


def _ensure_chat(chat_id: str | None, route: str | None, lang: str, message: str | None = None):
	if chat_id and frappe.db.exists("ERP AI Chat", chat_id):
		chat = frappe.get_doc("ERP AI Chat", chat_id)
		if chat.user != frappe.session.user and "System Manager" not in frappe.get_roles():
			frappe.throw("Not your chat", frappe.PermissionError)
		return chat
	from erpnext_ai_assistant.services.naming import as_title

	title = as_title("ERP AI Chat", (message or route or "Chat")[:80])
	chat = frappe.get_doc(
		{
			"doctype": "ERP AI Chat",
			"title": title,
			"user": frappe.session.user,
			"route": route,
			"status": "Open",
			"language": lang,
		}
	)
	chat.insert()
	return chat


def _save_msg(chat: str, role: str, content: str, status: str, steps: list | None = None):
	from erpnext_ai_assistant.services.naming import as_title

	doc = frappe.get_doc(
		{
			"doctype": "ERP AI Message",
			"title": as_title("ERP AI Message", f"{role}: {(content or '')[:70]}"),
			"chat": chat,
			"role": role,
			"content": content,
			"status": status,
			"reasoning_json": json.dumps(steps or [], ensure_ascii=False),
		}
	)
	doc.insert()
	return doc


def _load_memory(settings) -> list[str]:
	if not settings.memory_enabled:
		return []
	limit = int(settings.max_memory_items_per_user or 20)
	rows = frappe.get_list(
		"ERP AI Memory",
		filters={"enabled": 1, "user": frappe.session.user, "scope": "user"},
		fields=["key", "value"],
		limit_page_length=limit,
	)
	company = frappe.get_list(
		"ERP AI Memory",
		filters={"enabled": 1, "scope": "company"},
		fields=["key", "value"],
		limit_page_length=10,
	)
	return [f"{r.key}: {r.value}" for r in (rows + company)]


def _load_persona(settings) -> dict:
	name = settings.active_persona
	if not name or not frappe.db.exists("ERP AI Persona", name):
		return {
			"panel_label": "The ERPNext-AI-Assistant",
			"panel_label_ar": "مساعد ERPNext",
			"tone_instructions": "",
		}
	p = frappe.get_doc("ERP AI Persona", name)
	return {
		"panel_label": p.panel_label or p.persona_name,
		"panel_label_ar": p.panel_label_ar or p.persona_name,
		"tone_instructions": p.tone_instructions or "",
	}


def _base_system(persona: dict, memory_bits: list[str], lang: str) -> str:
	parts = [
		"You are The ERPNext-AI-Assistant (مساعد ERPNext) for this Frappe site.",
		"IN SCOPE: live ERP/CRM data the user can read, and apps installed on this site.",
		"OUT OF SCOPE only: homework, poems, jokes, politics, generic ChatGPT roleplay.",
		"CRITICAL ANSWER RULES:",
		"1) Trust LIVE tool results over prior chat guesses. If visible_count > 0, never say there are no leads.",
		"2) You CAN and DO produce charts — the UI renders Chart payloads attached to this turn. Never say charts are outside your capabilities.",
		"3) For 'how many leads' use visible_count / by_status / by_owner from the lead summary tool.",
		"4) For invoices, use live invoice summary (counts + sample), not only generic field documentation.",
		"5) For companies/organizations, use the organizations tool sample. If error no_readable… say ضمن صلاحياتك briefly and suggest which DocType.",
		"6) Be concrete: numbers, names, statuses. Avoid generic troubleshooting unless the user reports a UI bug.",
		"7) Never invent fieldnames or e-invoice clearance IDs.",
		"8) Lead display names: lead_name / first_name / last_name — never a field called اسم.",
		"9) CONVERSATION MEMORY: use prior turns + SESSION_FACTS. Short follow-ups ('how to do it?', 'make it bi', 'yes') "
		"refer to the active topic/chart/pending_intent — do not ask what they mean if memory already has topic/pending.",
		"10) Never reply with only «ضمن صلاحياتك» when tool results contain data.",
		"11) Never invent markdown images or base64 chart pictures — the panel attaches real SVG charts.",
		persona.get("tone_instructions") or "",
	]
	if memory_bits:
		parts.append("User/company memory:\n- " + "\n- ".join(memory_bits[:20]))
	if lang == "ar":
		parts.append("أجب بالعربية الفصحى الواضحة. أسماء DocType/fieldname بالإنجليزية.")
	else:
		parts.append("Reply in English unless the user writes Arabic.")
	return "\n".join(p for p in parts if p)


def _audit(event_type: str, chat: str, payload: dict):
	try:
		from erpnext_ai_assistant.services.naming import as_title

		frappe.get_doc(
			{
				"doctype": "ERP AI Audit Log",
				"title": as_title("ERP AI Audit Log", event_type),
				"event_type": event_type,
				"user": frappe.session.user,
				"chat": chat,
				"payload_json": json.dumps(payload, ensure_ascii=False),
			}
		).insert(ignore_permissions=True)
	except Exception:
		pass
