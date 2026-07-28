# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Move module workspaces out of Shipping module grouping."""

import frappe


def execute():
	if frappe.db.exists("Workspace", "Transportation"):
		frappe.db.set_value(
			"Workspace",
			"Transportation",
			{"module": "Transportation", "parent_page": ""},
			update_modified=False,
		)
