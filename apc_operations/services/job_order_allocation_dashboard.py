# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Job Order–centric batch allocation dashboard APIs."""

import frappe
from frappe import _
from frappe.utils import flt, today, getdate

from apc_operations.services.batch_allocation import (
    calculate_free_stock,
    get_available_batches,
)


def _parse_json(value):
    if not value:
        return value
    if isinstance(value, str):
        return frappe.parse_json(value)
    return value


def _get_job_order_doc(job_order):
    if not job_order or not frappe.db.exists("Job Order", job_order):
        frappe.throw(_("Job Order {0} not found").format(job_order))
    return frappe.get_doc("Job Order", job_order)


def _get_job_order_item_row(job_order_doc, job_order_item):
    for row in job_order_doc.items or []:
        if row.name == job_order_item:
            return row
    frappe.throw(_("Job Order Item {0} not found on {1}").format(job_order_item, job_order_doc.name))


def _resolve_sales_demand_item(job_order_doc, jo_item):
    if jo_item.sales_demand_item:
        return jo_item.sales_demand_item

    if not job_order_doc.sales_demand:
        return None

    filters = {
        "parent": job_order_doc.sales_demand,
        "item": jo_item.item,
    }
    if jo_item.grade:
        filters["grade"] = jo_item.grade

    return frappe.db.get_value("APC Sales Demand Item", filters, "name")


def _get_allocated_qty_for_line(sales_demand_item):
    if not sales_demand_item:
        return 0.0

    sd_allocated = frappe.db.get_value(
        "APC Sales Demand Item", sales_demand_item, "allocated_quantity"
    )
    if sd_allocated is not None:
        return flt(sd_allocated)

    return flt(
        frappe.db.sql(
            """
            SELECT COALESCE(SUM(d.allocated_quantity), 0)
            FROM `tabAPC Batch Allocation Detail` d
            INNER JOIN `tabAPC Batch Allocation` a ON a.name = d.parent
            WHERE d.sales_demand_item = %s
              AND d.status NOT IN ('Released')
              AND a.allocation_status NOT IN ('Released')
            """,
            (sales_demand_item,),
        )[0][0]
    )


def _get_line_allocation_context(job_order_doc, jo_item):
    sales_demand = job_order_doc.sales_demand
    sales_demand_item = _resolve_sales_demand_item(job_order_doc, jo_item)
    required_qty = flt(jo_item.quantity)
    allocated_qty = _get_allocated_qty_for_line(sales_demand_item)
    pending_qty = max(0.0, required_qty - allocated_qty)

    can_allocate = bool(
        sales_demand
        and sales_demand_item
        and job_order_doc.status not in ("Cancelled",)
        and pending_qty > 0
    )

    allocation_block_reason = None
    if not sales_demand:
        allocation_block_reason = _("Link a Sales Demand on this Job Order before allocating.")
    elif not sales_demand_item:
        allocation_block_reason = _("Link this line to a Sales Demand Item before allocating.")
    elif job_order_doc.status == "Draft":
        allocation_block_reason = _("Confirm the Job Order before allocating batches.")
    elif pending_qty <= 0:
        allocation_block_reason = _("This line is fully allocated.")

    return frappe._dict(
        job_order=job_order_doc.name,
        job_order_item=jo_item.name,
        sales_demand=sales_demand,
        sales_demand_item=sales_demand_item,
        item=jo_item.item,
        item_name=jo_item.item_name or jo_item.item,
        grade=jo_item.grade,
        specification=jo_item.specification,
        packaging_type=jo_item.packaging_type,
        warehouse=jo_item.warehouse,
        uom=jo_item.uom,
        required_qty=required_qty,
        allocated_qty=allocated_qty,
        pending_qty=pending_qty,
        can_allocate=can_allocate,
        allocation_block_reason=allocation_block_reason,
    )


