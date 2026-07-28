# Copyright (c) 2026, APC and contributors

import frappe
from frappe.tests.utils import FrappeTestCase

from apc_operations.shipping.services.zoho_import_receipt_sync_service import (
	push_import_receipt_to_zoho,
)
from apc_operations.shipping.doctype.job_order.test_job_order import (
	_ensure_customer,
	make_job_order,
)
from apc_operations.shipping.services.delivery_order_generation_service import (
	_ensure_apc_customer,
	generate_delivery_order_for_job_order,
)


class TestZohoImportReceiptSync(FrappeTestCase):
	def setUp(self):
		_ensure_apc_customer()
		frappe.db.set_single_value("APC Operations Settings", "zoho_dispatch_sync_enabled", 1)
		frappe.db.set_single_value("APC Operations Settings", "zoho_dispatch_stub_only", 1)

	def test_import_receipt_sync_type_allowed(self):
		jo = make_job_order(
			status="Confirmed",
			commercial_movement="Import",
			customer=None,
			supplier=frappe.db.get_value("Supplier", {}, "name"),
			mode_of_transport="Sea",
		)
		jo.reload()
		ts = frappe.get_doc("Transport Schedule", jo.transport_schedule)
		ts.assigned_vehicle = frappe.db.get_value("Vehicle", {}, "name")
		ts.assigned_driver = frappe.db.get_value("Driver", {}, "name")
		ts.transport_status = "Driver Assigned"
		ts.save(ignore_permissions=True)
		if jo.shipping_booking:
			frappe.db.set_value(
				"Shipping Booking", jo.shipping_booking, "vessel_status", "Cleared"
			)
		result = generate_delivery_order_for_job_order(jo.name, movement="Import")
		do_name = result["delivery_order"]

		resp = push_import_receipt_to_zoho(do_name)
		self.assertTrue(resp.get("success"))

		log = frappe.get_all(
			"Zoho Sync Log",
			filters={
				"apc_document_type": "Delivery Order",
				"apc_document": do_name,
				"sync_type": "Import Receipt",
			},
			fields=["sync_type", "sync_status"],
			limit=1,
		)
		self.assertTrue(log)
		self.assertEqual(log[0].sync_type, "Import Receipt")
