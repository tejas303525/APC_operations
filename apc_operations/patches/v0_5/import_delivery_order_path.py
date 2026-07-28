# Copyright (c) 2026, APC and contributors

import frappe


def execute():
	"""Add import DO / export handoff columns and backfill movement on existing DOs."""
	_add_column(
		"Delivery Order",
		"commercial_movement",
		"varchar(140) default 'Export'",
	)
	_add_column("Delivery Order", "supplier", "varchar(140)")
	_add_column("Delivery Order", "supplier_name", "varchar(140)")
	_add_column("Job Order", "linked_export_job_order", "varchar(140)")
	_add_column("Job Order", "source_import_job_order", "varchar(140)")
	_add_column("Job Order", "zoho_import_receipt_id", "varchar(140)")

	if frappe.db.has_column("Delivery Order", "commercial_movement"):
		frappe.db.sql(
			"""
			UPDATE `tabDelivery Order` do
			INNER JOIN `tabJob Order` jo ON jo.name = do.job_order
			SET do.commercial_movement = COALESCE(jo.commercial_movement, 'Export')
			WHERE IFNULL(do.commercial_movement, '') = ''
			"""
		)


def _add_column(doctype: str, fieldname: str, definition: str) -> None:
	if frappe.db.has_column(doctype, fieldname):
		return
	frappe.db.sql(f"ALTER TABLE `tab{doctype}` ADD COLUMN `{fieldname}` {definition}")
