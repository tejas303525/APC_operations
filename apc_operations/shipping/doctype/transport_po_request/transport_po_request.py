# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class TransportPORequest(Document):
    def validate(self):
        self.validate_unique_transport_schedule()

    def validate_unique_transport_schedule(self):
        if not self.transport_schedule:
            return

        existing = frappe.db.exists(
            "Transport PO Request",
            {
                "transport_schedule": self.transport_schedule,
                "name": ["!=", self.name],
            },
        )
        if existing:
            frappe.throw(
                _("Transport PO Request {0} already exists for Transport Schedule {1}").format(
                    existing, self.transport_schedule
                )
            )

    def on_update(self):
        self.sync_status_to_transport()

    def sync_status_to_transport(self):
        if not self.transport_schedule:
            return

        frappe.db.set_value(
            "Transport Schedule",
            self.transport_schedule,
            {
                "transport_po_request": self.name,
                "payables_status": self.payables_status
                if self.payables_status != "Draft"
                else "Pending Payables",
            },
            update_modified=False,
        )
