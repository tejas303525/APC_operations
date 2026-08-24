# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Populate APC Operations Settings.stock_console_view_roles with the
roles that were hardcoded before this became GUI-editable, so the
settings page shows real rows instead of appearing empty. Must run in
post_model_sync - the child table doesn't exist in the DB schema until
after the new field/table is created by schema sync."""

import frappe

DEFAULT_ROLES = ["Shipping Manager", "Shipping User", "Shipping Coordinator", "System Manager"]


def execute():
	if not frappe.db.exists("DocType", "APC Operations Settings"):
		return
	# Table MultiSelect is a virtual field (child rows, no column on the
	# parent table) - has_column would never see it. Check the synced
	# meta instead, which is only populated once schema sync has run.
	if not frappe.get_meta("APC Operations Settings").has_field("stock_console_view_roles"):
		return

	settings = frappe.get_single("APC Operations Settings")
	if settings.get("stock_console_view_roles"):
		return

	for role in DEFAULT_ROLES:
		if not frappe.db.exists("Role", role):
			continue
		settings.append("stock_console_view_roles", {"role": role})

	settings.save(ignore_permissions=True)
	frappe.db.commit()
