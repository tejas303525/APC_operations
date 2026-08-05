# Copyright (c) 2026, APC and contributors
"""Re-sync Standard Job Order (stacked logo layout) and install Standard Import PO."""

import os

import frappe
from frappe.modules.import_file import import_file_by_path


def _sync_html_backed_print_format(name: str, doc_type: str, module: str, folder: str, file_base: str) -> None:
	html_path = frappe.get_app_path(
		"apc_operations",
		module.lower() if module != "Shipping" else "shipping",
		"print_format",
		folder,
		f"{file_base}.html",
	)
	if not os.path.exists(html_path):
		frappe.log_error(f"Print HTML missing: {html_path}", "resync_job_order_and_import_po_print_formats")
		return

	with open(html_path, encoding="utf-8") as handle:
		html = handle.read()

	if frappe.db.exists("Print Format", name):
		doc = frappe.get_doc("Print Format", name)
		doc.html = html
		doc.doc_type = doc_type
		doc.module = module
		doc.disabled = 0
		doc.save(ignore_permissions=True)
	else:
		frappe.get_doc(
			{
				"doctype": "Print Format",
				"name": name,
				"doc_type": doc_type,
				"module": module,
				"print_format_type": "Jinja",
				"print_format_for": "DocType",
				"standard": "Yes",
				"custom_format": 1,
				"disabled": 0,
				"html": html,
			}
		).insert(ignore_permissions=True)


def execute():
	_sync_html_backed_print_format(
		"Standard Job Order",
		"Job Order",
		"Shipping",
		"standard_job_order",
		"standard_job_order",
	)

	import_po_json = frappe.get_app_path(
		"apc_operations", "shipping", "print_format", "standard_import_po", "standard_import_po.json"
	)
	if os.path.exists(import_po_json):
		import_file_by_path(import_po_json, force=True, reset_permissions=False)

	frappe.db.commit()
