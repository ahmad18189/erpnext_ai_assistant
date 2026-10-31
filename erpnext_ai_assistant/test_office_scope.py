"""Office mode: a skill with a server_policy keeps the panel inside that office on every path.

The policy here is a test double scoped to ToDo, so these tests do not depend on any office app.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext_ai_assistant.services import office_scope
from erpnext_ai_assistant.services.tools import registry
from erpnext_ai_assistant.services.tools.agent import active_tool_specs, dispatch

ROUTE = "/desk/test-office"
POLICY = "erpnext_ai_assistant.test_office_scope.fake_policy"


def fake_policy():
	return {
		"knowledge": False,
		"imports": False,
		"attachments": False,
		"outbound": {"ToDo": ("name", "status")},
		"clamp_fields": lambda doctype, fields: ["name", "status"],
		"outside_message": "OUTSIDE",
		"import_message": "NO IMPORTS",
		"attachment_message": "NO ATTACHMENTS",
		"preflight": lambda message: "",
		"check_write": lambda *args: "",
	}


def broken_policy():
	raise RuntimeError("cannot load")


class TestOfficeScope(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.skill = _skill(POLICY)
		self.todo = frappe.get_doc({"doctype": "ToDo", "description": "secret description", "status": "Open"}).insert()

	def tearDown(self):
		frappe.flags.erp_ai_office = None
		frappe.flags.erp_ai_context = None
		frappe.set_user("Administrator")

	def test_reads_are_clamped_to_the_outbound_fields(self):
		office_scope.activate(ROUTE, {})
		rows = registry.tool_erp_query("ToDo", filters={"name": self.todo.name}, fields=["*"])
		self.assertEqual(set(rows[0]), {"name", "status"})
		self.assertNotIn("secret description", str(rows))

	def test_every_read_path_refuses_other_doctypes(self):
		office_scope.activate(ROUTE, {})
		self.assertRaises(frappe.PermissionError, registry.tool_erp_query, "User", fields=["name"])
		self.assertRaises(frappe.PermissionError, registry.tool_erp_count, "User")
		self.assertEqual(dispatch("count_records", {"doctype": "User"}, None, "en", "count users").get("status"), "failed")

	def test_knowledge_tools_are_off(self):
		office_scope.activate(ROUTE, {})
		names = {(spec.get("function") or {}).get("name") for spec in active_tool_specs()}
		self.assertNotIn("search_knowledge", names)
		self.assertEqual(dispatch("search_knowledge", {"query": "x"}, None, "en", "x").get("status"), "failed")
		listed = dispatch("list_doctypes", {"query": "User"}, None, "en", "x")
		self.assertEqual([row["name"] for row in listed["doctypes"]], ["ToDo"])

	def test_browser_allow_list_is_checked_on_the_server(self):
		other = frappe.get_doc({"doctype": "ToDo", "description": "other"}).insert()
		office_scope.activate(
			ROUTE,
			{
				"doctype": "ToDo",
				"name": self.todo.name,
				"allow": [
					{"action": "update", "doctype": "ToDo", "name": self.todo.name},
					{"action": "update", "doctype": "ToDo", "name": other.name},  # not the open record
					{"action": "update", "doctype": "ToDo"},  # no name: any record
					{"action": "delete", "doctype": "ToDo", "name": self.todo.name},
				],
			},
		)
		allow = frappe.flags.erp_ai_context["allow"]
		self.assertEqual(allow, [{"action": "update", "doctype": "ToDo", "name": self.todo.name}])

	def test_allow_list_follows_the_users_permissions(self):
		user = _plain_user()
		frappe.set_user(user)
		office_scope.activate(
			ROUTE,
			{"doctype": "ToDo", "name": self.todo.name, "allow": [{"action": "update", "doctype": "ToDo", "name": self.todo.name}]},
		)
		self.assertEqual(frappe.flags.erp_ai_context["allow"], [])

	def test_a_policy_that_fails_to_load_refuses(self):
		self.skill.description = "server_policy: " + POLICY.replace("fake_policy", "broken_policy")
		self.skill.save()
		with patch.object(frappe, "log_error"):
			office_scope.activate(ROUTE, {})
		self.assertTrue(office_scope.preflight("hello"))
		self.assertFalse(office_scope.allows("knowledge"))

	def test_record_without_a_skill_stays_in_its_module(self):
		if not frappe.db.exists("DocType", "FL Matter"):
			self.skipTest("needs an FL DocType")
		self.skill.enabled = 0
		self.skill.save()
		office = office_scope.activate("/desk/somewhere", {"doctype": "FL Matter"})
		self.assertIn("FL Matter", office["doctypes"])
		self.assertNotIn("User", office["doctypes"])
		self.assertEqual(office_scope.guard_doctype("User").get("status"), "failed")


def _skill(policy):
	doc = frappe.get_doc(
		{
			"doctype": "ERP AI Skill",
			"title": "Test office " + frappe.generate_hash(length=6),
			"enabled": 1,
			"priority": 0,
			"routes": ROUTE,
			"doctypes": "ToDo",
			"description": "server_policy: " + policy,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def _plain_user():
	email = "office.scope.test@example.com"
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Scope", "send_welcome_email": 0, "user_type": "Website User"}
		).insert(ignore_permissions=True)
	return email
