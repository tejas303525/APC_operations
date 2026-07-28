# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now


class PreCheckClearance(Document):
    """Audit-trailed pre-check sign-off before a truck is allowed to load.

    Two independent sign-offs are required:

    * QC pre-check  \u2014 editable by Quality Manager / Quality User (permlevel 1).
    * Security pre-check \u2014 editable by Security Manager / Security User (permlevel 2).

    When both reach ``Passed``, ``overall_status`` flips to ``Authorized`` and
    the linked Delivery Order is moved to ``Pre-Check Cleared`` so the loading
    bay knows the truck is good to go.
    """

    def validate(self):
        self._stamp_qc_audit()
        self._stamp_security_audit()
        self._recompute_overall_status()

    def on_update(self):
        self._propagate_to_delivery_order()

    def _stamp_qc_audit(self):
        prev = self.get_doc_before_save()
        prev_status = prev.qc_status if prev else None
        if self.qc_pre_check_status != "On Hold":
            if self.qc_status == "Passed":
                self.qc_pre_check_status = "Passed"
            elif self.qc_status == "Failed":
                self.qc_pre_check_status = "Failed"
            elif self.qc_status == "Pending" and not self.qc_pre_check_status:
                self.qc_pre_check_status = "Pending"
        if self.qc_status and self.qc_status != prev_status and self.qc_status != "Pending":
            self.qc_checked_by = frappe.session.user
            self.qc_check_time = now()

    def _stamp_security_audit(self):
        prev = self.get_doc_before_save()
        prev_status = prev.security_status if prev else None
        if self.security_status and self.security_status != prev_status and self.security_status != "Pending":
            self.security_checked_by = frappe.session.user
            self.security_check_time = now()

    def _recompute_overall_status(self):
        if self.qc_pre_check_status == "On Hold":
            self.overall_status = "Blocked"
            if not self.block_reason:
                self.block_reason = self.failure_reason or self.qc_remarks or _("QC pre-check on hold")
        elif self.qc_status == "Passed" and self.security_status == "Passed":
            self.overall_status = "Authorized"
        elif self.qc_status == "Failed" or self.security_status == "Failed":
            self.overall_status = "Blocked"
            if not self.block_reason:
                bits = []
                if self.qc_status == "Failed":
                    bits.append(_("QC failed: {0}").format(self.failure_reason or self.qc_remarks or "—"))
                if self.security_status == "Failed":
                    bits.append(_("Security failed: {0}").format(self.security_remarks or "—"))
                self.block_reason = " | ".join(bits)
        else:
            self.overall_status = "Pending"

    def _propagate_to_delivery_order(self):
        if not self.delivery_order:
            return
        from apc_operations.shipping.doctype.delivery_order.delivery_order import (
            mark_do_pre_check_cleared,
        )
        from apc_operations.shipping.services.dispatch_lifecycle_service import (
            set_delivery_order_operational_status,
            sync_dispatch_lifecycle_status,
        )

        if self.overall_status == "Authorized":
            mark_do_pre_check_cleared(self.delivery_order)
            from apc_operations.shipping.services.import_grn_service import (
                maybe_ensure_import_grn_after_precheck_authorized,
            )

            maybe_ensure_import_grn_after_precheck_authorized(
                self.delivery_order, pcc_name=self.name
            )
        elif self.qc_pre_check_status == "On Hold":
            set_delivery_order_operational_status(
                self.delivery_order, "On Hold", force=True, update_modified=False
            )
        elif self.qc_status == "Failed":
            set_delivery_order_operational_status(
                self.delivery_order, "QC Pre-check Failed", force=True, update_modified=False
            )
            frappe.db.set_value(
                "Delivery Order",
                self.delivery_order,
                "do_status",
                "Pre-Check Pending",
                update_modified=False,
            )
        elif self.overall_status == "Blocked":
            frappe.db.set_value(
                "Delivery Order",
                self.delivery_order,
                "do_status",
                "Pre-Check Pending",
                update_modified=False,
            )
            sync_dispatch_lifecycle_status(self.delivery_order, update_modified=False)
        else:
            sync_dispatch_lifecycle_status(self.delivery_order, update_modified=False)
