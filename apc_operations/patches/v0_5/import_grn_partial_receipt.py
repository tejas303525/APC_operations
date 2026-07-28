# Copyright (c) 2026, APC and contributors

import frappe


def execute():
	if not frappe.db.table_exists("Import GRN"):
		return

	if not frappe.db.has_column("Import GRN", "total_expected_qty"):
		return

	rows = frappe.get_all("Import GRN", pluck="name", limit=2000)
	for name in rows:
		grn = frappe.get_doc("Import GRN", name)
		expected = sum(frappe.utils.flt(row.qty) for row in grn.items or [])
		arrived = sum(frappe.utils.flt(row.arrived_qty) for row in grn.items or [])
		pending = max(expected - arrived, 0)
		if arrived <= 0:
			receipt_type = "Pending"
			is_partial = 0
		elif pending > 0:
			receipt_type = "Partial"
			is_partial = 1
		else:
			receipt_type = "Full"
			is_partial = 0
		frappe.db.set_value(
			"Import GRN",
			name,
			{
				"total_expected_qty": expected,
				"total_arrived_qty": arrived,
				"pending_qty": pending,
				"receipt_type": receipt_type,
				"is_partial_receipt": is_partial,
			},
			update_modified=False,
		)

	if frappe.db.has_column("Transport Schedule", "inward_import_leg"):
		frappe.db.sql(
			"""
			UPDATE `tabTransport Schedule`
			SET inward_import_leg = 'Initial Import Leg'
			WHERE transport_type = 'Inward'
			  AND IFNULL(inward_import_leg, '') = ''
			"""
		)
