"""Security review of the panel redesign plan: cards, request methods, stale approvals, links."""

from __future__ import annotations

import os

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext_ai_assistant.api.chat import approve_action, reject_action
from erpnext_ai_assistant.services.tools.registry import propose_write


def _request(method: str):
	frappe.local.request = type("Req", (), {"method": method})()


class TestCardSecurity(FrappeTestCase):
	def setUp(self):
		super().setUp()
		_request("POST")
		frappe.set_user("Administrator")
		self.chat = frappe.get_doc({"doctype": "ERP AI Chat", "title": "sec " + frappe.generate_hash(length=6), "user": "Administrator"}).insert().name
		self.todo = frappe.get_doc({"doctype": "ToDo", "description": "security check", "allocated_to": "Administrator"}).insert().name

	def test_cards_cannot_be_inserted_outside_the_proposal_path(self):
		card = frappe.get_doc(
			{
				"doctype": "ERP AI Pending Action",
				"title": "forged " + frappe.generate_hash(length=6),
				"user": "Administrator",
				"action_type": "delete",
				"target_doctype": "ToDo",
				"target_name": self.todo,
				"summary": "looks harmless",
				"payload_json": "{}",
				"status": "pending",
			}
		)
		with self.assertRaises(frappe.PermissionError):
			card.insert(ignore_permissions=True)

	def test_users_have_no_rest_create_or_write_on_cards(self):
		perms = {row.role: row for row in frappe.get_meta("ERP AI Pending Action").permissions}
		self.assertFalse(perms["All"].create)
		self.assertFalse(perms["All"].write)

	def test_state_changing_endpoints_refuse_get(self):
		from frappe.handler import execute_cmd

		for method in ("approve_action", "reject_action", "save_my_memory", "clear_my_memory", "run", "upload_attachment"):
			_request("GET")
			frappe.local.form_dict = frappe._dict(cmd=f"erpnext_ai_assistant.api.chat.{method}")
			with self.assertRaises(frappe.PermissionError, msg=method):
				execute_cmd(f"erpnext_ai_assistant.api.chat.{method}")
		_request("POST")

	def test_record_changed_after_the_card_expires_it(self):
		card = propose_write(self.chat, "update", "ToDo", {"priority": "High"}, target_name=self.todo)
		frappe.db.set_value("ToDo", self.todo, "description", "changed by someone else", update_modified=True)
		out = approve_action(card["pending_action"], "ok", 1)
		self.assertEqual(out["status"], "expired")
		self.assertNotEqual(frappe.db.get_value("ToDo", self.todo, "priority"), "High")
		self.assertEqual(frappe.db.get_value("ERP AI Pending Action", card["pending_action"], "status"), "expired")

	def test_old_cards_expire(self):
		card = propose_write(self.chat, "update", "ToDo", {"priority": "High"}, target_name=self.todo)
		frappe.db.set_value("ERP AI Pending Action", card["pending_action"], "creation", frappe.utils.add_days(frappe.utils.now_datetime(), -2), update_modified=False)
		self.assertEqual(approve_action(card["pending_action"], "ok", 1)["status"], "expired")

	def test_only_the_requester_approves_but_a_manager_may_reject(self):
		card = propose_write(self.chat, "update", "ToDo", {"priority": "High"}, target_name=self.todo)
		other = "sec-other-" + frappe.generate_hash(length=6) + "@example.test"
		frappe.get_doc({"doctype": "User", "email": other, "first_name": "Other", "send_welcome_email": 0, "roles": [{"role": "System Manager"}]}).insert(ignore_permissions=True)
		frappe.set_user(other)
		with self.assertRaises(frappe.PermissionError):
			approve_action(card["pending_action"], "ok", 1)
		self.assertEqual(reject_action(card["pending_action"])["status"], "rejected")
		frappe.set_user("Administrator")

	def test_update_cannot_set_protected_fields(self):
		card = propose_write(self.chat, "update", "ToDo", {"priority": "High"}, target_name=self.todo)
		# Simulate a payload that slipped protected keys past the proposal.
		import json

		from erpnext_ai_assistant.services.writes import payload_hash

		payload = {"priority": "High", "owner": "someone@example.test", "docstatus": 1}
		frappe.db.set_value("ERP AI Pending Action", card["pending_action"], {"payload_json": json.dumps(payload), "payload_hash": payload_hash(payload)}, update_modified=False)
		approve_action(card["pending_action"], "ok", 1)
		row = frappe.db.get_value("ToDo", self.todo, ["priority", "owner", "docstatus"], as_dict=True)
		self.assertEqual(row.priority, "High")
		self.assertEqual(row.owner, "Administrator")
		self.assertEqual(row.docstatus, 0)


class TestPanelLinks(FrappeTestCase):
	def test_model_links_only_open_this_site(self):
		base = os.path.join(frappe.get_app_path("erpnext_ai_assistant"), "public", "js", "assistant")
		source = open(os.path.join(base, "render.js"), encoding="utf-8").read()
		self.assertIn('if (url.indexOf(window.location.origin + "/") !== 0) {', source)
		self.assertIn('return document.createTextNode(label + " (" + url + ")");', source)

	def test_answers_are_built_as_text_nodes(self):
		base = os.path.join(frappe.get_app_path("erpnext_ai_assistant"), "public", "js", "assistant")
		for name in ("render", "panel", "card", "charts", "desk_compat"):
			source = open(os.path.join(base, f"{name}.js"), encoding="utf-8").read()
			allowed = (
				'innerHTML = "";',
				"sizeBtn.innerHTML = state.expanded ? SHRINK_ICON : EXPAND_ICON; // fixed icon markup, no data",
				"fab.innerHTML =",
			)
			for line in source.splitlines():
				if ".innerHTML =" in line:
					# Only clearing a container or setting one of the two fixed icons is allowed.
					self.assertTrue(any(line.strip().endswith(ok) for ok in allowed), f"{name}: {line.strip()}")
