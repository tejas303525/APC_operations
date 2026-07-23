# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import today, getdate


class Vehicle(Document):
    def validate(self):
        self.validate_expiry_dates()
        self.update_status_from_expiry()

    def validate_expiry_dates(self):
        if self.insurance_expiry and getdate(self.insurance_expiry) < getdate(today()):
            frappe.msgprint(
                f"Warning: Insurance expired on {self.insurance_expiry}",
                indicator="red"
            )
        if self.registration_expiry and getdate(self.registration_expiry) < getdate(today()):
            frappe.msgprint(
                f"Warning: Registration expired on {self.registration_expiry}",
                indicator="red"
            )

    def update_status_from_expiry(self):
        if self.status == "Active":
            if (self.insurance_expiry and getdate(self.insurance_expiry) < getdate(today())) or \
               (self.registration_expiry and getdate(self.registration_expiry) < getdate(today())):
                frappe.msgprint(
                    "Vehicle status should be updated to Inactive due to expired documents",
                    indicator="orange"
                )
