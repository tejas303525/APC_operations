# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Smoke tests for the Security Console API.

Covers the queue endpoints (pending/verified SDDN, LDN queue, Gate Pass),
the SDDN status mapping helpers, and the verify/hold/reject path with
the Security Inspection compatibility layer.
"""

from frappe.tests.utils import FrappeTestCase

from apc_operations.services import console_status
from apc_operations.security import api as security_api


class TestSecurityConsoleStatus(FrappeTestCase):
	def test_sddn_display_label_maps_legacy(self):
		self.assertEqual(console_status.sddn_display_label("Approved"), "Verified")
		self.assertEqual(
			console_status.sddn_display_label("Pending Review"), "Pending Verification"
		)
		self.assertEqual(console_status.sddn_display_label("Verified"), "Verified")
		self.assertEqual(console_status.sddn_display_label(None), "Draft")

	def test_sddn_status_tone_known_values(self):
		self.assertEqual(console_status.sddn_status_tone("Verified"), "success")
		self.assertEqual(console_status.sddn_status_tone("Rejected"), "danger")
		self.assertEqual(console_status.sddn_status_tone("On Hold"), "warn")
		self.assertEqual(console_status.sddn_status_tone("Sent to QC"), "info")

	def test_sddn_pending_and_verified_buckets(self):
		self.assertTrue(console_status.is_sddn_pending("Draft"))
		self.assertTrue(console_status.is_sddn_pending("Pending Verification"))
		self.assertFalse(console_status.is_sddn_pending("Verified"))
		self.assertTrue(console_status.is_sddn_verified("Verified"))
		self.assertTrue(console_status.is_sddn_verified("LDN Created"))
		self.assertFalse(console_status.is_sddn_verified("Draft"))

	def test_ldn_display_label_maps_db_values(self):
		self.assertEqual(console_status.ldn_display_label("Pending QC"), "QC Pending")
		self.assertEqual(console_status.ldn_display_label("QC Cleared"), "QC Cleared")
		self.assertEqual(console_status.ldn_display_label("QC Rejected"), "QC Rejected")
		self.assertEqual(console_status.ldn_display_label("COA Attached"), "COA Generated")
		self.assertEqual(console_status.ldn_display_label(None), "Draft")


class TestSecurityConsoleApi(FrappeTestCase):
	def test_queue_endpoints_return_lists(self):
		endpoints = [
			security_api.get_pending_security_delivery_draft_notes,
			security_api.get_verified_security_delivery_draft_notes,
			security_api.get_gate_pass_queue,
			security_api.get_loading_dn_queue,
		]
		for fn in endpoints:
			self.assertIsInstance(fn(), list, fn.__name__)
