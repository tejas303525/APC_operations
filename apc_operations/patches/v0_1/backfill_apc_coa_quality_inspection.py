# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Backfill APC COA status from linked ERPNext Quality Inspections."""

import frappe


def execute():
    if "erpnext" not in frappe.get_installed_apps():
        frappe.throw("ERPNext must be installed before APC COA can be bridged to Quality Inspection.")

    if not frappe.db.has_column("APC COA", "quality_inspection"):
        return

    coas = frappe.get_all(
        "APC COA",
        filters={"quality_inspection": ["is", "set"]},
        pluck="name",
    )

    for coa_name in coas:
        doc = frappe.get_doc("APC COA", coa_name)
        doc.sync_from_quality_inspection()
        doc.save(ignore_permissions=True)

    frappe.db.commit()
