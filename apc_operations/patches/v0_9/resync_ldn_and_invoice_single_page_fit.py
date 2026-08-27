# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
import os


def execute():
	"""Re-import Standard Loading Delivery Note and Standard Invoice print
	formats after trimming oversized fixed heights that pushed both onto a
	second page (LDN's 340px goods-body row alone, and the ~277mm page-wide
	min-height both formats reserved). force=True since both records
	already exist - reload_doc silently no-ops without it."""
	base = frappe.get_app_path("apc_operations", "shipping", "print_format")

	ldn_path = os.path.join(base, "standard_loading_delivery_note", "standard_loading_delivery_note.json")
	if os.path.exists(ldn_path):
		frappe.reload_doc("shipping", "print_format", "standard_loading_delivery_note", force=True)

	inv_path = os.path.join(base, "standard_invoice", "standard_invoice.json")
	if os.path.exists(inv_path):
		frappe.reload_doc("shipping", "print_format", "standard_invoice", force=True)
