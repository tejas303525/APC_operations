# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt, today, getdate
from frappe import _
from apc_operations.services.email_recipients import role_user_emails


class APCBatch(Document):
    def validate(self):
        self.validate_batch_number()
        self.validate_erpnext_batch_link()
        self.calculate_available_quantity()
        self.validate_dates()
        self.update_batch_status()
        self.update_stock_status_from_qc()
        self.update_coa_status_field()

    def before_insert(self):
        if not self.batch_number:
            self.batch_number = self.name

    def after_insert(self):
        if not self.batch_number or self.batch_number != self.name:
            self.db_set("batch_number", self.name, update_modified=False)
        self.ensure_erpnext_batch()

    def validate_batch_number(self):
        if self.batch_number and self.is_new():
            existing = frappe.db.exists("APC Batch", {"batch_number": self.batch_number})
            if existing and existing != self.name:
                frappe.throw(_("Batch Number {0} already exists").format(self.batch_number))

    def calculate_available_quantity(self):
        """Calculate available quantity based on batch quantity minus allocated
        minus dispatched.

        Must account for dispatched_quantity too, not just allocated_quantity —
        otherwise any full document save (as opposed to the db_set() calls
        deduct_dispatch_qty() uses) silently un-deducts already-dispatched
        stock back into available_quantity, letting the same batch be
        allocated and dispatched again without limit.
        """
        if not self.allocated_quantity:
            self.allocated_quantity = 0

        available = flt(self.batch_quantity) - flt(self.allocated_quantity) - flt(self.dispatched_quantity)
        if available < 0:
            frappe.throw(_("Allocated + dispatched quantity cannot exceed batch quantity"))

        self.available_quantity = available

    def validate_dates(self):
        """Validate manufacturing and expiry dates."""
        if self.expiry_date and self.manufacturing_date:
            if getdate(self.expiry_date) <= getdate(self.manufacturing_date):
                frappe.throw(_("Expiry date must be after manufacturing date"))

        if self.manufacturing_date and getdate(self.manufacturing_date) > getdate(today()):
            frappe.throw(_("Manufacturing date cannot be in the future"))

    def update_batch_status(self):
        """Auto-update batch status based on quantity and dates."""
        if self.batch_status in ["Cancelled", "Depleted"]:
            return

        if flt(self.available_quantity) <= 0 and flt(self.allocated_quantity) <= 0:
            self.batch_status = "Depleted"
            return

        if self.expiry_date and getdate(self.expiry_date) <= getdate(today()):
            self.batch_status = "Expired"
            return

        if self.quality_status in ["Rejected", "QC Rejected"]:
            self.batch_status = "Blocked"
            return

    def update_stock_status_from_qc(self):
        """Set stock_status based on quality_status changes."""
        if self.quality_status in ("QC Cleared", "Approved"):
            if self.stock_status == "QC Hold":
                self.stock_status = "Available"
        elif self.quality_status in ("QC Rejected", "Rejected"):
            self.stock_status = "Rejected"

    def update_coa_status_field(self):
        """Compute coa_status from linked_coa."""
        if not self.linked_coa:
            self.coa_status = "Not Generated"
            return

        coa_approval = frappe.db.get_value("APC COA", self.linked_coa, "approval_status")
        if coa_approval == "Approved":
            self.coa_status = "Approved"
        elif coa_approval == "Rejected":
            self.coa_status = "Rejected"
        else:
            status = frappe.db.get_value("APC COA", self.linked_coa, "status")
            if status in ("Draft", "Pending Testing"):
                self.coa_status = "Pending"
            elif status in ("Passed", "Failed"):
                self.coa_status = "Generated"
            else:
                self.coa_status = "Pending"

    def on_update(self):
        self.ensure_erpnext_batch()
        self.sync_coa_status()
        self.check_allocation_limits()
        self.update_coa_status_field()

    def validate_erpnext_batch_link(self):
        """Keep the ERPNext Batch bridge tied to the same product."""
        if not self.erpnext_batch:
            return

        erpnext_item = frappe.db.get_value("Batch", self.erpnext_batch, "item")
        if not erpnext_item:
            frappe.throw(_("ERPNext Batch {0} does not exist").format(self.erpnext_batch))

        if erpnext_item != self.product:
            frappe.throw(_(
                "ERPNext Batch {0} belongs to item {1}, but this APC Batch is for item {2}"
            ).format(self.erpnext_batch, erpnext_item, self.product))

    def ensure_erpnext_batch(self):
        """Create or sync the linked ERPNext Batch record.

        APC Batch remains the operational allocation wrapper. ERPNext Batch is
        used as the stable stock backbone identifier.
        """
        if self.flags.in_erpnext_batch_sync or not self.product:
            return

        if not frappe.db.table_exists("Batch"):
            return

        self.flags.in_erpnext_batch_sync = True
        try:
            self.ensure_item_batch_tracking()
            erpnext_batch = self.erpnext_batch or frappe.db.exists("Batch", self.batch_number or self.name)

            if erpnext_batch:
                self.sync_erpnext_batch(erpnext_batch)
            else:
                erpnext_batch = self.create_erpnext_batch()

            if erpnext_batch and self.erpnext_batch != erpnext_batch:
                self.db_set("erpnext_batch", erpnext_batch, update_modified=False)
        finally:
            self.flags.in_erpnext_batch_sync = False

    def ensure_item_batch_tracking(self):
        """APC-created batches require the ERPNext item to allow batches."""
        if not frappe.db.exists("Item", self.product):
            frappe.throw(_("Item {0} does not exist").format(self.product))

        if not frappe.db.get_value("Item", self.product, "has_batch_no"):
            frappe.db.set_value("Item", self.product, "has_batch_no", 1, update_modified=False)

    def create_erpnext_batch(self):
        batch = frappe.new_doc("Batch")
        batch.batch_id = self.batch_number or self.name
        batch.item = self.product
        batch.manufacturing_date = self.manufacturing_date
        batch.expiry_date = self.expiry_date
        batch.reference_doctype = "APC Batch"
        batch.reference_name = self.name
        batch.description = self.get_erpnext_batch_description()
        batch.insert(ignore_permissions=True)
        return batch.name

    def sync_erpnext_batch(self, erpnext_batch):
        erpnext_item = frappe.db.get_value("Batch", erpnext_batch, "item")
        if erpnext_item != self.product:
            frappe.throw(_(
                "ERPNext Batch {0} belongs to item {1}, but this APC Batch is for item {2}"
            ).format(erpnext_batch, erpnext_item, self.product))

        frappe.db.set_value(
            "Batch",
            erpnext_batch,
            {
                "manufacturing_date": self.manufacturing_date,
                "expiry_date": self.expiry_date,
                "reference_doctype": "APC Batch",
                "reference_name": self.name,
                "description": self.get_erpnext_batch_description(),
            },
            update_modified=False,
        )

    def get_erpnext_batch_description(self):
        parts = []
        if self.grade:
            parts.append(_("Grade: {0}").format(self.grade))
        if self.specification:
            parts.append(_("Specification: {0}").format(self.specification))
        if self.packaging_type:
            parts.append(_("Packaging: {0}").format(self.packaging_type))
        return "\n".join(parts)

    def sync_coa_status(self):
        """Sync quality status from linked COA."""
        if self.linked_coa:
            coa = frappe.get_cached_doc("APC COA", self.linked_coa)
            if coa.approval_status == "Approved" and self.quality_status != "Approved":
                self.db_set("quality_status", "Approved", update_modified=False)
                self.db_set("qc_approved_by", coa.approved_by, update_modified=False)
                self.db_set("qc_approved_date", coa.approved_date, update_modified=False)

    def check_allocation_limits(self):
        """Ensure allocated quantity doesn't exceed available after update."""
        total_allocated = frappe.db.sql("""
            SELECT SUM(allocated_quantity)
            FROM `tabAPC Batch Allocation Detail`
            WHERE batch = %s AND docstatus < 2
        """, (self.name,))[0][0] or 0

        if flt(total_allocated) > flt(self.batch_quantity):
            frappe.throw(_(
                "Total allocated quantity ({0}) exceeds batch quantity ({1}). "
                "Release some allocations before proceeding."
            ).format(total_allocated, self.batch_quantity))

    def allocate_quantity(self, quantity):
        """Allocate quantity to this batch. Returns True if successful."""
        if self.batch_status not in ["Active", "On Hold"]:
            frappe.throw(_("Cannot allocate from batch with status: {0}").format(self.batch_status))

        if self.quality_status not in ("Approved", "QC Cleared"):
            frappe.throw(_("Cannot allocate from batch without approved COA"))

        if flt(quantity) > flt(self.available_quantity):
            frappe.throw(_(
                "Insufficient available quantity. Requested: {0}, Available: {1}"
            ).format(quantity, self.available_quantity))

        new_allocated = flt(self.allocated_quantity) + flt(quantity)
        new_available = flt(self.batch_quantity) - new_allocated
        self.db_set("allocated_quantity", new_allocated, update_modified=False)
        self.db_set("available_quantity", new_available, update_modified=False)
        # Only mark the batch Reserved once it is actually fully allocated -
        # a partial allocation still has free stock left and must stay
        # visible to get_available_batches() (which hard-filters on
        # stock_status == "Available"), or the remainder becomes invisible
        # to FIFO until the batch is released all the way back to zero.
        if new_available <= 0 and self.stock_status == "Available":
            self.db_set("stock_status", "Reserved", update_modified=False)

        return True

    def deduct_dispatch_qty(self, quantity):
        """Deduct dispatched quantity and update stock_status to Dispatched."""
        if flt(quantity) > flt(self.allocated_quantity):
            frappe.throw(_("Cannot dispatch more than allocated quantity for batch {0}").format(self.name))

        new_allocated = flt(self.allocated_quantity) - flt(quantity)
        new_dispatched = flt(self.dispatched_quantity) + flt(quantity)
        if new_allocated + new_dispatched > flt(self.batch_quantity) + 0.0001:
            frappe.throw(
                _(
                    "Dispatching {0} would take batch {1}'s allocated+dispatched total to {2}, "
                    "exceeding its batch quantity of {3}."
                ).format(quantity, self.name, new_allocated + new_dispatched, self.batch_quantity)
            )
        new_available = flt(self.available_quantity)

        self.db_set("allocated_quantity", new_allocated, update_modified=False)
        self.db_set("dispatched_quantity", new_dispatched, update_modified=False)
        self.db_set("available_quantity", new_available, update_modified=False)

        if new_allocated <= 0 and new_available <= 0:
            self.db_set("stock_status", "Dispatched", update_modified=False)
            self.db_set("batch_status", "Depleted", update_modified=False)
        elif new_allocated > 0:
            self.db_set("stock_status", "Reserved", update_modified=False)

        return True

    def auto_create_coa(self):
        """Auto-create APC COA for this batch after production. Called from after_insert."""
        if frappe.db.exists("APC COA", {"batch": self.name}):
            return

        coa = frappe.new_doc("APC COA")
        coa.batch = self.name
        coa.batch_number = self.batch_number or self.name
        coa.product = self.product
        coa.job_order = self.job_order
        coa.production_order = self.production_order
        coa.manufacturing_date = self.manufacturing_date
        coa.status = "Pending Testing"

        if self.product:
            coa.product_name = frappe.db.get_value("Item", self.product, "item_name") or self.product

        template = self._find_coa_template()
        if template:
            coa.coa_template = template
            coa.insert(ignore_permissions=True)
            coa.load_template_parameters()
            coa.save(ignore_permissions=True)
        else:
            coa.insert(ignore_permissions=True)

        self.db_set("linked_coa", coa.name, update_modified=False)
        self.db_set("coa_status", "Pending", update_modified=False)

        self.notify_qc_on_create(coa.name)
        return coa.name

    def _find_coa_template(self):
        """Find a COA Template matching this batch's product or product group."""
        if not self.product:
            return None

        item_group = frappe.db.get_value("Item", self.product, "item_group")

        template = frappe.db.get_value(
            "COA Template",
            {"product_name": self.product, "active": 1},
            "name"
        )
        if template:
            return template

        if item_group:
            template = frappe.db.get_value(
                "COA Template",
                {"product_group": item_group, "active": 1},
                "name"
            )
        return template

    def notify_qc_on_create(self, coa_name):
        """Send email notification to QC team when a new batch needs QC."""
        try:
            qc_users = frappe.get_all(
                "Has Role",
                filters={"role": ["in", ["Quality Manager", "Quality User"]]},
                fields=["parent"],
                distinct=True,
            )
            if not qc_users:
                return

            subject = _("New Batch Requires QC: {0}").format(self.batch_number or self.name)
            message = """
            <h3>New Batch Requires QC Testing</h3>
            <p><b>Batch:</b> {batch}</p>
            <p><b>Product:</b> {product}</p>
            <p><b>Grade:</b> {grade}</p>
            <p><b>Quantity:</b> {qty} {uom}</p>
            <p><b>Manufacturing Date:</b> {mfg_date}</p>
            <p><b>Production Order:</b> {po}</p>
            <p><b>COA:</b> {coa}</p>
            """.format(
                batch=self.batch_number or self.name,
                product=self.product or "",
                grade=self.grade or "",
                qty=self.batch_quantity,
                uom=self.uom or "",
                mfg_date=self.manufacturing_date or "",
                po=self.production_order or "N/A",
                coa=coa_name,
            )

            qc_emails = role_user_emails(["Quality Manager", "Quality User"])
            for user in qc_emails:
                frappe.sendmail(
                    recipients=user,
                    subject=subject,
                    message=message,
                    reference_doctype="APC COA",
                    reference_name=coa_name,
                )
        except Exception:
            frappe.log_error(frappe.get_traceback(), "APC Batch QC Notification")

    def release_allocation(self, quantity):
        """Release allocated quantity from this batch."""
        if flt(quantity) > flt(self.allocated_quantity):
            frappe.throw(_("Cannot release more than allocated quantity"))

        new_allocated = flt(self.allocated_quantity) - flt(quantity)
        new_available = flt(self.batch_quantity) - new_allocated
        self.db_set("allocated_quantity", new_allocated, update_modified=False)
        self.db_set("available_quantity", new_available, update_modified=False)

        if new_allocated == 0 and self.batch_status == "Depleted":
            self.db_set("batch_status", "Active", update_modified=False)

        # Mirror of the allocate_quantity() fix: any free stock at all should
        # make the batch visible to FIFO again, not only a full release back
        # to zero allocated.
        if new_available > 0 and self.stock_status == "Reserved":
            self.db_set("stock_status", "Available", update_modified=False)

        return True

    def get_free_stock(self):
        """Return free stock (available - any additional constraints)."""
        return flt(self.available_quantity)

    def is_available_for_allocation(self, grade=None, specification=None, packaging_type=None):
        """Check if batch is available for allocation with given criteria."""
        if self.batch_status not in ["Active", "On Hold"]:
            return False, "Batch status not active"

        if self.quality_status not in ("Approved", "QC Cleared"):
            return False, "COA not approved"

        if self.stock_status not in ("Available", "Reserved"):
            return False, "Stock not available"

        if flt(self.available_quantity) <= 0:
            return False, "No available quantity"

        if grade and self.grade != grade:
            return False, "Grade mismatch"

        if specification and self.specification != specification:
            return False, "Specification mismatch"

        if packaging_type and self.packaging_type != packaging_type:
            return False, "Packaging type mismatch"

        return True, "Available"


