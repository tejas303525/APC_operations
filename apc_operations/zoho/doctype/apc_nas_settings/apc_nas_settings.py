# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class APCNASSettings(Document):
    def validate(self):
        if self.enabled and not self.nas_base_path:
            frappe.throw("NAS base path is required when NAS is enabled.")
