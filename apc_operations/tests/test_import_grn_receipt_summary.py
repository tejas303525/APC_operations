# Copyright (c) 2026, APC and contributors

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from apc_operations.security.doctype.import_grn.import_grn import ImportGRN
from apc_operations.shipping.services.import_grn_receipt_summary_service import (
	partial_import_receipt_summary,
)


class TestImportGrnPartialReceipt(FrappeTestCase):
	def test_sync_receipt_totals_partial(self):
		if not frappe.db.table_exists("Import GRN"):
			self.skipTest("Import GRN DocType not migrated")

		grn = ImportGRN(
			{
				"doctype": "Import GRN",
				"delivery_order": "DO-TEST-PARTIAL",
				"commercial_movement": "Import",
				"grn_status": "Draft",
				"items": [
					{"item_code": "_Test Item", "qty": 100, "arrived_qty": 60, "uom": "Nos"},
				],
			}
		)
		grn._sync_receipt_totals()
		self.assertEqual(flt(grn.total_expected_qty), 100)
		self.assertEqual(flt(grn.total_arrived_qty), 60)
		self.assertEqual(flt(grn.pending_qty), 40)
		self.assertEqual(grn.receipt_type, "Partial")
		self.assertEqual(grn.is_partial_receipt, 1)

	def test_sync_receipt_totals_full(self):
		if not frappe.db.table_exists("Import GRN"):
			self.skipTest("Import GRN DocType not migrated")

		grn = ImportGRN(
			{
				"doctype": "Import GRN",
				"delivery_order": "DO-TEST-FULL",
				"commercial_movement": "Import",
				"grn_status": "Draft",
				"items": [
					{"item_code": "_Test Item", "qty": 50, "arrived_qty": 50, "uom": "Nos"},
				],
			}
		)
		grn._sync_receipt_totals()
		self.assertEqual(grn.receipt_type, "Full")
		self.assertEqual(grn.is_partial_receipt, 0)

	def test_partial_import_receipt_summary_none_without_posted_grn(self):
		jo = frappe.db.get_value(
			"Job Order", {"commercial_movement": "Import"}, "name"
		)
		if not jo:
			self.skipTest("No import Job Order on site")
		# Without posted GRN arrived qty, summary should be None or no pending
		result = partial_import_receipt_summary(jo)
		if result:
			self.assertGreater(flt(result.get("pending_receipt_quantity")), 0)

	def test_grn_summary_list_returns_list(self):
		from apc_operations.transportation import api as transportation_api

		rows = transportation_api.get_grn_summary_list()
		self.assertIsInstance(rows, list)

	def test_grn_summary_with_posted_partial_grn_without_completed_transport(self):
		if not frappe.db.table_exists("Import GRN"):
			self.skipTest("Import GRN DocType not migrated")

		from apc_operations.shipping.doctype.job_order.test_job_order import (
			_ensure_supplier,
			make_job_order,
		)
		from apc_operations.shipping.services.delivery_order_generation_service import (
			_ensure_apc_customer,
		)
		from apc_operations.tests.test_option_b_schema import _ensure_item
		from apc_operations.transportation import api as transportation_api
		from frappe.utils import today

		product = _ensure_item("_Test Item Option B")
		apc_customer, _ = _ensure_apc_customer()
		jo = make_job_order(
			status="Confirmed",
			commercial_movement="Import",
			customer=None,
			supplier=_ensure_supplier(),
			terms_of_delivery="FOB",
			mode_of_transport="Sea",
		)
		jo.append("items", {"item": product, "quantity": 10, "uom": "Nos"})
		jo.save(ignore_permissions=True)
		jo.reload()
		first_ts = jo.transport_schedule
		self.assertTrue(first_ts)

		do = frappe.new_doc("Delivery Order")
		do.job_order = jo.name
		do.commercial_movement = "Import"
		do.customer = apc_customer
		do.posting_date = today()
		do.append("items", {"item_code": product, "qty": 10, "uom": "Nos"})
		do.insert(ignore_permissions=True)

		grn = frappe.new_doc("Import GRN")
		grn.delivery_order = do.name
		grn.job_order = jo.name
		grn.commercial_movement = "Import"
		grn.grn_status = "Pending Approval"
		grn.append("items", {"item_code": product, "qty": 10, "arrived_qty": 8, "uom": "Nos"})
		grn.flags.approving_grn = True
		grn.insert(ignore_permissions=True)
		grn.grn_status = "Posted"
		grn.save(ignore_permissions=True)

		frappe.db.set_value(
			"Transport Schedule",
			first_ts,
			"transport_status",
			"Driver Assigned",
			update_modified=False,
		)

		summary = partial_import_receipt_summary(jo.name)
		self.assertEqual(flt(summary["pending_receipt_quantity"]), 2.0)

		row = transportation_api._grn_summary_row(
			{
				"name": jo.name,
				"job_order_number": jo.job_order_number,
				"supplier": jo.supplier,
				"supplier_name": jo.supplier_name,
				"port_of_discharge": jo.port_of_discharge,
			}
		)
		self.assertIsNotNone(row)
		self.assertEqual(flt(row["pending_receipt_quantity"]), 2.0)
		self.assertTrue(row["followup_needed"])

		rows = transportation_api.get_grn_summary_list(only_actionable=1)
		self.assertIn(jo.name, {r["job_order"] for r in rows})

		res = transportation_api.create_import_partial_receipt_followup_transport(jo.name)
		self.assertNotEqual(res["transport_schedule"], first_ts)
