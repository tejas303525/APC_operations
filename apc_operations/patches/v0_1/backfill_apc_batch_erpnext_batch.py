# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Backfill the APC Batch to ERPNext Batch bridge."""

import frappe


def execute():
    if "erpnext" not in frappe.get_installed_apps():
        frappe.throw("ERPNext must be installed before APC Batch can be bridged to ERPNext Batch.")

    if not frappe.db.has_column("APC Batch", "erpnext_batch"):
        return

    batches = frappe.get_all(
        "APC Batch",
        filters={"product": ["is", "set"]},
        fields=["name"],
        order_by="creation ASC",
    )

    for row in batches:
        doc = frappe.get_doc("APC Batch", row.name)
        doc.ensure_erpnext_batch()

    frappe.db.commit()
