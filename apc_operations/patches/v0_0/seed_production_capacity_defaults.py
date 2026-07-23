# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Idempotent seed for Production module defaults.

* Ensures `Production Manager` and `Production User` roles exist.
* Seeds default Production Capacity Configuration rows (Drums=600/day,
  Containers=5/day) if no active rule exists for those categories.

This patch is safe to re-run; it never creates duplicates.
"""

import frappe
from frappe.utils import today


DEFAULT_RULES = [
    {"production_category": "Drums", "max_quantity_per_day": 600.0, "uom": "Nos"},
    {"production_category": "Containers", "max_quantity_per_day": 5.0, "uom": "Nos"},
]

REQUIRED_ROLES = [
    "Production Manager",
    "Production User",
]


def execute():
    _ensure_roles()
    _seed_capacity_rules()


def _ensure_roles():
    for role_name in REQUIRED_ROLES:
        if not frappe.db.exists("Role", role_name):
            role = frappe.new_doc("Role")
            role.role_name = role_name
            role.desk_access = 1
            role.insert(ignore_permissions=True)
            frappe.db.commit()


def _seed_capacity_rules():
    if not frappe.db.table_exists("Production Capacity Configuration"):
        return

    today_str = today()
    flags_token = getattr(frappe, "flags", None)
    in_patch_was = getattr(flags_token, "in_patch", False) if flags_token else False
    if flags_token is not None:
        frappe.flags.in_patch = True

    try:
        for rule in DEFAULT_RULES:
            existing = frappe.db.exists(
                "Production Capacity Configuration",
                {
                    "production_category": rule["production_category"],
                    "active": 1,
                },
            )
            if existing:
                continue

            doc = frappe.new_doc("Production Capacity Configuration")
            doc.production_category = rule["production_category"]
            doc.max_quantity_per_day = rule["max_quantity_per_day"]
            doc.uom = rule["uom"]
            doc.applies_from = today_str
            doc.active = 1
            doc.notes = "Auto-seeded default capacity rule."
            doc.insert(ignore_permissions=True)
        frappe.db.commit()
    finally:
        if flags_token is not None:
            frappe.flags.in_patch = in_patch_was
