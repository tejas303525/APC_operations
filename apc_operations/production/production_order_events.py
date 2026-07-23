# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Doc event handlers for Production Order, registered via hooks.py."""

import frappe
from apc_operations.production.doctype.production_order.production_order import (
    evaluate_production_order_capacity,
)


def on_validate(doc, method=None):
    """Recalculate capacity status whenever the Production Order is validated."""
    evaluate_production_order_capacity(doc)


def on_update(doc, method=None):
    """Re-evaluate after writes; downstream sibling orders' totals can shift.

    Also trigger batch creation when status transitions to Completed.
    """
    evaluate_production_order_capacity(doc)
    _maybe_create_batch(doc)


def on_submit(doc, method=None):
    """Trigger batch creation when a submittable Production Order is submitted."""
    _maybe_create_batch(doc)


def _maybe_create_batch(doc):
    """Create APC Batch when Production Order status moves to Completed."""
    if doc.status != "Completed":
        return
    if doc.apc_batch:
        return
    if not doc.item:
        return

    # Avoid re-entrant calls
    if frappe.flags.get("in_production_batch_creation"):
        return

    frappe.flags.in_production_batch_creation = True
    try:
        doc.on_completion()
    finally:
        frappe.flags.in_production_batch_creation = False
