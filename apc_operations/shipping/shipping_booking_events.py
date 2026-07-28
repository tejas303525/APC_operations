# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe


def on_booking_update(doc, method):
    """Handle Shipping Booking update events"""
    cost_fields = {
        "freight_rate",
        "container_count",
        "thc",
        "tluc",
        "export_declaration",
        "currency",
    }
    if doc.job_order and any(doc.has_value_changed(f) for f in cost_fields):
        from apc_operations.shipping.services.logistics_cost_service import (
            refresh_job_order_logistics_display,
        )

        refresh_job_order_logistics_display(doc.job_order)

    if doc.has_value_changed("booking_status"):
        doc.add_comment(
            "Comment",
            text=f"Booking status changed to: {doc.booking_status}"
        )

    if doc.has_value_changed("cro_status"):
        doc.add_comment(
            "Comment",
            text=f"CRO status changed to: {doc.cro_status}"
        )


def on_booking_submit(doc, method):
    """Handle Shipping Booking submission — mark as Confirmed"""
    frappe.db.set_value(
        "Shipping Booking",
        doc.name,
        {"booking_status": "Confirmed"},
        update_modified=False
    )
