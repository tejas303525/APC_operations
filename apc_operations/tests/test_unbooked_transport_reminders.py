# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now

from apc_operations.shipping.reminders import (
	check_unbooked_transport_over_24h,
	get_unbooked_transport_job_orders,
)


class TestUnbookedTransportReminders(FrappeTestCase):
	def test_get_unbooked_transport_job_orders_excludes_recent(self):
		if not frappe.db.exists("Customer", "_Test Unbooked Transport Customer"):
			cust = frappe.new_doc("Customer")
			cust.customer_name = "_Test Unbooked Transport Customer"
			cust.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
			cust.territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
			cust.insert(ignore_permissions=True)

		jo = frappe.new_doc("Job Order")
		jo.customer = "_Test Unbooked Transport Customer"
		jo.date = frappe.utils.today()
		jo.status = "Confirmed"
		jo.commercial_movement = "Export"
		jo.terms_of_delivery = "FOB"
		jo.transport_required = 1
		jo.insert(ignore_permissions=True)
		frappe.db.set_value(
			"Job Order",
			jo.name,
			{
				"transport_schedule": None,
				"transport_status": "Pending Booking",
				"booking_requirement": "Transport Booking",
				"transport_required": 1,
			},
			update_modified=False,
		)

		all_unbooked = get_unbooked_transport_job_orders(limit=100)
		self.assertTrue(any(row.name == jo.name for row in all_unbooked))

		over_24h = get_unbooked_transport_job_orders(limit=100, unbooked_for_hours=24)
		self.assertFalse(any(row.name == jo.name for row in over_24h))

		frappe.db.set_value(
			"Job Order",
			jo.name,
			"modified",
			add_to_date(now(), hours=-25),
			update_modified=False,
		)

		over_24h = get_unbooked_transport_job_orders(limit=100, unbooked_for_hours=24)
		self.assertTrue(any(row.name == jo.name for row in over_24h))

	def test_check_unbooked_transport_over_24h_runs_without_error(self):
		check_unbooked_transport_over_24h()
