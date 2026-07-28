# Copyright (c) 2026, APC and contributors

import frappe
from frappe.tests.utils import FrappeTestCase

from apc_operations.shipping.services.logistics_cost_service import get_logistics_cost_summary


class TestLogisticsCostService(FrappeTestCase):
	def test_summary_returns_structure_for_existing_job_order(self):
		name = frappe.db.get_value("Job Order", {}, "name")
		if not name:
			self.skipTest("No Job Order in database")

		summary = get_logistics_cost_summary(name)
		self.assertIn("job_order", summary)
		self.assertIn("shipping_bookings", summary)
		self.assertIn("transport_schedules", summary)
		self.assertIn("totals_by_currency", summary)
