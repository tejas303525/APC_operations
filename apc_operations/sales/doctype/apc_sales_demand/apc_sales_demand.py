# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt, today
from frappe import _


class APCSalesDemand(Document):
    def validate(self):
        self.calculate_totals()
        self.update_item_status()

    def on_update(self):
        self.update_status()
        self.check_production_requirement()

    def calculate_totals(self):
        """Calculate totals from demand items."""
        total_demand = 0
        total_allocated = 0
        total_production = 0

        for item in self.items:
            total_demand += flt(item.demand_quantity)
            total_allocated += flt(item.allocated_quantity)
            total_production += flt(item.production_required_quantity)

        self.total_demand_quantity = total_demand
        self.total_allocated_quantity = total_allocated
        self.total_production_required_quantity = total_production

    def update_item_status(self):
        """Update status of each item line."""
        for item in self.items:
            if flt(item.allocated_quantity) >= flt(item.demand_quantity):
                item.status = "Fully Allocated"
            elif flt(item.allocated_quantity) > 0:
                item.status = "Partially Allocated"
            elif flt(item.production_required_quantity) > 0:
                item.status = "In Production"
            else:
                item.status = "Pending"

            item.pending_allocation = flt(item.demand_quantity) - flt(item.allocated_quantity)

    def update_status(self):
        """Update overall demand status."""
        if not self.items:
            self.allocation_status = "Not Allocated"
            return

        all_fully_allocated = all(
            flt(item.allocated_quantity) >= flt(item.demand_quantity)
            for item in self.items
        )
        any_allocated = any(
            flt(item.allocated_quantity) > 0
            for item in self.items
        )
        any_in_production = any(
            flt(item.production_required_quantity) > 0
            for item in self.items
        )

        if all_fully_allocated:
            self.allocation_status = "Fully Allocated"
            self.status = "Fully Allocated"
        elif any_allocated:
            self.allocation_status = "Partially Allocated"
            if any_in_production:
                self.status = "In Production"
            else:
                self.status = "Partially Allocated"
        else:
            self.allocation_status = "Not Allocated"
            if any_in_production:
                self.status = "In Production"

    def check_production_requirement(self):
        """Check if production requirements need to be created/updated."""
        for item in self.items:
            if flt(item.production_required_quantity) > 0:
                self.create_or_update_production_requirement(item)

    def create_or_update_production_requirement(self, item):
        """Create or update production requirement for a demand item."""
        existing = frappe.db.exists(
            "APC Production Requirement",
            {"sales_demand": self.name, "sales_demand_item": item.name}
        )

        if existing:
            prod_req = frappe.get_doc("APC Production Requirement", existing)
            if prod_req.status not in ["Completed", "Cancelled"]:
                prod_req.required_quantity = flt(item.production_required_quantity)
                prod_req.save()
        else:
            prod_req = frappe.new_doc("APC Production Requirement")
            prod_req.sales_demand = self.name
            prod_req.sales_demand_item = item.name
            prod_req.customer = self.customer
            prod_req.item = item.item
            prod_req.grade = item.grade
            prod_req.specification = item.specification
            prod_req.packaging_type = item.packaging_type
            prod_req.uom = item.uom
            prod_req.required_quantity = flt(item.production_required_quantity)
            prod_req.required_date = self.required_dispatch_date
            prod_req.warehouse = item.warehouse
            prod_req.status = "Draft"
            prod_req.insert()

    @frappe.whitelist()
    def calculate_production_requirement(self):
        """Calculate production requirement for all items."""
        from apc_operations.services.batch_allocation import calculate_production_requirement

        for item in self.items:
            item.production_required_quantity = calculate_production_requirement(item.name)

        self.save()
        return {"success": True, "message": "Production requirements calculated"}

    @frappe.whitelist()
    def allocate_batches(self):
        """Allocate batches to this demand using FIFO."""
        from apc_operations.services.batch_allocation import allocate_batches_fifo

        result = allocate_batches_fifo(self.name)
        return result


@frappe.whitelist()
def create_sales_demand_from_zoho(zoho_sales_order_id):
    """Create sales demand from Zoho Sales Order."""
    from apc_operations.zoho.integration import get_zoho_sales_order

    zoho_data = get_zoho_sales_order(zoho_sales_order_id)
    if not zoho_data:
        frappe.throw(_("Sales Order not found in Zoho"))

    demand = frappe.new_doc("APC Sales Demand")
    demand.zoho_sales_order_id = zoho_sales_order_id
    demand.zoho_sales_order_number = zoho_data.get("salesorder_number")
    demand.zoho_sync_status = "Synced"
    demand.zoho_sync_date = today()
    demand.customer = zoho_data.get("customer_id")
    demand.sales_order_date = zoho_data.get("date")
    demand.required_dispatch_date = zoho_data.get("expected_shipment_date")
    demand.status = "Draft"

    for line_item in zoho_data.get("line_items", []):
        demand.append("items", {
            "item": line_item.get("item_id"),
            "demand_quantity": line_item.get("quantity"),
            "uom": line_item.get("unit"),
        })

    demand.insert()
    return demand.name


@frappe.whitelist()
def get_demand_status(demand_name):
    """Get current status of a sales demand."""
    demand = frappe.get_doc("APC Sales Demand", demand_name)
    return {
        "status": demand.status,
        "allocation_status": demand.allocation_status,
        "total_demand": demand.total_demand_quantity,
        "total_allocated": demand.total_allocated_quantity,
        "total_production_required": demand.total_production_required_quantity,
    }


# Hook event handlers
def on_update_sales_demand(doc, method):
    """Hook handler for APC Sales Demand on_update event."""
    doc.update_status()
    doc.check_production_requirement()
