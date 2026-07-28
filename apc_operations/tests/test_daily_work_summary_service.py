# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

from frappe.tests.utils import FrappeTestCase

from apc_operations.services.daily_work_summary_service import (
	build_daily_work_summary,
	build_my_work_today,
	format_console_subtitle,
)


class TestDailyWorkSummaryService(FrappeTestCase):
	def test_build_daily_work_summary_all_hubs(self):
		summary = build_daily_work_summary()
		self.assertIn("security", summary)
		self.assertIn("qc", summary)
		self.assertIn("transportation", summary)
		self.assertIn("shipping", summary)
		for hub_data in summary.values():
			self.assertIn("queues", hub_data)
			self.assertIn("totals", hub_data)
			for key in ("overdue", "today", "this_week", "total"):
				self.assertIn(key, hub_data["totals"])

	def test_build_daily_work_summary_single_hub(self):
		summary = build_daily_work_summary("shipping")
		self.assertEqual(summary["hub"], "shipping")
		self.assertIn("pending_bookings", summary["queues"])

	def test_build_daily_work_summary_unknown_hub(self):
		summary = build_daily_work_summary("unknown")
		self.assertEqual(summary["hub"], "unknown")
		self.assertEqual(summary["totals"]["total"], 0)

	def test_format_console_subtitle(self):
		self.assertEqual(
			format_console_subtitle({"overdue": 2, "today": 1}),
			"2 overdue · 1 due today",
		)
		self.assertEqual(
			format_console_subtitle({"this_week": 3}),
			"3 this week",
		)
		self.assertEqual(format_console_subtitle({}), "")

	def test_build_my_work_today_structure(self):
		data = build_my_work_today("urgent")
		self.assertIn("date", data)
		self.assertEqual(data["filter"], "urgent")
		self.assertIn("totals", data)
		self.assertIn("hubs", data)
		for key in ("overdue", "today", "this_week", "total"):
			self.assertIn(key, data["totals"])
		for hub in data["hubs"]:
			self.assertIn("hub", hub)
			self.assertIn("label", hub)
			self.assertIn("console_page", hub)
			self.assertIn("queues", hub)
			for queue in hub["queues"]:
				self.assertGreater(queue.get("urgent_total", 0), 0)

	def test_build_my_work_today_invalid_filter_defaults_to_urgent(self):
		data = build_my_work_today("not-a-filter")
		self.assertEqual(data["filter"], "urgent")
