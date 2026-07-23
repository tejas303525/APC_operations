# Copyright (c) 2026, APC and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from apc_operations.shipping.doctype.job_order.test_job_order import make_job_order


class TestTransportSchedule(FrappeTestCase):
    def test_transport_status_syncs_to_job_order(self):
        job_order = make_job_order(status="Confirmed", terms_of_delivery="EXW", mode_of_transport="Road")
        transport = frappe.get_doc("Transport Schedule", job_order.transport_schedule)

        transport.transport_status = "Dispatched"
        transport.save()

        self.assertEqual(frappe.db.get_value("Job Order", job_order.name, "transport_status"), "In Progress")
        self.assertEqual(frappe.db.get_value("Job Order", job_order.name, "status"), "In Progress")
