# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt, cint, today, getdate, now
from frappe import _


def _coa_number(coa_name):
    """COA Number for a Loading DN Batch row - coa_number is a fetch_from
    field that only populates via client-side onchange, never for rows
    appended server-side, so every append site must set it explicitly."""
    if not coa_name:
        return None
    return frappe.db.get_value("APC COA", coa_name, "coa_number")


def _product_name(product):
    if not product:
        return None
    return frappe.db.get_value("Item", product, "item_name")


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


@frappe.whitelist()
def query_batches_fifo(doctype, txt, searchfield, start, page_len, filters):
    """Custom Link-field search for APC Batch, sorted true-FIFO (oldest
    manufacturing date first).

    Frappe's standard Link dropdown search (search_widget in
    frappe/desk/search.py) has no 'order_by' parameter at all - any
    order_by placed in the object returned by frm.set_query() is silently
    dropped. It instead sorts by `idx` (global link-reference count)
    first, then the target doctype's own sort_field - so a
    frequently-referenced newer batch can outrank an older, untouched one
    even though APC Batch.sort_field is manufacturing_date ASC. Routing
    the Batch field through this custom query (same pattern as
    packing_calculation_service.query_packaging_types_for_item) bypasses
    that default entirely.
    """
    filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
    filters = dict(filters)

    if txt:
        filters[searchfield or "name"] = ["like", f"%{txt}%"]

    rows = frappe.get_all(
        "APC Batch",
        filters=filters,
        fields=["name"],
        order_by="manufacturing_date asc, creation asc, name asc",
        limit_start=cint(start),
        limit_page_length=cint(page_len) or 20,
    )
    return [(r.name,) for r in rows]


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


def _resolve_sales_demand_items_for_job_order(job_order):
    """Return (sales_demand_name, set of sales_demand_item names) for a Job Order."""
    sales_demand = frappe.db.get_value("Job Order", job_order, "sales_demand")
    if not sales_demand:
        return None, set()

    jo_items = frappe.get_all(
        "Job Order Item",
        filters={"parent": job_order},
        fields=["item", "sales_demand_item", "grade"],
    )
    if not jo_items:
        return sales_demand, set()

    sd_items = set()
    for row in jo_items:
        if row.sales_demand_item:
            sd_items.add(row.sales_demand_item)
            continue

        filters = {"parent": sales_demand, "item": row.item}
        if row.grade:
            filters["grade"] = row.grade
        matched = frappe.db.get_value("APC Sales Demand Item", filters, "name")
        if matched:
            sd_items.add(matched)

    if not sd_items:
        product_items = [row.item for row in jo_items if row.item]
        if product_items:
            sd_items = set(
                frappe.get_all(
                    "APC Sales Demand Item",
                    filters={"parent": sales_demand, "item": ["in", product_items]},
                    pluck="name",
                )
            )

    return sales_demand, sd_items


def _allocation_detail_qty_for_ldn(detail):
    """Quantity to load on the LDN from an APC Batch Allocation Detail row."""
    remaining = flt(detail.get("remaining_quantity"))
    if remaining > 0:
        return remaining
    allocated = flt(detail.get("allocated_quantity"))
    dispatched = flt(detail.get("dispatched_quantity"))
    return max(0.0, allocated - dispatched)


def _get_active_allocation_details_for_sd_items(sales_demand, sd_item_names):
    if not sales_demand or not sd_item_names:
        return []

    placeholders = ", ".join(["%s"] * len(sd_item_names))
    return frappe.db.sql(
        f"""
        SELECT
            d.name,
            d.batch,
            d.batch_number,
            d.item,
            d.coa,
            d.manufacturing_date,
            d.fifo_sequence,
            d.sales_demand_item,
            d.allocated_quantity,
            d.dispatched_quantity,
            d.remaining_quantity,
            a.sales_demand
        FROM `tabAPC Batch Allocation Detail` d
        INNER JOIN `tabAPC Batch Allocation` a ON a.name = d.parent
        WHERE a.sales_demand = %s
          AND a.docstatus < 2
          AND a.allocation_status NOT IN ('Released', 'Cancelled')
          AND d.status NOT IN ('Released', 'Cancelled')
          AND d.sales_demand_item IN ({placeholders})
        ORDER BY d.fifo_sequence ASC, d.creation ASC, d.name ASC
        """,
        [sales_demand, *sd_item_names],
        as_dict=True,
    )


