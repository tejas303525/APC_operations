"""
Backfill the Incoterm responsibility fields introduced for the Incoterms
2020 cleanup (freight_borne_by, insurance_borne_by, transport_arranged_by,
shipping_arranged_by, insurance_required, risk_transfer_point) on every
existing Job Order.

Also corrects rows where prior buggy logic left:
  - FOB with transport_required = 0 (now should be 1)
  - CFR/CIF with transport_requirement_status = "Buyer Arranged"
  - DDP with booking_requirement = "Not Required"
"""

import frappe

from apc_operations.shipping.doctype.job_order.job_order import (
    INCOTERM_RULES,
    SHIPPING_BOOKING_MODES,
)


REQUIRED_COLUMNS = [
    "terms_of_delivery",
    "mode_of_transport",
    "freight_borne_by",
    "insurance_borne_by",
    "transport_arranged_by",
    "shipping_arranged_by",
    "insurance_required",
    "risk_transfer_point",
    "booking_requirement",
    "transport_required",
    "shipping_required",
    "transport_requirement_status",
    "transport_requirement_notes",
]


def execute():
    if not frappe.db.table_exists("Job Order"):
        return

    columns = set(frappe.db.get_table_columns("Job Order"))
    if not set(REQUIRED_COLUMNS).issubset(columns):
        # New columns not yet present (migrate hasn't run); abort safely.
        return

    job_orders = frappe.get_all(
        "Job Order",
        fields=["name", "terms_of_delivery", "mode_of_transport"],
    )

    updated = 0
    for jo in job_orders:
        incoterm = (jo.terms_of_delivery or "").strip().upper()
        rule = INCOTERM_RULES.get(incoterm)
        if rule is None:
            continue

        mode = (jo.mode_of_transport or "").strip().lower()
        rule_shipping_required = int(rule["shipping_required"])
        if rule_shipping_required and mode and mode not in SHIPPING_BOOKING_MODES:
            shipping_required = 0
            shipping_arranged_by = "Not Applicable"
        else:
            shipping_required = rule_shipping_required
            shipping_arranged_by = rule["shipping_arranged_by"]

        frappe.db.set_value(
            "Job Order",
            jo.name,
            {
                "freight_borne_by": rule["freight_borne_by"],
                "insurance_borne_by": rule["insurance_borne_by"],
                "transport_arranged_by": rule["transport_arranged_by"],
                "shipping_arranged_by": shipping_arranged_by,
                "insurance_required": int(rule["insurance_required"]),
                "risk_transfer_point": rule["risk_transfer_point"],
                "booking_requirement": rule["booking_requirement"],
                "transport_required": int(rule["transport_required"]),
                "shipping_required": shipping_required,
                "transport_requirement_status": rule["transport_requirement_status"],
                "transport_requirement_notes": rule["transport_requirement_notes"],
            },
            update_modified=False,
        )
        updated += 1

    if updated:
        frappe.db.commit()
