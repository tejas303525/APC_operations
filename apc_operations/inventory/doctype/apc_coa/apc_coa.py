# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now, today

from apc_operations.inventory.qc_spec import has_spec_limit, optional_spec_float


FINAL_STATUSES = {"Approved", "Rejected", "Cancelled"}


class APCCOA(Document):
    def before_insert(self):
        if not self.coa_date:
            self.coa_date = today()

    def validate(self):
        self.validate_batch_link()
        self.sync_batch_product()
        self.validate_quality_inspection_link()
        self.sync_from_quality_inspection()
        self.evaluate_test_results()
        self.sync_legacy_status_fields()

    def before_submit(self):
        if self.approval_status == "Pending":
            frappe.throw(_("Cannot submit COA with Pending approval status"))

    def on_update(self):
        self.sync_to_batch()

    def validate_batch_link(self):
        """Ensure COA is linked to a valid APC Batch when one is selected."""
        if not self.batch:
            return

        if not frappe.db.exists("APC Batch", self.batch):
            frappe.throw(_("Linked batch {0} does not exist").format(self.batch))

    def sync_batch_product(self):
        """Populate certificate identity fields from APC Batch/Item when available."""
        if self.batch:
            batch = frappe.db.get_value(
                "APC Batch",
                self.batch,
                ["batch_number", "product", "manufacturing_date", "production_order"],
                as_dict=True,
            )
            if batch:
                self.batch_number = self.batch_number or batch.batch_number or self.batch
                self.product = self.product or batch.product
                self.manufacturing_date = self.manufacturing_date or batch.manufacturing_date
                self.production_order = self.production_order or batch.production_order

        if self.product and not self.product_name:
            self.product_name = frappe.db.get_value("Item", self.product, "item_name") or self.product

        if self.product and not self.product_group:
            item_group = frappe.db.get_value("Item", self.product, "item_group")
            self.product_group = normalize_product_group(item_group) or self.product_group

    def validate_quality_inspection_link(self):
        """Keep ERPNext Quality Inspection tied to the same item and ERPNext Batch."""
        if not self.quality_inspection:
            return

        inspection = frappe.db.get_value(
            "Quality Inspection",
            self.quality_inspection,
            ["item_code", "batch_no"],
            as_dict=True,
        )
        if not inspection:
            frappe.throw(_("Quality Inspection {0} does not exist").format(self.quality_inspection))

        if self.product and inspection.item_code and inspection.item_code != self.product:
            frappe.throw(_(
                "Quality Inspection {0} is for item {1}, but this COA is for item {2}"
            ).format(self.quality_inspection, inspection.item_code, self.product))

        erpnext_batch = frappe.db.get_value("APC Batch", self.batch, "erpnext_batch") if self.batch else None
        if erpnext_batch and inspection.batch_no and inspection.batch_no != erpnext_batch:
            frappe.throw(_(
                "Quality Inspection {0} is for ERPNext Batch {1}, but this COA batch is linked to {2}"
            ).format(self.quality_inspection, inspection.batch_no, erpnext_batch))

    def sync_from_quality_inspection(self):
        """Pull ERPNext Quality Inspection result into testing status, not final approval."""
        if not self.quality_inspection:
            return

        inspection = frappe.db.get_value(
            "Quality Inspection",
            self.quality_inspection,
            ["status", "inspected_by", "report_date", "remarks"],
            as_dict=True,
        )
        if not inspection:
            return

        if inspection.status == "Accepted" and self.status not in FINAL_STATUSES:
            self.status = "Passed"
            if inspection.remarks and not self.qc_remarks:
                self.qc_remarks = inspection.remarks
        elif inspection.status == "Rejected" and self.status not in {"Approved", "Cancelled"}:
            self.status = "Failed"
            self.approval_status = "Rejected"
            if not self.rejected_by:
                self.rejected_by = inspection.inspected_by or frappe.session.user
            if not self.rejected_date:
                self.rejected_date = now()
            if inspection.remarks and not self.rejection_reason:
                self.rejection_reason = inspection.remarks

    def evaluate_test_results(self):
        """Evaluate child result rows and derive the COA testing status."""
        if self.status in FINAL_STATUSES:
            return

        if self.approval_status == "Approved":
            # Preserve legacy imports/tests that set approval directly.
            self.status = "Approved"
            return
        if self.approval_status == "Rejected":
            self.status = "Rejected"
            return

        if not self.test_results:
            self.status = self.status or "Draft"
            return

        for row in self.test_results:
            self.evaluate_result_row(row)

        mandatory_rows = [row for row in self.test_results if row.mandatory]
        rows_to_check = mandatory_rows or list(self.test_results)

        if any(row.status == "Fail" for row in mandatory_rows):
            self.status = "Failed"
        elif rows_to_check and all(row.status == "Pass" for row in rows_to_check):
            self.status = "Passed"
        elif any(row.status in {"Pass", "Fail"} for row in self.test_results):
            self.status = "Pending Testing"
        else:
            self.status = "Draft"

    def evaluate_result_row(self, row):
        value_type = row.value_type or "Text"

        if value_type == "Numeric":
            self.evaluate_numeric_result(row)
            return

        result = (row.text_result or row.result_value or "").strip()
        standard = (row.specification or "").strip()

        if not result:
            row.status = "Not Checked"
        elif standard:
            row.status = "Pass" if result.casefold() == standard.casefold() else "Fail"
        elif row.status not in {"Pass", "Fail"}:
            row.status = "Not Checked"

    def evaluate_numeric_result(self, row):
        if row.numeric_result in (None, "") and not row.result_value:
            row.status = "Not Checked"
            return

        result = flt(row.numeric_result if row.numeric_result not in (None, "") else row.result_value)
        row.numeric_result = result
        row.result_value = row.result_value or str(result)

        if has_spec_limit(row.min_value) and result < flt(row.min_value):
            row.status = "Fail"
        elif has_spec_limit(row.max_value) and result > flt(row.max_value):
            row.status = "Fail"
        else:
            row.status = "Pass"

    def sync_legacy_status_fields(self):
        if self.status == "Approved":
            self.approval_status = "Approved"
            self.coa_status = "Approved"
            self.approved_date = self.approved_date or self.approved_on
        elif self.status == "Rejected":
            self.approval_status = "Rejected"
            self.coa_status = "Rejected"
        else:
            self.approval_status = self.approval_status or "Pending"
            self.coa_status = self.status

    def validate_immutable_after_approval(self):
        """Block saves on approved COA unless it is an amendment."""
        if self.is_new():
            return
        if self.amended_from:
            return
        old_status = frappe.db.get_value("APC COA", self.name, "approval_status")
        if old_status == "Approved" and self.has_value_changed("approval_status") is False:
            # Allow saving meta-only fields (nas_path, loading_delivery_note)
            return
        if old_status == "Approved" and frappe.session.user != "Administrator":
            changed = self.get_doc_before_save()
            if changed:
                immutable = ["test_results", "batch", "product", "batch_number"]
                for f in immutable:
                    if getattr(self, f, None) != getattr(changed, f, None):
                        frappe.throw(
                            _("COA {0} is Approved and cannot be modified. Use Amendment.").format(self.name)
                        )

    def sync_to_batch(self):
        """Sync final COA status to linked APC Batch."""
        if not self.batch:
            return

        if self.status == "Approved" or self.approval_status == "Approved":
            frappe.db.set_value(
                "APC Batch",
                self.batch,
                {
                    "quality_status": "QC Cleared",
                    "stock_status": "Available",
                    "coa_status": "Approved",
                    "linked_coa": self.name,
                    "qc_approved_by": self.approved_by,
                    "qc_approved_date": self.approved_on or self.approved_date,
                },
                update_modified=False,
            )
        elif self.status == "Rejected" or self.approval_status == "Rejected":
            frappe.db.set_value(
                "APC Batch",
                self.batch,
                {
                    "quality_status": "QC Rejected",
                    "stock_status": "Rejected",
                    "coa_status": "Rejected",
                    "batch_status": "Blocked",
                    "qc_approved_by": self.rejected_by,
                    "qc_approved_date": self.rejected_date,
                },
                update_modified=False,
            )

    def load_template_parameters(self, clear_existing=False):
        """Load COA Test Result rows from the selected COA Template."""
        if not self.coa_template:
            frappe.throw(_("Select a COA Template first"))

        if self.test_results and not clear_existing:
            frappe.throw(_("This COA already has test results. Confirm before replacing them."))

        template = frappe.get_doc("COA Template", self.coa_template)
        if not template.active:
            frappe.throw(_("COA Template {0} is inactive").format(template.name))

        self.set("test_results", [])
        for row in sorted(template.parameters, key=lambda item: item.sequence or item.idx):
            self.append("test_results", {
                "parameter": row.parameter,
                "parameter_name": row.parameter_name,
                "uom": row.uom,
                "value_type": row.value_type,
                "min_value": optional_spec_float(row.min_value),
                "max_value": optional_spec_float(row.max_value),
                "specification": row.specification,
                "mandatory": row.mandatory,
                "status": "Not Checked",
                "method": row.method,
            })

        if self.status in {"Draft", "Passed", "Failed"}:
            self.status = "Pending Testing"

    @frappe.whitelist()
    def load_template(self, clear_existing=False):
        self.load_template_parameters(clear_existing=cint(clear_existing))
        self.save()
        return {"success": True, "rows": len(self.test_results)}

    def validate_checklist_complete(self):
        """Ensure all mandatory test result rows have passed before approval is allowed."""
        if not self.test_results:
            frappe.throw(_("No test results found. Load a COA Template and fill in test results before approving."))

        mandatory_rows = [r for r in self.test_results if r.mandatory]
        if not mandatory_rows:
            return

        incomplete = [r for r in mandatory_rows if r.status not in ("Pass",)]
        if incomplete:
            param_names = ", ".join(r.parameter_name or r.parameter for r in incomplete)
            frappe.throw(
                _("The following mandatory test parameters have not passed: {0}").format(param_names)
            )

    @frappe.whitelist()
    def approve_coa(self, remarks=None):
        """Approve this COA after mandatory test results pass. Only Quality Manager or System Manager may approve."""
        if frappe.session.user != "Administrator":
            allowed_roles = {"Quality Manager", "System Manager"}
            user_roles = set(frappe.get_roles(frappe.session.user))
            if not allowed_roles.intersection(user_roles):
                frappe.throw(
                    _("Only a Quality Manager or System Manager can approve a COA."),
                    frappe.PermissionError,
                )

        self.reload()
        self.evaluate_test_results()
        self.validate_checklist_complete()

        if self.status not in ("Passed",):
            frappe.throw(_("Only a COA with status 'Passed' can be approved. Current status: {0}").format(self.status))

        self.status = "Approved"
        self.approval_status = "Approved"
        self.coa_status = "Approved"
        self.approved_by = frappe.session.user
        self.approved_on = now()
        self.approved_date = self.approved_on
        if remarks:
            self.qc_remarks = remarks
        self.save()

        # Notify NAS save (non-blocking)
        try:
            from apc_operations.services.nas_service import save_coa_to_nas
            save_coa_to_nas(self.name)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "COA NAS Save")

        frappe.msgprint(_("COA {0} has been approved").format(self.name), indicator="green", alert=True)
        return {"success": True, "message": "COA approved"}

    @frappe.whitelist()
    def reject_coa(self, reason=None):
        if frappe.session.user != "Administrator":
            allowed_roles = {"Quality Manager", "System Manager"}
            user_roles = set(frappe.get_roles(frappe.session.user))
            if not allowed_roles.intersection(user_roles):
                frappe.throw(
                    _("Only a Quality Manager or System Manager can reject a COA."),
                    frappe.PermissionError,
                )

        if self.status == "Rejected" or self.approval_status == "Rejected":
            frappe.throw(_("COA is already rejected"))

        self.status = "Rejected"
        self.approval_status = "Rejected"
        self.coa_status = "Rejected"
        self.rejected_by = frappe.session.user
        self.rejected_date = now()
        if reason:
            self.rejection_reason = reason
        self.save()

        frappe.msgprint(_("COA {0} has been rejected").format(self.name), indicator="red", alert=True)
        return {"success": True, "message": "COA rejected"}


