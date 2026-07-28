# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Seed default empty packaging weights from APC product matrix footer."""

import frappe


DEFAULT_TARE = [
	("Steel", 18.5),
	("HDPE", 8.0),
	("IBC", 50.0),
	("Flexi", 120.0),
	("Cartons", 0.0),
	("Bags", 0.0),
]


def execute():
	if not frappe.db.exists("DocType", "APC Packaging Tare"):
		return

	for material, kg in DEFAULT_TARE:
		if frappe.db.exists("APC Packaging Tare", material):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "APC Packaging Tare",
				"packing_material": material,
				"empty_weight_kg": kg,
				"active": 1,
			}
		)
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
