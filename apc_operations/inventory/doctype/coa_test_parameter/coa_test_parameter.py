# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from apc_operations.inventory.qc_spec import optional_spec_float


class COATestParameter(Document):
    def validate(self):
        self.default_min_value = optional_spec_float(self.default_min_value)
        self.default_max_value = optional_spec_float(self.default_max_value)

        if self.default_min_value is not None and self.default_max_value is not None:
            if self.default_min_value > self.default_max_value:
                frappe.throw(_("Default Min Value cannot be greater than Default Max Value"))
