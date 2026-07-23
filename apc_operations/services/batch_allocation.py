# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt, today, getdate, now
from frappe import _


# =============================================================================
# FIFO Batch Allocation Engine
# =============================================================================

def get_available_batches(product, grade=None, specification=None, packaging_type=None,
                          warehouse=None, exclude_batches=None, limit=100):
    """
    Get available batches for allocation using FIFO priority rules.

    FIFO Priority Rules:
    1. Product must match
    2. Grade/specification must match
    3. Packaging type must match where applicable
    4. Batch must be quality-approved (QC Cleared or Approved)
    5. stock_status must be Available (not QC Hold/Reserved/Dispatched)
    6. Batch must not be blocked, expired, cancelled, or depleted
    7. Available quantity must be greater than zero
    8. Oldest manufacturing date first
    9. If manufacturing date is missing, use batch creation date
    10. If dates are equal, use batch name as tie-breaker
    """
    filters = [
        ["product", "=", product],
        ["batch_status", "in", ["Active", "On Hold"]],
        ["quality_status", "in", ["Approved", "QC Cleared"]],
        ["stock_status", "=", "Available"],
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

    if exclude_batches:
        if isinstance(exclude_batches, str):
            exclude_batches = [exclude_batches]
        filters.append(["name", "not in", exclude_batches])

    batches = frappe.get_all(
        "APC Batch",
        filters=filters,
        fields=[
            "name", "batch_number", "product", "grade", "specification",
            "packaging_type", "batch_quantity", "available_quantity",
            "allocated_quantity", "manufacturing_date", "expiry_date",
            "warehouse", "quality_status", "linked_coa", "production_order",
            "creation"
        ],
        order_by="manufacturing_date ASC, creation ASC, name ASC",
        limit_page_length=limit
    )

    return batches


def calculate_free_stock(batch_name):
    """
    Calculate free stock for a batch.
    Free stock = available_quantity - any pending reservations
    """
    batch = frappe.get_cached_doc("APC Batch", batch_name)

    # Get pending allocations (not yet dispatched)
    pending = frappe.db.sql("""
        SELECT SUM(remaining_quantity)
        FROM `tabAPC Batch Allocation Detail`
        WHERE batch = %s
        AND status IN ('Allocated', 'Partially Dispatched')
        AND docstatus < 2
    """, (batch_name,))[0][0] or 0

    return flt(batch.available_quantity) - flt(pending)


def calculate_production_requirement(sales_demand_item, consider_wip=True):
    """
    Calculate production required quantity for a demand item.

    Formula:
    Production Required = Demand Quantity
                        - Available Free Stock
                        - Already Allocated Quantity
                        - Relevant Scheduled/WIP Production Quantity

    Returns:
        float: Production required quantity (0 if no production needed)
    """
    item_doc = frappe.get_cached_doc("APC Sales Demand Item", sales_demand_item)

    demand_qty = flt(item_doc.demand_quantity)
    allocated_qty = flt(item_doc.allocated_quantity)

    # Calculate available free stock
    batches = get_available_batches(
        product=item_doc.item,
        grade=item_doc.grade,
        specification=item_doc.specification,
        packaging_type=item_doc.packaging_type,
        warehouse=item_doc.warehouse
    )

    total_free_stock = sum(flt(batch.available_quantity) for batch in batches)

    # Calculate WIP/Scheduled production
    wip_qty = 0
    if consider_wip:
        wip_qty = flt(item_doc.wip_production_quantity)

    # Calculate production requirement
    production_required = demand_qty - total_free_stock - allocated_qty - wip_qty

    return max(0, production_required)


def create_production_requirement_if_shortage(sales_demand):
    """
    Check sales demand and create/update production requirements if stock is insufficient.

    Args:
        sales_demand: Name or document of APC Sales Demand

    Returns:
        dict: Result with created/updated requirements
    """
    if isinstance(sales_demand, str):
        demand_doc = frappe.get_doc("APC Sales Demand", sales_demand)
    else:
        demand_doc = sales_demand

    created_requirements = []
    updated_requirements = []

    for item in demand_doc.items:
        production_required = calculate_production_requirement(item.name)

        if production_required > 0:
            # Check if requirement already exists
            existing = frappe.db.exists(
                "APC Production Requirement",
                {"sales_demand": demand_doc.name, "sales_demand_item": item.name}
            )

            if existing:
                # Update existing requirement
                req = frappe.get_doc("APC Production Requirement", existing)
                if req.status not in ["Completed", "Cancelled"]:
                    req.required_quantity = production_required
                    req.save()
                    updated_requirements.append(req.name)
            else:
                # Create new requirement
                req = frappe.new_doc("APC Production Requirement")
                req.sales_demand = demand_doc.name
                req.sales_demand_item = item.name
                req.customer = demand_doc.customer
                req.item = item.item
                req.item_name = item.item_name
                req.grade = item.grade
                req.specification = item.specification
                req.packaging_type = item.packaging_type
                req.uom = item.uom
                req.required_quantity = production_required
                req.required_date = demand_doc.required_dispatch_date
                req.warehouse = item.warehouse
                req.status = "Draft"
                req.insert()
                created_requirements.append(req.name)

    return {
        "success": True,
        "created": created_requirements,
        "updated": updated_requirements
    }


@frappe.whitelist()
def allocate_batches_fifo(sales_demand, items=None):
    """
    Allocate batches to sales demand using FIFO allocation logic.

    Args:
        sales_demand: Name or document of APC Sales Demand
        items: List of specific item names to allocate (None = all items)

    Returns:
        dict: Allocation result with allocated batches and any shortages
    """
    if isinstance(sales_demand, str):
        demand_doc = frappe.get_doc("APC Sales Demand", sales_demand)
    else:
        demand_doc = sales_demand

    # Create allocation document
    allocation = frappe.new_doc("APC Batch Allocation")
    allocation.sales_demand = demand_doc.name
    allocation.customer = demand_doc.customer
    allocation.allocation_date = today()
    allocation.allocation_status = "Draft"
    allocation.allocation_type = "Automatic"

    allocation_details = []
    shortages = []
    fifo_sequence = 0

    # Process each demand item
    for item in demand_doc.items:
        if items and item.name not in items:
            continue

        remaining_qty = flt(item.demand_quantity) - flt(item.allocated_quantity)

        if remaining_qty <= 0:
            continue

        # Get available batches for this item (FIFO order)
        batches = get_available_batches(
            product=item.item,
            grade=item.grade,
            specification=item.specification,
            packaging_type=item.packaging_type,
            warehouse=item.warehouse
        )

        if not batches:
            shortages.append({
                "item": item.item,
                "item_name": item.item_name,
                "required_qty": remaining_qty,
                "reason": "No available batches"
            })
            continue

        # Allocate from batches in FIFO order
        for batch in batches:
            if remaining_qty <= 0:
                break

            free_stock = calculate_free_stock(batch.name)

            if free_stock <= 0:
                continue

            alloc_qty = min(remaining_qty, free_stock)
            fifo_sequence += 1

            allocation_details.append({
                "sales_demand_item": item.name,
                "item": item.item,
                "item_name": item.item_name,
                "batch": batch.name,
                "batch_number": batch.batch_number,
                "coa": batch.linked_coa,
                "manufacturing_date": batch.manufacturing_date,
                "required_quantity": remaining_qty,
                "allocated_quantity": alloc_qty,
                "dispatched_quantity": 0,
                "remaining_quantity": alloc_qty,
                "warehouse": batch.warehouse,
                "fifo_sequence": fifo_sequence,
                "status": "Allocated"
            })

            remaining_qty -= alloc_qty

        # Record shortage if couldn't fully allocate
        if remaining_qty > 0:
            shortages.append({
                "item": item.item,
                "item_name": item.item_name,
                "required_qty": remaining_qty,
                "reason": "Insufficient stock"
            })

    # Save allocation if we have details
    if allocation_details:
        for detail in allocation_details:
            allocation.append("allocation_details", detail)

        allocation.insert()
        allocation.allocation_status = "Allocated"
        allocation.save()

        for detail in allocation.allocation_details:
            if detail.batch and flt(detail.allocated_quantity) > 0:
                batch_doc = frappe.get_doc("APC Batch", detail.batch)
                batch_doc.allocate_quantity(detail.allocated_quantity)

        allocation.update_sales_demand_allocation()

        return {
            "success": True,
            "allocation": allocation.name,
            "shortages": shortages,
            "message": f"Created allocation {allocation.name} with {len(allocation_details)} batch allocations"
        }
    else:
        return {
            "success": False,
            "allocation": None,
            "shortages": shortages,
            "message": "No batches available for allocation"
        }


@frappe.whitelist()
def release_allocation(allocation_name):
    """
    Release a batch allocation and return quantities to batches.

    Args:
        allocation_name: Name of APC Batch Allocation to release

    Returns:
        dict: Release result
    """
    allocation = frappe.get_doc("APC Batch Allocation", allocation_name)

    if allocation.allocation_status == "Released":
        return {"success": False, "message": "Allocation already released"}

    if allocation.allocation_status in ["Partially Dispatched", "Fully Dispatched"]:
        return {"success": False, "message": "Cannot release allocation with dispatched quantities"}

    # Release quantities back to batches
    for detail in allocation.allocation_details:
        if detail.batch and detail.allocated_quantity > 0:
            batch = frappe.get_doc("APC Batch", detail.batch)
            batch.release_allocation(detail.allocated_quantity)

    # Update allocation status
    allocation.allocation_status = "Released"
    allocation.save()

    # Update allocation details status
    for detail in allocation.allocation_details:
        detail.status = "Released"
        detail.save()

    return {"success": True, "message": f"Allocation {allocation_name} released"}


@frappe.whitelist()
def validate_dispatch_batches(dispatch_order):
    """
    Validate that dispatch batches are valid and have approved COAs.

    Args:
        dispatch_order: Name or document of APC Dispatch Order

    Returns:
        dict: Validation result with any errors
    """
    if isinstance(dispatch_order, str):
        dispatch_doc = frappe.get_doc("APC Dispatch Order", dispatch_order)
    else:
        dispatch_doc = dispatch_order

    errors = []

    for detail in dispatch_doc.batch_details:
        # Check batch exists
        if not frappe.db.exists("APC Batch", detail.batch):
            errors.append(f"Batch {detail.batch} does not exist")
            continue

        batch = frappe.get_cached_doc("APC Batch", detail.batch)

        # Check batch status
        if batch.batch_status not in ["Active", "On Hold"]:
            errors.append(f"Batch {detail.batch} status is {batch.batch_status}")

        # Check quality status
        if batch.quality_status != "Approved":
            errors.append(f"Batch {detail.batch} does not have approved COA")

        # Check COA exists for batch
        if not batch.linked_coa:
            errors.append(f"Batch {detail.batch} has no linked COA")

        # Check dispatch quantity doesn't exceed available
        if detail.quantity > batch.available_quantity:
            errors.append(
                f"Dispatch quantity ({detail.quantity}) exceeds available ({batch.available_quantity}) "
                f"for batch {detail.batch}"
            )

        # Validate COA belongs to batch
        if detail.coa and detail.coa != batch.linked_coa:
            errors.append(
                f"COA {detail.coa} does not belong to batch {detail.batch}"
            )

    return {
        "valid": len(errors) == 0,
        "errors": errors
    }


@frappe.whitelist()
def attach_batch_coas_to_dispatch(dispatch_order):
    """
    Attach COA documents to dispatch based on allocated batches.

    Args:
        dispatch_order: Name or document of APC Dispatch Order

    Returns:
        dict: Result with attached COAs
    """
    if isinstance(dispatch_order, str):
        dispatch_doc = frappe.get_doc("APC Dispatch Order", dispatch_order)
    else:
        dispatch_doc = dispatch_order

    attached_coas = []

    for detail in dispatch_doc.batch_details:
        if detail.coa:
            coa_doc = frappe.get_cached_doc("APC COA", detail.coa)

            dispatch_doc.append("attached_coas", {
                "batch": detail.batch,
                "batch_number": detail.batch_number,
                "coa": detail.coa,
                "coa_number": coa_doc.coa_number,
                "product": detail.item,
                "manufacturing_date": detail.manufacturing_date,
                "coa_pdf": coa_doc.coa_pdf
            })

            attached_coas.append({
                "batch": detail.batch,
                "coa": detail.coa,
                "coa_pdf": coa_doc.coa_pdf
            })

    if attached_coas:
        dispatch_doc.save()

    return {
        "success": True,
        "attached_coas": attached_coas,
        "count": len(attached_coas)
    }


# =============================================================================
# Utility Functions
# =============================================================================

def get_demand_summary(sales_demand):
    """Get summary of demand, allocation, and dispatch status."""
    if isinstance(sales_demand, str):
        demand = frappe.get_doc("APC Sales Demand", sales_demand)
    else:
        demand = sales_demand

    return {
        "demand": demand.total_demand_quantity,
        "allocated": demand.total_allocated_quantity,
        "dispatched": demand.total_dispatched_quantity,
        "production_required": demand.total_production_required_quantity,
        "status": demand.status,
        "allocation_status": demand.allocation_status
    }


@frappe.whitelist()
def create_loading_dn_batch_allocations(loading_dn_name, product=None, required_qty=None,
                                         grade=None, specification=None,
                                         packaging_type=None, warehouse=None):
    """
    Populate the batch_allocations child table on a Loading Delivery Note using FIFO.

    If product/required_qty are not provided, they are inferred from the Loading DN's
    material_description and quantity fields (best-effort) or from the linked Job Order's items.

    Returns dict with rows created and any shortage.
    """
    loading_dn = frappe.get_doc("Loading Delivery Note", loading_dn_name)

    if loading_dn.dispatch_confirmed:
        frappe.throw(_("Dispatch already confirmed — cannot reallocate batches."))

    # Resolve product / qty if not provided
    if not product or not required_qty:
        product, required_qty, grade, specification, packaging_type, warehouse = \
            _resolve_product_from_loading_dn(loading_dn, product, required_qty,
                                              grade, specification, packaging_type, warehouse)

    if not product:
        frappe.throw(_("Cannot determine product for FIFO allocation. Provide product parameter."))

    required_qty = flt(required_qty)
    if required_qty <= 0:
        frappe.throw(_("Required quantity must be greater than zero."))

    # Permission check for FIFO override validation (override is flagged per-row)
    is_qc_manager = frappe.session.user == "Administrator" or bool(
        set(frappe.get_roles(frappe.session.user)).intersection({"Quality Manager", "System Manager"})
    )

    batches = get_available_batches(
        product=product,
        grade=grade,
        specification=specification,
        packaging_type=packaging_type,
        warehouse=warehouse,
    )

    if not batches:
        frappe.msgprint(
            _("No QC-cleared batches available for product {0}. Loading DN saved without batch allocation.").format(product),
            indicator="orange",
        )
        return {"rows": [], "shortage": required_qty}

    # Clear existing batch allocation rows
    loading_dn.set("batch_allocations", [])

    remaining = required_qty
    rows_created = []
    fifo_seq = 0

    for batch in batches:
        if remaining <= 0:
            break

        # Validate COA exists and is approved
        if not batch.get("linked_coa"):
            continue

        coa_approval = frappe.db.get_value("APC COA", batch.linked_coa, "approval_status")
        if coa_approval != "Approved":
            continue

        take = min(remaining, flt(batch.available_quantity))
        if take <= 0:
            continue

        fifo_seq += 1
        row = loading_dn.append("batch_allocations", {
            "batch": batch.name,
            "batch_number": batch.batch_number,
            "product": batch.product,
            "uom": batch.get("uom") or "",
            "manufacturing_date": batch.manufacturing_date,
            "allocated_qty": take,
            "dispatched_qty": 0,
            "coa": batch.linked_coa,
            "fifo_sequence": fifo_seq,
            "is_fifo_override": 0,
        })
        remaining -= take
        rows_created.append({
            "batch": batch.name,
            "batch_number": batch.batch_number,
            "allocated_qty": take,
            "fifo_sequence": fifo_seq,
        })

    shortage = max(0, remaining)

    if shortage > 0:
        frappe.msgprint(
            _("Insufficient stock: {0} {1} could not be allocated. Partial allocation saved.").format(shortage, "units"),
            indicator="orange",
        )

    if loading_dn.batch_allocations:
        loading_dn.delivery_note_status = "Batch Allocated"
    else:
        loading_dn.delivery_note_status = "Batch Allocation Pending"

    loading_dn.save(ignore_permissions=True)

    return {
        "rows": rows_created,
        "shortage": shortage,
        "total_allocated": required_qty - shortage,
        "loading_dn": loading_dn_name,
    }


def _resolve_product_from_loading_dn(loading_dn, product, required_qty,
                                      grade, specification, packaging_type, warehouse):
    """Try to resolve missing product/qty from the Loading DN's linked Job Order."""
    if product and required_qty:
        return product, required_qty, grade, specification, packaging_type, warehouse

    if not loading_dn.job_order:
        return product, required_qty, grade, specification, packaging_type, warehouse

    items = frappe.get_all(
        "Job Order Item",
        filters={"parent": loading_dn.job_order},
        fields=["item_code", "item_name", "qty", "uom"],
        limit=1,
    )
    if items:
        return (
            product or items[0].item_code,
            required_qty or items[0].qty,
            grade,
            specification,
            packaging_type,
            warehouse,
        )

    return product, required_qty, grade, specification, packaging_type, warehouse


@frappe.whitelist()
def confirm_dispatch_and_deduct_stock(loading_dn_name):
    """
    Confirm dispatch on a Loading DN: deduct reserved stock from APC Batch records,
    set batch_allocations rows to dispatched, and mark the Loading DN as Dispatch Confirmed.
    """
    loading_dn = frappe.get_doc("Loading Delivery Note", loading_dn_name)

    if loading_dn.dispatch_confirmed:
        frappe.throw(_("Dispatch already confirmed for {0}.").format(loading_dn_name))

    if not loading_dn.batch_allocations:
        frappe.throw(_("No batch allocations found. Run FIFO allocation before confirming dispatch."))

    # Validate all rows have approved COAs
    errors = []
    for row in loading_dn.batch_allocations:
        if not row.coa:
            errors.append(_("Batch {0} has no linked COA.").format(row.batch_number or row.batch))
            continue

        coa_approval = frappe.db.get_value("APC COA", row.coa, "approval_status")
        if coa_approval != "Approved":
            errors.append(_("COA {0} for batch {1} is not approved.").format(row.coa, row.batch_number or row.batch))

        # Validate batch is still available/reserved
        batch_stock = frappe.db.get_value("APC Batch", row.batch, ["stock_status", "available_quantity"], as_dict=True)
        if batch_stock and batch_stock.stock_status == "Dispatched":
            errors.append(_("Batch {0} is already dispatched.").format(row.batch_number or row.batch))

    if errors:
        frappe.throw(_("Dispatch validation failed:\n") + "\n".join(f"• {e}" for e in errors))

    # Check FIFO override rows have permission + reason
    for row in loading_dn.batch_allocations:
        if row.is_fifo_override:
            allowed_roles = {"Quality Manager", "System Manager"}
            if not set(frappe.get_roles(frappe.session.user)).intersection(allowed_roles):
                frappe.throw(
                    _("FIFO override on batch {0} requires Quality Manager or System Manager role.").format(
                        row.batch_number or row.batch
                    ),
                    frappe.PermissionError,
                )
            if not row.override_reason:
                frappe.throw(
                    _("Override reason is mandatory for FIFO override on batch {0}.").format(
                        row.batch_number or row.batch
                    )
                )

    # Deduct stock from each batch
    for row in loading_dn.batch_allocations:
        batch_doc = frappe.get_doc("APC Batch", row.batch)
        batch_doc.deduct_dispatch_qty(flt(row.allocated_qty))
        row.db_set("dispatched_qty", flt(row.allocated_qty), update_modified=False)

        # Link COA to Loading DN
        frappe.db.set_value(
            "APC COA",
            row.coa,
            "loading_delivery_note",
            loading_dn_name,
            update_modified=False,
        )

    # Update Loading DN
    from frappe.utils import now as frappe_now
    loading_dn.db_set("dispatch_confirmed", 1, update_modified=False)
    loading_dn.db_set("dispatch_confirmed_on", frappe_now(), update_modified=False)
    loading_dn.db_set("dispatch_confirmed_by", frappe.session.user, update_modified=False)
    loading_dn.db_set("delivery_note_status", "Dispatch Confirmed", update_modified=False)

    frappe.msgprint(
        _("Dispatch confirmed for {0}. Stock deducted from {1} batch(es).").format(
            loading_dn_name, len(loading_dn.batch_allocations)
        ),
        indicator="green",
        alert=True,
    )

    return {"success": True, "loading_dn": loading_dn_name}


@frappe.whitelist()
def preview_fifo_allocation_for_loading_dn(product, required_qty, grade=None,
                                            specification=None, packaging_type=None, warehouse=None):
    """
    Preview FIFO allocation without saving — returns batch rows that would be selected.
    """
    required_qty = flt(required_qty)
    batches = get_available_batches(
        product=product,
        grade=grade,
        specification=specification,
        packaging_type=packaging_type,
        warehouse=warehouse,
    )

    preview_rows = []
    remaining = required_qty
    seq = 0

    for batch in batches:
        if remaining <= 0:
            break

        if not batch.get("linked_coa"):
            continue

        coa_approval = frappe.db.get_value("APC COA", batch.linked_coa, "approval_status")
        if coa_approval != "Approved":
            continue

        take = min(remaining, flt(batch.available_quantity))
        if take <= 0:
            continue

        seq += 1
        preview_rows.append({
            "fifo_sequence": seq,
            "batch": batch.name,
            "batch_number": batch.batch_number,
            "product": batch.product,
            "manufacturing_date": str(batch.manufacturing_date or ""),
            "available_quantity": batch.available_quantity,
            "allocated_qty": take,
            "coa": batch.linked_coa,
            "warehouse": batch.warehouse,
        })
        remaining -= take

    return {
        "rows": preview_rows,
        "shortage": max(0, remaining),
        "total_allocated": required_qty - max(0, remaining),
    }


def get_batch_allocation_report(product=None, grade=None, warehouse=None, as_of_date=None):
    """Get report of batch allocations."""
    filters = {}
    if product:
        filters["product"] = product
    if grade:
        filters["grade"] = grade
    if warehouse:
        filters["warehouse"] = warehouse

    batches = frappe.get_all(
        "APC Batch",
        filters=filters,
        fields=[
            "name", "batch_number", "product", "grade", "specification",
            "batch_quantity", "available_quantity", "allocated_quantity",
            "manufacturing_date", "quality_status", "warehouse"
        ]
    )

    for batch in batches:
        # Get allocation details
        allocations = frappe.get_all(
            "APC Batch Allocation Detail",
            filters={"batch": batch.name, "status": ["in", ["Allocated", "Partially Dispatched"]]},
            fields=["name", "allocated_quantity", "dispatched_quantity", "sales_demand_item"]
        )
        batch["allocations"] = allocations

    return batches
