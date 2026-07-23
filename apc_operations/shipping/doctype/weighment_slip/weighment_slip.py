# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _


class WeighmentSlip(Document):
    def validate(self):
        self.calculate_net_weight()

    def calculate_net_weight(self):
        if self.gross_weight and self.tare_weight:
            self.net_weight = self.gross_weight - self.tare_weight

    def on_submit(self):
        if self.security_inspection:
            frappe.db.set_value(
                "Security Inspection",
                self.security_inspection,
                {
                    "weighment_slip": self.name,
                    "gross_weight": self.gross_weight,
                    "tare_weight": self.tare_weight,
                    "net_weight": self.net_weight
                },
                update_modified=False
            )
