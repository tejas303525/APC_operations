# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""Re-import every standard print format that references the company
	logo, after switching all hardcoded /files/AP_Logo.webp references to
	/files/AP_Logo.png. wkhtmltopdf (Frappe's PDF engine) cannot render
	WebP images at all - the logo box has always rendered empty in every
	downloaded/emailed PDF across every print format in the system, even
	though it displays fine in the browser print preview (which uses the
	browser's own image decoder, not wkhtmltopdf). Also updates the
	Company.company_logo field itself, since several formats (e.g.
	Standard Transport PO) resolve the logo dynamically from there rather
	than hardcoding a path. force=True since every one of these records
	already exists - reload_doc silently no-ops on an update without it."""
	for module, folder in [
		("shipping", "standard_loading_delivery_note"),
		("shipping", "standard_import_po"),
		("shipping", "standard_qc_report_request"),
		("shipping", "standard_job_order"),
		("shipping", "standard_delivery_order"),
		("shipping", "standard_transport_po"),
		("shipping", "standard_invoice"),
		("shipping", "apc_coa_standard_certificate"),
	]:
		frappe.reload_doc(module, "print_format", folder, force=True)

	company = frappe.db.get_default("company")
	if company and frappe.db.get_value("Company", company, "company_logo") == "/files/AP_Logo.webp":
		frappe.db.set_value("Company", company, "company_logo", "/files/AP_Logo.png", update_modified=False)