@frappe.whitelist()
def get_available_batches(product, grade=None, specification=None, packaging_type=None, warehouse=None, limit=100):
    """Get list of available batches for allocation using FIFO rules."""
    filters = [
        ["product", "=", product],
        ["batch_status", "in", ["Active", "On Hold"]],
        ["quality_status", "in", ["Approved", "QC Cleared"]],
        ["stock_status", "in", ["Available", "Reserved"]],
        ["available_quantity", ">", 0],
    ]

    if grade:
        filters.append(["grade", "=", grade])
    if specification:
        filters.append(["specification", "=", specification])
    if packaging_type:
        filters.append(["packaging_type", "=", packaging_type])
    if warehouse:
        filters.append(["warehouse", "=", warehouse])

    batches = frappe.get_all(
        "APC Batch",
        filters=filters,
        fields=[
            "name", "batch_number", "product", "grade", "specification",
            "packaging_type", "batch_quantity", "available_quantity",
            "allocated_quantity", "manufacturing_date", "expiry_date",
            "warehouse", "quality_status", "linked_coa", "production_order",
            "erpnext_batch"
        ],
        order_by="manufacturing_date ASC, creation ASC",
        limit_page_length=limit
    )

    return batches


@frappe.whitelist()
def calculate_free_stock(batch_name):
    """Calculate free stock for a batch."""
    batch = frappe.get_doc("APC Batch", batch_name)
    return batch.get_free_stock()


