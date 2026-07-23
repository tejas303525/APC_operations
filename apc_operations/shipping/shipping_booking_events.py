# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe


def on_booking_update(doc, method):
    """Handle Shipping Booking update events"""
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
