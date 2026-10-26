"""Install / migrate seeds for The ERPNext-AI-Assistant."""

from __future__ import annotations

import frappe

from erpnext_ai_assistant.services.moderation.abuse import DEFAULT_ABUSE_TERMS
from erpnext_ai_assistant.services.arabic import normalize_arabic


def after_install():
	_ensure_settings()
	_seed_persona()
	_seed_skills()
	_seed_settings_children()
	_seed_desktop_icon()
	frappe.db.commit()


def after_migrate():
	_backfill_titles()
	_ensure_settings()
	_seed_persona()
	_seed_skills()
	_seed_settings_children()
	_seed_desktop_icon()
	try:
		from erpnext_ai_assistant.services.doctype_catalog import clear_doctype_catalog, get_doctype_catalog

		clear_doctype_catalog()
		get_doctype_catalog(force=True)
	except Exception:
		frappe.log_error(title="ERP AI DocType catalog rebuild on migrate")
	try:
		from erpnext_ai_assistant.services.rdf.graph import rebuild_rdf_graph

		rebuild_rdf_graph()
	except Exception:
		frappe.log_error(title="ERP AI RDF rebuild on migrate")
	try:
		from erpnext_ai_assistant.services.rag.service import reindex_knowledge

		reindex_knowledge()
	except Exception:
		frappe.log_error(title="ERP AI RAG reindex on migrate")


def _backfill_titles():
	"""Fill the Title field on older hash-named rows so list view has a label."""
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
	if not frappe.db.exists("DocType", "ERP AI Settings"):
		return
	if not frappe.db.exists("ERP AI Settings", "ERP AI Settings"):
		doc = frappe.new_doc("ERP AI Settings")
		doc.enabled = 1
		doc.work_only = 1
		doc.moderation_enabled = 1
		doc.memory_enabled = 1
		doc.allow_pending_writes = 1
		doc.abuse_threshold_count = 3
		doc.abuse_threshold_days = 30
		doc.provider_base_url = "https://api.openai.com/v1"
		doc.model = "gpt-4o-mini"
		doc.temperature = 0.2
		doc.max_tokens = 2048
		doc.insert(ignore_permissions=True)
	else:
		doc = frappe.get_single("ERP AI Settings")
		changed = False
		if not doc.provider_base_url:
			doc.provider_base_url = "https://api.openai.com/v1"
			changed = True
		if not doc.model:
			doc.model = "gpt-4o-mini"
			changed = True
		for fieldname, value in (
			("panel_title", "ERP Assistant"),
			("panel_subtitle", "مساعد أعمالك"),
			("panel_hint", "يجيب من بيانات العمل المتاحة لك. لا يُنفَّذ أي تعديل قبل موافقتك."),
			("panel_hint_en", "Answers from the business data you can access. Nothing changes until you approve."),
		):
			if frappe.get_meta("ERP AI Settings").has_field(fieldname) and not (doc.get(fieldname) or "").strip():
				doc.set(fieldname, value)
				changed = True
		# Prefer site_config over baking secrets into code
		site_key = frappe.conf.get("erp_ai_openai_api_key")
		if site_key and not doc.api_key:
			doc.api_key = site_key
			changed = True
		if changed:
			doc.save(ignore_permissions=True)


def _seed_settings_children():
	if not frappe.db.exists("DocType", "ERP AI Settings"):
		return
	doc = frappe.get_single("ERP AI Settings")
	changed = False
	# Merge any missing DEFAULT_ABUSE_TERMS (do not wipe custom additions)
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
		{"path_pattern": "/desk", "label": "Desk", "host_hint": "desk", "enabled": 1},
		{"path_pattern": "/app", "label": "Desk (legacy /app)", "host_hint": "desk", "enabled": 1},
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
	existing = {(r.path_pattern or "") for r in (doc.overlay_pages or [])}
	for row in wanted_overlays:
		if row["path_pattern"] not in existing:
			doc.append("overlay_pages", row)
			changed = True
	if not doc.active_persona and frappe.db.exists("DocType", "ERP AI Persona"):
		name = frappe.db.get_value("ERP AI Persona", {"persona_name": "Workplace Assistant"}, "name")
		if name:
			doc.active_persona = name
			changed = True
	if changed:
		doc.save(ignore_permissions=True)


