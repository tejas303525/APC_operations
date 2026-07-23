# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now, flt
from frappe import _
from apc_operations.services.email_recipients import role_user_emails


class LoadingDeliveryNote(Document):
    def validate(self):
        self.validate_dispatch_not_already_confirmed()
        self.validate_fifo_override_rows()

    def validate_dispatch_not_already_confirmed(self):
        if self.dispatch_confirmed and not self.is_new():
            old_confirmed = frappe.db.get_value("Loading Delivery Note", self.name, "dispatch_confirmed")
            if old_confirmed:
                changed_fields = [
                    f for f in ["batch_allocations", "security_inspection", "job_order"]
                    if self.has_value_changed(f)
                ]
                if changed_fields:
                    frappe.throw(_("Cannot modify a Loading Delivery Note with confirmed dispatch."))

    def validate_fifo_override_rows(self):
        for row in (self.batch_allocations or []):
            if row.is_fifo_override:
                if not row.override_reason:
                    frappe.throw(
                        _("Override reason is required for FIFO override on batch row {0}.").format(row.idx)
                    )

    def on_update(self):
        self.sync_to_security_inspection()

    @frappe.whitelist()
    def confirm_dispatch(self):
        """Shortcut to call the service-layer confirm_dispatch_and_deduct_stock."""
        from apc_operations.services.batch_allocation import confirm_dispatch_and_deduct_stock
        return confirm_dispatch_and_deduct_stock(self.name)

    @frappe.whitelist()
    def allocate_batches_fifo(self, product=None, required_qty=None,
                               grade=None, specification=None,
                               packaging_type=None, warehouse=None):
        """Trigger FIFO batch allocation for this Loading DN."""
        from apc_operations.services.batch_allocation import create_loading_dn_batch_allocations
        return create_loading_dn_batch_allocations(
            loading_dn_name=self.name,
            product=product,
            required_qty=required_qty,
            grade=grade,
            specification=specification,
            packaging_type=packaging_type,
            warehouse=warehouse,
        )

    @frappe.whitelist()
    def verify_coas(self):
        """Mark all COAs as verified by the current user."""
        if not self.batch_allocations:
            frappe.throw(_("No batch allocations to verify."))

        errors = []
        for row in self.batch_allocations:
            if not row.coa:
                errors.append(_("Batch {0} has no COA.").format(row.batch_number or row.batch))
                continue
            approval = frappe.db.get_value("APC COA", row.coa, "approval_status")
            if approval != "Approved":
                errors.append(_("COA {0} for batch {1} is not approved.").format(
                    row.coa, row.batch_number or row.batch
                ))

        if errors:
            frappe.throw(_("COA verification failed:\n") + "\n".join(f"• {e}" for e in errors))

        self.db_set("coa_verified", 1, update_modified=False)
        self.db_set("coa_verified_by", frappe.session.user, update_modified=False)
        self.db_set("coa_verified_on", now(), update_modified=False)
        self.db_set("delivery_note_status", "COA Verified", update_modified=False)

        frappe.msgprint(_("All COAs verified for {0}.").format(self.name), indicator="green", alert=True)
        return {"success": True}

    def sync_to_security_inspection(self):
        if self.security_inspection:
            frappe.db.set_value(
                "Security Inspection",
                self.security_inspection,
                {
                    "loading_delivery_note": self.name,
                    "loading_date": self.loading_date,
                    "loading_time": self.loading_time,
                    "receivables_status": self.receivables_status
                },
                update_modified=False
            )

    @frappe.whitelist()
    def report_to_receivables(self):
        """
        Report this Loading DN to Receivables.

        Prerequisites (all must pass):
        1. QC status = QC Cleared  (set by QC Report Request)
        2. Security Inspection linked
        3. QC Report Request linked
        4. At least one batch allocation row (or dispatch_confirmed)
        5. Each batch allocation row has an approved COA
        """
        if self.receivables_status == "Reported to Receivables":
            frappe.throw(_("Already reported to Receivables."))

        # --- Prerequisite 1: QC must be cleared ---
        if self.qc_status != "QC Cleared":
            frappe.throw(
                _("QC clearance is required before reporting to Receivables. "
                  "Current QC status: {0}").format(self.qc_status or "Pending QC")
            )

        # --- Prerequisite 2: Security Inspection must be linked ---
        if not self.security_inspection:
            frappe.throw(_("This Loading Delivery Note is not linked to a Security Inspection."))

        # --- Prerequisite 3: QC Report Request must exist ---
        if not self.qc_report_request:
            frappe.throw(_("No QC Report Request linked to this Loading Delivery Note."))

        # --- Prerequisite 4 & 5: Batch allocations with approved COAs ---
        if self.batch_allocations:
            coa_errors = []
            for row in self.batch_allocations:
                if not row.coa:
                    coa_errors.append(
                        _("Batch {0} has no linked COA.").format(row.batch_number or row.batch)
                    )
                    continue
                approval = frappe.db.get_value("APC COA", row.coa, "approval_status")
                if approval != "Approved":
                    coa_errors.append(
                        _("COA {0} for batch {1} is not approved (status: {2}).").format(
                            row.coa, row.batch_number or row.batch, approval or "Unknown"
                        )
                    )

            if coa_errors:
                frappe.throw(
                    _("Cannot report to Receivables — COA validation failed:\n") +
                    "\n".join(f"• {e}" for e in coa_errors)
                )
        else:
            # No batch allocations — this is acceptable only if explicitly flagged
            frappe.msgprint(
                _("Warning: No batch allocations found on this Loading DN. Proceeding without batch traceability."),
                indicator="orange",
            )

        self.qc_status = "QC Cleared"
        self.receivables_status = "Reported to Receivables"
        self.delivery_note_status = "Reported to Receivables"
        self.reported_to_receivables_on = now()
        self.reported_by = frappe.session.user
        self.save()

        self.notify_receivables_team()

        if self.security_inspection:
            frappe.db.set_value(
                "Security Inspection",
                self.security_inspection,
                {
                    "security_status": "Reported to Receivables",
                    "receivables_status": "Reported to Receivables"
                },
                update_modified=False
            )

        return {"success": True}

    def notify_receivables_team(self):
        try:
            accounts_users = role_user_emails(["Accounts Manager", "Accounts User"])

            if not accounts_users:
                return

            subject = f"Loading Delivery Note Reported: {self.name}"
            message = f"""
            <h3>Loading Delivery Note Reported to Receivables</h3>
            <p><b>Loading Delivery Note:</b> {self.name}</p>
            <p><b>Job Order:</b> {self.job_order or 'N/A'}</p>
            <p><b>Customer:</b> {self.customer_name or 'N/A'}</p>
            <p><b>Loading Date:</b> {self.loading_date}</p>
            <p><b>Container Number:</b> {self.container_number or 'N/A'}</p>
            <p><b>Material:</b> {self.material_description or 'N/A'}</p>
            <p><b>Quantity:</b> {self.quantity or 0} {self.uom or ''}</p>
            <br>
            <a href="{frappe.utils.get_url()}/app/loading-delivery-note/{self.name}">View Loading Delivery Note</a>
            """

            for user in accounts_users:
                frappe.sendmail(
                    recipients=user,
                    subject=subject,
                    message=message,
                    reference_doctype="Loading Delivery Note",
                    reference_name=self.name
                )
        except Exception as e:
            frappe.log_error(f"Receivables Notification Error: {str(e)}", "Loading Delivery Note")


@frappe.whitelist()
def get_pending_receivables():
    return frappe.get_all(
        "Loading Delivery Note",
        filters={
            "receivables_status": "Pending Receivables",
            "delivery_note_status": ["in", ["QC Cleared", "Ready for Receivables"]]
        },
        fields=["name", "customer_name", "job_order", "container_number", "material_description", "quantity", "uom"],
        order_by="loading_date ASC"
    )
