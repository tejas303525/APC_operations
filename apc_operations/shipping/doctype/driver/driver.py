# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import today, getdate


class Driver(Document):
    def validate(self):
        self.validate_license_expiry()
        self.validate_status()

    def validate_license_expiry(self):
        if self.license_expiry and getdate(self.license_expiry) < getdate(today()):
            frappe.msgprint(
                f"Warning: Driver license expired on {self.license_expiry}",
                indicator="red"
            )

    def validate_status(self):
        if self.status == "Active":
            if self.license_expiry and getdate(self.license_expiry) < getdate(today()):
                frappe.msgprint(
                    "Driver status should be updated as license has expired",
                    indicator="orange"
                )

@frappe.whitelist()
def get_active_drivers():
    meta = frappe.get_meta("Driver")
    name_field = "full_name" if meta.has_field("full_name") else "driver_name"
    return frappe.get_all(
        "Driver",
        filters={"status": "Active"},
        fields=["name", name_field, "phone", "cell_number", "license_number"],
        order_by=f"{name_field} asc"
    )
