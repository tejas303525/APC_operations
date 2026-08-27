# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
import os


def execute():
	"""Re-import Standard Invoice print format: full layout redesign matching
	a customer-supplied reference PDF (Bill To/Ship To boxes, unified goods
	table columns with always-visible Tax %/Tax Amount, Balance Due box,
	bank details, signature/stamp block). force=True since the record
	already exists."""
	path = frappe.get_app_path(
		"apc_operations",
		"shipping",
		"print_format",
		"standard_invoice",
		"standard_invoice.json",
	)
	if not os.path.exists(path):
		return
	frappe.reload_doc("shipping", "print_format", "standard_invoice", force=True)
