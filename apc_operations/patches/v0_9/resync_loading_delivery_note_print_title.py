# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
import os


def execute():
	"""Re-import Standard Loading Delivery Note print format from module JSON.

	The original sync patch (v0_4) already ran, and patches are one-shot -
	editing the JSON source afterward (title text change) does not get
	picked up again without a fresh patch to re-trigger reload_doc."""
	path = frappe.get_app_path(
		"apc_operations",
		"shipping",
		"print_format",
		"standard_loading_delivery_note",
		"standard_loading_delivery_note.json",
	)
	if not os.path.exists(path):
		return
	frappe.reload_doc("shipping", "print_format", "standard_loading_delivery_note")
