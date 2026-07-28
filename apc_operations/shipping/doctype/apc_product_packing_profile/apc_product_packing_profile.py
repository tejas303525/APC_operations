# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from apc_operations.shipping.services.packing_calculation_service import (
	compute_unit_gross_kg,
	resolve_empty_packaging_kg,
)


class APCProductPackingProfile(Document):
	def validate(self):
		if not flt(self.empty_packaging_kg) and self.packing_material:
			tare = resolve_empty_packaging_kg(self.packing_material)
			if tare > 0:
				self.empty_packaging_kg = tare
		self.unit_gross_kg = compute_unit_gross_kg(
			packing_unit_type=self.packing_unit_type,
			product_fill_kg=self.product_fill_kg,
			ibc_fill_kg=self.ibc_fill_kg,
			flexi_fill_mt=self.flexi_fill_mt,
			empty_packaging_kg=self.empty_packaging_kg,
		)
