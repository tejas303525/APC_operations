# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from apc_operations.production.doctype.production_capacity_configuration.production_capacity_configuration import (
    get_active_capacity,
)


# Keyword hints applied to item_description / notes when production_capacity_category
# is left blank by the user. Order matters — first match wins.
CATEGORY_KEYWORDS = [
    ("ISO Tanks", ["iso tank", "iso-tank", "isotank"]),
    ("Tankers", ["tanker"]),
    ("Drums", ["drum"]),
    ("Containers", ["container"]),
    ("Filling Orders", ["filling"]),
    ("Lubricants", ["lubricant", "lube"]),
    ("Plasticizers", ["plasticizer", "plasticiser", "dop", "doa"]),
    ("White Oil & Jellies", ["white oil", "jelly", "jellies", "petroleum jelly"]),
]


class ProductionOrder(Document):
    def validate(self):
        if self.name and not self.production_order_number:
            self.production_order_number = self.name
        self.fetch_item_name()
        evaluate_production_order_capacity(self)

    def after_insert(self):
        if not self.production_order_number:
            self.db_set("production_order_number", self.name, update_modified=False)

    def fetch_item_name(self):
        if self.item and not self.item_name:
            self.item_name = frappe.db.get_value("Item", self.item, "item_name") or self.item

    def on_completion(self):
        """Called when status transitions to Completed. Creates APC Batch if not already done."""
        if self.apc_batch:
            return
        if not self.item:
            return
        self._create_batch_on_completion()

    def _create_batch_on_completion(self):
        """Create an APC Batch linked to this Production Order when it completes."""
        from frappe.utils import today as frappe_today

        batch = frappe.new_doc("APC Batch")
        batch.product = self.item
        batch.grade = self.grade or ""
        batch.specification = self.specification or ""
        batch.packaging_type = self.packaging_type or ""
        batch.batch_quantity = flt(self.required_quantity)
        batch.available_quantity = flt(self.required_quantity)
        batch.allocated_quantity = 0
        batch.manufacturing_date = frappe_today()
        batch.warehouse = self.warehouse
        batch.batch_status = "Active"
        batch.quality_status = "Pending QC"
        batch.stock_status = "QC Hold"
        batch.production_order = self.name
        batch.created_from_production = 1

        if self.production_requirement:
            batch.job_order = frappe.db.get_value(
                "APC Production Requirement", self.production_requirement, "sales_demand"
            )

        batch.insert(ignore_permissions=True)
        self.db_set("apc_batch", batch.name, update_modified=False)

        frappe.msgprint(
            _("APC Batch {0} created from Production Order {1}").format(batch.name, self.name),
            indicator="green",
            alert=True,
        )


def _infer_category(doc) -> str:
    """Infer the production_capacity_category from text fields when not set."""
    haystack = " ".join(
        filter(
            None,
            [
                (doc.item_description or "").lower(),
                (doc.notes or "").lower(),
            ],
        )
    )
    if not haystack.strip():
        return "Other"

    for category, keywords in CATEGORY_KEYWORDS:
        for keyword in keywords:
            if keyword in haystack:
                return category

    return "Other"


def evaluate_production_order_capacity(doc):
    """Populate capacity_* fields on a Production Order doc based on the active
    Production Capacity Configuration for its planned_date.

    This function mutates `doc` in place. It is safe to call multiple times.
    Behavior:
      * If category is blank, infer from item_description / notes (defaults to Other).
      * capacity_quantity defaults to required_quantity when not explicitly set.
      * Looks up the active capacity rule for (category, planned_date).
      * Aggregates capacity_quantity from sibling Production Orders for the same
        (category, planned_date) and compares against max_quantity_per_day.
      * Sets capacity_status (Within Capacity / Over Capacity / Not Checked).
      * Emits a warning msgprint when over capacity but does not block save.
    """
    if not doc.production_capacity_category:
        doc.production_capacity_category = _infer_category(doc)

    if not doc.capacity_quantity:
        doc.capacity_quantity = flt(doc.required_quantity)

    if not doc.capacity_uom:
        doc.capacity_uom = doc.uom or ""

    if not doc.planned_date or not doc.production_capacity_category:
        doc.capacity_status = "Not Checked"
        doc.capacity_message = _("Set planned_date and category to evaluate capacity.")
        return

    rule = get_active_capacity(doc.production_capacity_category, doc.planned_date)

    if not rule:
        doc.capacity_status = "Not Checked"
        doc.capacity_message = _(
            "No active Production Capacity Configuration for {0} on {1}."
        ).format(doc.production_capacity_category, getdate(doc.planned_date))
        return

    max_per_day = flt(rule.get("max_quantity_per_day"))
    siblings_total = _sum_other_planned_quantity(
        category=doc.production_capacity_category,
        planned_date=doc.planned_date,
        exclude_name=doc.name,
    )
    planned_total = siblings_total + flt(doc.capacity_quantity)

    if max_per_day <= 0:
        doc.capacity_status = "Not Checked"
        doc.capacity_message = _(
            "Capacity rule {0} has max_quantity_per_day <= 0; cannot evaluate."
        ).format(rule.get("name"))
        return

    if planned_total > max_per_day:
        over_by = planned_total - max_per_day
        doc.capacity_status = "Over Capacity"
        doc.capacity_message = _(
            "Over Capacity: {0} {1} / {2} {3} (over by {4})."
        ).format(
            planned_total,
            doc.production_capacity_category,
            max_per_day,
            doc.capacity_uom or rule.get("uom") or "",
            over_by,
        )
        if not getattr(frappe.flags, "in_install", False) and not getattr(frappe.flags, "in_patch", False):
            frappe.msgprint(
                doc.capacity_message,
                title=_("Production Capacity Warning"),
                indicator="orange",
                alert=True,
            )
    else:
        doc.capacity_status = "Within Capacity"
        doc.capacity_message = _(
            "Within Capacity: {0} {1} / {2} {3}."
        ).format(
            planned_total,
            doc.production_capacity_category,
            max_per_day,
            doc.capacity_uom or rule.get("uom") or "",
        )


def _sum_other_planned_quantity(category, planned_date, exclude_name=None):
    """Sum capacity_quantity of other (non-cancelled) Production Orders for the
    same category and planned_date."""
    if not category or not planned_date:
        return 0.0

    filters = [
        ["production_capacity_category", "=", category],
        ["planned_date", "=", getdate(planned_date)],
        ["status", "!=", "Cancelled"],
    ]
    if exclude_name:
        filters.append(["name", "!=", exclude_name])

    rows = frappe.get_all(
        "Production Order",
        filters=filters,
        fields=["capacity_quantity"],
    )
    return sum(flt(r.capacity_quantity) for r in rows)
