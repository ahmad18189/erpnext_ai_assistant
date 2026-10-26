"""Server-side write contract. Summaries are derived from the stored payload."""

from __future__ import annotations

import hashlib
import json

import frappe


def payload_hash(payload) -> str:
	if isinstance(payload, str):
		try:
			payload = json.loads(payload) if payload else {}
		except Exception:
			payload = {"_raw": payload}
	canonical = json.dumps(payload or {}, sort_keys=True, ensure_ascii=False, default=str)
	return hashlib.sha256(canonical.encode()).hexdigest()


def summary_from_payload(action: str, doctype: str, payload: dict, target_name: str | None = None) -> str:
	lines = [f"{action} {doctype}" + (f" {target_name}" if target_name else "")]
	for key in sorted((payload or {}).keys()):
		value = payload[key]
		if isinstance(value, (dict, list)):
			value = json.dumps(value, ensure_ascii=False, default=str)
		label = key[1:] if str(key).startswith("_") else key
		lines.append(f"{label}: {value}")
	return "\n".join(lines)[:2000]
