# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def on_update_sales_demand(doc, method):
    """Handler for APC Sales Demand on_update event."""
    # Update status and check for production requirements
    doc.update_status()


def on_update_batch(doc, method):
    """Handler for APC Batch on_update event."""
    # Check if batch is depleted
    if doc.batch_status == "Depleted" and doc.available_quantity > 0:
        frappe.db.set_value("APC Batch", doc.name, "batch_status", "Active",
                           update_modified=False)


def on_update_coa(doc, method):
    """Handler for APC COA on_update event."""
    # Sync COA status to batch
    if doc.batch:
        batch = frappe.get_doc("APC Batch", doc.batch)
        batch.sync_coa_status()


def on_submit_allocation(doc, method):
    """Handler for APC Batch Allocation on_submit event."""
    # Reserve quantities in batches
    for detail in doc.allocation_details:
        if detail.batch:
            batch = frappe.get_doc("APC Batch", detail.batch)
            batch.allocate_quantity(detail.allocated_quantity)

    # Update sales demand
    doc.update_sales_demand_allocation()


def on_update_production_requirement(doc, method):
    """Handler for APC Production Requirement on_update event."""
    # Sync WIP to demand item
    doc.sync_to_demand_item()


def on_submit_dispatch(doc, method):
    """Handler for APC Dispatch Order on_submit event."""
    # Validate dispatch batches
    validation = doc.validate_dispatch_batches()

    if not validation.get("valid"):
        frappe.throw(
            _("Dispatch validation failed:\n") +
            "\n".join(f"• {e}" for e in validation.get("errors", []))
        )

    # Attach COAs
    doc.attach_batch_coas()

    # Update quantities
    doc.update_allocation_dispatched_qty()
    doc.update_batch_depletion()
    doc.update_sales_demand_status()