@frappe.whitelist()
def sync_loading_dn_from_job_order_allocations(loading_dn_name, force=False):
    """Copy existing Job Order / Sales Demand batch reservations onto a Loading DN.

    Uses ``APC Batch Allocation Detail`` rows already created via the Batch
    Allocation Dashboard (or Sales Demand FIFO). Does **not** call
    ``APC Batch.allocate_quantity`` again — stock is already reserved.
    """
    loading_dn = frappe.get_doc("Loading Delivery Note", loading_dn_name)

    if loading_dn.dispatch_confirmed:
        frappe.throw(_("Dispatch already confirmed — cannot reallocate batches."))

    if loading_dn.batch_allocations and not force:
        return {
            "rows": [],
            "skipped": True,
            "message": _("Loading DN already has batch allocations."),
            "loading_dn": loading_dn_name,
        }

    if not loading_dn.job_order:
        return {
            "rows": [],
            "message": _("No Job Order linked on this Loading Delivery Note."),
            "loading_dn": loading_dn_name,
        }

    sales_demand, sd_items = _resolve_sales_demand_items_for_job_order(loading_dn.job_order)
    if not sales_demand:
        return {
            "rows": [],
            "message": _("Job Order {0} has no Sales Demand linked.").format(loading_dn.job_order),
            "loading_dn": loading_dn_name,
        }

    if not sd_items:
        return {
            "rows": [],
            "message": _("Could not resolve Sales Demand Items for Job Order {0}.").format(
                loading_dn.job_order
            ),
            "loading_dn": loading_dn_name,
        }

    details = _get_active_allocation_details_for_sd_items(sales_demand, sd_items)
    if not details:
        return {
            "rows": [],
            "message": _("No active batch allocations found for this Job Order."),
            "loading_dn": loading_dn_name,
        }

    if force:
        loading_dn.set("batch_allocations", [])

    rows_created = []
    for detail in details:
        qty = _allocation_detail_qty_for_ldn(detail)
        if qty <= 0:
            continue

        batch_row = frappe.db.get_value(
            "APC Batch",
            detail.batch,
            ["name", "batch_number", "product", "uom", "manufacturing_date", "linked_coa"],
            as_dict=True,
        )
        if not batch_row:
            continue

        coa = detail.coa or batch_row.linked_coa
        product = detail.item or batch_row.product
        loading_dn.append(
            "batch_allocations",
            {
                "batch": detail.batch,
                "batch_number": detail.batch_number or batch_row.batch_number or detail.batch,
                "product": product,
                "product_name": _product_name(product),
                "uom": batch_row.uom or loading_dn.uom or "",
                "manufacturing_date": detail.manufacturing_date or batch_row.manufacturing_date,
                "allocated_qty": qty,
                "dispatched_qty": 0,
                "coa": coa,
                "coa_number": _coa_number(coa),
                "fifo_sequence": detail.fifo_sequence or (len(rows_created) + 1),
                "is_fifo_override": 0,
                "sales_demand": sales_demand,
                "sales_demand_item": detail.sales_demand_item,
                "batch_allocation_detail": detail.name,
            },
        )
        rows_created.append(
            {
                "batch": detail.batch,
                "batch_number": detail.batch_number or batch_row.batch_number,
                "allocated_qty": qty,
                "sales_demand_item": detail.sales_demand_item,
                "batch_allocation_detail": detail.name,
            }
        )

    if rows_created:
        if loading_dn.delivery_note_status in ("", "Batch Allocation Pending"):
            loading_dn.delivery_note_status = "Batch Allocated"
    elif not loading_dn.batch_allocations:
        if loading_dn.delivery_note_status in ("",):
            loading_dn.delivery_note_status = "Batch Allocation Pending"

    loading_dn.save(ignore_permissions=True)

    total_allocated = sum(flt(row["allocated_qty"]) for row in rows_created)
    return {
        "rows": rows_created,
        "total_allocated": total_allocated,
        "loading_dn": loading_dn_name,
        "message": _("Copied {0} batch allocation row(s) from Job Order reservations.").format(
            len(rows_created)
        )
        if rows_created
        else _("No allocatable quantity found on existing reservations."),
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

    # Option B: figure out which Sales Demand / SD Item drives this Loading DN
    # so we can stamp every Loading DN Batch row with its SD coordinates.
    sd_name, sd_item_name = _resolve_sales_demand_context_for_loading_dn(
        loading_dn, product
    )

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

        # Create / reuse a matching APC Batch Allocation Detail so the
        # reservation lives on a stable record. Remaining qty after partial
        # loading stays on this Detail (no auto-release per design D4).
        bad_name = _ensure_batch_allocation_detail(
            sales_demand=sd_name,
            sales_demand_item=sd_item_name,
            batch=batch,
            allocated_qty=take,
            fifo_sequence=fifo_seq,
        )

        batch_doc = frappe.get_doc("APC Batch", batch.name)
        batch_doc.allocate_quantity(take)

        row = loading_dn.append("batch_allocations", {
            "batch": batch.name,
            "batch_number": batch.batch_number,
            "product": batch.product,
            "product_name": _product_name(batch.product),
            "uom": batch.get("uom") or "",
            "manufacturing_date": batch.manufacturing_date,
            "allocated_qty": take,
            "dispatched_qty": 0,
            "coa": batch.linked_coa,
            "coa_number": _coa_number(batch.linked_coa),
            "fifo_sequence": fifo_seq,
            "is_fifo_override": 0,
            "sales_demand": sd_name,
            "sales_demand_item": sd_item_name,
            "batch_allocation_detail": bad_name,
        })
        remaining -= take
        rows_created.append({
            "batch": batch.name,
            "batch_number": batch.batch_number,
            "allocated_qty": take,
            "fifo_sequence": fifo_seq,
            "sales_demand": sd_name,
            "sales_demand_item": sd_item_name,
            "batch_allocation_detail": bad_name,
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


def _resolve_sales_demand_context_for_loading_dn(loading_dn, product):
    """Return (sales_demand_name, sales_demand_item_name) for a Loading DN.

    Looks up the Loading DN's Job Order, then finds the matching Job Order Item
    by product. If that Job Order Item carries a ``sales_demand_item`` reference,
    returns both the SD parent and the SD item. Returns (None, None) when no
    Sales Demand context exists (legacy / standalone Job Order).
    """
    if not loading_dn.job_order:
        return None, None

    sd_name = frappe.db.get_value("Job Order", loading_dn.job_order, "sales_demand")

    sd_item_name = None
    if product:
        filters = {"parent": loading_dn.job_order, "item": product}
        sd_item_name = frappe.db.get_value(
            "Job Order Item", filters, "sales_demand_item"
        )
    if not sd_item_name:
        # Fall back to the first Job Order Item with an SD reference
        sd_item_name = frappe.db.get_value(
            "Job Order Item",
            {"parent": loading_dn.job_order, "sales_demand_item": ["is", "set"]},
            "sales_demand_item",
        )

    if sd_item_name and not sd_name:
        sd_name = frappe.db.get_value(
            "APC Sales Demand Item", sd_item_name, "parent"
        )

    return sd_name, sd_item_name


def _ensure_batch_allocation_detail(sales_demand, sales_demand_item, batch,
                                     allocated_qty, fifo_sequence):
    """Create or update an APC Batch Allocation Detail row to back a
    Loading DN Batch reservation.

    A matching detail is one tied to the same SD item and same batch.  If
    found, its ``allocated_quantity`` is bumped; otherwise a new APC Batch
    Allocation parent is created (one per Sales Demand) and the detail row
    is appended. Returns the detail row name, or None when there is no SD
    context (the caller will simply skip SD linkage).
    """
    if not sales_demand:
        return None

    parent_alloc = frappe.db.get_value(
        "APC Batch Allocation",
        {"sales_demand": sales_demand, "allocation_status": ["in", ["Allocated", "Partially Dispatched"]]},
        "name",
    )
    if not parent_alloc:
        alloc_doc = frappe.new_doc("APC Batch Allocation")
        alloc_doc.sales_demand = sales_demand
        alloc_doc.customer = frappe.db.get_value(
            "APC Sales Demand", sales_demand, "customer"
        )
        alloc_doc.allocation_date = today()
        alloc_doc.allocation_status = "Allocated"
        alloc_doc.insert(ignore_permissions=True)
        parent_alloc = alloc_doc.name

    alloc_doc = frappe.get_doc("APC Batch Allocation", parent_alloc)

    existing_detail = None
    if sales_demand_item:
        for d in alloc_doc.allocation_details:
            if d.sales_demand_item == sales_demand_item and d.batch == batch.name:
                existing_detail = d
                break

    if existing_detail:
        existing_detail.allocated_quantity = flt(existing_detail.allocated_quantity) + flt(allocated_qty)
        existing_detail.required_quantity = max(
            flt(existing_detail.required_quantity), existing_detail.allocated_quantity
        )
        existing_detail.remaining_quantity = max(
            existing_detail.allocated_quantity - flt(existing_detail.dispatched_quantity), 0
        )
        detail_name = existing_detail.name
    else:
        new_detail = alloc_doc.append("allocation_details", {
            "sales_demand_item": sales_demand_item,
            "item": batch.product,
            "item_name": batch.get("product_name"),
            "batch": batch.name,
            "batch_number": batch.batch_number,
            "coa": batch.get("linked_coa"),
            "manufacturing_date": batch.manufacturing_date,
            "fifo_sequence": fifo_sequence,
            "required_quantity": allocated_qty,
            "allocated_quantity": allocated_qty,
            "dispatched_quantity": 0,
            "remaining_quantity": allocated_qty,
            "warehouse": batch.get("warehouse"),
            "status": "Allocated",
        })
        detail_name = new_detail.name

    alloc_doc.save(ignore_permissions=True)
    return detail_name


def _resolve_product_from_loading_dn(loading_dn, product, required_qty,
                                      grade, specification, packaging_type, warehouse):
    """Resolve missing product / qty / grade / spec / packaging / warehouse
    from the Loading DN's linked Job Order.

    Option B: if a Job Order Item carries a ``sales_demand_item`` reference,
    inherit grade / specification / packaging_type / warehouse from that SD
    line in preference to the caller's defaults (which are typically empty
    for legacy callers).
    """
    if product and required_qty and grade and specification and packaging_type and warehouse:
        return product, required_qty, grade, specification, packaging_type, warehouse

    if not loading_dn.job_order:
        return product, required_qty, grade, specification, packaging_type, warehouse

    items = frappe.get_all(
        "Job Order Item",
        filters={"parent": loading_dn.job_order},
        fields=[
            "item", "item_name", "quantity", "uom",
            "sales_demand_item", "grade", "specification",
            "packaging_type", "warehouse",
        ],
        limit=1,
    )
    if not items:
        return product, required_qty, grade, specification, packaging_type, warehouse

    row = items[0]

    sd_grade = sd_spec = sd_pack = sd_wh = None
    if row.get("sales_demand_item"):
        sd_row = frappe.db.get_value(
            "APC Sales Demand Item",
            row.sales_demand_item,
            ["grade", "specification", "packaging_type", "warehouse"],
            as_dict=True,
        ) or {}
        sd_grade = sd_row.get("grade")
        sd_spec = sd_row.get("specification")
        sd_pack = sd_row.get("packaging_type")
        sd_wh = sd_row.get("warehouse")

    return (
        product or row.item,
        required_qty or row.quantity,
        grade or sd_grade or row.get("grade"),
        specification or sd_spec or row.get("specification"),
        packaging_type or sd_pack or row.get("packaging_type"),
        warehouse or sd_wh or row.get("warehouse"),
    )


@frappe.whitelist()
def confirm_dispatch_and_deduct_stock(loading_dn_name):
    """
    Confirm dispatch on a Loading DN: deduct reserved stock from APC Batch records,
    set batch_allocations rows to dispatched, mark the Loading DN as Dispatch
    Confirmed, pull gross/tare/net weights from linked Weighment Slips,
    reconcile actual loaded weights against allocated weights using the
    tolerance setting, and create a side-effect ERPNext Delivery Note for
    tax/compliance traceability.
    """
    from apc_operations.shipping.services.dispatch_validation_service import (
        validate_delivery_note_generation,
    )

    loading_dn = frappe.get_doc("Loading Delivery Note", loading_dn_name)

    if loading_dn.dispatch_confirmed:
        frappe.throw(_("Dispatch already confirmed for {0}.").format(loading_dn_name))

    is_third_party = bool(
        loading_dn.transport_delivery_order
        and frappe.db.get_value(
            "Delivery Order", loading_dn.transport_delivery_order, "third_party_loading"
        )
    )

    if not loading_dn.batch_allocations and not is_third_party:
        frappe.throw(_("No batch allocations found. Run FIFO allocation before confirming dispatch."))

    # Pull weights before validation — weighment slips may populate gross/tare/net.
    _pull_weights_from_weighment_slips(loading_dn)
    _reconcile_loading_entries_into_batch_allocations(loading_dn)

    validate_delivery_note_generation(loading_dn_name)

    loading_dn.reload()

    # Guard against double-dispatch on individual batches.
    errors = []
    for row in loading_dn.batch_allocations:
        batch_stock = frappe.db.get_value(
            "APC Batch", row.batch, ["stock_status", "available_quantity"], as_dict=True
        )
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

    # Deduct stock from each batch (and roll dispatched qty into the
    # linked APC Sales Demand Item when the row is wired back to Option B).
    sd_items_to_refresh = set()
    sd_parents_to_refresh = set()

    for row in loading_dn.batch_allocations:
        batch_doc = frappe.get_doc("APC Batch", row.batch)
        dispatched_qty = flt(row.dispatched_qty) or flt(row.allocated_qty)
        allocated_qty = flt(row.allocated_qty)
        uom = _batch_uom_for_ldn_row(row) or batch_doc.uom or ""
        if allocated_qty > 0 and dispatched_qty > allocated_qty + 0.0001:
            frappe.throw(
                _(
                    "Cannot dispatch {0} {3} for batch {1}: allocated quantity is {2} {3}. "
                    "Check Security Inspection loading entries (weights are in kg)."
                ).format(
                    dispatched_qty,
                    row.batch_number or row.batch,
                    allocated_qty,
                    uom,
                )
            )
        _ensure_batch_reservation_for_dispatch(row, dispatched_qty, batch_doc)
        batch_doc.reload()
        batch_doc.deduct_dispatch_qty(dispatched_qty)
        row.db_set("dispatched_qty", dispatched_qty, update_modified=False)

        # Link COA to Loading DN
        frappe.db.set_value(
            "APC COA",
            row.coa,
            "loading_delivery_note",
            loading_dn_name,
            update_modified=False,
        )

        # Option B: bump APC Sales Demand Item.dispatched_quantity for the
        # matching SD line, and update the linked APC Batch Allocation
        # Detail (status + dispatched_quantity), so the remaining reserved
        # qty stays on the Detail (we do NOT auto-release).
        sd_item_name = row.get("sales_demand_item")
        bad_name = row.get("batch_allocation_detail")
        if bad_name:
            try:
                bad = frappe.get_doc("APC Batch Allocation Detail", bad_name)
                bad.dispatched_quantity = flt(bad.dispatched_quantity) + dispatched_qty
                bad.remaining_quantity = max(
                    flt(bad.allocated_quantity) - flt(bad.dispatched_quantity), 0
                )
                if bad.dispatched_quantity >= bad.allocated_quantity:
                    bad.status = "Dispatched"
                elif bad.dispatched_quantity > 0:
                    bad.status = "Partially Dispatched"
                bad.db_update()
                sd_parents_to_refresh.add(bad.parent)  # APC Batch Allocation parent
                if not sd_item_name:
                    sd_item_name = bad.sales_demand_item
            except frappe.DoesNotExistError:
                pass

        if sd_item_name:
            current = flt(
                frappe.db.get_value(
                    "APC Sales Demand Item", sd_item_name, "dispatched_quantity"
                )
            )
            demand_qty = flt(
                frappe.db.get_value(
                    "APC Sales Demand Item", sd_item_name, "demand_quantity"
                )
            )
            new_dispatched = current + dispatched_qty
            frappe.db.set_value(
                "APC Sales Demand Item",
                sd_item_name,
                {
                    "dispatched_quantity": new_dispatched,
                    "pending_dispatch_quantity": max(demand_qty - new_dispatched, 0),
                },
                update_modified=False,
            )
            sd_items_to_refresh.add(sd_item_name)

    # Refresh the owning APC Sales Demand totals so the UI reflects
    # demanded / allocated / dispatched / pending-to-customer correctly.
    parent_demands = set()
    for sd_item in sd_items_to_refresh:
        parent = frappe.db.get_value("APC Sales Demand Item", sd_item, "parent")
        if parent:
            parent_demands.add(parent)
    for sd_name in parent_demands:
        try:
            sd_doc = frappe.get_doc("APC Sales Demand", sd_name)
            sd_doc.calculate_totals()
            sd_doc.update_item_status()
            sd_doc.update_status()
            sd_doc.db_update()
            for child in sd_doc.items:
                child.db_update()
        except Exception:
            frappe.log_error(
                frappe.get_traceback(), f"APC Sales Demand refresh failed for {sd_name}"
            )

    # Update Loading DN
    from frappe.utils import now as frappe_now
    loading_dn.db_set("dispatch_confirmed", 1, update_modified=False)
    loading_dn.db_set("dispatch_confirmed_on", frappe_now(), update_modified=False)
    loading_dn.db_set("dispatch_confirmed_by", frappe.session.user, update_modified=False)
    loading_dn.db_set("delivery_note_status", "Dispatch Confirmed", update_modified=False)

    # Side-effect: create the ERPNext Delivery Note for tax/compliance.
    # Failure here must NOT block the APC Loading DN; mark sync as Failed
    # for later retry.
    try:
        erpnext_dn_name = _create_erpnext_delivery_note(loading_dn)
        if erpnext_dn_name:
            loading_dn.db_set("erpnext_delivery_note", erpnext_dn_name, update_modified=False)
            loading_dn.db_set("erpnext_dn_sync_status", "Synced", update_modified=False)
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"Loading DN {loading_dn_name}: ERPNext DN sync failed",
        )
        loading_dn.db_set("erpnext_dn_sync_status", "Failed", update_modified=False)

    # Side-effect: generate the APC Invoice (Tax Invoice for mainland UAE
    # sales, International Invoice otherwise). Failure here must NOT block
    # the dispatch confirmation - staff can regenerate manually.
    try:
        from apc_operations.shipping.services.invoice_service import (
            generate_invoice_for_loading_dn,
        )

        generate_invoice_for_loading_dn(loading_dn.name)
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"Loading DN {loading_dn_name}: invoice generation failed",
        )

    if is_third_party:
        frappe.msgprint(
            _("Dispatch confirmed for {0} (third-party loading).").format(loading_dn_name),
            indicator="green",
            alert=True,
        )
    else:
        frappe.msgprint(
            _("Dispatch confirmed for {0}. Stock deducted from {1} batch(es).").format(
                loading_dn_name, len(loading_dn.batch_allocations)
            ),
            indicator="green",
            alert=True,
        )

    if loading_dn.get("transport_delivery_order"):
        from apc_operations.shipping.services.dispatch_lifecycle_service import (
            sync_dispatch_lifecycle_status,
        )

        sync_dispatch_lifecycle_status(
            loading_dn.transport_delivery_order, update_modified=True
        )

    try:
        from apc_operations.shipping.services.zoho_dispatch_sync_service import (
            trigger_dispatch_confirmed_pipeline,
        )

        trigger_dispatch_confirmed_pipeline(loading_dn_name)
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"Loading DN {loading_dn_name}: Zoho DN push enqueue failed",
        )

    return {"success": True, "loading_dn": loading_dn_name}


