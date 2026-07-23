# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import today, add_days, getdate, flt


# =============================================================================
# QC Dashboard API
# =============================================================================

@frappe.whitelist()
def get_qc_dashboard_stats():
    """
    Aggregate statistics for the QC Dashboard KPI cards.
    Returns counts for pending, cleared, rejected QC requests and COA totals.
    """
    pending = frappe.db.count("QC Report Request", {"qc_status": ["in", ["Pending QC", "In Progress"]]})
    cleared = frappe.db.count("QC Report Request", {"qc_status": "QC Cleared"})
    rejected = frappe.db.count("QC Report Request", {"qc_status": "QC Rejected"})

    coa_count = frappe.db.count("APC COA", {"approval_status": ["in", ["Approved", "Pending"]]})
    coa_approved = frappe.db.count("APC COA", {"approval_status": "Approved"})

    batches_on_hold = frappe.db.count("APC Batch", {"quality_status": ["in", ["Pending QC", "On Hold"]]})
    batches_cleared = frappe.db.count("APC Batch", {"quality_status": "Approved", "batch_status": "Active"})

    return {
        "pending": pending,
        "cleared": cleared,
        "rejected": rejected,
        "coa_count": coa_count,
        "coa_approved": coa_approved,
        "batches_on_hold": batches_on_hold,
        "batches_cleared": batches_cleared,
    }


# =============================================================================
# Batch Allocation Dashboard API
# =============================================================================

@frappe.whitelist()
def get_batch_allocation_dashboard():
    """
    Get comprehensive dashboard data for batch allocation.
    Returns demand, stock, allocation, production, and COA status.
    """
    today_str = today()
    week_start = add_days(today_str, -7)
    week_end = add_days(today_str, 7)

    return {
        "kpis": get_dashboard_kpis(),
        "demand_summary": get_demand_summary_dashboard(),
        "stock_summary": get_stock_summary_dashboard(),
        "production_summary": get_production_summary_dashboard(),
        "dispatch_summary": get_dispatch_summary_dashboard(),
        "alerts": get_dashboard_alerts(),
    }


def get_dashboard_kpis():
    """Get key performance indicators for dashboard."""
    today_str = today()

    return {
        # Demand KPIs
        "total_pending_demand": frappe.db.count(
            "APC Sales Demand",
            {"status": ["in", ["Draft", "Confirmed", "Partially Allocated"]]}
        ),
        "total_demand_qty": frappe.db.sql("""
            SELECT SUM(total_demand_quantity) FROM `tabAPC Sales Demand`
            WHERE status NOT IN ('Completed', 'Cancelled')
        """)[0][0] or 0,

        # Stock KPIs
        "total_active_batches": frappe.db.count(
            "APC Batch",
            {"batch_status": ["in", ["Active", "On Hold"]]}
        ),
        "total_available_stock": frappe.db.sql("""
            SELECT SUM(available_quantity) FROM `tabAPC Batch`
            WHERE batch_status IN ('Active', 'On Hold')
            AND quality_status = 'Approved'
        """)[0][0] or 0,

        # Allocation KPIs
        "total_allocated_qty": frappe.db.sql("""
            SELECT SUM(total_allocated_quantity) FROM `tabAPC Sales Demand`
            WHERE status NOT IN ('Completed', 'Cancelled')
        """)[0][0] or 0,

        # Production KPIs
        "pending_production_requirements": frappe.db.count(
            "APC Production Requirement",
            {"status": ["not in", ["Completed", "Cancelled"]]}
        ),
        "production_required_qty": frappe.db.sql("""
            SELECT SUM(required_quantity - produced_quantity)
            FROM `tabAPC Production Requirement`
            WHERE status NOT IN ('Completed', 'Cancelled')
        """)[0][0] or 0,

        # COA KPIs
        "pending_coa_approvals": frappe.db.count(
            "APC COA",
            {"approval_status": "Pending"}
        ),
        "approved_coas": frappe.db.count(
            "APC COA",
            {"approval_status": "Approved"}
        ),

        # Dispatch KPIs
        "pending_dispatches": frappe.db.count(
            "APC Dispatch Order",
            {"status": ["in", ["Draft", "Ready", "Dispatched"]]}
        ),
        "dispatched_today": frappe.db.count(
            "APC Dispatch Order",
            {"dispatch_date": today_str, "status": "Dispatched"}
        ),
    }


