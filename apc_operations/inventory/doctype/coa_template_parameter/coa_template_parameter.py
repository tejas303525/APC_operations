# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from apc_operations.inventory.qc_spec import optional_spec_float


class COATemplateParameter(Document):
    def validate(self):
        self.min_value = optional_spec_float(self.min_value)
        self.max_value = optional_spec_float(self.max_value)