def _summarize_job_order(job_order_doc):
    lines_total = len(job_order_doc.items or [])
    lines_complete = 0
    lines_pending = 0
    total_required = 0.0
    total_allocated = 0.0
    total_pending = 0.0

    for row in job_order_doc.items or []:
        ctx = _get_line_allocation_context(job_order_doc, row)
        total_required += ctx.required_qty
        total_allocated += min(ctx.allocated_qty, ctx.required_qty)
        total_pending += ctx.pending_qty
        if ctx.pending_qty <= 0:
            lines_complete += 1
        else:
            lines_pending += 1

    allocation_pct = round((total_allocated / total_required) * 100, 1) if total_required else 100.0

    return {
        "lines_total": lines_total,
        "lines_complete": lines_complete,
        "lines_pending": lines_pending,
        "total_required_qty": total_required,
        "total_allocated_qty": total_allocated,
        "total_pending_qty": total_pending,
        "allocation_pct": allocation_pct,
    }


def _coa_info_for_batch(batch_name, linked_coa=None):
    linked_coa = linked_coa or frappe.db.get_value("APC Batch", batch_name, "linked_coa")
    if not linked_coa:
        return {
            "coa": None,
            "coa_status": "Missing",
            "coa_approval_status": None,
            "can_create_coa": True,
        }

    approval = frappe.db.get_value("APC COA", linked_coa, "approval_status")
    status = frappe.db.get_value("APC COA", linked_coa, "status")
    coa_status = approval or status or "Pending"
    return {
        "coa": linked_coa,
        "coa_status": coa_status,
        "coa_approval_status": approval,
        "can_create_coa": False,
    }


def _batch_can_allocate(batch_row, coa_info):
    if batch_row.batch_status in ("Blocked", "Cancelled", "Depleted", "Expired"):
        return False
    if batch_row.quality_status not in ("Approved", "QC Cleared"):
        return False
    if batch_row.stock_status != "Available":
        return False
    if flt(batch_row.available_quantity) <= 0:
        return False
    if coa_info.get("coa_approval_status") != "Approved":
        return False
    if batch_row.expiry_date and getdate(batch_row.expiry_date) < getdate(today()):
        return False
    return True


def _get_batches_query_filters(ctx):
    filters = [["product", "=", ctx.item], ["docstatus", "<", 2]]
    if ctx.grade:
        filters.append(["grade", "=", ctx.grade])
    if ctx.specification:
        filters.append(["specification", "=", ctx.specification])
    if ctx.packaging_type:
        filters.append(["packaging_type", "=", ctx.packaging_type])
    if ctx.warehouse:
        filters.append(["warehouse", "=", ctx.warehouse])
    return filters


def _already_allocated_on_batch(sales_demand_item, batch_name):
    if not sales_demand_item:
        return 0.0
    return flt(
        frappe.db.sql(
            """
            SELECT COALESCE(SUM(d.allocated_quantity), 0)
            FROM `tabAPC Batch Allocation Detail` d
            INNER JOIN `tabAPC Batch Allocation` a ON a.name = d.parent
            WHERE d.sales_demand_item = %s
              AND d.batch = %s
              AND d.status NOT IN ('Released')
              AND a.allocation_status NOT IN ('Released')
            """,
            (sales_demand_item, batch_name),
        )[0][0]
    )


def _product_group_key(item, grade=None, specification=None, packaging_type=None, warehouse=None):
    return (
        item or "",
        grade or "",
        specification or "",
        packaging_type or "",
        warehouse or "",
    )


def _line_row_from_context(jo_doc, ctx):
    today_date = getdate(today())
    is_overdue = bool(
        jo_doc.date
        and getdate(jo_doc.date) < today_date
        and ctx.pending_qty > 0
    )
    line_status = "Complete"
    if ctx.pending_qty <= 0:
        line_status = "Complete"
    elif ctx.allocated_qty > 0:
        line_status = "Partial"
    else:
        line_status = "Pending"

    return {
        "job_order": ctx.job_order,
        "job_order_item": ctx.job_order_item,
        "job_order_number": jo_doc.job_order_number or jo_doc.name,
        "customer": jo_doc.customer,
        "customer_name": jo_doc.customer_name,
        "date": jo_doc.date,
        "job_order_status": jo_doc.status,
        "sales_demand": ctx.sales_demand,
        "item": ctx.item,
        "item_name": ctx.item_name,
        "grade": ctx.grade,
        "specification": ctx.specification,
        "packaging_type": ctx.packaging_type,
        "warehouse": ctx.warehouse,
        "uom": ctx.uom,
        "required_qty": ctx.required_qty,
        "allocated_qty": ctx.allocated_qty,
        "pending_qty": ctx.pending_qty,
        "sales_demand_item": ctx.sales_demand_item,
        "can_allocate": ctx.can_allocate,
        "allocation_block_reason": ctx.allocation_block_reason,
        "line_status": line_status,
        "is_overdue": is_overdue,
    }


