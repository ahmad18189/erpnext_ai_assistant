"""Record one unfinished turn for a later release. The model does not implement the fix."""

from __future__ import annotations

import re

import frappe
from erpnext_ai_assistant.services.tools.agent import NOT_VERIFIED_AR, NOT_VERIFIED_EN

_PERMISSION = (
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

_SUGGESTIONS = {
	"not_verified": (
		"أضف تسمية في الفهرس أو اختصار عدد/قائمة حتى تستخدم الإصدارة التالية count_records أو query_records.\n"
		"Add a catalog label or count/list shortcut so the next release uses count_records or query_records."
	),
	"unknown_capability": (
		"النموذج استدعى أداة لا يوجد لها معالج. أضف الأداة أو أزل اسمها من التعليمات.\n"
		"The model called a tool dispatch does not implement. Add the tool or remove its name from the prompt."
	),
	"manual_miss": (
		"أضف مقطعاً معرفياً لهذا الموضوع يدوياً. لا تنشئه من المحادثة.\n"
		"Add a skill chunk for this manual topic by hand. Do not create it from the chat."
	),
	"tool_error": (
		"الأداة فشلت دون سبب صلاحية أو حقل ناقص. أعد التجربة من المحادثة ثم أصلح الأداة أو أضف الإجراء.\n"
		"The tool failed without a permission or missing-field reason. Reproduce from the chat and fix the tool or add the action."
	),
}


def record_gap(
	*,
	answer: str | None,
	pending: dict | None,
	signals: list | None,
	message: str,
	chat: str,
	route: str | None,
	persona: str | None,
	intent: dict | None,
	clarified: bool,
) -> None:
	"""Insert one Open row, or nothing. Never raises into the chat reply."""
	try:
		if not frappe.db.exists("DocType", "ERP AI Enhancement"):
			return
		gap = classify_gap(answer, pending, signals or [], clarified=clarified, intent=intent or {})
		if not gap:
			return
		key = _gap_key(gap)
		if _recent_duplicate(chat, key):
			return
		from erpnext_ai_assistant.services.naming import as_title

		stamp = frappe.utils.now_datetime().strftime("%H%M%S")
		tail = (chat or "")[-6:]
		label = gap.get("doctype") or gap.get("action") or gap["kind"]
		title = as_title("ERP AI Enhancement", f"{gap['kind']} {label} {tail} {stamp}")
		reply = answer or ""
		if gap["kind"] == "tool_error":
			reply = "تعذّر تنفيذ الأداة." if _arabic(message) else "Tool failed."
		elif gap["kind"] == "not_verified":
			reply = NOT_VERIFIED_AR if _arabic(message) else NOT_VERIFIED_EN
		persona_name = persona if persona and frappe.db.exists("ERP AI Persona", persona) else None
		frappe.get_doc(
			{
				"doctype": "ERP AI Enhancement",
				"title": title,
				"gap_key": key,
				"kind": gap["kind"],
				"status": "Open",
				"user": frappe.session.user,
				"chat": chat,
				"route": (route or "")[:140],
				"persona": persona_name,
				"action": (gap.get("action") or "")[:140],
				"doctype_name": (gap.get("doctype") or "")[:140],
				"app_name": (gap.get("app") or "")[:140],
				"excerpt": _clip(message),
				"reply_excerpt": _clip(reply),
				"suggested_solution": _SUGGESTIONS[gap["kind"]],
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="ERP AI enhancement record")


def classify_gap(answer: str | None, pending: dict | None, signals: list, clarified: bool, intent: dict) -> dict | None:
	if clarified:
		return None
	pending = pending if isinstance(pending, dict) else {}
	if pending.get("pending_action") or pending.get("status") in ("need_input", "pending"):
		return None
	if pending.get("error") in ("missing_name", "missing_required", "no_create_permission"):
		return None
	text = (answer or "").strip()
	if _is_permission(text) or _is_permission(str(pending.get("error") or "")):
		return None
	context = _context(intent, signals)
	if text in (NOT_VERIFIED_AR, NOT_VERIFIED_EN):
		return {"kind": "not_verified", **context}
	unknown = next((row for row in signals if row.get("kind") == "unknown_capability"), None)
	if unknown:
		return {"kind": "unknown_capability", "action": unknown.get("action") or "", "doctype": "", "app": context.get("app") or ""}
	had_data = any(row.get("kind") == "had_data" for row in signals)
	manual = next((row for row in signals if row.get("kind") == "manual_miss"), None)
	if manual and not had_data and not pending.get("pending_action"):
		topic = re.sub(r"\s+", " ", (manual.get("topic") or "")).strip()[:40]
		return {
			"kind": "manual_miss",
			"action": "search_manual",
			"doctype": "",
			"app": context.get("app") or "",
			"topic": topic,
		}
	failed = pending.get("status") == "failed"
	surfaced = any(row.get("kind") == "tool_error" and row.get("surfaced") for row in signals)
	if failed or surfaced:
		row = next((item for item in signals if item.get("kind") == "tool_error"), {})
		return {
			"kind": "tool_error",
			"action": row.get("action") or pending.get("action_type") or "",
			"doctype": row.get("doctype") or pending.get("target_doctype") or context.get("doctype") or "",
			"app": context.get("app") or "",
		}
	return None


def _context(intent: dict, signals: list) -> dict:
	doctype = ""
	app = ""
	action = (intent or {}).get("action") or ""
	if (intent or {}).get("confidence") == "high":
		candidates = (intent or {}).get("candidates") or []
		if candidates:
			doctype = candidates[0].get("doctype") or ""
			app = candidates[0].get("app") or ""
	for row in signals:
		if row.get("doctype"):
			doctype = row["doctype"]
		if row.get("app"):
			app = row["app"]
		if row.get("action") and row.get("kind") != "had_data":
			action = row["action"]
	return {"action": action if action not in ("unknown", "howto") else "", "doctype": doctype, "app": app}


def _gap_key(gap: dict) -> str:
	parts = [gap.get("kind") or "", gap.get("action") or "", gap.get("doctype") or "", gap.get("app") or ""]
	if gap.get("kind") == "manual_miss" and gap.get("topic"):
		parts.append(gap["topic"])
	return "|".join(parts)[:140]


def _recent_duplicate(chat: str, gap_key: str) -> bool:
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-10)
	rows = frappe.db.get_all(
		"ERP AI Enhancement",
		filters={
			"user": frappe.session.user,
			"chat": chat,
			"gap_key": gap_key,
			"creation": [">=", cutoff],
		},
		limit=1,
	)
	return bool(rows)


def _clip(text: str | None) -> str:
	raw = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "[redacted]", text or "")
	raw = re.sub(r"\b(?:api[_-]?key|token)\s*[:=]\s*\S+", "[redacted]", raw, flags=re.I)
	return raw.strip()[:400]


def _arabic(text: str | None) -> bool:
	return bool(re.search(r"[\u0600-\u06FF]", text or ""))


def _is_permission(text: str) -> bool:
	lower = (text or "").lower()
	return any(phrase in text or phrase in lower for phrase in _PERMISSION)