def normalize_product_group(item_group):
    if not item_group:
        return None

    item_group_lc = item_group.casefold()
    for product_group in ["Solvent", "Oil", "Lubricant", "Plasticizer", "White Oil", "Petroleum Jelly", "Other"]:
        if product_group.casefold() in item_group_lc:
            return product_group
    return None


@frappe.whitelist()
def get_template_parameters(coa_template):
    template = frappe.get_doc("COA Template", coa_template)
    if not template.active:
        frappe.throw(_("COA Template {0} is inactive").format(template.name))

    return [
        {
            "parameter": row.parameter,
            "parameter_name": row.parameter_name,
            "uom": row.uom,
            "value_type": row.value_type,
            "min_value": optional_spec_float(row.min_value),
            "max_value": optional_spec_float(row.max_value),
            "specification": row.specification,
            "mandatory": row.mandatory,
            "status": "Not Checked",
            "method": row.method,
        }
        for row in sorted(template.parameters, key=lambda item: item.sequence or item.idx)
    ]


@frappe.whitelist()
def find_matching_coa_template(product_name: str | None = None, product_group: str | None = None) -> str | None:
    """Standard test-parameter template for this product, if one has been set
    up - Product Name + Product Group is the intended match; falls back to
    Product Name alone so a template created before a group was settled on
    still gets picked up."""
    if not product_name:
        return None

    if product_group:
        name = frappe.db.get_value(
            "COA Template",
            {"product_name": product_name, "product_group": product_group, "active": 1},
            "name",
        )
        if name:
            return name

    return frappe.db.get_value(
        "COA Template", {"product_name": product_name, "active": 1}, "name"
    )


