# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
import os


def execute():
	"""Import Standard Delivery Order print format from module JSON."""
	path = frappe.get_app_path(
		"apc_operations",
		"shipping",
		"print_format",
		"standard_delivery_order",
		"standard_delivery_order.json",
	)
	if not os.path.exists(path):
		return
	frappe.reload_doc("shipping", "print_format", "standard_delivery_order")