def _seed_persona():
	if not frappe.db.exists("DocType", "ERP AI Persona"):
		return
	if frappe.db.exists("ERP AI Persona", {"persona_name": "Workplace Assistant"}):
		return
	doc = frappe.get_doc(
		{
			"doctype": "ERP AI Persona",
			"persona_name": "Workplace Assistant",
			"enabled": 1,
			"panel_label": "The ERPNext-AI-Assistant",
			"panel_label_ar": "مساعد ERPNext",
			"default_language": "ar",
			"tone_instructions": (
				"You are The ERPNext-AI-Assistant, a workplace ERP/CRM helper. "
				"Answer only about this site's business data. Be concise. Prefer Arabic when the user writes Arabic. "
				"Never invent DocType fields. Never invent e-invoice clearance identifiers."
			),
			"roles": [{"role": "System Manager"}, {"role": "Sales User"}, {"role": "Sales Manager"}],
		}
	)
	doc.insert(ignore_permissions=True)


def _skill_seed_rows():
	from erpnext_ai_assistant.skills.seed import SKILL_SEEDS

	return SKILL_SEEDS


def _seed_skills():
	if not frappe.db.exists("DocType", "ERP AI Skill"):
		return
	for seed in _skill_seed_rows():
		existing = frappe.db.get_value("ERP AI Skill", {"title": seed["title"]}, "name")
		if existing:
			continue
		doc = frappe.get_doc({"doctype": "ERP AI Skill", **seed})
		doc.insert(ignore_permissions=True)


def _seed_desktop_icon():
	"""Ensure Desk grid shows The ERPNext-AI-Assistant (Desktop Icons mode)."""
	if not frappe.db.exists("DocType", "Desktop Icon"):
		return
	import json

	label = "The ERPNext-AI-Assistant"
	logo = "/assets/erpnext_ai_assistant/images/erp-ai-logo.svg"
	link = "/desk/the-erpnext-ai-assistant"
	if frappe.db.exists("Desktop Icon", label):
		doc = frappe.get_doc("Desktop Icon", label)
		changed = False
		if doc.hidden:
			doc.hidden = 0
			changed = True
		if doc.logo_url != logo:
			doc.logo_url = logo
			changed = True
		if doc.link != link:
			doc.link = link
			changed = True
		if doc.icon_type != "App":
			doc.icon_type = "App"
			changed = True
		if doc.app != "erpnext_ai_assistant":
			doc.app = "erpnext_ai_assistant"
			changed = True
		if changed:
			doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Desktop Icon",
				"label": label,
				"icon_type": "App",
				"link_type": "External",
				"link": link,
				"app": "erpnext_ai_assistant",
				"icon": "message",
				"logo_url": logo,
				"hidden": 0,
				"standard": 1,
				"idx": 3,
			}
		)
		doc.insert(ignore_permissions=True)

	# Workspace must stay public/visible for the Desk link
	if frappe.db.exists("Workspace", label):
		frappe.db.set_value(
			"Workspace",
			label,
			{"public": 1, "is_hidden": 0, "icon": "message", "type": "Workspace"},
			update_modified=False,
		)

	# Desktop Icons home uses per-user Desktop Layout — inject if missing
	if frappe.db.exists("DocType", "Desktop Layout"):
		entry = {
			"label": doc.label,
			"bg_color": getattr(doc, "bg_color", None) or "blue",
			"link": doc.link,
			"link_type": doc.link_type,
			"app": doc.app,
			"icon_type": doc.icon_type,
			"parent_icon": None,
			"icon": doc.icon,
			"link_to": doc.link_to,
			"idx": 2,
			"standard": 1,
			"logo_url": doc.logo_url,
			"hidden": 0,
			"name": doc.name,
			"restrict_removal": 0,
			"icon_image": None,
			"child_icons": [],
		}
		for lay in frappe.get_all("Desktop Layout", pluck="name"):
			raw = frappe.db.get_value("Desktop Layout", lay, "layout") or "[]"
			try:
				data = json.loads(raw)
			except Exception:
				continue
			if not isinstance(data, list):
				continue
			names = {(x.get("name") or x.get("label")) for x in data if isinstance(x, dict)}
			if doc.name in names or doc.label in names:
				for x in data:
					if x.get("name") == doc.name or x.get("label") == doc.label:
						x["hidden"] = 0
						x["logo_url"] = doc.logo_url
						x["link"] = doc.link
			else:
				data.insert(min(1, len(data)), entry)
			frappe.db.set_value(
				"Desktop Layout",
				lay,
				"layout",
				json.dumps(data, ensure_ascii=False),
				update_modified=False,
			)

	try:
		from frappe.desk.doctype.desktop_icon.desktop_icon import (
			clear_desktop_icons_cache,
			clear_every_users_desktop_icons,
		)

		clear_every_users_desktop_icons()
		clear_desktop_icons_cache()
	except Exception:
		frappe.cache.delete_key("desktop_icons")
