"""Install / migrate seeds for The ERPNext-AI-Assistant.

Seeds run insert-if-missing only. Existing persona, skills, settings text, and
custom rows are never overwritten on migrate. After install, set the OpenAI
API key on ERP AI Settings — indexes rebuild safely on each migrate.
"""

from __future__ import annotations

import frappe

from erpnext_ai_assistant.services.arabic import normalize_arabic
from erpnext_ai_assistant.services.moderation.abuse import DEFAULT_ABUSE_TERMS

PERSONA_NAME = "Workplace Assistant"
PERSONA_TONE = (
	"You are a Frappe framework assistant for this site. "
	"Help with any DocType the signed-in user can read, including custom apps. "
	"Resolve Arabic labels from translations and the DocType schema. Never invent fieldnames. "
	"Use count_records for quantities. Ask one missing field at a time on creates. "
	"Prefer Arabic when the user writes Arabic. Nothing is saved until the user approves."
)
GENERIC_PERSONA = "Frappe helper"


def after_install():
	_bootstrap()
	frappe.db.commit()


def after_migrate():
	_backfill_titles()
	_bootstrap()


def _bootstrap():
	_ensure_settings()
	_seed_persona()
	_seed_framework_personas()
	_seed_skills()
	_seed_settings_children()
	_seed_desktop_icon()
	_rebuild_indexes()


def _rebuild_indexes():
	"""Safe to re-run: catalog/RDF/RAG rebuild from current DocTypes and skills."""
	try:
		from erpnext_ai_assistant.services.rdf.graph import rebuild_rdf_graph

		rebuild_rdf_graph()
	except Exception:
		frappe.log_error(title="ERP AI RDF rebuild")
	try:
		from erpnext_ai_assistant.services.doctype_catalog import clear_doctype_catalog, get_doctype_catalog

		clear_doctype_catalog()
		get_doctype_catalog(force=True)
	except Exception:
		frappe.log_error(title="ERP AI DocType catalog rebuild")
	try:
		from erpnext_ai_assistant.services.rag.service import reindex_knowledge

		reindex_knowledge()
	except Exception:
		frappe.log_error(title="ERP AI RAG reindex")


def _backfill_titles():
	"""Fill empty Title only — never replace an existing title."""
	jobs = [
		("ERP AI Chat", "COALESCE(NULLIF(title, ''), LEFT(name, 40))"),
		("ERP AI Message", "COALESCE(NULLIF(title, ''), CONCAT(IFNULL(role, 'message'), ': ', LEFT(IFNULL(content, name), 60)))"),
		("ERP AI Memory", "COALESCE(NULLIF(title, ''), CONCAT(IFNULL(scope, 'user'), ': ', IFNULL(`key`, name)))"),
		("ERP AI Knowledge Chunk", "COALESCE(NULLIF(title, ''), CONCAT('Chunk ', IFNULL(chunk_index, 0)))"),
		("ERP AI Pending Action", "COALESCE(NULLIF(title, ''), CONCAT(IFNULL(action_type, 'action'), ' ', IFNULL(target_doctype, '')))"),
		("ERP AI Abuse Event", "COALESCE(NULLIF(title, ''), CONCAT(IFNULL(category, 'event'), ': ', LEFT(IFNULL(excerpt, name), 40)))"),
		("ERP AI Audit Log", "COALESCE(NULLIF(title, ''), IFNULL(event_type, name))"),
		("ERP AI Generated Chart", "COALESCE(NULLIF(title, ''), IFNULL(chart_type, 'Chart'))"),
		("ERP AI Generated Query", "COALESCE(NULLIF(title, ''), CONCAT(IFNULL(query_type, 'Query'), ' ', IFNULL(doctype_name, '')))"),
		("ERP AI Metadata Cache", "COALESCE(NULLIF(title, ''), CONCAT(IFNULL(kind, 'cache'), ': ', IFNULL(ref_name, name)))"),
	]
	for doctype, expr in jobs:
		if not frappe.db.exists("DocType", doctype):
			continue
		if not frappe.db.has_column(doctype, "title"):
			continue
		frappe.db.sql(f"update `tab{doctype}` set title = {expr} where ifnull(title, '') = ''")


