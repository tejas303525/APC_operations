# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""Seed the editable Security Checklist Template with the checklist that
	used to be hardcoded in security_inspection.py (DEFAULT_CHECKLIST_ITEMS),
	so security can maintain it from the UI from now on. Runs post model
	sync (the new doctypes must exist first) and never overwrites a template
	someone has already filled in."""
	from apc_operations.security.doctype.security_inspection.security_inspection import (
		DEFAULT_CHECKLIST_ITEMS,
	)

	doc = frappe.get_doc("Security Checklist Template")
	if doc.items:
		return

	for item in DEFAULT_CHECKLIST_ITEMS:
		doc.append(
			"items",
			{
				"checklist_item": item["checklist_item"],
				"required": int(item.get("required", 0)),
				"active": 1,
			},
		)
	doc.save(ignore_permissions=True)
