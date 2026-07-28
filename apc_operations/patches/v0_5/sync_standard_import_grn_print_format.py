# Copyright (c) 2026, APC and contributors
"""Install / reload Standard Import GRN print format."""

import os

import frappe


def execute():
	html_path = frappe.get_app_path(
		"apc_operations",
		"security",
		"print_format",
		"standard_import_grn",
		"standard_import_grn.html",
	)
	if not os.path.exists(html_path):
		return

	with open(html_path, encoding="utf-8") as handle:
		html = handle.read()

	name = "Standard Import GRN"
	if frappe.db.exists("Print Format", name):
		doc = frappe.get_doc("Print Format", name)
		doc.html = html
		doc.doc_type = "Import GRN"
		doc.module = "Security"
		doc.disabled = 0
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Print Format",
				"name": name,
				"doc_type": "Import GRN",
				"module": "Security",
				"print_format_type": "Jinja",
				"print_format_for": "DocType",
				"standard": "Yes",
				"custom_format": 1,
				"disabled": 0,
				"html": html,
			}
		)
		doc.insert(ignore_permissions=True)

	frappe.db.set_value(
		"DocType",
		"Import GRN",
		"default_print_format",
		"Standard Import GRN",
		update_modified=False,
	)
