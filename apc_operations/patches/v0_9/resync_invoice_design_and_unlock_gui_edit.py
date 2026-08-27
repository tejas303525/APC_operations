# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
import os


def execute():
	"""Re-import Standard Invoice print format: fixes narrow-column header
	overlap (Marks/Pkgs columns were too narrow for their own header text),
	bigger company logo, adds the stamp/watermark element that was defined
	in CSS but never actually placed in the body, and flips standard from
	Yes to No so it can be edited directly via the GUI going forward
	(standard=Yes formats reject in-place Desk edits outside developer mode)."""
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
