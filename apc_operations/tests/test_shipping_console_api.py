# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Smoke tests for the Shipping Console API.

Covers list endpoints, detail endpoints (when data is present), and the
``generate_delivery_order_for_export`` guard (Section 7.7 narrow
allowlist).
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from apc_operations.services import console_status
from apc_operations.shipping.api import (
	generate_delivery_order_for_export,
	get_open_cro_schedule,
	get_pending_bookings,
	get_pending_cros,
)


class TestShippingConsoleApi(FrappeTestCase):
	def test_pending_bookings_returns_list(self):
		self.assertIsInstance(get_pending_bookings(), list)

	def test_pending_cros_returns_list(self):
		self.assertIsInstance(get_pending_cros(), list)

	def test_open_cro_schedule_returns_list(self):
		self.assertIsInstance(get_open_cro_schedule(), list)

	def test_generate_do_rejects_invalid_transport_status(self):
		"""Section 7.7: DO generation only allowed for the narrow allowlist."""
		# Find any Job Order with an active Transport Schedule whose status
		# is NOT in the allowlist. If none exists, skip.
		ts = frappe.get_all(
			"Transport Schedule",
			filters={"transport_status": ["not in", list(console_status.DO_GENERATION_ALLOWED_TRANSPORT_STATUSES) + ["Cancelled"]]},
			fields=["job_order", "transport_status"],
			limit=1,
		)
		if not ts or not ts[0].get("job_order"):
			self.skipTest("No Transport Schedule outside the allowlist available")
		with self.assertRaises(frappe.exceptions.ValidationError):
			generate_delivery_order_for_export(job_order=ts[0]["job_order"])


class TestShippingConsoleStatus(FrappeTestCase):
	def test_vessel_status_tone(self):
		self.assertEqual(console_status.vessel_status_tone("In Transit"), "info")
		self.assertEqual(console_status.vessel_status_tone("Berthed"), "warn")
		self.assertEqual(console_status.vessel_status_tone("Cleared"), "success")

	def test_do_display_label(self):
		self.assertEqual(console_status.do_display_label(None), "Pending")
		self.assertEqual(
			console_status.do_display_label({"status": "Submitted", "docstatus": 1}), "Generated"
		)
		self.assertEqual(
			console_status.do_display_label({"status": "Delivered", "docstatus": 1}), "Completed"
		)
		self.assertEqual(
			console_status.do_display_label({"status": "Draft", "docstatus": 2}), "Cancelled"
		)