# -----------------------------------------------------------------------
# Phase 4 helpers: weighment pull, loading-entry reconciliation, ERPNext DN
# -----------------------------------------------------------------------

def _pull_weights_from_weighment_slips(loading_dn):
    """Pull gross/tare/net weights onto the Loading DN from any linked
    Weighment Slips on the source Delivery Order.

    Best-effort: leaves existing values alone if no slips are linked.
    """
    gross = tare = None

    do_name = loading_dn.get("transport_delivery_order")
    if do_name:
        do = frappe.db.get_value(
            "Delivery Order", do_name,
            ["weighment_slip_gross", "weighment_slip_tare"],
            as_dict=True,
        ) or {}
        if do.get("weighment_slip_gross"):
            gross = frappe.db.get_value(
                "Weighment Slip", do.weighment_slip_gross, "gross_weight"
            )
        if do.get("weighment_slip_tare"):
            tare = frappe.db.get_value(
                "Weighment Slip", do.weighment_slip_tare, "tare_weight"
            )

    if gross is not None:
        loading_dn.db_set("gross_weight", flt(gross), update_modified=False)
    if tare is not None:
        loading_dn.db_set("tare_weight", flt(tare), update_modified=False)
    if gross is not None and tare is not None:
        loading_dn.db_set("net_weight", flt(gross) - flt(tare), update_modified=False)


