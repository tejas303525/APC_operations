# Copyright (c) 2026, APC and contributors

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from apc_operations.shipping.services.import_grn_service import (
	_PENDING_GRN_STATUSES,
	_grn_status_tone,
	approve_import_grn,
)


class TestImportGrnBackfill(FrappeTestCase):
	def test_backfill_returns_structure(self):
		if not frappe.db.table_exists("Import GRN"):
			self.skipTest("Import GRN DocType not migrated")
		from apc_operations.shipping.services.import_grn_service import (
			backfill_missing_import_grns,
		)

		result = backfill_missing_import_grns(limit=10)
		self.assertIn("created", result)
		self.assertIn("errors", result)
		self.assertIn("count", result)

	def test_grn_status_tone(self):
		self.assertEqual(_grn_status_tone("Posted"), "success")
		self.assertEqual(_grn_status_tone("Pending Approval"), "warn")

	def test_approve_requires_pending_status(self):
		if not frappe.db.table_exists("Import GRN"):
			self.skipTest("Import GRN DocType not migrated")

		grn_name = frappe.db.get_value(
			"Import GRN", {"grn_status": ["in", list(_PENDING_GRN_STATUSES)]}, "name"
		)
		if not grn_name:
			self.skipTest("No pending Import GRN on site")

		with patch(
			"apc_operations.shipping.services.import_grn_service._post_zoho_receipt",
			return_value={"success": True, "zoho_receipt_id": "STUB-TEST", "stub": True},
		):
			result = approve_import_grn(grn_name)
		self.assertTrue(result.get("success"))
		self.assertIn(
			frappe.db.get_value("Import GRN", grn_name, "grn_status"),
			("Approved", "Posted"),
		)