def _collect_job_order_line_rows(filters=None):
    """Return flat Job Order line rows with allocation context."""
    filters = _parse_json(filters) or {}
    conditions = ["jo.docstatus < 2", "jo.status NOT IN ('Cancelled')"]
    params = {}

    if filters.get("customer"):
        conditions.append("jo.customer = %(customer)s")
        params["customer"] = filters["customer"]
    if filters.get("search"):
        conditions.append(
            "(jo.name LIKE %(search)s OR jo.job_order_number LIKE %(search)s "
            "OR jo.customer_name LIKE %(search)s OR joi.item LIKE %(search)s "
            "OR joi.item_name LIKE %(search)s)"
        )
        params["search"] = f"%{filters['search']}%"

    rows = frappe.db.sql(
        f"""
        SELECT
            jo.name AS job_order,
            joi.name AS job_order_item
        FROM `tabJob Order` jo
        INNER JOIN `tabJob Order Item` joi ON joi.parent = jo.name
        WHERE {" AND ".join(conditions)}
        ORDER BY jo.date ASC, jo.creation ASC, joi.idx ASC
        LIMIT 1000
        """,
        params,
        as_dict=True,
    )

    line_rows = []
    for row in rows:
        jo_doc = frappe.get_doc("Job Order", row.job_order)
        jo_item = _get_job_order_item_row(jo_doc, row.job_order_item)
        ctx = _get_line_allocation_context(jo_doc, jo_item)
        line_rows.append(_line_row_from_context(jo_doc, ctx))

    return line_rows


def _available_fifo_stock_for_product(item, grade=None, specification=None, packaging_type=None, warehouse=None):
    batches = get_available_batches(
        product=item,
        grade=grade,
        specification=specification,
        packaging_type=packaging_type,
        warehouse=warehouse,
        limit=200,
    )
    return sum(flt(calculate_free_stock(batch.name)) for batch in batches)


@frappe.whitelist()
def get_product_lines_for_allocation_dashboard(filters=None):
    """Return product groups with aggregated pending demand (step 1)."""
    filters = _parse_json(filters) or {}
    line_rows = _collect_job_order_line_rows(filters)
    groups = {}

    for row in line_rows:
        key = _product_group_key(
            row["item"],
            row.get("grade"),
            row.get("specification"),
            row.get("packaging_type"),
            row.get("warehouse"),
        )
        bucket = groups.setdefault(
            key,
            {
                "product": row["item"],
                "item_name": row["item_name"],
                "grade": row.get("grade"),
                "specification": row.get("specification"),
                "packaging_type": row.get("packaging_type"),
                "warehouse": row.get("warehouse"),
                "total_required_qty": 0.0,
                "total_allocated_qty": 0.0,
                "total_pending_qty": 0.0,
                "job_order_count": 0,
                "lines_pending_count": 0,
                "_job_orders": set(),
            },
        )

        bucket["total_required_qty"] += flt(row["required_qty"])
        bucket["total_allocated_qty"] += min(flt(row["allocated_qty"]), flt(row["required_qty"]))
        bucket["total_pending_qty"] += flt(row["pending_qty"])
        bucket["_job_orders"].add(row["job_order"])
        if flt(row["pending_qty"]) > 0:
            bucket["lines_pending_count"] += 1

    results = []
    for bucket in groups.values():
        if flt(bucket["total_pending_qty"]) <= 0 and filters.get("pending_only", True):
            continue

        available_stock = _available_fifo_stock_for_product(
            bucket["product"],
            bucket.get("grade"),
            bucket.get("specification"),
            bucket.get("packaging_type"),
            bucket.get("warehouse"),
        )
        pending = flt(bucket["total_pending_qty"])
        if pending <= 0:
            coverage_status = "Complete"
        elif available_stock >= pending:
            coverage_status = "Covered"
        elif available_stock > 0:
            coverage_status = "Partial"
        else:
            coverage_status = "Shortage"

        results.append(
            {
                "product": bucket["product"],
                "item_name": bucket["item_name"],
                "grade": bucket.get("grade"),
                "specification": bucket.get("specification"),
                "packaging_type": bucket.get("packaging_type"),
                "warehouse": bucket.get("warehouse"),
                "total_required_qty": bucket["total_required_qty"],
                "total_allocated_qty": bucket["total_allocated_qty"],
                "total_pending_qty": pending,
                "job_order_count": len(bucket["_job_orders"]),
                "lines_pending_count": bucket["lines_pending_count"],
                "available_fifo_stock": available_stock,
                "coverage_status": coverage_status,
            }
        )

    results.sort(
        key=lambda row: (
            0 if row["coverage_status"] in ("Shortage", "Partial") else 1,
            -flt(row["total_pending_qty"]),
            row.get("item_name") or row.get("product") or "",
        )
    )
    return results


