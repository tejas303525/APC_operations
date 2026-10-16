# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""Import the new Standard Security Checklist print format (Security
	Inspection) so the Security Console can print the checklist."""
	frappe.reload_doc("security", "print_format", "standard_security_checklist", force=True)
