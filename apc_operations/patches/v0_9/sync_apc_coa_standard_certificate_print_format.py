# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
import os


def execute():
	"""Import APC COA Standard Certificate print format from module JSON.

	This format existed only as a live DB record (created directly via the
	GUI) until now - never fixture-tracked, so a lost/rebuilt site would
	have lost it entirely. Exporting it here also captures the batch-field
	priority fix and the one-page CSS trims applied directly in production."""
	path = frappe.get_app_path(
		"apc_operations",
		"shipping",
		"print_format",
		"apc_coa_standard_certificate",
		"apc_coa_standard_certificate.json",
	)
	if not os.path.exists(path):
		return
	# force=True: reload_doc silently no-ops on an already-existing record
	# unless forced (confirmed live - the sibling standard_invoice patch
	# below ran without error but wrote nothing until force=True was added).
	frappe.reload_doc("shipping", "print_format", "apc_coa_standard_certificate", force=True)
