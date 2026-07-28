# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

from frappe.tests.utils import FrappeTestCase
import frappe

from apc_operations.shipping.services.delivery_order_print_service import get_print_context


class TestDeliveryOrderPrintService(FrappeTestCase):
	def test_get_print_context_returns_transport_keys(self):
		do_name = frappe.db.get_value("Delivery Order", {}, "name")
		if not do_name:
			self.skipTest("No Delivery Order on site")
		ctx = get_print_context(do_name)
		for key in (
			"driver_name",
			"driver_phone",
			"vehicle",
			"payment_terms",
			"job_order_date",
			"planned_qty_display",
			"delivery_date",
			"item_lines",
			"buyer_name",
			"buyer_address",
		):
			self.assertIn(key, ctx)
		self.assertIsInstance(ctx["item_lines"], list)