def _batch_uom_for_ldn_row(row) -> str | None:
    uom = (row.uom or "").strip() if getattr(row, "uom", None) else ""
    if uom:
        return uom
    return frappe.db.get_value("APC Batch", row.batch, "uom")


def _ensure_batch_reservation_for_dispatch(row, dispatched_qty: float, batch_doc) -> None:
    """Reserve on APC Batch when LDN rows exist but batch.allocated_quantity was never bumped."""
    needed = flt(dispatched_qty)
    if needed <= 0:
        return
    gap = needed - flt(batch_doc.allocated_quantity)
    if gap > 0.0001:
        batch_doc.allocate_quantity(gap)


def _reconcile_loading_entries_into_batch_allocations(loading_dn):
    """Sum actual weights from the linked Security Inspection's
    ``loading_entries`` per batch and reconcile them against the Loading
    DN's batch_allocations rows. Any discrepancy beyond the configured
    tolerance is flagged via msgprint and requires manual reconciliation
    (the dispatch still proceeds; the operator can adjust afterwards).
    """
    from apc_operations.shipping.doctype.apc_operations_settings.apc_operations_settings import (
        loading_quantity_tolerance_pct,
    )
    from apc_operations.shipping.services.uom_service import (
        kg_to_commercial_quantity,
        quantity_to_kg,
    )

    si_name = loading_dn.get("security_inspection")
    if not si_name:
        return

    rows = frappe.get_all(
        "Loading Entry",
        filters={"parent": si_name, "parenttype": "Security Inspection"},
        fields=["batch", "bags_count", "actual_weight_kg"],
    )
    if not rows:
        return

    totals_kg = {}
    for r in rows:
        if not r.batch:
            continue
        totals_kg.setdefault(r.batch, 0.0)
        totals_kg[r.batch] += flt(r.actual_weight_kg)

    tolerance_pct = loading_quantity_tolerance_pct()
    discrepancies = []
    for row in loading_dn.batch_allocations:
        actual_kg = totals_kg.get(row.batch)
        if actual_kg is None:
            continue
        uom = _batch_uom_for_ldn_row(row)
        actual_qty = kg_to_commercial_quantity(actual_kg, uom)
        allocated = flt(row.allocated_qty)
        # Record actual in commercial UOM so batch deduction matches allocated_qty.
        row.db_set("dispatched_qty", actual_qty, update_modified=False)
        if allocated > 0:
            allocated_kg = quantity_to_kg(allocated, uom)
            if allocated_kg > 0:
                diff_pct = abs(actual_kg - allocated_kg) / allocated_kg * 100
            else:
                diff_pct = 0.0
            if diff_pct > tolerance_pct:
                discrepancies.append(
                    _("Batch {0}: allocated {1} {2}, loaded {3} kg ({4:.2f}% off, tolerance {5}%)").format(
                        row.batch_number or row.batch,
                        allocated,
                        uom or "",
                        actual_kg,
                        diff_pct,
                        tolerance_pct,
                    )
                )

    if discrepancies:
        frappe.msgprint(
            _("Loading entry reconciliation flagged discrepancies. Manual review recommended:")
            + "<br/>" + "<br/>".join(f"\u2022 {d}" for d in discrepancies),
            indicator="orange",
        )


