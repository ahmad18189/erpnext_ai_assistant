"""Fixes 1–3 in docs/USABILITY_FIXES.md. Queries run against the site, not mocks."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext_ai_assistant.services import targeting
from erpnext_ai_assistant.services.intent import _action_name
from erpnext_ai_assistant.services.tools.agent import leave_draft
from erpnext_ai_assistant.services.tools.registry import propose_write
from erpnext_ai_assistant.services.writes import _check_record, resolve_write_target

TAG = "usab-" + frappe.generate_hash(length=6)


def _todo(text: str, **extra) -> str:
	return frappe.get_doc({"doctype": "ToDo", "description": f"{TAG} {text}", **extra}).insert().name


class TestCountQueries(FrappeTestCase):
	"""Fix 1: aggregates go through get_list in the form this Frappe version accepts."""

	def test_total_bounds_and_groups_run_for_real(self):
		_todo("one", priority="High", date="2026-01-05")
		_todo("two", priority="High", date="2026-03-09")
		_todo("three", priority="Low", date="2026-02-01")
		filters = [["ToDo", "description", "like", f"{TAG}%"]]
		self.assertEqual(targeting._sql_total("ToDo", filters), 3)
		first, last = targeting._sql_bounds("ToDo", "date", filters)
		self.assertEqual(str(first), "2026-01-05")
		self.assertEqual(str(last), "2026-03-09")
		meta = frappe.get_meta("ToDo")
		groups = targeting._sql_groups("ToDo", meta, {"group": "priority"}, filters)
		self.assertEqual({row["priority"]: row["total"] for row in groups}, {"High": 2, "Low": 1})

	def test_aggregate_form_follows_frappe_version(self):
		with patch.object(frappe, "__version__", "16.53.0"):
			self.assertEqual(targeting._agg("count", "*", "total"), {"COUNT": "*", "as": "total"})
		with patch.object(frappe, "__version__", "15.80.1"):
			self.assertEqual(targeting._agg("count", "*", "total"), "count(name) as total")
			self.assertEqual(targeting._agg("sum", "grand_total", "amount"), "sum(grand_total) as amount")


class TestWriteTargets(FrappeTestCase):
	"""Fix 2: a non-create card only points at a real record the user may change."""

	def test_real_name_is_kept(self):
		name = _todo("exact")
		self.assertEqual(resolve_write_target("update", "ToDo", name, {"status": "Closed"}), {"status": "ok", "name": name})

	def test_one_match_by_description_is_used(self):
		name = _todo("call the supplier")
		result = resolve_write_target("update", "ToDo", f"{TAG} call the supplier", {"status": "Closed"})
		self.assertEqual(result, {"status": "ok", "name": name})

	def test_several_matches_ask_which_one(self):
		_todo("follow up A")
		_todo("follow up B")
		result = resolve_write_target("update", "ToDo", f"{TAG} follow up", {"status": "Closed"})
		self.assertEqual(result["status"], "need_input")
		self.assertEqual(result["error"], "several_targets")
		self.assertEqual(len(result["choices"]), 2)

	def test_no_match_prepares_nothing(self):
		before = frappe.db.count("ERP AI Pending Action")
		chat = frappe.get_doc({"doctype": "ERP AI Chat", "title": f"{TAG} chat", "user": frappe.session.user}).insert()
		result = propose_write(chat.name, "update", "ToDo", {"status": "Closed"}, target_name=f"{TAG} nothing like this")
		self.assertEqual(result["status"], "failed")
		self.assertEqual(result["error"], "target_not_found")
		self.assertIn("Nothing was prepared", result["message_en"])
		self.assertEqual(frappe.db.count("ERP AI Pending Action"), before)

	def test_wrong_state_is_refused(self):
		meta = frappe._dict(is_submittable=1, get_field=lambda key: None)
		cases = [("submit", 1, "already submitted"), ("cancel", 0, "Only a submitted"), ("delete", 1, "Cancel it before deleting"), ("update", 1, "can no longer change")]
		for action, docstatus, phrase in cases:
			with patch("frappe.db.get_value", return_value=docstatus):
				result = _check_record(action, "Sales Invoice", meta, "SINV-1", {"status": "Paid"}, "Sales Invoice", "فاتورة")
			self.assertEqual(result["error"], "wrong_state", action)
			self.assertIn(phrase, result["message_en"])

	def test_submit_needs_a_submittable_doctype(self):
		name = _todo("not submittable")
		result = resolve_write_target("submit", "ToDo", name, {})
		self.assertEqual(result["error"], "wrong_state")

	def test_no_permission_on_the_record(self):
		name = _todo("someone else's")
		with patch("frappe.has_permission", return_value=False):
			result = resolve_write_target("delete", "ToDo", name, {})
		self.assertEqual(result["error"], "no_permission")

	def test_record_actions_skip_the_count_show_create_menu(self):
		self.assertEqual(_action_name("submit the draft sales invoice for Delta Systems"), "submit")
		self.assertEqual(_action_name("cancel sales invoice ACC-SINV-2026-00005"), "cancel")
		self.assertEqual(_action_name("احذف المهمة"), "delete")
		self.assertEqual(_action_name("اعتمد فاتورة المبيعات"), "submit")


class TestLeaveDraft(FrappeTestCase):
	"""Fix 3: an unfinished create does not swallow the next message."""

	draft = {"pending_intent": "create:Quotation", "collected": {}, "next_field": "naming_series"}

	def test_no_draft_means_nothing_to_leave(self):
		self.assertIsNone(leave_draft("cancel", {}))

	def test_cancel_words_drop_the_draft(self):
		for text in ("cancel", "never mind", "إلغاء", "خلاص", "Stop"):
			self.assertEqual(leave_draft(text, self.draft), "cancel", text)

	def test_questions_and_other_actions_set_it_aside(self):
		for text in ("what is overdue?", "how many customers do we have", "كم عدد العملاء؟", "change customer Delta Systems group to Key Accounts"):
			self.assertEqual(leave_draft(text, self.draft), "aside", text)

	def test_cancelling_a_record_is_not_dropping_the_draft(self):
		self.assertEqual(leave_draft("cancel sales invoice ACC-SINV-2026-00005", self.draft), "aside")

	def test_a_value_continues_the_draft(self):
		for text in ("SAL-QTN-.YYYY.-", "Majal", "SAR", "2 laptops for Delta Systems"):
			self.assertIsNone(leave_draft(text, self.draft), text)


class TestRightDocTypeAndFilters(FrappeTestCase):
	"""Fix 15: the number belongs to the question that was asked."""

	def test_phrases_grouping_and_party_words(self):
		cases = {
			"كم عدد اوامر البيع": "Sales Order",
			"show a chart of sales invoices by customer": "Sales Invoice",
			"Create a quotation for Al-Ofuq company": "Quotation",
			"أنشئ عرض سعر لشركة الأفق": "Quotation",
			"how many customers do we have?": "Customer",
		}
		for text, doctype in cases.items():
			if frappe.db.exists("DocType", doctype):
				self.assertEqual(targeting.match_doctype(text), doctype, text)

	def test_state_words_become_filters(self):
		filters, note = targeting.state_filters_for("ToDo", "how many closed todos", "en")
		self.assertEqual(filters, [["ToDo", "status", "=", "Closed"]])
		self.assertEqual(note, "closed")
		# "open the list" is navigation, not the Open status.
		self.assertEqual(targeting.state_filters_for("ToDo", "open the todo list", "en")[0], [])

	def test_submitted_and_unpaid_on_submittable_doctypes(self):
		if not frappe.db.exists("DocType", "Sales Invoice"):
			self.skipTest("ERPNext not installed")
		filters, _note = targeting.state_filters_for("Sales Invoice", "how many submitted invoices", "en")
		self.assertIn(["Sales Invoice", "docstatus", "=", 1], filters)
		filters, _note = targeting.state_filters_for("Sales Invoice", "كم عدد الفواتير غير المدفوعة", "ar")
		self.assertIn(["Sales Invoice", "outstanding_amount", ">", 0], filters)


class TestFollowUps(FrappeTestCase):
	"""Fix 16: follow-ups point back at the previous answer."""

	def test_refers_back(self):
		from erpnext_ai_assistant.services.run_chat import refers_back

		for text in ("show them", "which customer has the biggest one?", "اعرضها", "export them to excel"):
			self.assertTrue(refers_back(text), text)
		for text in ("how many customers do we have?", "create a quotation"):
			self.assertFalse(refers_back(text), text)


class TestAutofill(FrappeTestCase):
	"""Fix 4: system fields come from defaults; business values from the sentence or the user."""

	def test_typed_defaults(self):
		from erpnext_ai_assistant.services.schema import typed_default

		self.assertIs(typed_default("Check", "0"), 0)
		self.assertEqual(typed_default("Float", "1.5"), 1.5)
		self.assertEqual(typed_default("Data", "0"), "0")

	def test_header_fills_single_option_select_and_drops_fake_company(self):
		from erpnext_ai_assistant.services.autofill import fill_header

		fields = [
			{"fieldname": "naming_series", "label": "Series", "fieldtype": "Select", "options": "\nTST-.####", "reqd": 1, "read_only": 0},
			{"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company", "reqd": 1, "read_only": 0},
		]
		values = {"company": "Not A Real Company " + TAG}
		filled = fill_header(fields, values)
		self.assertEqual(values["naming_series"], "TST-.####")
		self.assertNotEqual(values.get("company"), "Not A Real Company " + TAG)
		self.assertIn("naming_series", {row["fieldname"] for row in filled})

	def test_sentence_values_reads_party_items_and_dates(self):
		if not frappe.db.exists("DocType", "Sales Order"):
			self.skipTest("ERPNext not installed")
		from erpnext_ai_assistant.services.autofill import sentence_date

		self.assertEqual(sentence_date("deliver on 2026-11-20"), "2026-11-20")
		self.assertEqual(sentence_date("deliver in 10 days"), str(frappe.utils.add_days(frappe.utils.nowdate(), 10)))
		self.assertIsNone(sentence_date("2 laptops for Delta"))


class TestCardText(FrappeTestCase):
	"""Fix 5: the card names the record and the change in plain words."""

	def test_update_card_shows_before_and_after(self):
		from erpnext_ai_assistant.services.writes import summary_from_payload

		name = _todo("card text", priority="Low")
		text = summary_from_payload("update", "ToDo", {"priority": "High"}, name)
		self.assertTrue(text.startswith(f"Change ToDo {name}"))
		self.assertIn("Low → High", text)
		self.assertNotIn("priority:", text)
