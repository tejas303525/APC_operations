# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now
from frappe import _
from apc_operations.services.email_recipients import role_user_emails


class QCReportRequest(Document):
    def on_update(self):
        if self.has_value_changed("qc_status"):
            self.update_security_inspection()

    def update_security_inspection(self):
        if not self.security_inspection:
            return

        if self.qc_status == "QC Cleared":
            self.qc_checked_by = frappe.session.user
            self.qc_checked_on = now()

            frappe.db.set_value(
                "Security Inspection",
                self.security_inspection,
                {
                    "qc_status": "QC Cleared",
                    "qc_checked_by": self.qc_checked_by,
                    "qc_checked_on": self.qc_checked_on,
                    "security_status": "QC Cleared",
                },
                update_modified=False,
            )

            if self.loading_delivery_note:
                ldn_update = {
                    "qc_status": "QC Cleared",
                    "qc_cleared_by": self.qc_checked_by,
                    "qc_cleared_on": self.qc_checked_on,
                    "delivery_note_status": "QC Cleared",
                }
                # Auto-set coa_verified if there are approved batch COAs
                ldn_batch_rows = frappe.get_all(
                    "Loading DN Batch",
                    filters={"parent": self.loading_delivery_note},
                    fields=["coa"],
                )
                if ldn_batch_rows and all(r.coa for r in ldn_batch_rows):
                    all_approved = all(
                        frappe.db.get_value("APC COA", r.coa, "approval_status") == "Approved"
                        for r in ldn_batch_rows if r.coa
                    )
                    if all_approved:
                        ldn_update["coa_verified"] = 1
                        ldn_update["delivery_note_status"] = "COA Attached"

                frappe.db.set_value(
                    "Loading Delivery Note",
                    self.loading_delivery_note,
                    ldn_update,
                    update_modified=False,
                )

            self.notify_security_team_cleared()

        elif self.qc_status == "QC Rejected":
            frappe.db.set_value(
                "Security Inspection",
                self.security_inspection,
                {
                    "qc_status": "QC Rejected",
                    "security_status": "QC Rejected",
                },
                update_modified=False,
            )

            if self.loading_delivery_note:
                # Set to QC Rejected — NOT Cancelled; Security decides next action
                frappe.db.set_value(
                    "Loading Delivery Note",
                    self.loading_delivery_note,
                    {
                        "qc_status": "QC Rejected",
                        "delivery_note_status": "QC Rejected",
                    },
                    update_modified=False,
                )

            self.notify_security_team_rejected()

    def notify_security_team_cleared(self):
        try:
            security_users = role_user_emails(["Security Manager", "Security User"])

            if not security_users:
                return

            ldn_link = (
                f'<p><b>Loading Delivery Note:</b> '
                f'<a href="{frappe.utils.get_url()}/app/loading-delivery-note/{self.loading_delivery_note}">'
                f'{self.loading_delivery_note}</a></p>'
                if self.loading_delivery_note else ""
            )
            subject = f"QC Cleared: {self.security_inspection}"
            message = f"""
            <h3>QC Inspection Cleared</h3>
            <p><b>Security Inspection:</b> {self.security_inspection}</p>
            <p><b>QC Report Request:</b> {self.name}</p>
            <p><b>Container Number:</b> {self.container_number or 'N/A'}</p>
            <p><b>QC Checked By:</b> {self.qc_checked_by}</p>
            <p><b>QC Checked On:</b> {self.qc_checked_on}</p>
            {ldn_link}
            <p>The Loading Delivery Note is now cleared for Receivables reporting.</p>
            <br>
            <a href="{frappe.utils.get_url()}/app/security-inspection/{self.security_inspection}">
                View Security Inspection
            </a>
            """

            for user in security_users:
                frappe.sendmail(
                    recipients=user,
                    subject=subject,
                    message=message,
                    reference_doctype="QC Report Request",
                    reference_name=self.name
                )
        except Exception as e:
            frappe.log_error(f"QC Clear Notification Error: {str(e)}", "QC Report Request")

    def notify_security_team_rejected(self):
        try:
            security_users = role_user_emails(["Security Manager", "Security User"])

            if not security_users:
                return

            subject = f"QC REJECTED: {self.security_inspection} - Action Required"
            message = f"""
            <h3 style="color: red;">QC Inspection Rejected</h3>
            <p><b>Security Inspection:</b> {self.security_inspection}</p>
            <p><b>QC Report Request:</b> {self.name}</p>
            <p><b>Container Number:</b> {self.container_number or 'N/A'}</p>
            <p><b>QC Remarks:</b> {self.qc_remarks or 'No remarks provided'}</p>
            <p><b>Action Required:</b> Review and take corrective action.</p>
            <br>
            <a href="{frappe.utils.get_url()}/app/qc-report-request/{self.name}">
                View QC Report Request
            </a>
            """

            for user in security_users:
                frappe.sendmail(
                    recipients=user,
                    subject=subject,
                    message=message,
                    reference_doctype="QC Report Request",
                    reference_name=self.name
                )
        except Exception as e:
            frappe.log_error(f"QC Reject Notification Error: {str(e)}", "QC Report Request")


@frappe.whitelist()
def get_pending_qc_requests():
    return frappe.get_all(
        "QC Report Request",
        filters={"qc_status": "Pending QC"},
        fields=[
            "name",
            "security_inspection",
            "job_order",
            "container_number",
            "material_description",
            "requested_on",
            "requested_by"
        ],
        order_by="requested_on ASC"
    )
