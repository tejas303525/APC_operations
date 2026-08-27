# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
import os


def execute():
	"""Import Standard Invoice print format from module JSON.

	Removes the redundant Destination field (duplicate of City/Port of
	Discharge) and fixes goods-table column widths that summed to 104%
	for the Tax Invoice variant - table-layout: fixed silently overflowed
	the rightmost numeric columns (Amount/Taxable Value/VAT/Total),
	rendering them visually cramped/overlapping."""
	path = frappe.get_app_path(
		"apc_operations",
		"shipping",
		"print_format",
		"standard_invoice",
		"standard_invoice.json",
	)
	if not os.path.exists(path):
		return
	# force=True: reload_doc silently no-ops on an already-existing record
	# unless forced - discovered live when this patch ran without error
	# but the Destination-field removal and column-width fix never
	# actually landed in the DB until force-reloaded manually.
	frappe.reload_doc("shipping", "print_format", "standard_invoice", force=True)
