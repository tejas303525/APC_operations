# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
import os


def execute():
	"""Import Standard QC Report Request print format from module JSON."""
	path = frappe.get_app_path(
		"apc_operations",
		"shipping",
		"print_format",
		"standard_qc_report_request",
		"standard_qc_report_request.json",
	)
	if not os.path.exists(path):
		return
	frappe.reload_doc("shipping", "print_format", "standard_qc_report_request")
