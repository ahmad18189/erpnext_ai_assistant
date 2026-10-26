"""OpenAI chat completions — called last in run_chat.

API key lives in ERP AI Settings → API Key (Password field), or site_config
`erp_ai_openai_api_key` / env OPENAI_API_KEY. Never commit keys to git.
"""

from __future__ import annotations

import json
import os
import urllib.request

import frappe

DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


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
	except Exception:
		frappe.log_error(title="ERP AI LLM call failed")
		return _fallback(user, tool_context)


def chat_message(messages: list[dict], tools: list | None = None, settings=None, api_key: str | None = None, base: str | None = None, model: str | None = None) -> dict:
	"""One chat completion. Returns the assistant message, including tool_calls when tools are set."""
	settings = settings or frappe.get_single("ERP AI Settings")
	api_key = api_key or get_openai_api_key(settings)
	base = (base or settings.provider_base_url or DEFAULT_OPENAI_BASE).rstrip("/")
	model = model or settings.model or DEFAULT_MODEL
	if not api_key:
		raise frappe.ValidationError("No model key")
	payload = {
		"model": model,
		"temperature": float(settings.temperature or 0.2),
		"max_tokens": int(settings.max_tokens or 2048),
		"messages": messages,
	}
	if tools:
		payload["tools"] = tools
		payload["tool_choice"] = "auto"
	req = urllib.request.Request(
		f"{base}/chat/completions",
		data=json.dumps(payload).encode(),
		headers={
			"Content-Type": "application/json",
			"Authorization": f"Bearer {api_key}",
		},
		method="POST",
	)
	with urllib.request.urlopen(req, timeout=60) as resp:
		data = json.loads(resp.read().decode())
	return data["choices"][0]["message"]


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