def _ensure_settings():
	"""Create Settings once; only fill blank fields afterward. Never overwrite site edits."""
	if not frappe.db.exists("DocType", "ERP AI Settings"):
		return
	meta = frappe.get_meta("ERP AI Settings")
	creating = not frappe.db.exists("ERP AI Settings", "ERP AI Settings")
	doc = frappe.new_doc("ERP AI Settings") if creating else frappe.get_single("ERP AI Settings")

	defaults = {
		"enabled": 1,
		"work_only": 1,
		"moderation_enabled": 1,
		"memory_enabled": 1,
		"allow_pending_writes": 1,
		"abuse_threshold_count": 3,
		"abuse_threshold_days": 30,
		"abuse_score_limit": 5,
		"provider_base_url": "https://api.openai.com/v1",
		"model": "gpt-4o-mini",
		"temperature": 0.2,
		"max_tokens": 2048,
		"max_calls_per_user_day": 100,
		"turn_deadline_seconds": 90,
		"max_memory_items_per_user": 20,
		"panel_title": "ERP Assistant",
		"panel_subtitle": "مساعد أعمالك",
		"panel_hint": "يجيب من بيانات العمل المتاحة لك. لا يُنفَّذ أي تعديل قبل موافقتك.",
		"panel_hint_en": "Answers from the business data you can access. Nothing changes until you approve.",
		"refusal_text_ar": "أنا مساعد عمل لنظام ERP فقط. يرجى طرح سؤال متعلق بالعمل على هذا الموقع.",
		"refusal_text_en": "I am a workplace ERP assistant only. Please ask a work-related question about this site.",
	}
	changed = False
	for fieldname, value in defaults.items():
		if not meta.has_field(fieldname):
			continue
		current = doc.get(fieldname)
		if creating:
			doc.set(fieldname, value)
			changed = True
			continue
		# Existing site: fill only empty / null. Do not reset 0 checks the admin turned off
		# except call-cap fields where 0 means "never set" and blocks the assistant.
		if current in (None, ""):
			doc.set(fieldname, value)
			changed = True

	site_key = frappe.conf.get("erp_ai_openai_api_key")
	if site_key and not doc.api_key and meta.has_field("api_key"):
		doc.api_key = site_key
		changed = True

	if creating:
		doc.insert(ignore_permissions=True)
	elif changed:
		doc.save(ignore_permissions=True)


def _seed_settings_children():
	"""Append missing abuse terms / overlays / notify roles / active persona only."""
	if not frappe.db.exists("DocType", "ERP AI Settings"):
		return
	doc = frappe.get_single("ERP AI Settings")
	changed = False
	existing = {
		(normalize_arabic(r.term or "").lower() or (r.term or "").lower())
		for r in (doc.abuse_terms or [])
		if r.term
	}
	for row in DEFAULT_ABUSE_TERMS:
		term = (row.get("term") or "").strip()
		if not term:
			continue
		key = normalize_arabic(term).lower() or term.lower()
		if key in existing:
			continue
		doc.append("abuse_terms", row)
		existing.add(key)
		changed = True
	if not doc.notify_roles:
		doc.append("notify_roles", {"role": "System Manager"})
		changed = True
	from erpnext_ai_assistant.services.apps import installed_app_routes

	wanted_overlays = [
		{"path_pattern": "/app", "label": "Desk", "host_hint": "desk", "enabled": 1},
	]
	for app_route in installed_app_routes():
		wanted_overlays.append(
			{
				"path_pattern": app_route["route"],
				"label": app_route["title"] or app_route["app"],
				"host_hint": "app",
				"enabled": 1,
			}
		)
	existing_paths = {(r.path_pattern or "") for r in (doc.overlay_pages or [])}
	for row in wanted_overlays:
		if row["path_pattern"] not in existing_paths:
			doc.append("overlay_pages", row)
			existing_paths.add(row["path_pattern"])
			changed = True

	# Link the generic persona only when unset. A saved choice stays.
	if not doc.active_persona and frappe.db.exists("DocType", "ERP AI Persona"):
		name = frappe.db.get_value("ERP AI Persona", {"persona_name": GENERIC_PERSONA}, "name")
		if name:
			doc.active_persona = name
			changed = True
	if changed:
		doc.save(ignore_permissions=True)


def _seed_persona():
	"""Insert the default persona once. Never edit an existing persona row."""
	if not frappe.db.exists("DocType", "ERP AI Persona"):
		return
	if frappe.db.exists("ERP AI Persona", {"persona_name": PERSONA_NAME}):
		return
	doc = frappe.get_doc(
		{
			"doctype": "ERP AI Persona",
			"persona_name": PERSONA_NAME,
			"enabled": 1,
			"panel_label": "The ERPNext-AI-Assistant",
			"panel_label_ar": "مساعد العمل",
			"default_language": "ar",
			"tone_instructions": PERSONA_TONE,
			"roles": _roles_that_exist(
				[
					{"role": "System Manager"},
					{"role": "Sales User"},
					{"role": "Sales Manager"},
				]
			),
		}
	)
	doc.insert(ignore_permissions=True)


def _roles_that_exist(rows: list | None) -> list:
	"""Drop Role links that are not on this site. Keep the parent row."""
	kept = []
	for row in rows or []:
		role = (row or {}).get("role")
		if role and frappe.db.exists("Role", role):
			kept.append({"role": role})
	return kept


