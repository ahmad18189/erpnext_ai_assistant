"""CRM-day language on /crm: the right DocType, and no write before approval."""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext_ai_assistant.api.chat import approve_action
from erpnext_ai_assistant.install import seed_plan
from erpnext_ai_assistant.services import targeting
from erpnext_ai_assistant.services.arabic import normalize_arabic
from erpnext_ai_assistant.services.crm_day import CONVERT_METHOD, REMINDER_METHOD, handle
from erpnext_ai_assistant.services.rdf.graph import _apply_crm_aliases

TAG = "crd" + frappe.generate_hash(length=6)


class TestCrmDay(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		frappe.reload_doc("erp_ai_assistant", "doctype", "erp_ai_pending_action", force=True)
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.flags.erp_ai_route = ""
		self.chat = frappe.get_doc(
			{"doctype": "ERP AI Chat", "title": TAG + "-" + frappe.generate_hash(length=6), "user": frappe.session.user}
		).insert().name

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_route_words(self):
		self.assertEqual(targeting.match_doctype("اعمل مهمة"), "ToDo")
		self.assertEqual(targeting.match_doctype("كم عميل"), "Customer")
		self.assertEqual(targeting.match_doctype("اعمل مهمة", route="/crm"), "CRM Task")
		self.assertEqual(targeting.match_doctype("كم عميل", route="/crm"), "CRM Lead")
		self.assertEqual(targeting.match_doctype("اعرض صفقة", route="/crm"), "CRM Deal")
		self.assertEqual(targeting.match_doctype("todo غدا", route="/crm"), "ToDo")
		self.assertIn("CRM day on /crm", seed_plan(installed={"frappe"}, doctypes={"CRM Lead"})["skills"])
		self.assertNotIn("CRM day on /crm", seed_plan(installed={"frappe"}, doctypes=set())["skills"])

	def test_rdf_alias_is_a_boost_not_a_second_graph(self):
		bucket: dict = {}
		row = {
			"doctype": "CRM Deal",
			"fieldname": "organization_name",
			"label": "Organization Name",
			"fieldtype": "Data",
		}
		_apply_crm_aliases(bucket, "CRM Deal", row)
		key = normalize_arabic("صفقة")
		stored = list(bucket[key].values())[0]
		self.assertEqual(stored["doctype"], "CRM Deal")
		self.assertEqual(stored["fieldname"], "organization_name")
		self.assertEqual(stored["boost"], 2)

	def test_my_leads_and_status_card(self):
		lead = _lead(f"خالد{TAG}")
		listed = handle("ورّيني عملائي", "/crm", self.chat, "ar")
		self.assertIn(f"خالد{TAG}", listed["answer"])
		self.assertNotIn("CRM Lead", listed["answer"])
		self.assertIsNone(listed["pending"])

		card = handle(f"خالد{TAG} تم التواصل", "/crm", self.chat, "ar")
		summary = card["pending"]["summary"]
		self.assertIn(f"خالد{TAG}", summary)
		self.assertIn("تم التواصل", summary)
		self.assertNotIn("CRM Lead", summary)
		self.assertNotIn("status", summary)
		self.assertEqual(frappe.db.get_value("CRM Lead", lead.name, "status"), "New")
		task = handle(f"سجّل مهمة أرسل العرض خالد{TAG}", "/crm", self.chat, "ar")
		self.assertEqual(task["pending"]["target_doctype"], "CRM Task")
		self.assertIn("مهمة", task["pending"]["summary"])
		self.assertNotIn("ToDo", task["pending"]["summary"])
		self.assertFalse(frappe.db.exists("CRM Task", {"reference_docname": lead.name}))

	def test_two_names_ask_instead_of_a_card(self):
		_lead(f"خالد{TAG}")
		_lead(f"خالد{TAG}")
		out = handle(f"حوّل خالد{TAG} لصفقة", "/crm", self.chat, "ar")
		self.assertIsNone(out["pending"])
		self.assertIn("أكثر", out["answer"])

	def test_reminder_and_convert_wait_for_approval(self):
		lead = _lead(f"ليلى{TAG}")
		before_reminders = frappe.db.count("Yalla CRM Reminder")
		before_deals = frappe.db.count("CRM Deal")
		reminder = handle(f"حط تذكير بكرة الصباح ليلى{TAG}", "/crm", self.chat, "ar")
		self.assertEqual(reminder["pending"]["action_type"], "method")
		self.assertIn(f"ليلى{TAG}", reminder["pending"]["summary"])
		self.assertIn("صباح", reminder["pending"]["summary"])
		self.assertNotRegex(reminder["pending"]["summary"], r"\d{4}-\d{2}-\d{2}")
		self.assertEqual(frappe.db.count("Yalla CRM Reminder"), before_reminders)
		payload = json.loads(frappe.db.get_value("ERP AI Pending Action", reminder["pending"]["pending_action"], "payload_json"))
		self.assertEqual(payload["method"], REMINDER_METHOD)
		with patch("frappe.call", return_value={"name": "REM"}) as mocked:
			approve_action(reminder["pending"]["pending_action"], "موافق", 1)
			self.assertEqual(mocked.call_args[0][0], REMINDER_METHOD)
		self.assertEqual(frappe.db.count("Yalla CRM Reminder"), before_reminders)

		lost = _lead(f"نادر{TAG}")
		frappe.db.set_value("CRM Lead", lost.name, "status", "Unqualified", update_modified=False)
		refused = handle(f"حوّل نادر{TAG} لصفقة", "/crm", self.chat, "ar")
		self.assertIsNone(refused["pending"])
		self.assertIn("خاسرة", refused["answer"])

		conversion = handle(f"حوّل ليلى{TAG} لصفقة", "/crm", self.chat, "ar")
		self.assertEqual(conversion["pending"]["action_type"], "method")
		self.assertIn(f"ليلى{TAG}", conversion["pending"]["summary"])
		self.assertIn("صفقة", conversion["pending"]["summary"])
		self.assertNotIn("CRM Lead", conversion["pending"]["summary"])
		self.assertEqual(frappe.db.count("CRM Deal"), before_deals)
		body = json.loads(frappe.db.get_value("ERP AI Pending Action", conversion["pending"]["pending_action"], "payload_json"))
		self.assertEqual(body["method"], CONVERT_METHOD)
		self.assertEqual(body["args"]["lead"], lead.name)
		with patch("frappe.call", return_value={"name": "DEAL"}) as mocked:
			approve_action(conversion["pending"]["pending_action"], "موافق", 1)
			self.assertEqual(mocked.call_args[0][0], CONVERT_METHOD)
		self.assertEqual(frappe.db.count("CRM Deal"), before_deals)


def _lead(name: str, status: str = "New"):
	return frappe.get_doc(
		{
			"doctype": "CRM Lead",
			"first_name": name,
			"lead_name": name,
			"status": status,
			"lead_owner": frappe.session.user,
		}
	).insert()
