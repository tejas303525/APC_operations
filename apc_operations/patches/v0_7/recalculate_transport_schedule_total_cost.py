# Copyright (c) 2026, APC and contributors
"""Recalculate Transport Schedule total_cost (fix string-concatenated values)."""

import frappe
from frappe.utils import flt


def execute():
	for row in frappe.get_all(
		"Transport Schedule",
		filters={"docstatus": ["!=", 2]},
		fields=["name", "transport_charges", "fuel_cost", "additional_charges", "total_cost"],
	):
		expected = (
			flt(row.transport_charges) + flt(row.fuel_cost) + flt(row.additional_charges)
		)
		if flt(row.total_cost) != expected:
			frappe.db.set_value(
				"Transport Schedule",
				row.name,
				"total_cost",
				expected,
				update_modified=False,
			)
