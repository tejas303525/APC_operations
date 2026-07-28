# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Reload DO/LDN print formats: buyer-only party block and packaging column."""

import os

import frappe


def _reload_print_format(module: str, name: str) -> None:
	path = frappe.get_app_path(
		"apc_operations",
		module,
		"print_format",
		name,
		f"{name}.json",
	)
	if not os.path.exists(path):
		return
	frappe.reload_doc(module, "print_format", name, force=True)


def execute():
	_reload_print_format("shipping", "standard_delivery_order")
	_reload_print_format("shipping", "standard_loading_delivery_note")