def get_demand_summary_dashboard():
    """Get demand summary for dashboard."""
    return {
        "by_status": frappe.db.sql("""
            SELECT status, COUNT(*) as count, SUM(total_demand_quantity) as qty
            FROM `tabAPC Sales Demand`
            WHERE status NOT IN ('Completed', 'Cancelled')
            GROUP BY status
        """, as_dict=True),

        "by_customer": frappe.db.sql("""
            SELECT customer, COUNT(*) as demand_count,
                   SUM(total_demand_quantity) as total_qty,
                   SUM(total_allocated_quantity) as allocated_qty
            FROM `tabAPC Sales Demand`
            WHERE status NOT IN ('Completed', 'Cancelled')
            GROUP BY customer
            ORDER BY total_qty DESC
            LIMIT 10
        """, as_dict=True),

        "upcoming_dispatch": frappe.get_all(
            "APC Sales Demand",
            filters={
                "required_dispatch_date": ["between", [today(), add_days(today(), 7)]],
                "status": ["not in", ["Completed", "Cancelled", "Fully Dispatched"]]
            },
            fields=["name", "customer", "customer_name", "required_dispatch_date",
                    "total_demand_quantity", "total_allocated_quantity", "status"],
            order_by="required_dispatch_date ASC",
            limit=10
        ),

        "overdue_demand": frappe.get_all(
            "APC Sales Demand",
            filters={
                "required_dispatch_date": ["<", today()],
                "status": ["not in", ["Completed", "Cancelled", "Fully Dispatched"]]
            },
            fields=["name", "customer", "customer_name", "required_dispatch_date",
                    "total_demand_quantity", "allocation_status"],
            order_by="required_dispatch_date ASC",
            limit=10
        ),
    }


def get_stock_summary_dashboard():
    """Get stock summary for dashboard."""
    return {
        "by_product": frappe.db.sql("""
            SELECT product, COUNT(*) as batch_count,
                   SUM(available_quantity) as available_qty,
                   SUM(allocated_quantity) as allocated_qty
            FROM `tabAPC Batch`
            WHERE batch_status IN ('Active', 'On Hold')
            AND quality_status = 'Approved'
            GROUP BY product
            ORDER BY available_qty DESC
            LIMIT 10
        """, as_dict=True),

        "by_warehouse": frappe.db.sql("""
            SELECT warehouse, COUNT(*) as batch_count,
                   SUM(available_quantity) as available_qty
            FROM `tabAPC Batch`
            WHERE batch_status IN ('Active', 'On Hold')
            AND quality_status = 'Approved'
            GROUP BY warehouse
            ORDER BY available_qty DESC
        """, as_dict=True),

        "low_stock_items": frappe.db.sql("""
            SELECT product, grade, specification,
                   SUM(available_quantity) as total_available
            FROM `tabAPC Batch`
            WHERE batch_status IN ('Active', 'On Hold')
            AND quality_status = 'Approved'
            GROUP BY product, grade, specification
            HAVING total_available < 100
            ORDER BY total_available ASC
            LIMIT 10
        """, as_dict=True),

        "expiring_batches": frappe.get_all(
            "APC Batch",
            filters={
                "expiry_date": ["between", [today(), add_days(today(), 30)]],
                "batch_status": ["in", ["Active", "On Hold"]]
            },
            fields=["name", "batch_number", "product", "expiry_date",
                    "available_quantity", "warehouse"],
            order_by="expiry_date ASC",
            limit=10
        ),
    }


def get_production_summary_dashboard():
    """Get production summary for dashboard."""
    return {
        "by_status": frappe.db.sql("""
            SELECT status, COUNT(*) as count,
                   SUM(required_quantity) as required_qty,
                   SUM(produced_quantity) as produced_qty
            FROM `tabAPC Production Requirement`
            GROUP BY status
        """, as_dict=True),

        "priority_requirements": frappe.get_all(
            "APC Production Requirement",
            filters={
                "status": ["not in", ["Completed", "Cancelled"]],
                "required_date": ["<=", add_days(today(), 7)]
            },
            fields=["name", "sales_demand", "customer", "item", "item_name",
                    "required_quantity", "produced_quantity", "required_date", "priority"],
            order_by="required_date ASC, FIELD(priority, 'Urgent', 'High', 'Normal')",
            limit=10
        ),

        "production_trend": frappe.db.sql("""
            SELECT DATE(creation) as date, COUNT(*) as count,
                   SUM(required_quantity) as qty
            FROM `tabAPC Production Requirement`
            WHERE creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            GROUP BY DATE(creation)
            ORDER BY date DESC
            LIMIT 30
        """, as_dict=True),
    }


