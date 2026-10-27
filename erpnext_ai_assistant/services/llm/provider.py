"""OpenAI chat completions — called last in run_chat.

API key lives in ERP AI Settings → API Key (Password field), or site_config
`erp_ai_openai_api_key` / env OPENAI_API_KEY. Never commit keys to git.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import date

import frappe

DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

LIMIT_AR = "بلغت حد الاستدعاءات اليومي. حاول مرة أخرى غداً."
LIMIT_EN = "You reached today's call limit. Try again tomorrow."
DEADLINE_AR = "انتهى وقت هذا الدور قبل استدعاء النموذج."
DEADLINE_EN = "This turn ran out of time before another model call."


class CallLimitExceeded(Exception):
	"""Raised when the per-user daily provider call cap is hit."""

	def __init__(self, lang: str = "en"):
		self.lang = lang
		super().__init__(LIMIT_AR if lang == "ar" else LIMIT_EN)


class TurnDeadlineExceeded(Exception):
	"""Raised when the turn deadline is past before another provider call."""

	def __init__(self, lang: str = "en"):
		self.lang = lang
		super().__init__(DEADLINE_AR if lang == "ar" else DEADLINE_EN)


def get_openai_api_key(settings=None) -> str | None:
	settings = settings or frappe.get_single("ERP AI Settings")
	api_key = None
	if settings.api_key:
		try:
			api_key = settings.get_password("api_key")
		except Exception:
			api_key = None
	return (
		api_key
		or frappe.conf.get("erp_ai_openai_api_key")
		or os.environ.get("ERP_AI_API_KEY")
		or os.environ.get("OPENAI_API_KEY")
	)


def complete(
	system: str,
	user: str,
	tool_context: str = "",
	history: list[dict] | None = None,
	chat_summary: str = "",
	images: list[dict] | None = None,
) -> str:
	"""Run chat completion with optional multi-turn history + rolling summary."""
	from erpnext_ai_assistant.services.conversation import build_messages

	settings = frappe.get_single("ERP AI Settings")
	if not settings.enabled:
		return _fallback(user, tool_context)
	api_key = get_openai_api_key(settings)
	base = (settings.provider_base_url or DEFAULT_OPENAI_BASE).rstrip("/")
	model = settings.model or DEFAULT_MODEL
	if not api_key:
		return _fallback(user, tool_context)

	messages = build_messages(
		system=system,
		tool_context=tool_context,
		history=history or [],
		user_message=user,
		chat_summary=chat_summary or "",
		images=images or [],
	)

	try:
		message = chat_message(messages, tools=None, settings=settings, api_key=api_key, base=base, model=model)
		return message.get("content") or ""
	except CallLimitExceeded as exc:
		return str(exc)
	except TurnDeadlineExceeded as exc:
		return str(exc)
	except Exception:
		frappe.log_error(title="ERP AI LLM call failed")
		return _fallback(user, tool_context)


def chat_message(
	messages: list[dict],
	tools: list | None = None,
	settings=None,
	api_key: str | None = None,
	base: str | None = None,
	model: str | None = None,
	chat_id: str | None = None,
	lang: str = "en",
) -> dict:
	"""One chat completion. Returns the assistant message, including tool_calls when tools are set."""
	settings = settings or frappe.get_single("ERP AI Settings")
	api_key = api_key or get_openai_api_key(settings)
	base = (base or settings.provider_base_url or DEFAULT_OPENAI_BASE).rstrip("/")
	model = model or settings.model or DEFAULT_MODEL
	if not api_key:
		raise frappe.ValidationError("No model key")

	_check_turn_deadline(lang)
	_consume_call_quota(settings, lang)

	payload = {
		"model": model,
		"temperature": float(settings.temperature or 0.2),
		"max_tokens": int(settings.max_tokens or 2048),
		"messages": messages,
	}
	if tools:
		payload["tools"] = tools
		payload["tool_choice"] = "auto"
	body = json.dumps(payload).encode()
	_audit_provider_call(messages, tools, len(body), chat_id)
	req = urllib.request.Request(
		f"{base}/chat/completions",
		data=body,
		headers={
			"Content-Type": "application/json",
			"Authorization": f"Bearer {api_key}",
		},
		method="POST",
	)
	with urllib.request.urlopen(req, timeout=60) as resp:
		data = json.loads(resp.read().decode())
	return data["choices"][0]["message"]


def begin_turn_deadline(settings=None):
	"""Mark when this turn started so later rounds can stop at the deadline."""
	settings = settings or frappe.get_single("ERP AI Settings")
	import time

	frappe.flags.erp_ai_turn_started = time.time()
	frappe.flags.erp_ai_turn_deadline = _stored_int(settings, "turn_deadline_seconds", 90)


def _check_turn_deadline(lang: str):
	import time

	started = getattr(frappe.flags, "erp_ai_turn_started", None)
	deadline = getattr(frappe.flags, "erp_ai_turn_deadline", None)
	if started is None or deadline is None:
		return
	if time.time() - float(started) > float(deadline):
		raise TurnDeadlineExceeded(lang)


def _stored_int(settings, field: str, default: int) -> int:
	"""None or blank uses the default. A saved 0 stays 0."""
	value = getattr(settings, field, None)
	if value is None or value == "":
		return default
	return int(value)


def _consume_call_quota(settings, lang: str):
	user = frappe.session.user or "Guest"
	cap = _stored_int(settings, "max_calls_per_user_day", 100)
	key = f"erp_ai_calls:{user}:{date.today().isoformat()}"
	used = int(frappe.cache().get_value(key) or 0)
	if used >= cap:
		raise CallLimitExceeded(lang)
	frappe.cache().set_value(key, used + 1, expires_in_sec=60 * 60 * 36)


def _audit_provider_call(messages: list[dict], tools: list | None, byte_size: int, chat_id: str | None):
	"""One audit row per provider call. DocTypes and field names only — no key, bytes, or raw messages."""
	try:
		doctypes, fields, images = _summarize_payload(messages, tools)
		from erpnext_ai_assistant.services.naming import as_title

		frappe.get_doc(
			{
				"doctype": "ERP AI Audit Log",
				"title": as_title("ERP AI Audit Log", "provider_call"),
				"event_type": "provider_call",
				"user": frappe.session.user,
				"chat": chat_id,
				"payload_json": json.dumps(
					{
						"doctypes": sorted(doctypes),
						"fields": sorted(fields)[:80],
						"image_count": images,
						"request_bytes": byte_size,
					},
					ensure_ascii=False,
				),
			}
		).insert(ignore_permissions=True)
	except Exception:
		pass


def _summarize_payload(messages: list[dict], tools: list | None) -> tuple[set, set, int]:
	doctypes: set[str] = set()
	fields: set[str] = set()
	images = 0
	for msg in messages or []:
		content = msg.get("content")
		if isinstance(content, list):
			for part in content:
				if isinstance(part, dict) and part.get("type") == "image_url":
					images += 1
		if msg.get("role") == "tool":
			try:
				body = json.loads(msg.get("content") or "{}")
			except Exception:
				body = {}
			if isinstance(body, dict):
				if body.get("doctype"):
					doctypes.add(str(body["doctype"]))
				for row in body.get("rows") or []:
					if isinstance(row, dict):
						fields.update(str(k) for k in row.keys())
				for hit in body.get("hits") or []:
					if isinstance(hit, dict) and hit.get("fieldname"):
						fields.add(str(hit["fieldname"]))
					if isinstance(hit, dict) and hit.get("doctype"):
						doctypes.add(str(hit["doctype"]))
		for call in msg.get("tool_calls") or []:
			fn = (call.get("function") or {}) if isinstance(call, dict) else {}
			try:
				args = json.loads(fn.get("arguments") or "{}")
			except Exception:
				args = {}
			if isinstance(args, dict):
				if args.get("doctype"):
					doctypes.add(str(args["doctype"]))
				for key in (args.get("filters") or {}) if isinstance(args.get("filters"), dict) else {}:
					fields.add(str(key))
				for fname in args.get("fields") or []:
					fields.add(str(fname))
	return doctypes, fields, images


def _fallback(user: str, tool_context: str) -> str:
	if tool_context.strip():
		return (
			"نتائج الاستعلام / Query results:\n\n"
			+ tool_context[:4000]
			+ "\n\n(لم يتم تكوين مفتاح نموذج؛ عُرضت نتائج الأدوات فقط.)"
		)
	return (
		"لا تتوفر نتائج من النظام حالياً. تأكد من السؤال أو صلاحياتك. "
		"(No model key configured; no tool results.)"
	)
