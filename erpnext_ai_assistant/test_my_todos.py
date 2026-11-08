"""Own-todo list, one-shot alarms, and chat alarm values."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, now_datetime, nowdate

from erpnext_ai_assistant.api.todos import create_my_todo, due_my_alarms, list_my_todos, update_my_todo
from erpnext_ai_assistant.install import ensure_todo_alarm_fields
from erpnext_ai_assistant.services import targeting
from erpnext_ai_assistant.services.schema import prepare_payload

TAG = "todo-alarm-" + frappe.generate_hash(length=6)


class TestMyTodos(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		ensure_todo_alarm_fields()
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def test_due_alarm_after_backdate_then_complete_and_snooze(self):
		created = create_my_todo(f"{TAG} buy milk", alarm_at=add_to_date(now_datetime(), minutes=30))
		name = created["item"]["name"]
		self.assertEqual(created["item"]["alarm_enabled"], 1)
		self.assertNotIn(name, [row["name"] for row in due_my_alarms()["items"]])

		frappe.db.set_value(
			"ToDo",
			name,
			"custom_erp_ai_alarm_at",
			add_to_date(now_datetime(), minutes=-2),
			update_modified=False,
		)
		due = [row["name"] for row in due_my_alarms()["items"]]
		self.assertIn(name, due)

		update_my_todo(name, alarm_fired=1)
		self.assertNotIn(name, [row["name"] for row in due_my_alarms()["items"]])

		snoozed = update_my_todo(name, snooze_minutes=10)
		self.assertEqual(snoozed["item"]["alarm_fired"], 0)
		self.assertEqual(snoozed["item"]["alarm_enabled"], 1)
		self.assertGreater(str(snoozed["item"]["alarm_at"]), str(now_datetime()))
		self.assertNotIn(name, [row["name"] for row in due_my_alarms()["items"]])

		closed = update_my_todo(name, status="Closed")
		self.assertEqual(closed["item"]["status"], "Closed")
		self.assertEqual(frappe.db.get_value("ToDo", name, "status"), "Closed")
		self.assertNotIn(name, [row["name"] for row in list_my_todos()["items"]])

	def test_foreign_user_cannot_update(self):
		created = create_my_todo(f"{TAG} mine only")
		name = created["item"]["name"]
		other = f"{TAG}@example.test"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": other,
				"first_name": "Other",
				"send_welcome_email": 0,
				"roles": [{"role": "System Manager"}],
			}
		).insert(ignore_permissions=True)
		frappe.set_user(other)
		with self.assertRaises(frappe.PermissionError):
			update_my_todo(name, status="Closed")
		self.assertNotIn(name, [row["name"] for row in list_my_todos()["items"]])
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("ToDo", name, "status"), "Open")

	def test_chat_clock_and_day_set_alarm(self):
		tomorrow = str(add_days(nowdate(), 1))
		values = targeting._values("ToDo", "مهمة اجتماع غدا الساعة 3 مساء")
		self.assertEqual(values.get("date"), tomorrow)
		self.assertEqual(values.get("custom_erp_ai_alarm_at"), f"{tomorrow} 15:00:00")
		self.assertEqual(values.get("custom_erp_ai_alarm_enabled"), 1)
		prepared = prepare_payload("ToDo", values, "create")
		self.assertEqual(prepared["errors"], [])
		self.assertEqual(prepared["payload"].get("custom_erp_ai_alarm_at"), f"{tomorrow} 15:00:00")
		self.assertIn("custom_erp_ai_alarm_at", targeting.list_fields("ToDo"))

		plain = targeting._values("ToDo", "create a todo buy milk today")
		self.assertNotIn("custom_erp_ai_alarm_at", plain)

	def test_guest_cannot_list(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			list_my_todos()
