# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""Re-import all four print formats after enlarging their header logos.
	force=True since every one of these records already exists - reload_doc
	silently no-ops on an update without it."""
	frappe.reload_doc("shipping", "print_format", "standard_invoice", force=True)
	frappe.reload_doc("shipping", "print_format", "standard_loading_delivery_note", force=True)
	frappe.reload_doc("shipping", "print_format", "apc_coa_standard_certificate", force=True)
	frappe.reload_doc("shipping", "print_format", "standard_qc_report_request", force=True)