@frappe.whitelist()
def get_job_orders_for_product_line(
    product,
    grade=None,
    specification=None,
    packaging_type=None,
    warehouse=None,
    filters=None,
):
    """Return Job Order lines for a product group (step 2)."""
    if not product:
        frappe.throw(_("Product is required"))

    filters = _parse_json(filters) or {}
    line_rows = _collect_job_order_line_rows(filters)
    target_key = _product_group_key(product, grade, specification, packaging_type, warehouse)

    matching = []
    for row in line_rows:
        row_key = _product_group_key(
            row["item"],
            row.get("grade"),
            row.get("specification"),
            row.get("packaging_type"),
            row.get("warehouse"),
        )
        if row_key != target_key:
            continue
        if flt(row["pending_qty"]) <= 0:
            continue
        matching.append(row)

    matching.sort(
        key=lambda row: (
            0 if row.get("is_overdue") else 1,
            row.get("date") or today(),
            row.get("job_order_number") or row.get("job_order") or "",
        )
    )

    return {
        "product": {
            "product": product,
            "grade": grade,
            "specification": specification,
            "packaging_type": packaging_type,
            "warehouse": warehouse,
            "total_pending_qty": sum(flt(row["pending_qty"]) for row in matching),
            "available_fifo_stock": _available_fifo_stock_for_product(
                product, grade, specification, packaging_type, warehouse
            ),
            "item_name": matching[0]["item_name"] if matching else product,
        },
        "lines": matching,
    }


@frappe.whitelist()
def get_job_orders_for_allocation_dashboard(filters=None):
    """Return all Job Orders with allocation summary."""
    filters = _parse_json(filters) or {}
    conditions = ["jo.docstatus < 2"]
    params = {}

    if filters.get("customer"):
        conditions.append("jo.customer = %(customer)s")
        params["customer"] = filters["customer"]
    if filters.get("status"):
        conditions.append("jo.status = %(status)s")
        params["status"] = filters["status"]
    if filters.get("search"):
        conditions.append(
            "(jo.name LIKE %(search)s OR jo.job_order_number LIKE %(search)s OR jo.customer_name LIKE %(search)s)"
        )
        params["search"] = f"%{filters['search']}%"

    rows = frappe.db.sql(
        f"""
        SELECT
            jo.name,
            jo.job_order_number,
            jo.customer,
            jo.customer_name,
            jo.date,
            jo.status,
            jo.sales_demand,
            jo.commercial_movement
        FROM `tabJob Order` jo
        WHERE {" AND ".join(conditions)}
        ORDER BY jo.date ASC, jo.creation ASC
        LIMIT 500
        """,
        params,
        as_dict=True,
    )

    today_date = getdate(today())
    for row in rows:
        jo_doc = frappe.get_doc("Job Order", row.name)
        summary = _summarize_job_order(jo_doc)
        row.update(summary)
        row["is_overdue"] = bool(row.date and getdate(row.date) < today_date and summary["lines_pending"] > 0)
        row["can_open_allocation"] = row.status not in ("Cancelled",)

    rows.sort(
        key=lambda r: (
            0 if r["lines_pending"] > 0 else 1,
            0 if r.get("is_overdue") else 1,
            r.get("date") or today(),
        )
    )
    return rows