def seed_plan(installed: set[str] | None = None, doctypes: set[str] | None = None) -> dict:
	"""Names a fresh site would insert. Existing rows are never deleted by the caller."""
	if installed is None:
		try:
			installed = set(frappe.get_installed_apps())
		except Exception:
			installed = set()
	else:
		installed = set(installed)
	if doctypes is None:
		doctypes = set()
		if frappe.db.exists("DocType", "CRM Lead"):
			doctypes.add("CRM Lead")
	else:
		doctypes = set(doctypes)
	skills = ["Frappe core", "Site installed apps"]
	personas = [GENERIC_PERSONA, PERSONA_NAME]
	if "erpnext" in installed:
		skills.extend(["ERPNext manual how-to", "Stock", "Finance / invoices"])
		personas.append("ERPNext helper")
	if "CRM Lead" in doctypes:
		skills.append("CRM leads & deals")
	if "crm" in installed:
		personas.append("CRM helper")
	if "hrms" in installed:
		skills.append("HR / payroll")
	return {"skills": skills, "personas": personas}


def _insert_persona(payload: dict) -> None:
	"""Insert a persona once. Skip when the name already exists. Never update tone."""
	if frappe.db.exists("ERP AI Persona", {"persona_name": payload.get("persona_name")}):
		return
	meta = frappe.get_meta("ERP AI Persona")
	data = {"doctype": "ERP AI Persona"}
	for key, value in payload.items():
		if key == "roles":
			data[key] = _roles_that_exist(value)
			continue
		if meta.has_field(key):
			data[key] = value
	frappe.get_doc(data).insert(ignore_permissions=True)


def _seed_framework_personas():
	"""Generic persona always; specialty personas only when that app is installed."""
	if not frappe.db.exists("DocType", "ERP AI Persona"):
		return
	_insert_persona(
		{
			"persona_name": GENERIC_PERSONA,
			"enabled": 1,
			"panel_label": "Frappe helper",
			"panel_label_ar": "مساعد العمل",
			"default_language": "ar",
			"priority": 0,
			"tone_instructions": PERSONA_TONE,
			"roles": [],
		}
	)
	optional = [
		(
			"ERPNext helper",
			"erpnext",
			20,
			"ERPNext helper",
			"مساعد ERPNext",
			"Help with ERPNext DocTypes this user can read. Use count_records for quantities "
			"and the manual tool for how-to questions. Never invent fields.",
		),
		(
			"CRM helper",
			"crm",
			30,
			"CRM helper",
			"مساعد العلاقات",
			"Help with CRM DocTypes this user can read. Map Arabic name labels to lead_name "
			"when that field exists. Creates stay pending until the user approves.",
		),
	]
	try:
		installed = set(frappe.get_installed_apps())
	except Exception:
		installed = set()
	for name, app, priority, label, label_ar, tone in optional:
		if app not in installed:
			continue
		_insert_persona(
			{
				"persona_name": name,
				"enabled": 1,
				"panel_label": label,
				"panel_label_ar": label_ar,
				"default_language": "ar",
				"priority": priority,
				"match_apps": app,
				"tone_instructions": tone,
				"roles": [],
			}
		)


def _seed_skills():
	"""Insert each seeded skill once by title. Never overwrite existing skills."""
	if not frappe.db.exists("DocType", "ERP AI Skill"):
		return
	from erpnext_ai_assistant.skills.seed import SKILL_SEEDS

	allowed = set(seed_plan()["skills"])
	for seed in SKILL_SEEDS:
		if seed["title"] not in allowed:
			continue
		if frappe.db.exists("ERP AI Skill", {"title": seed["title"]}):
			continue
		payload = dict(seed)
		payload["roles"] = _roles_that_exist(seed.get("roles"))
		doc = frappe.get_doc({"doctype": "ERP AI Skill", **payload})
		doc.insert(ignore_permissions=True)


def _seed_desktop_icon():
	"""Ensure the v15 Desk icon and workspace exist. Do not touch other icons."""
	if not frappe.db.exists("DocType", "Desktop Icon"):
		return

	label = "The ERPNext-AI-Assistant"
	link = "/app/the-erpnext-ai-assistant"
	# v15 autonames Desktop Icon with a hash, and standard icons are unique per module.
	existing = frappe.db.get_value(
		"Desktop Icon",
		{"module_name": "ERP AI Assistant", "standard": 1},
		"name",
	) or frappe.db.get_value("Desktop Icon", {"label": label}, "name")
	if existing:
		doc = frappe.get_doc("Desktop Icon", existing)
		changed = False
		if doc.hidden:
			doc.hidden = 0
			changed = True
		if doc.link != link:
			doc.link = link
			changed = True
		if not doc.type:
			doc.type = "link"
			changed = True
		if changed:
			doc.save(ignore_permissions=True)
	else:
		frappe.get_doc(
			{
				"doctype": "Desktop Icon",
				"label": label,
				"module_name": "ERP AI Assistant",
				"type": "link",
				"link": link,
				"app": "erpnext_ai_assistant",
				"icon": "message",
				"color": "#1e3a5f",
				"hidden": 0,
				"standard": 1,
				"idx": 3,
			}
		).insert(ignore_permissions=True)

	if frappe.db.exists("Workspace", label):
		frappe.db.set_value(
			"Workspace",
			label,
			{"public": 1, "is_hidden": 0},
			update_modified=False,
		)

	frappe.cache.delete_key("desktop_icons")
