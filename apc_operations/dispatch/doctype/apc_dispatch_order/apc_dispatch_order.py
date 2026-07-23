# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt, now, today
from frappe import _


class APCDispatchOrder(Document):
    def validate(self):
        self.validate_batch_quantities()
        self.calculate_totals()
        self.validate_coa_requirements()

    def before_submit(self):
        self.validate_dispatch_batches()
        self.attach_batch_coas()

    def on_submit(self):
        self.update_allocation_dispatched_qty()
        self.update_batch_depletion()
        self.update_sales_demand_status()

    def validate_batch_quantities(self):
        """Validate that dispatch quantities don't exceed available."""
        for detail in self.batch_details:
            if detail.batch:
                batch = frappe.get_cached_doc("APC Batch", detail.batch)

                # Check if batch has approved COA
                if batch.quality_status != "Approved":
                    frappe.throw(
                        _("Batch {0} does not have approved COA").format(detail.batch_number)
                    )

                # Check batch status
                if batch.batch_status in ["Blocked", "Expired", "Cancelled", "Depleted"]:
                    frappe.throw(
                        _("Cannot dispatch from batch with status: {0}").format(batch.batch_status)
                    )

                # Check quantity
                if detail.quantity > batch.available_quantity:
                    frappe.throw(
                        _("Dispatch quantity ({0}) exceeds available ({1}) for batch {2}").format(
                            detail.quantity, batch.available_quantity, detail.batch_number
                        )
                    )

    def validate_coa_requirements(self):
        """Ensure all batches have valid COAs attached."""
        for detail in self.batch_details:
            if detail.batch:
                batch = frappe.get_cached_doc("APC Batch", detail.batch)

                if not batch.linked_coa:
                    frappe.throw(
                        _("Batch {0} has no linked COA. Cannot dispatch without approved COA.").format(
                            detail.batch_number
                        )
                    )

                if detail.coa and detail.coa != batch.linked_coa:
                    frappe.throw(
                        _("COA {0} does not belong to batch {1}").format(detail.coa, detail.batch_number)
                    )

                # Set COA from batch if not already set
                if not detail.coa:
                    detail.coa = batch.linked_coa

    def calculate_totals(self):
        """Calculate total quantities."""
        total_qty = 0
        total_dispatched = 0

        for detail in self.batch_details:
            total_qty += flt(detail.quantity)

        self.total_quantity = total_qty
        self.total_dispatched_quantity = total_dispatched

    def validate_dispatch_batches(self):
        """Pre-submit validation for dispatch."""
        if not self.batch_details:
            frappe.throw(_("At least one batch detail is required for dispatch"))

        errors = []

        for detail in self.batch_details:
            if not detail.batch:
                errors.append(f"Batch is required for item {detail.item}")
                continue

            batch = frappe.get_cached_doc("APC Batch", detail.batch)

            # Validate batch has approved COA
            if batch.quality_status != "Approved":
                errors.append(
                    f"Batch {detail.batch_number} does not have approved COA"
                )

            # Validate batch status
            if batch.batch_status not in ["Active", "On Hold"]:
                errors.append(
                    f"Cannot dispatch from batch {detail.batch_number} with status {batch.batch_status}"
                )

            # Validate COA belongs to batch
            if detail.coa and detail.coa != batch.linked_coa:
                errors.append(
                    f"COA {detail.coa} does not belong to batch {detail.batch_number}"
                )

            # Validate quantity
            if detail.quantity <= 0:
                errors.append(f"Quantity must be greater than zero for batch {detail.batch_number}")

            if detail.quantity > batch.available_quantity:
                errors.append(
                    f"Dispatch quantity ({detail.quantity}) exceeds available ({batch.available_quantity}) "
                    f"for batch {detail.batch_number}"
                )

        if errors:
            frappe.throw(
                _("Dispatch validation failed:\n") + "\n".join(f"• {e}" for e in errors)
            )

    def attach_batch_coas(self):
        """Attach COA documents from allocated batches."""
        from apc_operations.services.batch_allocation import attach_batch_coas_to_dispatch

        result = attach_batch_coas_to_dispatch(self)

        if result.get("success"):
            frappe.msgprint(
                _("{0} COA(s) attached to dispatch").format(result.get("count", 0)),
                indicator="green"
            )

    def update_allocation_dispatched_qty(self):
        """Update dispatched quantities in batch allocation."""
        if not self.batch_allocation:
            return

        allocation = frappe.get_doc("APC Batch Allocation", self.batch_allocation)

        for detail in self.batch_details:
            if detail.sales_demand_item:
                # Find matching allocation detail
                alloc_details = frappe.get_all(
                    "APC Batch Allocation Detail",
                    filters={
                        "parent": self.batch_allocation,
                        "sales_demand_item": detail.sales_demand_item,
                        "batch": detail.batch
                    }
                )

                for alloc_detail_name in alloc_details:
                    alloc_detail = frappe.get_doc("APC Batch Allocation Detail", alloc_detail_name.name)
                    alloc_detail.dispatched_quantity = flt(alloc_detail.dispatched_quantity) + flt(detail.quantity)

                    if alloc_detail.dispatched_quantity >= alloc_detail.allocated_quantity:
                        alloc_detail.status = "Dispatched"
                        alloc_detail.remaining_quantity = 0
                    else:
                        alloc_detail.status = "Partially Dispatched"
                        alloc_detail.remaining_quantity = flt(alloc_detail.allocated_quantity) - flt(alloc_detail.dispatched_quantity)

                    alloc_detail.save()

        # Update allocation status
        self.update_allocation_status(allocation)

    def update_allocation_status(self, allocation):
        """Update batch allocation status based on dispatch status."""
        total_allocated = 0
        total_dispatched = 0

        for detail in allocation.allocation_details:
            total_allocated += flt(detail.allocated_quantity)
            total_dispatched += flt(detail.dispatched_quantity)

        if total_dispatched >= total_allocated:
            allocation.allocation_status = "Fully Dispatched"
        elif total_dispatched > 0:
            allocation.allocation_status = "Partially Dispatched"

        allocation.save()

    def update_batch_depletion(self):
        """Update batch quantities after dispatch."""
        for detail in self.batch_details:
            if detail.batch:
                batch = frappe.get_doc("APC Batch", detail.batch)
                # Reduce available quantity
                new_available = flt(batch.available_quantity) - flt(detail.quantity)
                batch.db_set("available_quantity", new_available, update_modified=False)

                # Check if batch is depleted
                if new_available <= 0:
                    batch.db_set("batch_status", "Depleted", update_modified=False)

    def update_sales_demand_status(self):
        """Update sales demand dispatch status."""
        if not self.sales_demand:
            return

        demand = frappe.get_doc("APC Sales Demand", self.sales_demand)

        # Update dispatched quantity on items
        for detail in self.batch_details:
            if detail.sales_demand_item:
                item = frappe.get_doc("APC Sales Demand Item", detail.sales_demand_item)
                item.db_set(
                    "dispatched_quantity",
                    flt(item.dispatched_quantity) + flt(detail.quantity),
                    update_modified=False
                )

        # Update total dispatched
        demand.db_set(
            "total_dispatched_quantity",
            flt(demand.total_dispatched_quantity) + flt(self.total_quantity),
            update_modified=False
        )

        # Update status
        if demand.total_dispatched_quantity >= demand.total_demand_quantity:
            demand.db_set("status", "Fully Dispatched", update_modified=False)
            demand.db_set("fulfillment_status", "Fully Dispatched", update_modified=False)
        elif demand.total_dispatched_quantity > 0:
            demand.db_set("status", "Partially Dispatched", update_modified=False)
            demand.db_set("fulfillment_status", "Partially Dispatched", update_modified=False)