@frappe.whitelist()
def get_job_order_allocation_lines(job_order):
    """Return product lines for a Job Order (step 2)."""
    jo_doc = _get_job_order_doc(job_order)
    lines = []

    for row in jo_doc.items or []:
        ctx = _get_line_allocation_context(jo_doc, row)
        line_status = "Complete"
        if ctx.pending_qty <= 0:
            line_status = "Complete"
        elif ctx.allocated_qty > 0:
            line_status = "Partial"
        else:
            line_status = "Pending"

        lines.append(
            {
                "job_order_item": ctx.job_order_item,
                "item": ctx.item,
                "item_name": ctx.item_name,
                "grade": ctx.grade,
                "specification": ctx.specification,
                "packaging_type": ctx.packaging_type,
                "warehouse": ctx.warehouse,
                "uom": ctx.uom,
                "required_qty": ctx.required_qty,
                "allocated_qty": ctx.allocated_qty,
                "pending_qty": ctx.pending_qty,
                "sales_demand": ctx.sales_demand,
                "sales_demand_item": ctx.sales_demand_item,
                "can_allocate": ctx.can_allocate,
                "allocation_block_reason": ctx.allocation_block_reason,
                "line_status": line_status,
            }
        )

    header = {
        "job_order": jo_doc.name,
        "job_order_number": jo_doc.job_order_number or jo_doc.name,
        "customer": jo_doc.customer,
        "customer_name": jo_doc.customer_name,
        "date": jo_doc.date,
        "status": jo_doc.status,
        "sales_demand": jo_doc.sales_demand,
        "summary": _summarize_job_order(jo_doc),
    }
    return {"header": header, "lines": lines}


@frappe.whitelist()
def get_batches_for_job_order_line(job_order, job_order_item):
    """Return FIFO batches for a Job Order line (step 3)."""
    jo_doc = _get_job_order_doc(job_order)
    jo_item = _get_job_order_item_row(jo_doc, job_order_item)
    ctx = _get_line_allocation_context(jo_doc, jo_item)

    allocatable_names = {
        b.name for b in get_available_batches(
            product=ctx.item,
            grade=ctx.grade,
            specification=ctx.specification,
            packaging_type=ctx.packaging_type,
            warehouse=ctx.warehouse,
            limit=200,
        )
    }

    batch_rows = frappe.get_all(
        "APC Batch",
        filters=_get_batches_query_filters(ctx),
        fields=[
            "name",
            "batch_number",
            "product",
            "grade",
            "specification",
            "packaging_type",
            "warehouse",
            "batch_quantity",
            "available_quantity",
            "allocated_quantity",
            "manufacturing_date",
            "expiry_date",
            "quality_status",
            "batch_status",
            "stock_status",
            "linked_coa",
            "creation",
        ],
        order_by="manufacturing_date asc, creation asc, name asc",
        limit_page_length=200,
    )

    batches = []
    fifo_sequence = 0
    for batch_row in batch_rows:
        fifo_sequence += 1
        coa_info = _coa_info_for_batch(batch_row.name, batch_row.linked_coa)
        free_stock = flt(calculate_free_stock(batch_row.name))
        can_allocate = _batch_can_allocate(batch_row, coa_info) and batch_row.name in allocatable_names
        already_on_line = _already_allocated_on_batch(ctx.sales_demand_item, batch_row.name)

        batches.append(
            {
                "name": batch_row.name,
                "batch_number": batch_row.batch_number or batch_row.name,
                "manufacturing_date": batch_row.manufacturing_date,
                "expiry_date": batch_row.expiry_date,
                "available_quantity": flt(batch_row.available_quantity),
                "free_stock": free_stock,
                "quality_status": batch_row.quality_status,
                "batch_status": batch_row.batch_status,
                "stock_status": batch_row.stock_status,
                "fifo_sequence": fifo_sequence,
                "can_allocate": can_allocate,
                "already_allocated_on_line": already_on_line,
                **coa_info,
            }
        )

    return {
        "context": {
            "job_order": ctx.job_order,
            "job_order_item": ctx.job_order_item,
            "job_order_number": jo_doc.job_order_number or jo_doc.name,
            "customer_name": jo_doc.customer_name,
            "date": jo_doc.date,
            "item": ctx.item,
            "item_name": ctx.item_name,
            "grade": ctx.grade,
            "specification": ctx.specification,
            "packaging_type": ctx.packaging_type,
            "warehouse": ctx.warehouse,
            "required_qty": ctx.required_qty,
            "allocated_qty": ctx.allocated_qty,
            "pending_qty": ctx.pending_qty,
            "sales_demand": ctx.sales_demand,
            "sales_demand_item": ctx.sales_demand_item,
            "can_allocate": ctx.can_allocate,
            "allocation_block_reason": ctx.allocation_block_reason,
        },
        "batches": batches,
    }


