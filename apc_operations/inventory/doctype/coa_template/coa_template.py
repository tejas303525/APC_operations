# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from apc_operations.inventory.qc_spec import optional_spec_float


class COATemplate(Document):
    def validate(self):
        self.validate_unique_parameters()
        self.apply_parameter_defaults()

    def validate_unique_parameters(self):
        seen = set()
        for row in self.parameters:
            if not row.parameter:
                continue
            if row.parameter in seen:
                frappe.throw(_("Parameter {0} is duplicated in this template").format(row.parameter))
            seen.add(row.parameter)

    def apply_parameter_defaults(self):
        for idx, row in enumerate(self.parameters, start=1):
            if not row.parameter:
                continue

            parameter = frappe.get_cached_doc("COA Test Parameter", row.parameter)
            row.parameter_name = parameter.parameter_name
            row.uom = row.uom or parameter.uom
            row.value_type = row.value_type or parameter.value_type
            row.min_value = optional_spec_float(row.min_value)
            if row.min_value is None:
                row.min_value = optional_spec_float(parameter.default_min_value)

            row.max_value = optional_spec_float(row.max_value)
            if row.max_value is None:
                row.max_value = optional_spec_float(parameter.default_max_value)

            row.standard_value = row.standard_value or parameter.default_standard_value
            row.mandatory = row.mandatory or parameter.mandatory_by_default
            row.sequence = row.sequence or idx

            min_v = optional_spec_float(row.min_value)
            max_v = optional_spec_float(row.max_value)
            if min_v is not None and max_v is not None and min_v > max_v:
                frappe.throw(_("Min Value cannot be greater than Max Value for {0}").format(row.parameter_name))
