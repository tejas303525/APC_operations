# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Packing matrix DocTypes and dispatch quantity fields."""

import frappe


def execute():
	_add_job_order_item_columns()
	_add_delivery_order_columns()
	_add_loading_delivery_note_columns()
	_add_loading_entry_columns()
	_add_security_inspection_columns()

	for dt in (
		"APC Packaging Tare",
		"APC Container Load Capacity",
		"APC Product Packing Profile",
		"Job Order Item",
		"Delivery Order",
		"Delivery Order Item",
		"Loading Delivery Note",
		"Loading Entry",
		"Security Inspection",
		"APC Operations Settings",
	):
		try:
			frappe.reload_doctype(dt)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"reload_doctype failed for {dt}")


def _add_job_order_item_columns():
	frappe.db.sql(
		"""
		ALTER TABLE `tabJob Order Item`
		ADD COLUMN IF NOT EXISTS `packing_unit_type` varchar(140) DEFAULT NULL,
		ADD COLUMN IF NOT EXISTS `packing_profile` varchar(140) DEFAULT NULL,
		ADD COLUMN IF NOT EXISTS `product_fill_kg` decimal(18,6) DEFAULT 0,
		ADD COLUMN IF NOT EXISTS `empty_packaging_kg` decimal(18,6) DEFAULT 0,
		ADD COLUMN IF NOT EXISTS `unit_gross_kg` decimal(18,6) DEFAULT 0,
		ADD COLUMN IF NOT EXISTS `packaging_qty` int(11) NOT NULL DEFAULT 0,
		ADD COLUMN IF NOT EXISTS `packaging_qty_override` int(1) NOT NULL DEFAULT 0,
		ADD COLUMN IF NOT EXISTS `planned_product_kg` decimal(18,6) DEFAULT 0,
		ADD COLUMN IF NOT EXISTS `planned_gross_kg` decimal(18,6) DEFAULT 0
		"""
	)


def _add_delivery_order_columns():
	frappe.db.sql(
		"""
		ALTER TABLE `tabDelivery Order`
		ADD COLUMN IF NOT EXISTS `planned_product_kg` decimal(18,6) DEFAULT 0,
		ADD COLUMN IF NOT EXISTS `planned_gross_kg` decimal(18,6) DEFAULT 0,
		ADD COLUMN IF NOT EXISTS `expected_packaging_qty` int(11) NOT NULL DEFAULT 0
		"""
	)
	frappe.db.sql(
		"""
		ALTER TABLE `tabDelivery Order Item`
		ADD COLUMN IF NOT EXISTS `packing_unit_type` varchar(140) DEFAULT NULL
		"""
	)


def _add_loading_delivery_note_columns():
	frappe.db.sql(
		"""
		ALTER TABLE `tabLoading Delivery Note`
		ADD COLUMN IF NOT EXISTS `calculated_gross_kg` decimal(18,6) DEFAULT 0,
		ADD COLUMN IF NOT EXISTS `expected_packaging_qty` int(11) NOT NULL DEFAULT 0,
		ADD COLUMN IF NOT EXISTS `loaded_packaging_qty` int(11) NOT NULL DEFAULT 0,
		ADD COLUMN IF NOT EXISTS `package_variance_qty` int(11) NOT NULL DEFAULT 0,
		ADD COLUMN IF NOT EXISTS `package_variance_status` varchar(140) DEFAULT NULL
		"""
	)


def _add_loading_entry_columns():
	frappe.db.sql(
		"""
		ALTER TABLE `tabLoading Entry`
		ADD COLUMN IF NOT EXISTS `packing_unit_type` varchar(140) DEFAULT NULL,
		ADD COLUMN IF NOT EXISTS `units_loaded` int(11) NOT NULL DEFAULT 0,
		ADD COLUMN IF NOT EXISTS `unit_gross_kg` decimal(18,6) DEFAULT 0
		"""
	)


def _add_security_inspection_columns():
	frappe.db.sql(
		"""
		ALTER TABLE `tabSecurity Inspection`
		ADD COLUMN IF NOT EXISTS `expected_packaging_qty` int(11) NOT NULL DEFAULT 0,
		ADD COLUMN IF NOT EXISTS `loaded_packaging_qty` int(11) NOT NULL DEFAULT 0
		"""
	)
