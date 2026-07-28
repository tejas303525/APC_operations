# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from apc_operations.shipping.services.packing_calculation_service import (
	apply_packing_fields,
	compute_unit_gross_kg,
	expected_packaging_qty,
	infer_packing_unit_type,
	normalize_packing_material,
	product_fill_kg_for_profile,
)


class TestPackingCalculationService(FrappeTestCase):
	def test_normalize_packing_material(self):
		self.assertEqual(normalize_packing_material("STEEL"), "Steel")
		self.assertEqual(normalize_packing_material("hdpe drum"), "HDPE")

	def test_infer_packing_unit_type(self):
		self.assertEqual(infer_packing_unit_type(packaging_type="Steel Drums"), "Drum")
		self.assertEqual(infer_packing_unit_type(packaging_type="IBC"), "IBC")
		self.assertEqual(infer_packing_unit_type(packaging_type="Flexi Bag"), "Flexi")

	def test_unit_gross_kg_drum(self):
		gross = compute_unit_gross_kg(
			packing_unit_type="Drum",
			product_fill_kg=185,
			empty_packaging_kg=18.5,
		)
		self.assertEqual(gross, 203.5)

	def test_expected_packaging_qty_ceil(self):
		profile = {
			"packing_unit_type": "Drum",
			"product_fill_kg": 185,
		}
		qty = expected_packaging_qty(quantity=14.8, uom="MT", profile=profile)
		self.assertEqual(qty, 80)

	def test_apply_packing_fields_without_profile(self):
		row = {
			"item": "_Test Item",
			"quantity": 10,
			"uom": "MT",
			"packaging_type": "Steel",
		}
		if not frappe.db.exists("Item", "_Test Item"):
			self.skipTest("Test item not available")
		apply_packing_fields(row)
		self.assertEqual(flt(row.get("planned_product_kg")), 10000.0)
		self.assertEqual(flt(row.get("net_weight")), 10000.0)

	def test_product_fill_ibc(self):
		profile = {"packing_unit_type": "IBC", "ibc_fill_kg": 850, "product_fill_kg": 185}
		self.assertEqual(product_fill_kg_for_profile(profile), 850.0)
