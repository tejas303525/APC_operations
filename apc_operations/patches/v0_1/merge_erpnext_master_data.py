# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Merge APC Operations master-data assumptions with ERPNext masters.

This patch keeps APC's outward movement workflows custom, but makes ERPNext
the source for shared operational masters such as Item, Customer, Warehouse,
and UOM.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    if "erpnext" not in frappe.get_installed_apps():
        frappe.throw("ERPNext must be installed before APC master data merge can run.")

    _ensure_zoho_tracking_fields()
    _ensure_apc_item_defaults()


def _ensure_zoho_tracking_fields():
    """Add Zoho identifiers to ERPNext masters used by APC demand import."""
    custom_fields = {
        "Customer": [
            {
                "fieldname": "zoho_customer_id",
                "label": "Zoho Customer ID",
                "fieldtype": "Data",
                "insert_after": "customer_name",
                "unique": 1,
                "no_copy": 1,
            },
        ],
        "Item": [
            {
                "fieldname": "zoho_item_id",
                "label": "Zoho Item ID",
                "fieldtype": "Data",
                "insert_after": "item_name",
                "unique": 1,
                "no_copy": 1,
            },
            {
                "fieldname": "apc_grade",
                "label": "APC Grade",
                "fieldtype": "Data",
                "insert_after": "zoho_item_id",
            },
            {
                "fieldname": "apc_specification",
                "label": "APC Specification",
                "fieldtype": "Data",
                "insert_after": "apc_grade",
            },
            {
                "fieldname": "apc_packaging_type",
                "label": "APC Packaging Type",
                "fieldtype": "Data",
                "insert_after": "apc_specification",
            },
        ],
    }
    create_custom_fields(custom_fields, ignore_validate=True)


def _ensure_apc_item_defaults():
    """Create a safe Item Group for Zoho-created stock items if needed."""
    if not frappe.db.exists("Item Group", "APC Products"):
        parent = (
            frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ["is", "not set"]}, "name")
            or frappe.db.get_value("Item Group", {"is_group": 1}, "name")
        )
        item_group = frappe.new_doc("Item Group")
        item_group.item_group_name = "APC Products"
        item_group.parent_item_group = parent
        item_group.is_group = 0
        item_group.insert(ignore_permissions=True)
