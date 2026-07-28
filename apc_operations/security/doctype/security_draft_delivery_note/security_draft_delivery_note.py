# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SecurityDraftDeliveryNote(Document):
    def validate(self):
        from apc_operations.services.customer_link_service import ensure_sddn_customer_links

        ensure_sddn_customer_links(self)
        self.validate_unique_transport_schedule()

    def validate_unique_transport_schedule(self):
        if not self.transport_schedule:
            return

        existing = frappe.db.exists(
            "Security Draft Delivery Note",
            {
                "transport_schedule": self.transport_schedule,
                "name": ["!=", self.name],
            },
        )
        if existing:
            frappe.throw(
                _("Security Draft Delivery Note {0} already exists for Transport Schedule {1}").format(
                    existing, self.transport_schedule
                )
            )

    def on_update(self):
        self.sync_status_to_transport()

    def sync_status_to_transport(self):
        if not self.transport_schedule:
            return

        frappe.db.set_value(
            "Transport Schedule",
            self.transport_schedule,
            {
                "security_draft_delivery_note": self.name,
                "security_status": self.security_status,
            },
            update_modified=False,
        )

    @frappe.whitelist()
    def promote_to_inspection(self):
        """Promote this Draft DN to a Security Inspection for the security team to process."""
        if self.security_status != "Pending Review":
            frappe.throw(
                _("Only Draft DNs in Pending Review can be promoted to Security Inspection")
            )

        from apc_operations.security.doctype.security_inspection.security_inspection import (
            create_security_inspection_from_draft_dn,
        )

        result = create_security_inspection_from_draft_dn(self.name)
        return result
