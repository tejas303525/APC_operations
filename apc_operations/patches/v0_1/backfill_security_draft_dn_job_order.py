"""
Backfill job_order on Security Draft Delivery Note.

Previously the field was misnamed (job_order_number) and the server-side
auto-creation code was writing to draft_dn.job_order which was silently
discarded. This patch reads the job_order from the linked Transport Schedule
and writes it to the now-correctly-named job_order field.
"""

import frappe


def execute():
    draft_dns = frappe.get_all(
        "Security Draft Delivery Note",
        filters={"job_order": ["is", "not set"]},
        fields=["name", "transport_schedule"],
    )

    updated = 0
    for row in draft_dns:
        if not row.transport_schedule:
            continue

        job_order = frappe.db.get_value(
            "Transport Schedule", row.transport_schedule, "job_order"
        )
        if not job_order:
            continue

        frappe.db.set_value(
            "Security Draft Delivery Note",
            row.name,
            "job_order",
            job_order,
            update_modified=False,
        )
        updated += 1

    frappe.db.commit()
    print(f"Backfilled job_order on {updated} Security Draft Delivery Note(s).")
