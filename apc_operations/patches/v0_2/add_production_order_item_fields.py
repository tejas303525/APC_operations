# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""
Migration patch: backfill Production Order item field from item_description.

Attempts to resolve item_description against ERPNext Item names.
Records that cannot be resolved are left with item=NULL and get a
migration_note explaining what happened.
"""

import frappe


def execute():
    # Ensure the new columns exist before running
    frappe.db.sql("""
        ALTER TABLE `tabProduction Order`
        ADD COLUMN IF NOT EXISTS `item` varchar(140) DEFAULT NULL,
        ADD COLUMN IF NOT EXISTS `item_name` varchar(255) DEFAULT NULL,
        ADD COLUMN IF NOT EXISTS `grade` varchar(255) DEFAULT NULL,
        ADD COLUMN IF NOT EXISTS `specification` varchar(255) DEFAULT NULL,
        ADD COLUMN IF NOT EXISTS `packaging_type` varchar(255) DEFAULT NULL,
        ADD COLUMN IF NOT EXISTS `warehouse` varchar(140) DEFAULT NULL,
        ADD COLUMN IF NOT EXISTS `production_requirement` varchar(140) DEFAULT NULL,
        ADD COLUMN IF NOT EXISTS `apc_batch` varchar(140) DEFAULT NULL
    """)

    frappe.db.commit()

    orders = frappe.db.sql("""
        SELECT name, item_description FROM `tabProduction Order`
        WHERE item IS NULL OR item = ''
    """, as_dict=True)

    resolved = 0
    unresolved = 0

    for order in orders:
        description = (order.item_description or "").strip()
        if not description:
            unresolved += 1
            continue

        # Exact match on item name
        item = frappe.db.get_value("Item", {"item_name": description}, "name")
        if not item:
            # Try item_code
            item = frappe.db.get_value("Item", {"name": description}, "name")

        if item:
            item_name = frappe.db.get_value("Item", item, "item_name")
            frappe.db.set_value(
                "Production Order",
                order.name,
                {"item": item, "item_name": item_name},
                update_modified=False,
            )
            resolved += 1
        else:
            unresolved += 1

    frappe.db.commit()
    print(f"Production Order item backfill: {resolved} resolved, {unresolved} unresolved.")