def _create_erpnext_delivery_note(loading_dn):
    """Side-effect: create an ERPNext Delivery Note mirroring the APC
    Loading DN at finalisation. Maps one-to-one.

    Field mapping:
        APC Loading DN                       \u2192 ERPNext Delivery Note
        customer                             \u2192 customer
        loading_date                         \u2192 posting_date
        batch_allocations[].product          \u2192 items[].item_code
        batch_allocations[].dispatched_qty   \u2192 items[].qty
        APC Batch.warehouse                  \u2192 items[].warehouse
        APC Batch.erpnext_batch              \u2192 items[].batch_no

    Returns the new ERPNext DN name, or None on skip.
    """
    if not loading_dn.customer:
        return None

    # Idempotent: do not double-create
    if loading_dn.get("erpnext_delivery_note"):
        return loading_dn.erpnext_delivery_note

    if not frappe.db.exists("DocType", "Delivery Note"):
        return None  # ERPNext stock module not installed

    dn = frappe.new_doc("Delivery Note")
    dn.customer = loading_dn.customer
    dn.posting_date = loading_dn.loading_date or today()
    dn.flags.ignore_permissions = True
    dn.flags.ignore_mandatory = True

    for row in loading_dn.batch_allocations:
        if not row.batch or not row.product:
            continue
        erpnext_batch = frappe.db.get_value("APC Batch", row.batch, "erpnext_batch")
        dn.append("items", {
            "item_code": row.product,
            "qty": flt(row.dispatched_qty) or flt(row.allocated_qty),
            "uom": row.uom or frappe.db.get_value("Item", row.product, "stock_uom"),
            "warehouse": frappe.db.get_value("APC Batch", row.batch, "warehouse"),
            "batch_no": erpnext_batch,
        })

    if not dn.items:
        return None

    try:
        dn.insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"ERPNext DN insert failed for Loading DN {loading_dn.name}",
        )
        return None

    return dn.name


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