def get_dispatch_summary_dashboard():
    """Get dispatch summary for dashboard."""
    return {
        "by_status": frappe.db.sql("""
            SELECT status, COUNT(*) as count, SUM(total_quantity) as qty
            FROM `tabAPC Dispatch Order`
            GROUP BY status
        """, as_dict=True),

        "today_dispatches": frappe.get_all(
            "APC Dispatch Order",
            filters={"dispatch_date": today()},
            fields=["name", "customer", "total_quantity", "status"],
            order_by="creation DESC"
        ),

        "upcoming_dispatches": frappe.get_all(
            "APC Dispatch Order",
            filters={
                "dispatch_date": [">=", today()],
                "status": ["in", ["Draft", "Ready"]]
            },
            fields=["name", "customer", "dispatch_date", "total_quantity", "status"],
            order_by="dispatch_date ASC",
            limit=10
        ),
    }


def get_dashboard_alerts():
    """Get alerts for dashboard."""
    alerts = []

    # Overdue demands
    overdue_count = frappe.db.count(
        "APC Sales Demand",
        {
            "required_dispatch_date": ["<", today()],
            "status": ["not in", ["Completed", "Cancelled", "Fully Dispatched"]]
        }
    )
    if overdue_count:
        alerts.append({
            "type": "danger",
            "title": f"{overdue_count} overdue demand(s)",
            "message": "Demands past required dispatch date",
            "action": "View Demands"
        })

    # Batches without COA
    no_coa_count = frappe.db.count(
        "APC Batch",
        {"linked_coa": ["is", "not set"], "batch_status": "Active"}
    )
    if no_coa_count:
        alerts.append({
            "type": "warning",
            "title": f"{no_coa_count} batch(es) without COA",
            "message": "Batches waiting for COA approval",
            "action": "View Batches"
        })

    # Low stock items
    low_stock = frappe.db.sql("""
        SELECT product, SUM(available_quantity) as qty
        FROM `tabAPC Batch`
        WHERE batch_status IN ('Active', 'On Hold')
        AND quality_status = 'Approved'
        GROUP BY product
        HAVING qty < 50
        LIMIT 5
    """)
    if low_stock:
        alerts.append({
            "type": "warning",
            "title": f"{len(low_stock)} item(s) with low stock",
            "message": "Stock below threshold",
            "action": "View Stock"
        })

    # Expiring batches
    expiring_count = frappe.db.count(
        "APC Batch",
        {
            "expiry_date": ["between", [today(), add_days(today(), 7)]],
            "batch_status": ["in", ["Active", "On Hold"]]
        }
    )
    if expiring_count:
        alerts.append({
            "type": "info",
            "title": f"{expiring_count} batch(es) expiring soon",
            "message": "Batches expiring within 7 days",
            "action": "View Batches"
        })

    return alerts


# =============================================================================
# Reports
# =============================================================================