@frappe.whitelist()
def get_coa_for_batch(batch):
    """Get the approved COA for a batch."""
    return frappe.db.get_value(
        "APC COA",
        {"batch": batch, "approval_status": "Approved"},
        ["name", "coa_number", "approval_status", "approved_by", "approved_on", "approved_date", "coa_pdf"],
        as_dict=True,
    )


@frappe.whitelist()
def get_batch_coas(product=None, batch=None):
    """Get approved COAs for a product or batch."""
    filters = {"approval_status": "Approved"}

    if batch:
        filters["batch"] = batch
    elif product:
        filters["product"] = product

    return frappe.get_all(
        "APC COA",
        filters=filters,
        fields=["name", "coa_number", "batch", "batch_number", "product", "product_name", "approved_on", "coa_pdf"],
        order_by="approved_on DESC",
    )


@frappe.whitelist()
def sync_quality_inspection_status(coa):
    doc = frappe.get_doc("APC COA", coa)
    doc.sync_from_quality_inspection()
    doc.save()
    return {
        "success": True,
        "approval_status": doc.approval_status,
        "status": doc.status,
    }


def sync_apc_coa_from_quality_inspection(doc, method=None):
    """Hook target for ERPNext Quality Inspection status changes."""
    linked_coas = frappe.get_all(
        "APC COA",
        filters={"quality_inspection": doc.name},
        pluck="name",
    )

    for coa_name in linked_coas:
        coa = frappe.get_doc("APC COA", coa_name)
        coa.sync_from_quality_inspection()
        coa.save(ignore_permissions=True)