def reconcile_batch_quantities(batch_name, dry_run=False):
    """Recompute allocated_quantity/dispatched_quantity/available_quantity for
    one APC Batch from current ground-truth reservation records, instead of
    trusting whatever is currently stored.

    Ground truth = APC Batch Allocation Detail rows (survive independently of
    Loading DN deletion — see design note in _ensure_batch_allocation_detail)
    plus any Loading DN Batch rows not backed by a Detail (ad-hoc reservations
    seeded directly onto a Loading DN, e.g. from a QC Report Request). Rows on
    a deleted Loading Delivery Note leave no trace here by construction, so a
    batch whose only reservation lived on a since-deleted LDN reconciles back
    to 0 for that reservation — deleting an LDN does not reverse a stock
    deduction anywhere else in this codebase either, so this is consistent
    with the rest of the system's behaviour, not a new gap.

    Returns the recomputed values; only writes them when dry_run is False.
    """
    batch = frappe.get_doc("APC Batch", batch_name)

    detail_rows = frappe.get_all(
        "APC Batch Allocation Detail",
        filters={
            "batch": batch_name,
            "docstatus": ["<", 2],
            "status": ["not in", ["Released", "Cancelled"]],
        },
        fields=["name", "allocated_quantity", "dispatched_quantity"],
    )
    dispatched = sum(flt(r.dispatched_quantity) for r in detail_rows)
    allocated = sum(max(flt(r.allocated_quantity) - flt(r.dispatched_quantity), 0) for r in detail_rows)
    counted_detail_names = {r.name for r in detail_rows}

    ldn_rows = frappe.db.sql(
        """
        SELECT ldb.allocated_qty, ldb.dispatched_qty, ldb.batch_allocation_detail
        FROM `tabLoading DN Batch` ldb
        INNER JOIN `tabLoading Delivery Note` ldn ON ldn.name = ldb.parent
        WHERE ldb.batch = %s AND ldn.docstatus < 2
        """,
        (batch_name,),
        as_dict=True,
    )
    for row in ldn_rows:
        if row.batch_allocation_detail and row.batch_allocation_detail in counted_detail_names:
            continue
        dispatched += flt(row.dispatched_qty)
        allocated += max(flt(row.allocated_qty) - flt(row.dispatched_qty), 0)

    available = flt(batch.batch_quantity) - allocated - dispatched

    result = {
        "batch": batch_name,
        "before": {
            "allocated_quantity": flt(batch.allocated_quantity),
            "dispatched_quantity": flt(batch.dispatched_quantity),
            "available_quantity": flt(batch.available_quantity),
        },
        "after": {
            "allocated_quantity": allocated,
            "dispatched_quantity": dispatched,
            "available_quantity": available,
        },
        "changed": (
            flt(batch.allocated_quantity) != allocated
            or flt(batch.dispatched_quantity) != dispatched
            or flt(batch.available_quantity) != available
        ),
    }

    if not dry_run and result["changed"]:
        batch.db_set(
            {
                "allocated_quantity": allocated,
                "dispatched_quantity": dispatched,
                "available_quantity": available,
            },
            update_modified=False,
        )

    return result


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