@frappe.whitelist()
def get_batch_allocation_report(filters=None):
    """Get detailed batch allocation report."""
    if not filters:
        filters = {}

    conditions = []
    params = []

    if filters.get("product"):
        conditions.append("batch.product = %s")
        params.append(filters["product"])

    if filters.get("grade"):
        conditions.append("batch.grade = %s")
        params.append(filters["grade"])

    if filters.get("warehouse"):
        conditions.append("batch.warehouse = %s")
        params.append(filters["warehouse"])

    if filters.get("batch_status"):
        conditions.append("batch.batch_status = %s")
        params.append(filters["batch_status"])

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    data = frappe.db.sql(f"""
        SELECT
            batch.name as batch,
            batch.batch_number,
            batch.product,
            batch.grade,
            batch.specification,
            batch.packaging_type,
            batch.batch_quantity,
            batch.available_quantity,
            batch.allocated_quantity,
            batch.manufacturing_date,
            batch.expiry_date,
            batch.batch_status,
            batch.quality_status,
            batch.warehouse,
            coa.name as coa,
            coa.approval_status as coa_status
        FROM `tabAPC Batch` batch
        LEFT JOIN `tabAPC COA` coa ON batch.linked_coa = coa.name
        WHERE {where_clause}
        ORDER BY batch.manufacturing_date ASC
    """, params, as_dict=True)

    # Get allocations for each batch
    for row in data:
        allocations = frappe.get_all(
            "APC Batch Allocation Detail",
            filters={"batch": row.batch, "status": ["in", ["Allocated", "Partially Dispatched"]]},
            fields=["sales_demand_item", "allocated_quantity", "dispatched_quantity"]
        )
        row["allocations"] = allocations

    return data


@frappe.whitelist()
def get_demand_fulfillment_report(filters=None):
    """Get demand fulfillment report."""
    if not filters:
        filters = {}

    demands = frappe.get_all(
        "APC Sales Demand",
        filters={
            "status": ["not in", ["Cancelled"]],
            "creation": [">=", filters.get("from_date", add_days(today(), -90))]
        },
        fields=["name", "customer", "customer_name", "sales_order_date",
                "required_dispatch_date", "status", "total_demand_quantity",
                "total_allocated_quantity", "total_dispatched_quantity"],
        order_by="required_dispatch_date DESC"
    )

    for demand in demands:
        demand["fulfillment_pct"] = (
            (demand.total_dispatched_quantity / demand.total_demand_quantity * 100)
            if demand.total_demand_quantity else 0
        )

        # Get allocation details
        demand["allocations"] = frappe.get_all(
            "APC Batch Allocation",
            filters={"sales_demand": demand.name},
            fields=["name", "allocation_status", "allocation_date"]
        )

    return demands


@frappe.whitelist()
def get_production_planning_report(filters=None):
    """Get production planning report."""
    if not filters:
        filters = {}

    requirements = frappe.get_all(
        "APC Production Requirement",
        filters={
            "status": ["not in", ["Completed", "Cancelled"]],
            "required_date": ["<=", filters.get("planning_horizon", add_days(today(), 30))]
        },
        fields=["name", "sales_demand", "customer", "item", "item_name",
                "grade", "specification", "required_quantity", "produced_quantity",
                "remaining_quantity", "wip_quantity", "required_date", "priority",
                "production_order"],
        order_by="required_date ASC, FIELD(priority, 'Urgent', 'High', 'Normal')"
    )

    return requirements


# =============================================================================
# Widget Data
# =============================================================================

@frappe.whitelist()
def get_widget_data(widget_type, **kwargs):
    """Get data for specific dashboard widgets."""
    if widget_type == "demand_trend":
        return frappe.db.sql("""
            SELECT DATE(creation) as date, COUNT(*) as count,
                   SUM(total_demand_quantity) as qty
            FROM `tabAPC Sales Demand`
            WHERE creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            GROUP BY DATE(creation)
            ORDER BY date
        """, as_dict=True)

    elif widget_type == "stock_vs_demand":
        return {
            "demand": frappe.db.sql("""
                SELECT SUM(total_demand_quantity - total_allocated_quantity)
                FROM `tabAPC Sales Demand`
                WHERE status NOT IN ('Completed', 'Cancelled')
            """)[0][0] or 0,
            "stock": frappe.db.sql("""
                SELECT SUM(available_quantity)
                FROM `tabAPC Batch`
                WHERE batch_status IN ('Active', 'On Hold')
                AND quality_status = 'Approved'
            """)[0][0] or 0
        }

    elif widget_type == "allocation_status":
        return frappe.db.sql("""
            SELECT allocation_status, COUNT(*) as count
            FROM `tabAPC Sales Demand`
            WHERE status NOT IN ('Completed', 'Cancelled')
            GROUP BY allocation_status
        """, as_dict=True)

    return []


