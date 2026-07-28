# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Smoke tests for the Transportation Console API.

These tests exercise:
- The pure helpers in ``apc_operations.services.console_status`` that
  back the Transportation Console badges.
- The whitelisted endpoint surface (each list/detail/pending-counts
  endpoint is callable and returns the expected shape) on whatever
  data the site currently has.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from apc_operations.services import console_status
from apc_operations.shipping.doctype.job_order.test_job_order import (
	_ensure_supplier,
	make_job_order,
)
from apc_operations.transportation import api as transportation_api


class TestTransportationConsoleStatus(FrappeTestCase):
	"""Pure-Python status mapping for the Transportation Console."""

	def test_docs_status_label(self):
		self.assertEqual(console_status.docs_status_label("Delivered"), "Cleared")
		self.assertEqual(console_status.docs_status_label("Completed"), "Cleared")
		self.assertEqual(console_status.docs_status_label("Scheduled"), "Uncleared")
		self.assertEqual(console_status.docs_status_label(None), "Uncleared")
		self.assertEqual(console_status.docs_status_label("Cancelled"), "Hidden")

	def test_vessel_status_label_defaults_in_transit(self):
		self.assertEqual(console_status.vessel_status_label(None), "In Transit")
		self.assertEqual(console_status.vessel_status_label("Berthed"), "Berthed")

	def test_transport_booking_label(self):
		self.assertEqual(console_status.transport_booking_label("Draft"), "Pending")
		self.assertEqual(
			console_status.transport_booking_label("Pending Assignment"), "Pending"
		)
		self.assertEqual(console_status.transport_booking_label("Scheduled"), "Booked")
		self.assertEqual(
			console_status.transport_booking_label("Vehicle Assigned"), "Booked"
		)

	def test_can_generate_delivery_order_allowlist(self):
		for status in ("Vehicle Assigned", "Driver Assigned", "Scheduled", "Dispatched"):
			self.assertTrue(console_status.can_generate_delivery_order(status), status)
		for status in ("Draft", "Pending Assignment", "Delivered", "Completed", None):
			self.assertFalse(console_status.can_generate_delivery_order(status), status)

	def test_filter_visible_transport_statuses(self):
		rows = [
			{"transport_status": "Scheduled"},
			{"transport_status": "Cancelled"},
			{"transport_status": "Delivered"},
		]
		visible = console_status.filter_visible_transport_statuses(rows)
		self.assertEqual(len(visible), 2)
		self.assertTrue(all(r["transport_status"] != "Cancelled" for r in visible))


class TestTransportationConsoleApi(FrappeTestCase):
	"""Endpoint surface — each list endpoint returns a list."""

	def test_list_endpoints_return_lists(self):
		endpoints = [
			transportation_api.get_inward_import_list,
			transportation_api.get_inward_land_list,
			transportation_api.get_local_delivery_list,
			transportation_api.get_export_container_list,
		]
		for fn in endpoints:
			rows = fn()
			self.assertIsInstance(rows, list, fn.__name__)

	def test_pending_counts_shape(self):
		counts = transportation_api.get_transportation_pending_counts()
		self.assertIsInstance(counts, dict)
		self.assertEqual(set(counts.keys()), {"transport", "do", "sddn"})
		for value in counts.values():
			self.assertIsInstance(value, int)

	def test_active_transport_for_job_order_respects_movement(self):
		imp = make_job_order(
			status="Confirmed",
			commercial_movement="Import",
			customer=None,
			supplier=_ensure_supplier(),
			terms_of_delivery="EXW",
			mode_of_transport="Sea",
		)
		row = transportation_api._active_transport_for_job_order(imp.name)
		self.assertTrue(row)
		self.assertEqual(row.get("transport_type"), "Inward")

		exp = make_job_order(
			status="Confirmed",
			commercial_movement="Outward",
			terms_of_delivery="FOB",
			mode_of_transport="Sea",
		)
		row_o = transportation_api._active_transport_for_job_order(exp.name)
		self.assertTrue(row_o)
		self.assertEqual(row_o.get("transport_type"), "Outward")

	def test_update_inward_import_tracking_on_placeholder_shipping_booking(self):
		imp = make_job_order(
			status="Confirmed",
			commercial_movement="Import",
			customer=None,
			supplier=_ensure_supplier(),
			terms_of_delivery="FOB",
			mode_of_transport="Sea",
		)
		imp.reload()
		self.assertTrue(imp.shipping_booking)

		result = transportation_api.update_inward_import_tracking(
			imp.name,
			vessel_status="Berthed",
			cutoff_date="2026-05-20",
			remarks="Vessel berthed at POD",
		)
		self.assertEqual(result.get("vessel_status_value"), "Berthed")
		self.assertEqual(str(result.get("cutoff_date")), "2026-05-20")

		sb_status = frappe.db.get_value(
			"Shipping Booking", imp.shipping_booking, "vessel_status"
		)
		self.assertEqual(sb_status, "Berthed")
		sb_cutoff = frappe.db.get_value(
			"Shipping Booking", imp.shipping_booking, "cutoff_date"
		)
		self.assertEqual(str(sb_cutoff), "2026-05-20")
		self.assertEqual(
			frappe.db.get_value("Job Order", imp.name, "loading_remarks"),
			"Vessel berthed at POD",
		)
