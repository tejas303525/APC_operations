# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Smoke tests for the QC Console API.

Covers:
- List endpoints (new / pending / completed / rejected) return lists.
- Status mapping helpers (QC + COA).
- ``create_apc_coa_from_qc`` idempotency contract: if the QC Report
  Request has no batch, the helper returns ``None`` without raising.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from apc_operations.inventory.doctype.apc_coa.apc_coa import create_apc_coa_from_qc
from apc_operations.quality import api as quality_api
from apc_operations.services import console_status


class TestQcConsoleStatus(FrappeTestCase):
	def test_qc_status_label_and_tone(self):
		self.assertEqual(console_status.qc_status_label(None), "Pending QC")
		self.assertEqual(console_status.qc_status_label("QC Cleared"), "QC Cleared")
		self.assertEqual(console_status.qc_status_tone("Pending QC"), "warn")
		self.assertEqual(console_status.qc_status_tone("QC Cleared"), "success")
		self.assertEqual(console_status.qc_status_tone("QC Rejected"), "danger")

	def test_coa_display_label(self):
		self.assertEqual(console_status.coa_display_label(None), "Pending")
		self.assertEqual(
			console_status.coa_display_label({"status": "Approved", "coa_pdf": "/file.pdf"}),
			"Uploaded",
		)
		self.assertEqual(
			console_status.coa_display_label({"status": "Approved", "coa_pdf": None}),
			"Generated",
		)


class TestQcConsoleApi(FrappeTestCase):
	def test_list_endpoints_return_lists(self):
		for fn in (
			quality_api.get_new_qc_items,
			quality_api.get_pending_qc_items,
			quality_api.get_completed_qc_items,
			quality_api.get_rejected_qc_items,
			quality_api.get_new_dos_without_qc,
			quality_api.get_pending_qc_dos,
			quality_api.get_completed_qc_dos,
			quality_api.get_rejected_qc_dos,
		):
			self.assertIsInstance(fn(), list, fn.__name__)

	def test_qc_console_counts(self):
		counts = quality_api.get_qc_console_counts()
		for key in ("new", "pending", "completed", "rejected"):
			self.assertIn(key, counts)


class TestCreateApcCoaFromQc(FrappeTestCase):
	def test_returns_none_when_qcr_missing(self):
		self.assertIsNone(create_apc_coa_from_qc(None))

	def test_returns_none_when_no_batch_linked(self):
		# Find a QC Report Request with no batch; if none exists, skip.
		qcr_name = frappe.db.get_value(
			"QC Report Request", {"batch": ["in", ["", None]]}, "name"
		)
		if not qcr_name:
			self.skipTest("No QC Report Request without a batch is available")
		self.assertIsNone(create_apc_coa_from_qc(qcr_name))
