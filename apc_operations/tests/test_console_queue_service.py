# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from apc_operations.services.console_queue_service import (
	URGENCY_OVERDUE,
	URGENCY_TODAY,
	URGENCY_UPCOMING,
	attach_delivery_due_fields,
	delivery_urgency,
	enrich_and_sort_console_queue,
	filter_by_urgency,
	sort_console_queue,
	summarize_urgency_counts,
)


class TestConsoleQueueService(FrappeTestCase):
	def test_delivery_urgency_buckets(self):
		self.assertEqual(delivery_urgency(add_days(today(), -1)), URGENCY_OVERDUE)
		self.assertEqual(delivery_urgency(today()), URGENCY_TODAY)
		self.assertEqual(delivery_urgency(add_days(today(), 2)), URGENCY_UPCOMING)

	def test_sort_console_queue_orders_overdue_before_upcoming(self):
		items = [
			{"name": "B", "delivery_due_date": add_days(today(), 3), "delivery_urgency": URGENCY_UPCOMING},
			{"name": "A", "delivery_due_date": add_days(today(), -2), "delivery_urgency": URGENCY_OVERDUE},
			{"name": "C", "delivery_due_date": today(), "delivery_urgency": URGENCY_TODAY},
		]
		sorted_names = [row["name"] for row in sort_console_queue(items)]
		self.assertEqual(sorted_names, ["A", "C", "B"])

	def test_sort_within_same_urgency_by_date(self):
		items = [
			{"name": "later", "delivery_due_date": add_days(today(), 5), "delivery_urgency": URGENCY_UPCOMING},
			{"name": "sooner", "delivery_due_date": add_days(today(), 1), "delivery_urgency": URGENCY_UPCOMING},
		]
		sorted_names = [row["name"] for row in sort_console_queue(items)]
		self.assertEqual(sorted_names, ["sooner", "later"])

	def test_attach_delivery_due_fields_from_job_order(self):
		if not frappe.db.exists("Customer", "_Test Console Queue Customer"):
			cust = frappe.new_doc("Customer")
			cust.customer_name = "_Test Console Queue Customer"
			cust.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
			cust.territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
			cust.insert(ignore_permissions=True)

		jo = frappe.new_doc("Job Order")
		jo.customer = "_Test Console Queue Customer"
		jo.date = add_days(today(), -1)
		jo.status = "Confirmed"
		jo.commercial_movement = "Export"
		jo.insert(ignore_permissions=True)

		card = attach_delivery_due_fields({"job_order": jo.name})
		self.assertEqual(str(card["delivery_due_date"]), str(jo.date))
		self.assertEqual(card["delivery_urgency"], URGENCY_OVERDUE)
		self.assertTrue(card["is_delivery_overdue"])

	def test_enrich_and_sort_console_queue(self):
		items = enrich_and_sort_console_queue(
			[
				{"job_order": None, "scheduled_delivery_date": add_days(today(), 1)},
				{"job_order": None, "scheduled_delivery_date": add_days(today(), -1)},
			]
		)
		self.assertEqual(items[0]["delivery_urgency"], URGENCY_OVERDUE)
		self.assertEqual(items[1]["delivery_urgency"], URGENCY_UPCOMING)

	def test_summarize_urgency_counts(self):
		items = [
			{"delivery_urgency": URGENCY_OVERDUE, "delivery_due_date": add_days(today(), -1)},
			{"delivery_urgency": URGENCY_TODAY, "delivery_due_date": today()},
			{"delivery_urgency": URGENCY_UPCOMING, "delivery_due_date": add_days(today(), 3)},
			{"delivery_urgency": URGENCY_UPCOMING, "delivery_due_date": add_days(today(), 14)},
		]
		counts = summarize_urgency_counts(items)
		self.assertEqual(counts["overdue"], 1)
		self.assertEqual(counts["today"], 1)
		self.assertEqual(counts["this_week"], 1)
		self.assertEqual(counts["upcoming"], 1)
		self.assertEqual(counts["total"], 4)

	def test_filter_by_urgency_week_includes_overdue_and_today(self):
		items = [
			{"delivery_urgency": URGENCY_OVERDUE, "delivery_due_date": add_days(today(), -2)},
			{"delivery_urgency": URGENCY_TODAY, "delivery_due_date": today()},
			{"delivery_urgency": URGENCY_UPCOMING, "delivery_due_date": add_days(today(), 14)},
		]
		filtered = filter_by_urgency(items, "week")
		self.assertEqual(len(filtered), 2)
