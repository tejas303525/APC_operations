# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""QC Console queue filters after pre-check pass."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from apc_operations.services.delivery_order_service import (
	do_awaiting_qc_precheck,
	do_qc_precheck_passed_pending_followup,
)


class TestQcConsoleQueueHelpers(FrappeTestCase):
	def test_awaiting_precheck_when_qc_not_passed(self):
		card = {"delivery_order": "DO-TEST-1", "name": "DO-TEST-1"}
		with patch(
			"apc_operations.services.delivery_order_service._pcc_for_do",
			return_value={"qc_status": "Pending", "qc_pre_check_status": "Pending"},
		):
			self.assertTrue(do_awaiting_qc_precheck(card))

	def test_not_awaiting_when_qc_passed(self):
		card = {"delivery_order": "DO-TEST-1", "name": "DO-TEST-1"}
		with patch(
			"apc_operations.services.delivery_order_service._pcc_for_do",
			return_value={"qc_status": "Passed", "overall_status": "Pending"},
		):
			self.assertFalse(do_awaiting_qc_precheck(card))
			self.assertTrue(do_qc_precheck_passed_pending_followup(card))

	def test_pending_followup_import_without_export_jo(self):
		card = {
			"delivery_order": "DO-TEST-2",
			"name": "DO-TEST-2",
			"commercial_movement": "Import",
			"job_order": "JO-TEST-1",
		}
		with patch(
			"apc_operations.services.delivery_order_service._pcc_for_do",
			return_value={
				"qc_status": "Passed",
				"overall_status": "Authorized",
			},
		):
			with patch.object(frappe.db, "get_value", return_value=None):
				self.assertTrue(do_qc_precheck_passed_pending_followup(card))
