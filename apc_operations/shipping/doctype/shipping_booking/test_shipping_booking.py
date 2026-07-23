# Copyright (c) 2026, APC and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from apc_operations.shipping.doctype.job_order.test_job_order import (
	_ensure_supplier,
	make_job_order,
)


class TestShippingBooking(FrappeTestCase):
	def test_generate_transportation_import_creates_inward_ts(self):
		jo = make_job_order(
			commercial_movement="Import",
			customer=None,
			supplier=_ensure_supplier(),
			terms_of_delivery="EXW",
			mode_of_transport="Sea",
			status="Draft",
		)
		sb = frappe.new_doc("Shipping Booking")
		sb.job_order = jo.name
		sb.supplier = jo.supplier
		sb.job_order_number = jo.job_order_number or jo.name
		sb.port_of_loading = jo.port_of_loading
		sb.port_of_discharge = jo.port_of_discharge
		sb.cargo_description = "Test import cargo"
		sb.insert(ignore_permissions=True, ignore_mandatory=True)
		sb.cro_number = "CRO-TEST-IMPORT-001"
		sb.generate_transportation()
		linked = frappe.get_all(
			"Transport Schedule",
			filters={"shipping_booking": sb.name},
			pluck="name",
		)
		self.assertTrue(linked)
		ts = frappe.get_doc("Transport Schedule", linked[0])
		self.assertEqual(ts.transport_type, "Inward")
		self.assertNotEqual(ts.transport_type, "Outward")

	def test_import_tracking_booking_save_without_export_fields(self):
		jo = make_job_order(
			commercial_movement="Import",
			customer=None,
			supplier=_ensure_supplier(),
			terms_of_delivery="FOB",
			mode_of_transport="Sea",
		)
		sb = frappe.new_doc("Shipping Booking")
		sb.job_order = jo.name
		sb.supplier = jo.supplier
		sb.booking_status = "Tracking"
		sb.vessel_status = "In Transit"
		sb.insert(ignore_permissions=True, ignore_mandatory=True)
		sb.vessel_status = "Berthed"
		sb.save()
		sb.reload()
		self.assertEqual(sb.vessel_status, "Berthed")
