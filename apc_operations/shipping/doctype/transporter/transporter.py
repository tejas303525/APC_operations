# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import today, getdate


class Transporter(Document):
    def validate(self):
        self.validate_expiry_dates()
        self.update_vehicle_driver_counts()

    def validate_expiry_dates(self):
        if self.insurance_expiry and getdate(self.insurance_expiry) < getdate(today()):
            frappe.msgprint(
                f"Warning: Insurance expired on {self.insurance_expiry}",
                indicator="red"
            )
        if self.license_expiry and getdate(self.license_expiry) < getdate(today()):
            frappe.msgprint(
                f"Warning: Operating license expired on {self.license_expiry}",
                indicator="red"
            )
        if self.contract_expiry and getdate(self.contract_expiry) < getdate(today()):
            frappe.msgprint(
                f"Warning: Contract expired on {self.contract_expiry}",
                indicator="red"
            )

    def update_vehicle_driver_counts(self):
        if self.name:
            self.vehicle_count = frappe.db.count("Vehicle", {"transporter": self.name})
            self.driver_count = frappe.db.count("Driver", {"transporter": self.name})