def on_update_coa(doc, method):
    doc.sync_to_batch()


# ---------------------------------------------------------------------------
# QC Console — DO/LDN-driven COA creation (DESIGN_CONCEPT.md Section 9.9)
# ---------------------------------------------------------------------------


def create_apc_coa_from_qc(qc_report_request_name):
    """Create an APC COA from a cleared QC Report Request.

    This is the DO/LDN-driven COA path used by the new QC Console.
    The function is idempotent: if a COA already exists for the same
    batch + QC Report Request, it is returned unchanged. The existing
    ``Quality Inspection -> APC COA`` hook (
    ``sync_apc_coa_from_quality_inspection``) is intentionally untouched.

    Args:
        qc_report_request_name: Name of the ``QC Report Request`` doc.

    Returns:
        The APC COA document name (existing or newly created), or
        ``None`` if no batch is linked to the QC request.
    """
    if not qc_report_request_name:
        return None

    qcr = frappe.get_doc("QC Report Request", qc_report_request_name)

    # If COA is already linked, return it.
    if qcr.coa and frappe.db.exists("APC COA", qcr.coa):
        return qcr.coa

    batch = qcr.batch
    if not batch:
        # The QC console flow requires a batch to attach the COA.
        # Return None instead of raising so callers can fall back.
        return None

    # Idempotency: look for a COA for the same batch first; reuse if present.
    existing = frappe.db.get_value(
        "APC COA",
        {"batch": batch},
        "name",
    )
    if existing:
        if qcr.coa != existing:
            frappe.db.set_value(
                "QC Report Request",
                qcr.name,
                "coa",
                existing,
                update_modified=False,
            )
        # Also link COA back to the LDN for traceability.
        if qcr.loading_delivery_note:
            frappe.db.set_value(
                "APC COA",
                existing,
                "loading_delivery_note",
                qcr.loading_delivery_note,
                update_modified=False,
            )
        return existing

    # Create a fresh COA tied to the batch and QC artefacts.
    batch_data = frappe.db.get_value(
        "APC Batch",
        batch,
        ["batch_number", "product", "production_order", "manufacturing_date"],
        as_dict=True,
    ) or {}

    coa = frappe.new_doc("APC COA")
    coa.batch = batch
    if batch_data.get("batch_number"):
        coa.batch_number = batch_data["batch_number"]
    if batch_data.get("product"):
        coa.product = batch_data["product"]
    if batch_data.get("production_order"):
        coa.production_order = batch_data["production_order"]
    if batch_data.get("manufacturing_date"):
        coa.manufacturing_date = batch_data["manufacturing_date"]
    coa.job_order = qcr.job_order
    coa.loading_delivery_note = qcr.loading_delivery_note
    coa.coa_date = today()
    coa.status = "Approved"
    coa.approval_status = "Approved"
    coa.approved_by = frappe.session.user
    coa.approved_date = today()
    coa.approved_on = now()
    coa.qc_remarks = qcr.qc_remarks
    coa.remarks = _("Auto-generated from QC Report Request {0}").format(qcr.name)
    coa.insert(ignore_permissions=True)

    frappe.db.set_value(
        "QC Report Request",
        qcr.name,
        "coa",
        coa.name,
        update_modified=False,
    )

    if qcr.loading_delivery_note:
        try:
            frappe.get_doc(
                {
                    "doctype": "Comment",
                    "comment_type": "Comment",
                    "reference_doctype": "Loading Delivery Note",
                    "reference_name": qcr.loading_delivery_note,
                    "content": _("APC COA generated: {0}").format(coa.name),
                }
            ).insert(ignore_permissions=True)
        except Exception:
            pass

    return coa.name