@frappe.whitelist()
def get_batch_allocation_rows(batch_name, limit=50):
    """Return active APC Batch Allocation Detail rows for a batch.

    APC Batch Allocation Detail is a child table (istable:1), so Frappe's
    permission check for a direct frappe.db.get_list() on it always defers
    to the parent doctype and requires an explicit parent_doctype - which
    the standard frappe.client.get_list whitelisted endpoint has no way to
    supply. That made the direct client-side query in apc_batch.js fail
    with "Insufficient Permission" for every non-Administrator user
    regardless of role. Routing through here checks read access on the
    APC Batch itself (via get_doc) and then queries the child table with
    ignore_permissions=True, since that access has already been verified.
    """
    frappe.get_doc("APC Batch", batch_name)
    return frappe.get_all(
        "APC Batch Allocation Detail",
        filters={
            "batch": batch_name,
            "status": ["in", ["Allocated", "Partially Dispatched"]],
        },
        fields=["parent", "allocated_quantity", "dispatched_quantity", "remaining_quantity"],
        limit=limit,
        ignore_permissions=True,
    )


@frappe.whitelist()
def create_coa_for_batch(batch_name):
    """Manually trigger COA creation for a batch that doesn't have one."""
    batch = frappe.get_doc("APC Batch", batch_name)
    if batch.linked_coa:
        frappe.throw(_("APC Batch {0} already has a linked COA: {1}").format(batch_name, batch.linked_coa))
    coa_name = batch.auto_create_coa()
    return {"success": True, "coa": coa_name}


# Hook event handlers
def on_update_batch(doc, method):
    """Hook handler for APC Batch on_update event."""
    if doc.batch_status == "Depleted" and flt(doc.available_quantity) > 0:
        doc.db_set("batch_status", "Active", update_modified=False)


def after_insert_batch(doc, method):
    """Hook handler for APC Batch after_insert: auto-create COA when from production."""
    if doc.created_from_production:
        if frappe.flags.get("in_auto_coa_creation"):
            return
        frappe.flags.in_auto_coa_creation = True
        try:
            doc.auto_create_coa()
        except Exception:
            frappe.log_error(frappe.get_traceback(), "APC Batch Auto COA Creation")
        finally:
            frappe.flags.in_auto_coa_creation = False