@frappe.whitelist()
def get_available_batches_for_dashboard(filters=None):
    """Return FIFO-sorted available batches for dashboard filters."""
    filters = frappe.parse_json(filters) if filters else {}
    from apc_operations.services.batch_allocation import get_available_batches

    return get_available_batches(
        product=filters.get("product"),
        grade=filters.get("grade"),
        specification=filters.get("specification"),
        packaging_type=filters.get("packaging_type"),
        warehouse=filters.get("warehouse"),
        limit=filters.get("limit") or 100,
    ) if filters.get("product") else []


@frappe.whitelist()
def get_pending_demands_for_allocation(filters=None):
    """Return sales demand item rows that still need batch allocation."""
    filters = frappe.parse_json(filters) if filters else {}
    conditions = [
        "parent.status NOT IN ('Completed', 'Cancelled', 'Fully Dispatched')",
        "(item.demand_quantity - item.allocated_quantity) > 0",
    ]
    params = {}

    if filters.get("sales_demand"):
        conditions.append("parent.name = %(sales_demand)s")
        params["sales_demand"] = filters.get("sales_demand")
    if filters.get("product"):
        conditions.append("item.item = %(product)s")
        params["product"] = filters.get("product")
    if filters.get("warehouse"):
        conditions.append("item.warehouse = %(warehouse)s")
        params["warehouse"] = filters.get("warehouse")
    if filters.get("grade"):
        conditions.append("item.grade = %(grade)s")
        params["grade"] = filters.get("grade")

    return frappe.db.sql(f"""
        SELECT
            parent.name AS sales_demand,
            parent.customer,
            parent.customer_name,
            parent.required_dispatch_date,
            item.name AS sales_demand_item,
            item.item,
            item.item_name,
            item.grade,
            item.specification,
            item.packaging_type,
            item.uom,
            item.warehouse,
            item.demand_quantity,
            item.allocated_quantity,
            (item.demand_quantity - item.allocated_quantity) AS pending_quantity,
            item.free_stock_available,
            item.production_required_quantity,
            item.status
        FROM `tabAPC Sales Demand Item` item
        INNER JOIN `tabAPC Sales Demand` parent ON parent.name = item.parent
        WHERE {" AND ".join(conditions)}
        ORDER BY parent.required_dispatch_date ASC, parent.creation ASC, item.idx ASC
        LIMIT 100
    """, params, as_dict=True)


@frappe.whitelist()
def preview_fifo_allocation(sales_demand, items=None):
    """Preview FIFO allocation without creating allocation records."""
    from apc_operations.services.batch_allocation import calculate_free_stock, get_available_batches

    demand_doc = frappe.get_doc("APC Sales Demand", sales_demand)
    selected_items = frappe.parse_json(items) if items else None
    allocations = []
    shortages = []
    fifo_sequence = 0

    for item in demand_doc.items:
        if selected_items and item.name not in selected_items:
            continue

        remaining_qty = flt(item.demand_quantity) - flt(item.allocated_quantity)
        if remaining_qty <= 0:
            continue

        batches = get_available_batches(
            product=item.item,
            grade=item.grade,
            specification=item.specification,
            packaging_type=item.packaging_type,
            warehouse=item.warehouse,
        )

        for batch in batches:
            if remaining_qty <= 0:
                break

            free_stock = flt(calculate_free_stock(batch.name))
            if free_stock <= 0:
                continue

            allocated_qty = min(remaining_qty, free_stock)
            fifo_sequence += 1
            allocations.append({
                "sales_demand": demand_doc.name,
                "sales_demand_item": item.name,
                "item": item.item,
                "item_name": item.item_name,
                "batch": batch.name,
                "batch_number": batch.batch_number,
                "coa": batch.linked_coa,
                "manufacturing_date": batch.manufacturing_date,
                "expiry_date": batch.expiry_date,
                "warehouse": batch.warehouse,
                "required_quantity": remaining_qty,
                "allocated_quantity": allocated_qty,
                "fifo_sequence": fifo_sequence,
            })
            remaining_qty -= allocated_qty

        if remaining_qty > 0:
            shortages.append({
                "sales_demand": demand_doc.name,
                "sales_demand_item": item.name,
                "item": item.item,
                "item_name": item.item_name,
                "required_qty": remaining_qty,
                "reason": "Insufficient approved FIFO stock",
            })

    return {
        "allocations": allocations,
        "shortages": shortages,
        "can_allocate": bool(allocations),
    }