@frappe.whitelist()
def preview_job_order_line_allocation(job_order, job_order_item, lines=None):
    """Validate proposed allocation lines without saving."""
    jo_doc = _get_job_order_doc(job_order)
    jo_item = _get_job_order_item_row(jo_doc, job_order_item)
    ctx = _get_line_allocation_context(jo_doc, jo_item)
    lines = _parse_json(lines) or []

    if not ctx.can_allocate:
        frappe.throw(ctx.allocation_block_reason or _("This line cannot be allocated."))

    total_new = 0.0
    validated = []
    errors = []

    for idx, line in enumerate(lines, start=1):
        batch_name = line.get("batch")
        qty = flt(line.get("allocated_quantity"))
        if qty <= 0:
            continue

        total_new += qty
        try:
            _validate_allocation_line(ctx, batch_name, qty)
            validated.append({"batch": batch_name, "allocated_quantity": qty, "fifo_sequence": idx})
        except frappe.ValidationError as exc:
            errors.append({"batch": batch_name, "message": str(exc)})

    remaining_after = max(0.0, ctx.pending_qty - total_new)
    return {
        "valid": not errors and total_new > 0,
        "total_new_allocation": total_new,
        "remaining_after": remaining_after,
        "shortage": remaining_after if total_new > 0 else ctx.pending_qty,
        "validated_lines": validated,
        "errors": errors,
    }


def _validate_allocation_line(ctx, batch_name, qty):
    if qty <= 0:
        frappe.throw(_("Allocation quantity must be greater than zero."))

    if not frappe.db.exists("APC Batch", batch_name):
        frappe.throw(_("Batch {0} not found").format(batch_name))

    batch = frappe.get_doc("APC Batch", batch_name)
    if batch.product != ctx.item:
        frappe.throw(_("Batch {0} product does not match the Job Order line.").format(batch_name))
    if ctx.grade and batch.grade and batch.grade != ctx.grade:
        frappe.throw(_("Batch {0} grade does not match the Job Order line.").format(batch_name))
    if ctx.specification and batch.specification and batch.specification != ctx.specification:
        frappe.throw(_("Batch {0} specification does not match the Job Order line.").format(batch_name))
    if ctx.packaging_type and batch.packaging_type and batch.packaging_type != ctx.packaging_type:
        frappe.throw(_("Batch {0} packaging does not match the Job Order line.").format(batch_name))
    if ctx.warehouse and batch.warehouse and batch.warehouse != ctx.warehouse:
        frappe.throw(_("Batch {0} warehouse does not match the Job Order line.").format(batch_name))

    coa_info = _coa_info_for_batch(batch_name, batch.linked_coa)
    if not _batch_can_allocate(batch, coa_info):
        frappe.throw(_("Batch {0} is not eligible for allocation (COA, QC, or stock).").format(batch_name))

    free_stock = flt(calculate_free_stock(batch_name))
    if qty > free_stock:
        frappe.throw(
            _("Allocation quantity ({0}) exceeds free stock ({1}) for batch {2}.").format(
                qty, free_stock, batch_name
            )
        )


