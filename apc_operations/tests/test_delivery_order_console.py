# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from apc_operations.quality import api as quality_api
from apc_operations.security import api as security_api
from apc_operations.services.delivery_order_service import (
	compute_operational_status,
	find_delivery_order_for_job_order_primary,
	get_security_console_counts,
	operational_status_tone,
)
class TestDeliveryOrderOperationalStatus(FrappeTestCase):
	def test_compute_pending_security(self):
		self.assertEqual(
			compute_operational_status("DO-TEST", sddn_status=None, shipping_status="Draft"),
			"Pending Security",
		)

	def test_compute_security_in_progress(self):
		self.assertEqual(
			compute_operational_status("DO-TEST", sddn_status="Pending Verification"),
			"Security In Progress",
		)

	def test_compute_sent_to_qc(self):
		self.assertEqual(
			compute_operational_status(
				"DO-TEST",
				sddn_status="Sent to QC",
				ldn_status="Pending QC",
				ldn_qc_status="Pending QC",
			),
			"Sent to QC",
		)

	def test_compute_qc_cleared(self):
		self.assertEqual(
			compute_operational_status(
				"DO-TEST",
				ldn_qc_status="QC Cleared",
				ldn_status="QC Cleared",
			),
			"QC Cleared",
		)

	def test_operational_status_tone(self):
		self.assertEqual(operational_status_tone("Completed"), "success")
		self.assertEqual(operational_status_tone("Security In Progress"), "warn")


class TestDeliveryOrderConsoleApi(FrappeTestCase):
	def test_security_do_list_endpoints_return_lists(self):
		if not frappe.db.has_column("Delivery Order", "job_order"):
			self.skipTest("Delivery Order operational fields not migrated")
		for fn in (
			security_api.get_security_new_dos,
			security_api.get_security_pending_dos,
			security_api.get_security_in_progress_dos,
			security_api.get_security_completed_dos,
		):
			self.assertIsInstance(fn(), list, fn.__name__)

	def test_security_console_counts(self):
		if not frappe.db.has_column("Delivery Order", "job_order"):
			self.skipTest("Delivery Order operational fields not migrated")
		counts = get_security_console_counts()
		for key in ("new", "pending", "in_progress", "completed"):
			self.assertIn(key, counts)
			self.assertIsInstance(counts[key], int)

	def test_qc_do_aliases_return_lists(self):
		for fn in (
			quality_api.get_new_dos_without_qc,
			quality_api.get_pending_qc_dos,
			quality_api.get_completed_qc_dos,
			quality_api.get_rejected_qc_dos,
		):
			self.assertIsInstance(fn(), list, fn.__name__)

	def test_find_do_primary_without_column(self):
		# Should not raise when column missing (returns None or legacy match).
		result = find_delivery_order_for_job_order_primary("_nonexistent_jo_test_")
		self.assertTrue(result is None or isinstance(result, str))