@frappe.whitelist()
def create_dispatch_from_allocation(allocation_name, dispatch_date=None):
    """Create a dispatch order from a batch allocation."""
    if not dispatch_date:
        dispatch_date = today()

    allocation = frappe.get_doc("APC Batch Allocation", allocation_name)

    if allocation.allocation_status in ["Released", "Fully Dispatched"]:
        frappe.throw(_("Cannot create dispatch from {0} allocation").format(allocation.allocation_status))

    dispatch = frappe.new_doc("APC Dispatch Order")
    dispatch.sales_demand = allocation.sales_demand
    dispatch.batch_allocation = allocation.name
    dispatch.customer = allocation.customer
    dispatch.dispatch_date = dispatch_date
    dispatch.status = "Draft"

    # Add batch details from allocation
    for detail in allocation.allocation_details:
        if detail.status == "Allocated":  # Only include non-dispatched allocations
            dispatch.append("batch_details", {
                "sales_demand_item": detail.sales_demand_item,
                "item": detail.item,
                "item_name": detail.item_name,
                "batch": detail.batch,
                "batch_number": detail.batch_number,
                "quantity": detail.allocated_quantity,
                "coa": detail.coa,
                "manufacturing_date": detail.manufacturing_date,
                "warehouse": detail.warehouse,
                "quality_status": "Approved"
            })

    dispatch.insert()

    return dispatch.name


@frappe.whitelist()
def validate_dispatch_batches_api(dispatch_order):
    """API endpoint to validate dispatch batches."""
    from apc_operations.services.batch_allocation import validate_dispatch_batches
    return validate_dispatch_batches(dispatch_order)


# Hook event handlers
def on_submit_dispatch(doc, method):
    """Hook handler for APC Dispatch Order on_submit event."""
    # Validate dispatch batches
    doc.validate_dispatch_batches()

    # Attach COAs
    doc.attach_batch_coas()

    # Update quantities
    doc.update_allocation_dispatched_qty()
    doc.update_batch_depletion()
    doc.update_sales_demand_status()