@frappe.whitelist()
def save_job_order_line_allocation(job_order, job_order_item, lines=None):
    """Persist manual / FIFO allocation lines for a Job Order item."""
    jo_doc = _get_job_order_doc(job_order)
    jo_item = _get_job_order_item_row(jo_doc, job_order_item)
    ctx = _get_line_allocation_context(jo_doc, jo_item)
    lines = _parse_json(lines) or []

    if not ctx.can_allocate:
        frappe.throw(ctx.allocation_block_reason or _("This line cannot be allocated."))

    active_lines = [line for line in lines if flt(line.get("allocated_quantity")) > 0]
    if not active_lines:
        frappe.throw(_("Enter at least one allocation quantity before saving."))

    total_new = sum(flt(line.get("allocated_quantity")) for line in active_lines)
    if total_new > ctx.pending_qty + 0.0001:
        frappe.throw(
            _("Total allocation ({0}) exceeds pending quantity ({1}).").format(
                total_new, ctx.pending_qty
            )
        )

    for line in active_lines:
        batch_doc = frappe.get_doc("APC Batch", line.get("batch"))
        batch_doc.reload()
        _validate_allocation_line(ctx, line.get("batch"), flt(line.get("allocated_quantity")))

    fifo_base = frappe.db.sql(
        """
        SELECT COALESCE(MAX(d.fifo_sequence), 0)
        FROM `tabAPC Batch Allocation Detail` d
        WHERE d.sales_demand_item = %s
        """,
        (ctx.sales_demand_item,),
    )[0][0]

    parent_alloc = frappe.db.get_value(
        "APC Batch Allocation",
        {
            "sales_demand": ctx.sales_demand,
            "allocation_status": ["in", ["Draft", "Allocated", "Partially Dispatched"]],
        },
        "name",
    )

    if parent_alloc:
        allocation = frappe.get_doc("APC Batch Allocation", parent_alloc)
    else:
        allocation = frappe.new_doc("APC Batch Allocation")
        allocation.sales_demand = ctx.sales_demand
        allocation.customer = jo_doc.customer
        allocation.allocation_date = today()
        allocation.allocation_status = "Draft"
        allocation.allocation_type = "Manual"

    for idx, line in enumerate(active_lines, start=1):
        batch_name = line.get("batch")
        qty = flt(line.get("allocated_quantity"))
        batch_doc = frappe.get_doc("APC Batch", batch_name)
        batch_doc.reload()

        allocation.append(
            "allocation_details",
            {
                "sales_demand_item": ctx.sales_demand_item,
                "item": ctx.item,
                "item_name": ctx.item_name,
                "batch": batch_name,
                "batch_number": batch_doc.batch_number or batch_name,
                "coa": batch_doc.linked_coa,
                "manufacturing_date": batch_doc.manufacturing_date,
                "required_quantity": qty,
                "allocated_quantity": qty,
                "dispatched_quantity": 0,
                "remaining_quantity": qty,
                "warehouse": batch_doc.warehouse,
                "fifo_sequence": fifo_base + idx,
                "status": "Allocated",
            },
        )

    allocation.allocation_type = "Manual"
    allocation.allocation_status = "Allocated"
    allocation.save(ignore_permissions=True)

    for line in active_lines:
        batch_doc = frappe.get_doc("APC Batch", line.get("batch"))
        batch_doc.allocate_quantity(flt(line.get("allocated_quantity")))

    allocation.update_sales_demand_allocation()

    refreshed = _get_line_allocation_context(jo_doc, jo_item)
    return {
        "success": True,
        "allocation": allocation.name,
        "details_saved": len(active_lines),
        "total_allocated": total_new,
        "remaining_pending": refreshed.pending_qty,
        "message": _("Saved {0} batch allocation row(s).").format(len(active_lines)),
    }


@frappe.whitelist()
def auto_fifo_lines_for_job_order_line(job_order, job_order_item):
    """Build FIFO allocation line suggestions for the dashboard Auto FIFO action."""
    data = get_batches_for_job_order_line(job_order, job_order_item)
    ctx = data["context"]
    if not ctx.get("can_allocate"):
        frappe.throw(ctx.get("allocation_block_reason") or _("This line cannot be allocated."))

    remaining = flt(ctx.get("pending_qty"))
    suggestions = []

    for batch in data.get("batches") or []:
        if remaining <= 0:
            break
        if not batch.get("can_allocate"):
            continue

        take = min(remaining, flt(batch.get("free_stock")))
        if take <= 0:
            continue

        suggestions.append(
            {
                "batch": batch["name"],
                "batch_number": batch.get("batch_number"),
                "allocated_quantity": take,
                "fifo_sequence": batch.get("fifo_sequence"),
            }
        )
        remaining -= take

    return {
        "lines": suggestions,
        "remaining_shortage": max(0.0, remaining),
        "pending_qty": flt(ctx.get("pending_qty")),
    }
