# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt, now, today
from frappe import _


class APCBatchAllocation(Document):
    def validate(self):
        self.validate_allocation_quantities()
        self.calculate_totals()
        self.update_detail_status()

    def before_insert(self):
        if not self.allocation_number:
            self.allocation_number = self.name
        if not self.allocation_date:
            self.allocation_date = today()

    def after_insert(self):
        if not self.allocation_number or self.allocation_number != self.name:
            self.db_set("allocation_number", self.name, update_modified=False)

    def validate_allocation_quantities(self):
        """Validate that allocated quantities don't exceed batch availability."""
        for detail in self.allocation_details:
            if detail.batch:
                batch = frappe.get_cached_doc("APC Batch", detail.batch)
                if detail.allocated_quantity > batch.available_quantity:
                    frappe.throw(_(
                        "Allocated quantity ({0}) exceeds available quantity ({1}) for batch {2}"
                    ).format(detail.allocated_quantity, batch.available_quantity, batch.name))

                if batch.batch_status in ["Blocked", "Expired", "Cancelled", "Depleted"]:
                    frappe.throw(_("Cannot allocate from batch with status: {0}").format(batch.batch_status))

                if batch.quality_status not in ("Approved", "QC Cleared"):
                    frappe.throw(_("Cannot allocate from batch without approved quality clearance"))

    def calculate_totals(self):
        """Calculate totals from allocation details."""
        total_required = 0
        total_allocated = 0
        total_dispatched = 0

        for detail in self.allocation_details:
            total_required += flt(detail.required_quantity)
            total_allocated += flt(detail.allocated_quantity)
            total_dispatched += flt(detail.dispatched_quantity)

        self.total_required_quantity = total_required
        self.total_allocated_quantity = total_allocated
        self.total_dispatched_quantity = total_dispatched

    def update_detail_status(self):
        """Update status of each allocation detail."""
        for detail in self.allocation_details:
            if flt(detail.dispatched_quantity) >= flt(detail.allocated_quantity):
                detail.status = "Dispatched"
                detail.remaining_quantity = 0
            elif flt(detail.dispatched_quantity) > 0:
                detail.status = "Partially Dispatched"
                detail.remaining_quantity = flt(detail.allocated_quantity) - flt(detail.dispatched_quantity)
            else:
                detail.status = "Allocated"
                detail.remaining_quantity = detail.allocated_quantity

    def on_submit(self):
        """Reserve quantities in batches when allocation is submitted."""
        for detail in self.allocation_details:
            if detail.batch and detail.allocated_quantity > 0:
                batch = frappe.get_doc("APC Batch", detail.batch)
                batch.allocate_quantity(detail.allocated_quantity)

        self.update_sales_demand_allocation()

    def on_cancel(self):
        """Release quantities in batches when allocation is cancelled."""
        for detail in self.allocation_details:
            if detail.batch and detail.allocated_quantity > 0:
                batch = frappe.get_doc("APC Batch", detail.batch)
                batch.release_allocation(detail.allocated_quantity)

        self.update_sales_demand_allocation()

    def update_sales_demand_allocation(self):
        """Update allocated quantities on sales demand items."""
        demand = frappe.get_doc("APC Sales Demand", self.sales_demand)

        for item in demand.items:
            total_allocated = frappe.db.sql("""
                SELECT SUM(allocated_quantity)
                FROM `tabAPC Batch Allocation Detail`
                WHERE sales_demand_item = %s AND docstatus < 2
            """, (item.name,))[0][0] or 0

            item.allocated_quantity = total_allocated
            item.pending_allocation = flt(item.demand_quantity) - total_allocated

        demand.save()

    @frappe.whitelist()
    def release_allocation(self):
        """Release this allocation and return quantities to batches."""
        if self.allocation_status == "Released":
            frappe.throw(_("Allocation is already released"))

        for detail in self.allocation_details:
            if detail.batch and detail.allocated_quantity > 0:
                batch = frappe.get_doc("APC Batch", detail.batch)
                batch.release_allocation(detail.allocated_quantity)

        self.allocation_status = "Released"
        self.save()

        frappe.msgprint(_("Allocation {0} has been released").format(self.name))
        return {"success": True}


@frappe.whitelist()
def create_batch_allocation(sales_demand, items=None):
    """Create a new batch allocation for a sales demand."""
    from apc_operations.services.batch_allocation import allocate_batches_fifo

    return allocate_batches_fifo(sales_demand, items)


# Hook event handlers
def on_submit_allocation(doc, method):
    """Hook handler for APC Batch Allocation on_submit event."""
    # Reserve quantities in batches
    for detail in doc.allocation_details:
        if detail.batch and detail.allocated_quantity > 0:
            batch = frappe.get_doc("APC Batch", detail.batch)
            batch.allocate_quantity(detail.allocated_quantity)

    # Update sales demand
    doc.update_sales_demand_allocation()
