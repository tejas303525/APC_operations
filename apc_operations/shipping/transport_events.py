# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe


TRANSPORT_TO_JOB_ORDER_STATUS = {
    "Draft": "Pending Booking",
    "Pending Assignment": "Pending Booking",
    "Scheduled": "Scheduled",
    "Vehicle Assigned": "Scheduled",
    "Driver Assigned": "Scheduled",
    "Dispatched": "In Progress",
    "Picked Up": "In Progress",
    "Gate In": "In Progress",
    "In Transit": "In Progress",
    "Delivered": "Completed",
    "Completed": "Completed",
    "Cancelled": "Cancelled",
}


def on_transport_update(doc, method):
    """Handle Transport Schedule update events — sync status back to parent docs."""
    if doc.shipping_booking:
        mapped_status = doc.get_booking_transport_status() if hasattr(doc, "get_booking_transport_status") else "Pending"
        frappe.db.set_value(
            "Shipping Booking",
            doc.shipping_booking,
            {
                "transport_status": mapped_status,
                "linked_transport": doc.name
            },
            update_modified=False
        )

    sync_transport_to_job_order(doc)


def on_transport_submit(doc, method):
    """Handle Transport Schedule submission — mark parent docs as completed."""
    if doc.shipping_booking:
        frappe.db.set_value(
            "Shipping Booking",
            doc.shipping_booking,
            {"transport_status": "Completed"},
            update_modified=False
        )

    sync_transport_to_job_order(doc)


def sync_transport_to_job_order(doc):
    if not doc.job_order:
        return

    # Prevent recursive updates - if we're already syncing from Job Order, don't loop back
    if frappe.flags.in_sync_transport_to_job_order:
        return

    values = {
        "transport_schedule": doc.name,
        "transport_status": TRANSPORT_TO_JOB_ORDER_STATUS.get(doc.transport_status, "Pending Booking"),
    }

    job_status = frappe.db.get_value("Job Order", doc.job_order, "status")
    if doc.transport_status in ["Dispatched", "Picked Up", "Gate In", "In Transit"]:
        if job_status not in ["Completed", "Cancelled"]:
            values["status"] = "In Progress"
    elif doc.transport_status in ["Delivered", "Completed"]:
        if job_status != "Cancelled":
            values["status"] = "Completed"

    frappe.flags.in_sync_transport_to_job_order = True
    try:
        frappe.db.set_value("Job Order", doc.job_order, values, update_modified=False)
        from apc_operations.shipping.services.logistics_cost_service import (
            refresh_job_order_logistics_display,
        )

        refresh_job_order_logistics_display(doc.job_order)
    finally:
        frappe.flags.in_sync_transport_to_job_order = False
