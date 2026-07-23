# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import today
from frappe import _
from apc_operations.services.email_recipients import role_user_emails


def on_security_inspection_update(doc, method):
    """Handle Security Inspection update events."""
    if doc.has_value_changed("security_status"):
        doc.add_comment(
            "Comment",
            text=f"Security status changed to: {doc.security_status}"
        )


def on_qc_report_request_update(doc, method):
    """
    Handle QC Report Request update events.

    Syncs qc_status back to:
    1. Security Inspection (primary sync — done inside qc_report_request.py controller)
    2. Loading Delivery Note (qc_status field and delivery_note_status)

    This hook guards against edge cases where the controller sync may have been
    skipped (e.g., direct db.set_value calls from other places).
    """
    if not doc.has_value_changed("qc_status"):
        return

    # Sync to Security Inspection (guard — controller already does this)
    if doc.security_inspection:
        current_si_qc = frappe.db.get_value("Security Inspection", doc.security_inspection, "qc_status")
        if current_si_qc != doc.qc_status:
            update = {"qc_status": doc.qc_status}
            if doc.qc_status == "QC Cleared":
                update["security_status"] = "QC Cleared"
                update["qc_checked_by"] = doc.qc_checked_by
                update["qc_checked_on"] = doc.qc_checked_on
            elif doc.qc_status == "QC Rejected":
                update["security_status"] = "QC Rejected"
            frappe.db.set_value("Security Inspection", doc.security_inspection, update, update_modified=False)

    # Sync to Loading DN
    if doc.loading_delivery_note:
        current_ldn_qc = frappe.db.get_value("Loading Delivery Note", doc.loading_delivery_note, "qc_status")
        if current_ldn_qc != doc.qc_status:
            if doc.qc_status == "QC Cleared":
                frappe.db.set_value(
                    "Loading Delivery Note",
                    doc.loading_delivery_note,
                    {
                        "qc_status": "QC Cleared",
                        "delivery_note_status": "QC Cleared",
                        "qc_cleared_by": doc.qc_checked_by,
                        "qc_cleared_on": doc.qc_checked_on,
                    },
                    update_modified=False,
                )
            elif doc.qc_status == "QC Rejected":
                frappe.db.set_value(
                    "Loading Delivery Note",
                    doc.loading_delivery_note,
                    {
                        "qc_status": "QC Rejected",
                        "delivery_note_status": "QC Rejected",
                    },
                    update_modified=False,
                )


def on_loading_delivery_note_update(doc, method):
    """
    Handle Loading Delivery Note update events.

    - Sync receivables_status back to Security Inspection.
    - Advance Security Inspection security_status when Loading DN reaches Reported to Receivables.
    """
    status_changed = doc.has_value_changed("receivables_status") or doc.has_value_changed("delivery_note_status")
    if not status_changed:
        return

    if not doc.security_inspection:
        return

    update = {}
    if doc.has_value_changed("receivables_status"):
        update["receivables_status"] = doc.receivables_status

    if doc.receivables_status == "Reported to Receivables":
        update["security_status"] = "Reported to Receivables"

    if update:
        frappe.db.set_value(
            "Security Inspection",
            doc.security_inspection,
            update,
            update_modified=False,
        )


def on_security_draft_dn_update(doc, method):
    """Handle Security Draft Delivery Note update events."""
    if doc.has_value_changed("security_status"):
        doc.add_comment(
            "Comment",
            text=f"Security Draft DN status changed to: {doc.security_status}"
        )

        if doc.security_status == "Pending Review":
            _notify_security_team_draft_dn(doc)


def _notify_security_team_draft_dn(doc):
    """Notify security users when a Draft DN moves to Pending Review."""
    try:
        security_users = role_user_emails(["Security Manager", "Security User"])

        if not security_users:
            return

        subject = f"Security Review Required: Draft DN {doc.name}"
        message = f"""
        <h3>Security Draft Delivery Note Pending Review</h3>
        <p><b>Draft DN:</b> {doc.name}</p>
        <p><b>Transport Schedule:</b> {doc.transport_schedule or 'N/A'}</p>
        <p><b>Customer:</b> {doc.customer or 'N/A'}</p>
        <p><b>Pickup Date:</b> {doc.pickup_date or 'N/A'}</p>
        <p><b>Vehicle:</b> {doc.vehicle or 'Not Assigned'}</p>
        <p><b>Driver:</b> {doc.driver or 'Not Assigned'}</p>
        <br>
        <a href="{frappe.utils.get_url()}/app/security-draft-delivery-note/{doc.name}">
            Review Draft Delivery Note
        </a>
        """

        for user in security_users:
            frappe.sendmail(
                recipients=user,
                subject=subject,
                message=message,
                reference_doctype="Security Draft Delivery Note",
                reference_name=doc.name,
            )
    except Exception as e:
        frappe.log_error(
            f"Security Draft DN Notification Error: {str(e)}",
            "Security Draft Delivery Note"
        )
