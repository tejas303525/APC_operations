# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""Default all existing Job Orders to Export commercial movement."""
	if not frappe.db.has_column("Job Order", "commercial_movement"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabJob Order`
		SET commercial_movement = 'Export'
		WHERE IFNULL(commercial_movement, '') = ''
		"""
	)
