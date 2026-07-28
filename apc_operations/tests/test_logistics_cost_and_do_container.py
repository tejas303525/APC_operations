# Copyright (c) 2026, APC and contributors

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from apc_operations.shipping.services.delivery_order_print_service import (
	_resolve_container_fields,
	_resolve_shipping_booking_name,
)
from apc_operations.shipping.services.logistics_cost_service import get_logistics_cost_summary
class TestTransportScheduleTotalCost(FrappeTestCase):
	def test_calculate_total_cost_uses_numeric_sum(self):
		doc = frappe.get_doc({"doctype": "Transport Schedule"})
		doc.transport_charges = "100"
		doc.fuel_cost = "100"
		doc.additional_charges = "100"
		doc.calculate_total_cost()
		self.assertEqual(flt(doc.total_cost), 300.0)


class TestLogisticsCostSummaryTransportTotal(FrappeTestCase):
	def test_transport_row_total_is_sum_not_concatenated(self):
		jo = frappe.db.get_value("Job Order", {}, "name")
		if not jo:
			self.skipTest("No Job Order on site")
		summary = get_logistics_cost_summary(jo)
		for ts in summary.get("transport_schedules") or []:
			expected = (
				flt(ts.get("transport_charges"))
				+ flt(ts.get("fuel_cost"))
				+ flt(ts.get("additional_charges"))
			)
			self.assertEqual(flt(ts.get("total_cost")), expected)


class TestDeliveryOrderContainerResolution(FrappeTestCase):
	def test_resolve_container_from_shipping_booking(self):
		sb = frappe.db.get_value("Shipping Booking", {}, "name")
		if not sb:
			self.skipTest("No Shipping Booking on site")
		frappe.db.set_value(
			"Shipping Booking",
			sb,
			{"container_number": "TESTU1234567", "container_type": "20FT Standard"},
			update_modified=False,
		)
		jo = frappe.db.get_value("Shipping Booking", sb, "job_order")
		ts = frappe.db.get_value(
			"Transport Schedule", {"shipping_booking": sb}, "name"
		)
		number, ctype = _resolve_container_fields(None, ts, jo)
		self.assertEqual(number, "TESTU1234567")
		self.assertEqual(ctype, "20FT Standard")
		frappe.db.set_value(
			"Shipping Booking", sb, "container_number", None, update_modified=False
		)

	def test_legacy_si_type_in_number_field_uses_booking(self):
		sb = frappe.db.get_value("Shipping Booking", {}, "name")
		if not sb:
			self.skipTest("No Shipping Booking on site")
		frappe.db.set_value(
			"Shipping Booking",
			sb,
			{"container_number": "MSCU9999999", "container_type": "40FT Standard"},
			update_modified=False,
		)
		jo = frappe.db.get_value("Shipping Booking", sb, "job_order")
		ts = frappe.db.get_value(
			"Transport Schedule", {"shipping_booking": sb}, "name"
		)
		si = {
			"container_number": "40FT Standard",
			"container_type": "40FT Standard",
		}
		number, ctype = _resolve_container_fields(si, ts, jo)
		self.assertEqual(number, "MSCU9999999")
		self.assertEqual(ctype, "40FT Standard")
		frappe.db.set_value(
			"Shipping Booking", sb, "container_number", None, update_modified=False
		)

	def test_resolve_shipping_booking_from_job_order(self):
		sb = frappe.db.get_value(
			"Shipping Booking", {"job_order": ["is", "set"]}, "name"
		)
		if not sb:
			self.skipTest("No Shipping Booking with Job Order")
		jo = frappe.db.get_value("Shipping Booking", sb, "job_order")
		self.assertEqual(_resolve_shipping_booking_name(jo, None), sb)
