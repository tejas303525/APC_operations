# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def on_gate_pass_update(doc, method):
    """Handle Gate Pass update events"""
    # Update transport schedule when gate pass is completed
    if doc.get("transport_schedule") and doc.status == "Delivered":
        # Check if all gate passes for this transport are completed
        incomplete_count = frappe.db.count(
            "Gate Pass",
            {
                "transport_schedule": doc.transport_schedule,
                "status": ["!=", "Delivered"]
            }
        )

        if incomplete_count == 0:
            # All gate passes completed, update transport
            frappe.db.set_value(
                "Transport Schedule",
                doc.transport_schedule,
                {"transport_status": "Completed"},
                update_modified=False
            )
