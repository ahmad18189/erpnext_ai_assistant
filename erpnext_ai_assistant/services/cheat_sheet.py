"""Fixed list of what the assistant can do. No model call and no counts."""

from __future__ import annotations

import frappe
from erpnext_ai_assistant.services.arabic import normalize_arabic
from erpnext_ai_assistant.services.targeting import _has

_ASKS = (
	"ماذا تستطيع",
	"ماذا يمكنك",
	"وش تقدر",
	"what can you do",
	"what can you",
)


def is_cheat_sheet(message: str | None) -> bool:
	norm = normalize_arabic(message)
	raw = (message or "").strip().lower()
	if raw in {"help", "?", "مساعدة"}:
		return True
	return any(_has(norm, phrase) for phrase in _ASKS)


def cheat_sheet_text(lang: str) -> str:
	erpnext = False
	try:
		erpnext = "erpnext" in set(frappe.get_installed_apps())
	except Exception:
		erpnext = False
	if lang == "ar":
		lines = [
			"عدّ أو اعرض السجلات التي تستطيع قراءتها. مثال: كم عدد المهام",
			"افتح شاشة في هذا المكتب. مثال: افتح أداة الاستيراد",
			"أنشئ أو عدّل سجلًا حقلًا واحدًا في كل مرة. لا يُحفظ شيء قبل موافقتك.",
			"راجع جدولًا، ثم استورده فقط بعد موافقتك.",
		]
		if erpnext:
			lines.append("اسأل عن خطوات العمل في دليل ERPNext عندما يكون مثبتًا.")
		lines.append("احفظ حقيقة عنك فقط بعد تفعيل خانة التأكيد.")
		return "\n".join(f"- {line}" for line in lines)
	lines = [
		"Count or list records you can read. Example: how many todos",
		"Open a screen on this Desk. Example: open the import tool",
		"Create or update one field at a time. Nothing is saved until you approve.",
		"Review a spreadsheet, then import it only after you approve.",
	]
	if erpnext:
		lines.append("Ask how to do something in the ERPNext manual when ERPNext is installed.")
	lines.append("Save a fact about you only after you check the confirm box.")
	return "\n".join(f"- {line}" for line in lines)
