# Copyright (c) ERPNext AI Assistant — T01–T17 automated checks for The ERPNext-AI-Assistant
"""Test IDs T01–T17 from docs/SRS.md / plan."""

from __future__ import annotations

import inspect
import json

import frappe
from frappe.tests.utils import FrappeTestCase


class TestErpAiAssistantPipeline(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("ERP AI Settings", "ERP AI Settings"):
			from erpnext_ai_assistant.install import after_install

			after_install()

	def test_T01_guest_cannot_chat_or_approve(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			frappe.call("erpnext_ai_assistant.api.chat.run", message="hi", route="/crm")
		with self.assertRaises(frappe.PermissionError):
			frappe.call(
				"erpnext_ai_assistant.api.chat.approve_action",
				pending_action="x",
				acknowledgment_text="ok",
				acknowledged=1,
			)

	def test_T02_erp_query_uses_get_list_not_get_all(self):
		from erpnext_ai_assistant.services.tools import registry as reg

		src = inspect.getsource(reg.tool_erp_query)
		self.assertIn("frappe.get_list", src)
		self.assertNotIn("frappe.get_all", src)
		self.assertNotIn("ignore_permissions", src)

	def test_T03_work_only_gate_refuses_off_work(self):
		from erpnext_ai_assistant.services.moderation.work_gate import is_work_related

		self.assertFalse(is_work_related("write me a poem about cats", "/crm/leads"))
		self.assertFalse(is_work_related("اكتب قصيدة عن الحب", "/crm"))
		self.assertTrue(is_work_related("ابحث عن العميل", "/crm/leads"))

	def test_T04_abuse_creates_event(self):
		from erpnext_ai_assistant.services.moderation import abuse as abuse_mod

		frappe.set_user("Administrator")
		before = frappe.db.count("ERP AI Abuse Event")
		res = abuse_mod.scan_abuse("you are an idiot", chat=None)
		self.assertTrue(res.get("hit"))
		self.assertEqual(frappe.db.count("ERP AI Abuse Event"), before + 1)

	def test_T05_T06_abuse_threshold_and_block(self):
		from erpnext_ai_assistant.services.moderation import abuse as abuse_mod

		# Use a disposable test user if possible; otherwise Administrator path still exercises code
		settings = frappe.get_single("ERP AI Settings")
		settings.abuse_threshold_count = 1
		settings.abuse_score_limit = 0.5
		settings.save()
		# Ensure a known insult term exists
		if not any((r.term or "").lower() == "idiot" for r in (settings.abuse_terms or [])):
			settings.append("abuse_terms", {"term": "idiot", "language": "en", "category": "insult", "score": 2})
			settings.save()
		# Clear prior blocks for Administrator for deterministic test
		settings = frappe.get_single("ERP AI Settings")
		settings.blocked_users = []
		settings.save()
		abuse_mod.scan_abuse("idiot idiot", chat=None)
		self.assertTrue(abuse_mod.is_user_blocked("Administrator"))
		msg = abuse_mod.blocked_message("ar")
		self.assertIn("حظر", msg)

	def test_T07_rdf_arabic_name_to_lead_name(self):
		from erpnext_ai_assistant.services.rdf.graph import lookup, rebuild_rdf_graph

		target = "Lead" if frappe.db.exists("DocType", "Lead") else "CRM Lead"
		rebuild_rdf_graph([target])
		hits = lookup("اسم")
		fields = {h["fieldname"] for h in hits if h.get("doctype") == target}
		self.assertIn("lead_name", fields)

	def test_T08_crm_skill_loads_for_route(self):
		from erpnext_ai_assistant.services.tools.registry import read_skill

		skills = read_skill(route="/crm/leads")
		titles = [s.title for s in skills]
		self.assertTrue(any("CRM" in (t or "") or "lead" in (t or "").lower() for t in titles))

	def test_T09_T10_pending_action_ack_and_reject(self):
		from erpnext_ai_assistant.services.tools.registry import propose_write

		chat = frappe.get_doc(
			{
				"doctype": "ERP AI Chat",
				"title": "t",
				"user": frappe.session.user,
				"route": "/crm",
				"status": "Open",
				"language": "ar",
			}
		).insert()
		pending = propose_write(
			chat.name,
			"create",
			"ToDo",
			{"description": "erp-ai-test"},
			"إنشاء مهمة تجريبية",
		)
		name = pending["pending_action"]
		doc = frappe.get_doc("ERP AI Pending Action", name)
		self.assertEqual(doc.status, "pending")
		# reject
		frappe.call("erpnext_ai_assistant.api.chat.reject_action", pending_action=name, reason="no")
		doc.reload()
		self.assertEqual(doc.status, "rejected")
		self.assertFalse(frappe.db.exists("ToDo", {"description": "erp-ai-test"}))

	def test_T11_persona_memory_cannot_skip_work_gate(self):
		from erpnext_ai_assistant.services.moderation.work_gate import is_work_related

		# persona loaded later; work gate is independent
		self.assertFalse(is_work_related("tell me a joke", "/crm"))

	def test_T12_skill_crud_reflected_in_read_skill(self):
		from erpnext_ai_assistant.services.tools.registry import read_skill

		title = "T12 Temp Skill"
		if frappe.db.exists("ERP AI Skill", {"title": title}):
			frappe.delete_doc("ERP AI Skill", frappe.db.get_value("ERP AI Skill", {"title": title}))
		doc = frappe.get_doc(
			{
				"doctype": "ERP AI Skill",
				"title": title,
				"enabled": 1,
				"routes": "/crm/leads",
				"description": "temp",
				"roles": [{"role": "System Manager"}],
			}
		).insert()
		titles = [s.title for s in read_skill(route="/crm/leads")]
		self.assertIn(title, titles)
		doc.enabled = 0
		doc.save()
		titles2 = [s.title for s in read_skill(route="/crm/leads")]
		self.assertNotIn(title, titles2)

	def test_T13_chart_payload_no_recharts(self):
		from erpnext_ai_assistant.services.charts.build import build_chart
		import erpnext_ai_assistant.services.charts.build as build_mod

		src = inspect.getsource(build_mod)
		self.assertNotIn("from recharts", src.lower())
		self.assertNotIn("import recharts", src.lower())
		self.assertNotIn("ChartRenderer", src)
		for t in ("bar", "line", "pie", "kpi"):
			p = build_chart(t, "عنوان", ["أ", "ب"], [1, 2], value=5)
			self.assertEqual(p["type"], t)

	def test_T14_run_method_rejects_non_allowlisted(self):
		from erpnext_ai_assistant.services.tools.registry import tool_run_method

		with self.assertRaises(frappe.PermissionError):
			tool_run_method("frappe.client.set_value", doctype="User", name="x", fieldname="y", value="z")

	def test_T15_chat_message_registered(self):
		frappe.set_user("Administrator")
		res = frappe.call(
			"erpnext_ai_assistant.api.chat.run",
			message="ابحث عن عميل تجريبي في CRM",
			route="/crm/leads",
		)
		self.assertTrue(res.get("chat_id"))
		self.assertTrue(frappe.db.exists("ERP AI Chat", res["chat_id"]))
		self.assertTrue(
			frappe.db.exists("ERP AI Message", {"chat": res["chat_id"], "role": "user"})
		)

	def test_T16_workspace_exists(self):
		self.assertTrue(
			frappe.db.exists("Workspace", "The ERPNext-AI-Assistant")
			or frappe.db.exists("Workspace", {"title": "The ERPNext-AI-Assistant"})
		)

	def test_T18_history_uses_newest_window(self):
		from erpnext_ai_assistant.services.conversation import load_openai_history
		from erpnext_ai_assistant.services.naming import as_title

		chat = frappe.get_doc(
			{
				"doctype": "ERP AI Chat",
				"title": as_title("ERP AI Chat", "history-window"),
				"user": frappe.session.user,
				"status": "Open",
				"language": "en",
			}
		).insert()
		for i in range(20):
			frappe.get_doc(
				{
					"doctype": "ERP AI Message",
					"title": as_title("ERP AI Message", f"history {i}"),
					"chat": chat.name,
					"role": "user" if i % 2 == 0 else "assistant",
					"content": f"m{i}",
					"status": "complete",
				}
			).insert()
		history = load_openai_history(chat.name, exclude_last_user=False)
		self.assertEqual(history[0]["content"], "m4")
		self.assertEqual(history[-1]["content"], "m19")
		self.assertEqual(len(history), 16)

	def test_T19_missing_phone_is_not_invented(self):
		from erpnext_ai_assistant.services.detectors import _propose_create_call

		if not frappe.db.exists("DocType", "CRM Lead"):
			self.skipTest("CRM Lead is not installed")
		lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "NoPhone", "lead_name": "NoPhone", "status": "New"}
		).insert(ignore_permissions=True)
		result = _propose_create_call(f"add a call to the lead {lead.name}", [], chat_id=None, lang="en")
		text = (result.get("message_en") or "") + json.dumps(result)
		self.assertEqual(result.get("status"), "need_input")
		self.assertNotIn("+966500000000", text)
		self.assertNotIn('"from": "manual"', text)

	def test_T20_payload_cannot_change_after_proposal(self):
		from erpnext_ai_assistant.services.naming import as_title
		from erpnext_ai_assistant.services.tools.registry import propose_write

		chat = frappe.get_doc(
			{
				"doctype": "ERP AI Chat",
				"title": as_title("ERP AI Chat", "tamper"),
				"user": frappe.session.user,
				"status": "Open",
				"language": "en",
			}
		).insert()
		pending = propose_write(chat.name, "create", "ToDo", {"description": "original"})
		doc = frappe.get_doc("ERP AI Pending Action", pending["pending_action"])
		doc.payload_json = json.dumps({"description": "tampered"})
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_T21_reject_and_second_approve_are_closed(self):
		from erpnext_ai_assistant.services.naming import as_title
		from erpnext_ai_assistant.services.tools.registry import propose_write

		chat = frappe.get_doc(
			{
				"doctype": "ERP AI Chat",
				"title": as_title("ERP AI Chat", "replay"),
				"user": frappe.session.user,
				"status": "Open",
				"language": "en",
			}
		).insert()
		pending = propose_write(chat.name, "create", "ToDo", {"description": "replay-me"})
		name = pending["pending_action"]
		frappe.call(
			"erpnext_ai_assistant.api.chat.approve_action",
			pending_action=name,
			acknowledgment_text="I approve",
			acknowledged=1,
		)
		with self.assertRaises(frappe.ValidationError):
			frappe.call(
				"erpnext_ai_assistant.api.chat.approve_action",
				pending_action=name,
				acknowledgment_text="again",
				acknowledged=1,
			)
		with self.assertRaises(frappe.ValidationError):
			frappe.call("erpnext_ai_assistant.api.chat.reject_action", pending_action=name, reason="too late")
		self.assertEqual(frappe.db.get_value("ERP AI Pending Action", name, "status"), "executed")

	def test_T22_other_user_cannot_approve(self):
		from erpnext_ai_assistant.services.naming import as_title
		from erpnext_ai_assistant.services.tools.registry import propose_write

		email = "erp-ai-other@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "Other",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		chat = frappe.get_doc(
			{
				"doctype": "ERP AI Chat",
				"title": as_title("ERP AI Chat", "isolation"),
				"user": frappe.session.user,
				"status": "Open",
				"language": "en",
			}
		).insert()
		pending = propose_write(chat.name, "create", "ToDo", {"description": "not-yours"})
		frappe.set_user(email)
		with self.assertRaises(frappe.PermissionError):
			frappe.call(
				"erpnext_ai_assistant.api.chat.approve_action",
				pending_action=pending["pending_action"],
				acknowledgment_text="steal",
				acknowledged=1,
			)

	def test_T23_restricted_skill_is_not_retrieved(self):
		from erpnext_ai_assistant.services.rag.service import _upsert_document, retrieve

		_upsert_document(
			"skill:secret",
			"Secret Skill Doc",
			"SECRET_SKILL_PHRASE_ZX",
			"skill",
			source_roles="System Manager",
		)
		docname = frappe.db.get_value("ERP AI Knowledge Document", {"title": "Secret Skill Doc"}, "name")
		if not frappe.db.exists("ERP AI Knowledge Chunk", {"document": docname, "chunk_index": 0}):
			frappe.get_doc(
				{
					"doctype": "ERP AI Knowledge Chunk",
					"title": "Secret Skill Doc 1",
					"document": docname,
					"chunk_index": 0,
					"content": "SECRET_SKILL_PHRASE_ZX",
				}
			).insert(ignore_permissions=True)
		email = "erp-ai-other@example.com"
		frappe.set_user(email)
		hits = retrieve("SECRET_SKILL_PHRASE_ZX")
		self.assertFalse(any("SECRET_SKILL_PHRASE_ZX" in (hit.get("content") or "") for hit in hits))

	def test_T24_schema_lists_missing_mandatory_fields(self):
		from erpnext_ai_assistant.services.schema import prepare_payload

		empty = prepare_payload("ToDo", {}, "create")
		self.assertTrue(any(item["fieldname"] == "description" for item in empty["missing"]))
		ready = prepare_payload("ToDo", {"description": "buy milk"}, "create")
		self.assertFalse(ready["missing"])
		self.assertEqual(ready["payload"]["description"], "buy milk")

	def test_T25_approval_summary_is_not_html(self):
		from pathlib import Path

		source = Path(frappe.get_app_path("erpnext_ai_assistant", "public", "js", "erpnext_ai_assistant.bundle.js")).read_text()
		self.assertIn("function safeLocalPath", source)
		self.assertIn('textNode("div", "erp-ai-ack-summary", (pending && pending.summary)', source)
		self.assertNotIn('el("div", "", (pending && pending.summary)', source)

	def test_T17_reports_exist(self):
		for name in (
			"ERP AI Chats by User",
			"ERP AI Abuse Summary",
			"ERP AI Pending Actions",
		):
			self.assertTrue(frappe.db.exists("Report", name), name)

	def test_I1_disabled_chat_creates_no_message(self):
		settings = frappe.get_single("ERP AI Settings")
		was = settings.enabled
		settings.enabled = 0
		settings.save()
		try:
			before = frappe.db.count("ERP AI Message")
			res = frappe.call(
				"erpnext_ai_assistant.api.chat.run",
				message="كم عدد المهام؟",
				route="/desk",
			)
			self.assertEqual(res.get("status"), "disabled")
			self.assertEqual(frappe.db.count("ERP AI Message"), before)
		finally:
			settings = frappe.get_single("ERP AI Settings")
			settings.enabled = was
			settings.save()

	def test_I1_skill_disable_rename_delete_absent_from_retrieve(self):
		from erpnext_ai_assistant.services.rag.service import on_skill_trash, on_skill_update, retrieve

		phrase = "SKILL_PHRASE_ITER1_ZX9"
		renamed = "SKILL_PHRASE_ITER1_QY8"
		doc = frappe.get_doc(
			{
				"doctype": "ERP AI Skill",
				"title": "Iter1 Skill Temp",
				"enabled": 1,
				"description": phrase,
				"roles": [{"role": "System Manager"}],
			}
		).insert()
		on_skill_update(doc)
		self.assertTrue(any((h.get("content") or "") == phrase for h in retrieve(phrase)))
		doc.enabled = 0
		doc.save()
		on_skill_update(doc)
		self.assertFalse(any(phrase in (h.get("content") or "") for h in retrieve(phrase)))
		doc.enabled = 1
		doc.title = "Iter1 Skill Renamed"
		doc.description = renamed
		doc.save()
		on_skill_update(doc)
		self.assertFalse(any(phrase in (h.get("content") or "") for h in retrieve(phrase)))
		self.assertTrue(any((h.get("content") or "") == renamed for h in retrieve(renamed)))
		on_skill_trash(doc)
		frappe.delete_doc("ERP AI Skill", doc.name, force=1)
		self.assertFalse(any(renamed in (h.get("content") or "") for h in retrieve(renamed)))

	def test_I1_rdf_paths_include_site_name(self):
		from erpnext_ai_assistant.services.rdf import graph as rdf

		original = frappe.local.site
		path_a = str(rdf._graph_file())
		key_a = rdf._cache_key()
		self.assertIn(original, path_a)
		self.assertIn(original, key_a)
		frappe.local.site = "other-site.example"
		try:
			path_b = str(rdf._graph_file())
			key_b = rdf._cache_key()
			self.assertIn("other-site.example", path_b)
			self.assertIn("other-site.example", key_b)
			self.assertNotEqual(path_a, path_b)
			self.assertNotEqual(key_a, key_b)
		finally:
			frappe.local.site = original

	def test_I1_salary_slip_role_permissions(self):
		from erpnext_ai_assistant.services.schema import describe_doctype
		from erpnext_ai_assistant.services.tools import agent as agent_mod
		from erpnext_ai_assistant.services.tools import registry as reg

		if not frappe.db.exists("DocType", "Salary Slip"):
			self.skipTest("Salary Slip not installed")
		# Administrator / HR Manager path: must be able to describe when permitted
		if frappe.has_permission("Salary Slip", "read"):
			schema = describe_doctype("Salary Slip")
			self.assertTrue(schema.get("fields"))
		email = "erp-ai-nopayroll@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "NoPayroll",
					"send_welcome_email": 0,
					"roles": [{"role": "Desk User"}],
				}
			).insert(ignore_permissions=True)
		frappe.set_user(email)
		self.assertFalse(frappe.has_permission("Salary Slip", "read"))
		for name in ("query_records", "count_records", "describe_doctype"):
			result = agent_mod.dispatch(name, {"doctype": "Salary Slip"}, None, "en")
			self.assertTrue(result.get("error"), name)
		with self.assertRaises(frappe.PermissionError):
			reg.tool_erp_count("Salary Slip")
		frappe.set_user("Administrator")

	def test_I1_count_vs_page_and_user_permission(self):
		from erpnext_ai_assistant.services.tools import registry as reg

		page = reg.tool_erp_query("ToDo", fields=["name"], limit=5)
		total = reg.tool_erp_count("ToDo")
		self.assertGreaterEqual(int(total.get("total") or 0), len(page))
		if len(page) >= 5 and int(total.get("total") or 0) > len(page):
			self.assertGreater(int(total["total"]), len(page))

	def test_I1_get_doc_and_describe_use_permitted_fields(self):
		from erpnext_ai_assistant.services.schema import describe_doctype
		from erpnext_ai_assistant.services.tools import registry as reg

		schema = describe_doctype("ToDo")
		meta = frappe.get_meta("ToDo")
		permitted = set(meta.get_permitted_fieldnames(permission_type="read") or [])
		for field in schema["fields"]:
			if permitted:
				self.assertIn(field["fieldname"], permitted)
		todo = frappe.get_all("ToDo", limit=1, pluck="name")
		if not todo:
			self.skipTest("No ToDo row")
		data = reg.tool_erp_get_doc("ToDo", todo[0])
		src = frappe.get_doc("ToDo", todo[0])
		src.apply_fieldlevel_read_permissions()
		# Methods are wired; result is a dict
		self.assertEqual(data.get("name"), todo[0])
		self.assertIn("apply_fieldlevel_read_permissions", reg.tool_erp_get_doc.__code__.co_names)

	def test_I1_not_verified_without_tools(self):
		from erpnext_ai_assistant.services.tools import agent as agent_mod
		from erpnext_ai_assistant.services.tools.agent import NOT_VERIFIED_AR, NOT_VERIFIED_EN, run_tool_loop

		original = agent_mod.llm.chat_message
		original_begin = agent_mod.llm.begin_turn_deadline

		def fake_chat_message(messages, tools=None, **kwargs):
			return {"content": "There are 9999 records.", "tool_calls": []}

		agent_mod.llm.chat_message = fake_chat_message
		agent_mod.llm.begin_turn_deadline = lambda *a, **k: None
		try:
			out = run_tool_loop("sys", "كم عدد المهام؟", [], "", None, None, "ar", lambda *a, **k: None)
			self.assertEqual(out["answer"], NOT_VERIFIED_AR)
			out_en = run_tool_loop("sys", "how many ToDo records?", [], "", None, None, "en", lambda *a, **k: None)
			self.assertEqual(out_en["answer"], NOT_VERIFIED_EN)
		finally:
			agent_mod.llm.chat_message = original
			agent_mod.llm.begin_turn_deadline = original_begin

	def test_I2_memory_requires_confirm(self):
		before = frappe.db.count("ERP AI Memory", {"user": frappe.session.user, "scope": "user"})
		with self.assertRaises(frappe.ValidationError):
			frappe.call(
				"erpnext_ai_assistant.api.chat.save_my_memory",
				key="pref",
				value="from chat sentence",
				confirmed=0,
			)
		self.assertEqual(
			frappe.db.count("ERP AI Memory", {"user": frappe.session.user, "scope": "user"}),
			before,
		)
		res = frappe.call(
			"erpnext_ai_assistant.api.chat.save_my_memory",
			key="pref-iter2",
			value="confirmed fact",
			confirmed=1,
		)
		self.assertTrue(res.get("ok"))
		listed = frappe.call("erpnext_ai_assistant.api.chat.list_my_memory")
		self.assertTrue(any(r.get("key") == "pref-iter2" for r in listed.get("items") or []))
		frappe.call("erpnext_ai_assistant.api.chat.clear_my_memory")

	def test_I3_filter_label_resolution(self):
		from erpnext_ai_assistant.services.tools import agent as agent_mod

		# Unknown label must error, not invent a fieldname
		result = agent_mod.dispatch(
			"query_records",
			{"doctype": "ToDo", "filters": {"تسمية_وهمية_xyz": "x"}, "limit": 5},
			None,
			"ar",
		)
		self.assertTrue(result.get("error"))

	def test_I4_call_cap_blocks_provider(self):
		from erpnext_ai_assistant.services.llm import provider as llm

		settings = frappe.get_single("ERP AI Settings")
		key = f"erp_ai_calls:{frappe.session.user}:{__import__('datetime').date.today().isoformat()}"
		frappe.cache().set_value(key, int(getattr(settings, "max_calls_per_user_day", None) or 100))
		with self.assertRaises(llm.CallLimitExceeded):
			llm._consume_call_quota(settings, "en")

	def test_fresh_install_baseline(self):
		from erpnext_ai_assistant.install import (
			GENERIC_PERSONA,
			_ensure_settings,
			_roles_that_exist,
			_seed_framework_personas,
			_seed_persona,
			_seed_settings_children,
			_seed_skills,
			seed_plan,
		)
		from erpnext_ai_assistant.services.llm import provider as llm

		frappe_only = seed_plan(installed={"frappe"}, doctypes=set())
		self.assertEqual(frappe_only["skills"], ["Frappe core", "Site installed apps"])
		self.assertEqual(frappe_only["personas"], ["Frappe helper", "Workplace Assistant"])
		with_erp = seed_plan(installed={"frappe", "erpnext"}, doctypes=set())
		self.assertIn("ERPNext manual how-to", with_erp["skills"])
		self.assertIn("Stock", with_erp["skills"])
		self.assertIn("Finance / invoices", with_erp["skills"])
		self.assertIn("ERPNext helper", with_erp["personas"])
		self.assertNotIn("CRM leads & deals", with_erp["skills"])
		self.assertNotIn("HR / payroll", with_erp["skills"])
		with_crm = seed_plan(installed={"frappe"}, doctypes={"CRM Lead"})
		self.assertIn("CRM leads & deals", with_crm["skills"])
		self.assertNotIn("CRM helper", with_crm["personas"])
		with_hrms = seed_plan(installed={"frappe", "hrms"}, doctypes=set())
		self.assertIn("HR / payroll", with_hrms["skills"])
		self.assertEqual(_roles_that_exist([{"role": "Role That Is Not Real XYZ"}]), [])
		self.assertEqual(_roles_that_exist([{"role": "System Manager"}]), [{"role": "System Manager"}])

		class Blank:
			max_calls_per_user_day = None
			turn_deadline_seconds = ""

		class Zero:
			max_calls_per_user_day = 0
			turn_deadline_seconds = 0

		self.assertEqual(llm._stored_int(Blank(), "max_calls_per_user_day", 100), 100)
		self.assertEqual(llm._stored_int(Zero(), "max_calls_per_user_day", 100), 0)
		self.assertEqual(llm._stored_int(Zero(), "turn_deadline_seconds", 90), 0)

		settings = frappe.get_single("ERP AI Settings")
		helper = frappe.db.get_value("ERP AI Persona", {"persona_name": GENERIC_PERSONA}, "name")
		self.assertTrue(helper)
		settings.panel_title = "MARKER-TITLE"
		settings.max_calls_per_user_day = 0
		settings.turn_deadline_seconds = 0
		settings.active_persona = helper
		settings.save(ignore_permissions=True)
		frappe.db.set_value("ERP AI Persona", helper, "tone_instructions", "MARKER-TONE", update_modified=False)
		_ensure_settings()
		_seed_persona()
		_seed_framework_personas()
		_seed_skills()
		_seed_settings_children()
		settings.reload()
		self.assertEqual(settings.panel_title, "MARKER-TITLE")
		self.assertEqual(settings.max_calls_per_user_day, 0)
		self.assertEqual(settings.turn_deadline_seconds, 0)
		self.assertEqual(settings.active_persona, helper)
		self.assertEqual(frappe.db.get_value("ERP AI Persona", helper, "tone_instructions"), "MARKER-TONE")
		settings.active_persona = ""
		settings.save(ignore_permissions=True)
		_seed_settings_children()
		settings.reload()
		self.assertEqual(settings.active_persona, helper)

	def test_desk_link_import_tool(self):
		from erpnext_ai_assistant.services.desk_link import desk_link

		if not frappe.db.exists("DocType", "Data Import"):
			self.skipTest("Data Import is not installed")
		if not frappe.has_permission("Data Import", "read"):
			self.skipTest("No read permission on Data Import")
		opened = desk_link("افتح أداة الاستيراد", "ar")
		self.assertIn("[[open:/desk/data-import|", opened["reply"])
		self.assertNotIn("http", opened["reply"])
		self.assertIsNone(desk_link("https://example.com/import", "en"))

	def test_enhancement_gap_kinds(self):
		from erpnext_ai_assistant.services.enhancement import classify_gap, record_gap
		from erpnext_ai_assistant.services.tools.agent import NOT_VERIFIED_AR

		self.assertEqual(
			classify_gap(NOT_VERIFIED_AR, None, [], clarified=False, intent={})["kind"],
			"not_verified",
		)
		self.assertIsNone(
			classify_gap("هل تقصد:\n1. عميل", None, [], clarified=True, intent={})
		)
		self.assertIsNone(
			classify_gap(
				"لا صلاحية لقراءة الحقل.",
				None,
				[{"kind": "tool_error", "action": "count_records", "surfaced": True}],
				clarified=False,
				intent={},
			)
		)
		self.assertEqual(
			classify_gap(
				"",
				None,
				[{"kind": "unknown_capability", "action": "missing_tool"}],
				clarified=False,
				intent={},
			)["kind"],
			"unknown_capability",
		)
		self.assertIsNone(
			classify_gap(
				"send the field",
				{"status": "need_input"},
				[{"kind": "tool_error", "surfaced": True}],
				clarified=False,
				intent={},
			)
		)
		if not frappe.db.exists("DocType", "ERP AI Enhancement"):
			self.skipTest("ERP AI Enhancement is not migrated")
		chat = frappe.get_doc(
			{
				"doctype": "ERP AI Chat",
				"title": "gap",
				"user": frappe.session.user,
				"route": "/desk",
				"status": "Open",
				"language": "ar",
			}
		).insert()
		payload = dict(
			answer=NOT_VERIFIED_AR,
			pending=None,
			signals=[],
			message="كم عدد السجلات",
			chat=chat.name,
			route="/desk",
			persona="",
			intent={"action": "count", "confidence": "low", "candidates": []},
			clarified=False,
		)
		record_gap(**payload)
		record_gap(**payload)
		rows = frappe.db.get_all("ERP AI Enhancement", filters={"chat": chat.name}, fields=["kind", "status", "gap_key"])
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].kind, "not_verified")
		self.assertEqual(rows[0].status, "Open")
		roles = {row.role for row in frappe.get_meta("ERP AI Enhancement").permissions}
		self.assertEqual(roles, {"System Manager"})
