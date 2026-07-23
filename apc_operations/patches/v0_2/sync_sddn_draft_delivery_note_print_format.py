"""Reload **Draft Delivery Note** print format from app JSON.

Desk edits or copies from ERPNext Delivery Note sometimes reference
`address_display`, which does not exist on **Security Draft Delivery Note**
and breaks PDF generation. Force-importing the canonical print format from
the `apc_operations` module restores a template that only uses real SDDN /
Transport Schedule / Customer / Address fields.
"""

import frappe


def execute():
	frappe.reload_doc("security", "print_format", "draft_delivery_note", force=True)
