# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt, now, today
from frappe import _


class APCProductionRequirement(Document):
    def validate(self):
        self.calculate_remaining()
        self.update_status()

    def calculate_remaining(self):
        """Calculate remaining quantity to produce."""
        total_produced = flt(self.produced_quantity) + flt(self.wip_quantity)
        self.remaining_quantity = max(0, flt(self.required_quantity) - total_produced)

    def update_status(self):
        """Update status based on quantities."""
        if self.status in ["Completed", "Cancelled"]:
            return

        total_produced = flt(self.produced_quantity) + flt(self.wip_quantity)

        if flt(self.produced_quantity) >= flt(self.required_quantity):
            self.status = "Completed"
        elif flt(self.produced_quantity) > 0:
            self.status = "Partially Completed"
        elif flt(self.wip_quantity) > 0:
            self.status = "In Production"
        elif self.production_order:
            self.status = "Planned"

    def on_update(self):
        self.sync_to_demand_item()

    def sync_to_demand_item(self):
        """Update WIP quantity on demand item."""
        if self.sales_demand_item:
            frappe.db.set_value(
                "APC Sales Demand Item",
                self.sales_demand_item,
                "wip_production_quantity",
                flt(self.wip_quantity) + flt(self.produced_quantity),
                update_modified=False
            )

    @frappe.whitelist()
    def create_batch_from_production(self, batch_quantity, manufacturing_date=None, production_batch_number=None):
        """Create a batch when production is completed."""
        from apc_operations.inventory.doctype.apc_batch.apc_batch import APCBatch

        if self.batch_created:
            frappe.throw(_("Batch already created for this requirement"))

        if not manufacturing_date:
            manufacturing_date = today()

        # Create new batch
        batch = frappe.new_doc("APC Batch")
        batch.product = self.item
        batch.grade = self.grade
        batch.specification = self.specification
        batch.packaging_type = self.packaging_type
        batch.batch_quantity = flt(batch_quantity)
        batch.available_quantity = flt(batch_quantity)
        batch.allocated_quantity = 0
        batch.manufacturing_date = manufacturing_date
        batch.warehouse = self.warehouse
        batch.batch_status = "Active"
        batch.quality_status = "Pending QC"
        batch.production_order = self.production_order
        batch.production_batch_number = production_batch_number
        batch.created_from_production = 1
        batch.stock_status = "QC Hold"

        batch.insert()

        # Update requirement
        self.batch_created = 1
        self.produced_quantity = flt(batch_quantity)
        self.save()

        frappe.msgprint(_("Batch {0} created successfully").format(batch.name))
        return batch.name


@frappe.whitelist()
def get_pending_production_requirements():
    """Get list of pending production requirements."""
    return frappe.get_all(
        "APC Production Requirement",
        filters={"status": ["not in", ["Completed", "Cancelled"]]},
        fields=[
            "name", "sales_demand", "customer", "item", "item_name",
            "required_quantity", "produced_quantity", "remaining_quantity",
            "required_date", "status"
        ],
        order_by="required_date ASC"
    )


# Hook event handlers
def on_update_production_requirement(doc, method):
    """Hook handler for APC Production Requirement on_update event."""
    # Sync WIP to demand item
    doc.sync_to_demand_item()
    _ensure_production_order(doc)


def _ensure_production_order(doc):
    """Auto-create the matching Production Order the moment a requirement is
    raised, so Production sees it on their dashboard without someone having
    to remember to convert it by hand. production_order/production_requirement
    are already cross-linked fields on both doctypes - this just wires the
    creation step, doesn't invent new schema."""
    if doc.production_order or doc.status in ("Completed", "Cancelled"):
        return
    if flt(doc.remaining_quantity) <= 0:
        return

    po = frappe.new_doc("Production Order")
    po.item = doc.item
    po.item_name = doc.item_name
    po.item_description = doc.item_name
    po.planned_date = doc.required_date or doc.planned_date
    po.status = "Draft"
    po.required_quantity = doc.remaining_quantity
    po.uom = doc.uom
    po.grade = doc.grade
    po.specification = doc.specification
    po.packaging_type = doc.packaging_type
    po.warehouse = doc.warehouse
    po.production_requirement = doc.name
    po.insert(ignore_permissions=True)

    frappe.db.set_value(
        "APC Production Requirement", doc.name, "production_order", po.name,
        update_modified=False,
    )
