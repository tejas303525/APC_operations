# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Whitelisted API endpoints powering the Production Dashboard and Calendar."""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date as date_cls

import frappe
from frappe import _
from frappe.utils import add_days, add_months, flt, getdate, today

from apc_operations.production.doctype.production_capacity_configuration.production_capacity_configuration import (
    get_active_capacity,
    get_all_active_capacities,
)
from apc_operations.production.doctype.production_order.production_order import (
    evaluate_production_order_capacity,
)


CATEGORIES = [
    "Drums",
    "Containers",
    "ISO Tanks",
    "Tankers",
    "Filling Orders",
    "Lubricants",
    "Plasticizers",
    "White Oil & Jellies",
    "Other",
]


# ──────────────────────────────────────────────────────────────────────────
# Dashboard
# ──────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def get_production_dashboard_data():
    """Return data for the Production Dashboard custom Page."""
    today_str = today()
    today_date = getdate(today_str)
    horizon_end = add_days(today_str, 30)

    active_rules_by_cat = get_all_active_capacities(today_str)

    active_rules = []
    for category in CATEGORIES:
        rule = active_rules_by_cat.get(category)
        if rule:
            active_rules.append({
                "category": category,
                "max": flt(rule.get("max_quantity_per_day")),
                "uom": rule.get("uom") or "",
                "configured": True,
                "rule_name": rule.get("name"),
            })
        else:
            active_rules.append({
                "category": category,
                "max": None,
                "uom": "",
                "configured": False,
                "rule_name": None,
            })

    capacity_alerts = _build_capacity_alerts(today_str, horizon_end)

    over_capacity_dates = sorted({row["date"] for row in capacity_alerts})
    open_statuses = ["Draft", "Planned", "In Progress"]

    kpis = {
        "pending_orders": frappe.db.count("Production Order", {"status": ["in", ["Draft", "Planned"]]}),
        "partially_filled": frappe.db.count("Production Order", {"status": "In Progress"}),
        "completed_today": _count_completed_today(today_date),
        "overdue_orders": frappe.db.count(
            "Production Order",
            {
                "planned_date": ["<", today_date],
                "status": ["in", open_statuses],
            },
        ),
        "lubricants_pending": _count_open_by_category("Lubricants", open_statuses),
        "plasticizers_pending": _count_open_by_category("Plasticizers", open_statuses),
        "white_oil_pending": _count_open_by_category("White Oil & Jellies", open_statuses),
        "over_capacity_days": len(over_capacity_dates),
        "active_rules": sum(1 for r in active_rules if r["configured"]),
        "categories_configured": sum(1 for r in active_rules if r["configured"]),
    }

    recent_orders = frappe.get_all(
        "Production Order",
        fields=[
            "name", "production_order_number", "item_description", "planned_date",
            "status", "production_capacity_category", "capacity_quantity", "capacity_uom",
            "capacity_status", "required_quantity", "uom", "apc_batch",
        ],
        order_by="planned_date desc, modified desc",
        limit=20,
    )
    _attach_dispatch_info(recent_orders)

    return {
        "active_rules": active_rules,
        "alerts": _build_dashboard_alerts(capacity_alerts, today_date, open_statuses),
        "capacity_alerts": capacity_alerts,
        "calendar": _build_week_calendar(today_date),
        "category_summaries": _build_category_summaries(open_statuses),
        "kpis": kpis,
        "quick_links": _build_quick_links(),
        "recent_orders": recent_orders,
        "today_actions": _build_today_actions(today_date, open_statuses),
        "categories": CATEGORIES,
    }


def _count_open_by_category(category, open_statuses):
    return frappe.db.count(
        "Production Order",
        {
            "production_capacity_category": category,
            "status": ["in", open_statuses],
        },
    )


def _count_completed_today(today_date):
    """Count orders completed or edited today with Completed status."""
    return frappe.db.count(
        "Production Order",
        {
            "status": "Completed",
            "modified": [">=", f"{today_date} 00:00:00"],
        },
    )


def _build_week_calendar(today_date):
    week_start = add_days(today_date, -today_date.weekday())
    week_end = add_days(week_start, 6)
    orders = frappe.get_all(
        "Production Order",
        filters=[
            ["planned_date", ">=", week_start],
            ["planned_date", "<=", week_end],
            ["status", "!=", "Cancelled"],
        ],
        fields=[
            "name", "production_order_number", "planned_date", "item_description",
            "production_capacity_category", "capacity_quantity", "capacity_uom",
            "required_quantity", "uom", "status",
        ],
        order_by="planned_date asc, creation asc",
    )

    orders_by_date = defaultdict(list)
    legend = []
    for order in orders:
        category = order.production_capacity_category or "Other"
        if category not in legend:
            legend.append(category)
        orders_by_date[getdate(order.planned_date)].append({
            "name": order.name,
            "production_order_number": order.production_order_number or order.name,
            "item_description": order.item_description or "",
            "category": category,
            "qty": flt(order.capacity_quantity or order.required_quantity),
            "uom": order.capacity_uom or order.uom or "",
            "status": order.status or "",
        })

    days = []
    for offset in range(7):
        current = getdate(add_days(week_start, offset))
        days.append({
            "date": current.isoformat(),
            "weekday": current.strftime("%a"),
            "day_label": current.strftime("%d %b"),
            "is_today": current == today_date,
            "orders": orders_by_date.get(current, []),
        })

    return {
        "start": getdate(week_start).isoformat(),
        "end": getdate(week_end).isoformat(),
        "label": f"{getdate(week_start).strftime('%d %b')} - {getdate(week_end).strftime('%d %b %Y')}",
        "days": days,
        "legend": legend[:6],
    }


def _build_category_summaries(open_statuses):
    priority_categories = ["Filling Orders", "Lubricants", "Plasticizers", "White Oil & Jellies"]
    summaries = []

    for category in priority_categories:
        orders = frappe.get_all(
            "Production Order",
            filters={
                "production_capacity_category": category,
                "status": ["in", open_statuses],
            },
            fields=[
                "name", "production_order_number", "item_description", "planned_date",
                "status", "capacity_status", "capacity_quantity", "capacity_uom",
                "required_quantity", "uom",
            ],
            order_by="planned_date asc, modified desc",
            limit=3,
        )
        summaries.append({
            "category": category,
            "count": frappe.db.count(
                "Production Order",
                {
                    "production_capacity_category": category,
                    "status": ["in", open_statuses],
                },
            ),
            "orders": orders,
        })

    return summaries


def _build_today_actions(today_date, open_statuses):
    return [
        {
            "label": _("Review pending production orders"),
            "count": frappe.db.count("Production Order", {"status": ["in", ["Draft", "Planned"]]}),
            "icon": "clipboard",
            "color": "blue",
            "route": ["List", "Production Order", {"status": ["in", ["Draft", "Planned"]]}],
        },
        {
            "label": _("Complete filling logs"),
            "count": frappe.db.count("Production Order", {"status": "In Progress"}),
            "icon": "edit",
            "color": "green",
            "route": ["List", "Production Order", {"status": "In Progress"}],
        },
        {
            "label": _("Report to QC"),
            "count": frappe.db.count(
                "Production Order",
                {
                    "planned_date": ["<=", today_date],
                    "status": ["in", open_statuses],
                },
            ),
            "icon": "assign",
            "color": "purple",
            "route": ["List", "Production Order", {"planned_date": ["<=", today_date]}],
        },
        {
            "label": _("Create Loading DN"),
            "count": frappe.db.count("Production Order", {"status": "Completed"}),
            "icon": "small-file",
            "color": "blue",
            "route": ["List", "Production Order", {"status": "Completed"}],
        },
        {
            "label": _("Send to receivables"),
            "count": 0,
            "icon": "mail",
            "color": "indigo",
            "route": ["List", "Production Order"],
        },
        {
            "label": _("Review overdue production"),
            "count": frappe.db.count(
                "Production Order",
                {
                    "planned_date": ["<", today_date],
                    "status": ["in", open_statuses],
                },
            ),
            "icon": "warning",
            "color": "red",
            "route": ["List", "Production Order", {"planned_date": ["<", today_date]}],
        },
    ]


def _build_dashboard_alerts(capacity_alerts, today_date, open_statuses):
    overdue_count = frappe.db.count(
        "Production Order",
        {
            "planned_date": ["<", today_date],
            "status": ["in", open_statuses],
        },
    )
    in_progress_count = frappe.db.count("Production Order", {"status": "In Progress"})
    today_open_count = frappe.db.count(
        "Production Order",
        {
            "planned_date": today_date,
            "status": ["in", open_statuses],
        },
    )

    alerts = []
    if overdue_count:
        alerts.append({
            "message": _("{0} production orders are overdue").format(overdue_count),
            "detail": _("Review planned dates and dispatch readiness."),
            "color": "red",
            "route": ["List", "Production Order", {"planned_date": ["<", today_date]}],
        })
    if in_progress_count:
        alerts.append({
            "message": _("{0} partially filled orders need attention").format(in_progress_count),
            "detail": _("Complete filling and update production status."),
            "color": "amber",
            "route": ["List", "Production Order", {"status": "In Progress"}],
        })
    if capacity_alerts:
        alerts.append({
            "message": _("{0} dates exceed configured capacity").format(len(capacity_alerts)),
            "detail": _("Use the production calendar to rebalance planned quantities."),
            "color": "blue",
            "route": ["production-calendar"],
        })
    if today_open_count:
        alerts.append({
            "message": _("{0} orders planned for today").format(today_open_count),
            "detail": _("Confirm filling progress before handover."),
            "color": "green",
            "route": ["List", "Production Order", {"planned_date": today_date}],
        })

    return alerts


def _build_quick_links():
    return [
        {"label": _("Production Orders"), "route": ["List", "Production Order"]},
        {"label": _("Production Calendar"), "route": ["production-calendar"]},
        {"label": _("Capacity Rules"), "route": ["List", "Production Capacity Configuration"]},
        {"label": _("New Production Order"), "route": ["Form", "Production Order", "new-production-order"]},
    ]


def _build_capacity_alerts(start_date, end_date):
    """Return list of capacity-alert rows for over-capacity days in [start_date, end_date].

    Each row: {date, category, planned, capacity, over_by, orders:[{name, qty}], rule_name}
    """
    start_date = getdate(start_date)
    end_date = getdate(end_date)

    orders = frappe.get_all(
        "Production Order",
        filters=[
            ["planned_date", ">=", start_date],
            ["planned_date", "<=", end_date],
            ["status", "!=", "Cancelled"],
        ],
        fields=[
            "name", "production_order_number", "planned_date",
            "production_capacity_category", "capacity_quantity", "capacity_uom",
        ],
        order_by="planned_date asc",
    )

    bucket = defaultdict(lambda: {"planned": 0.0, "orders": []})
    for o in orders:
        category = o.production_capacity_category or "Other"
        key = (getdate(o.planned_date), category)
        bucket[key]["planned"] += flt(o.capacity_quantity)
        bucket[key]["orders"].append({
            "name": o.name,
            "production_order_number": o.production_order_number or o.name,
            "qty": flt(o.capacity_quantity),
            "uom": o.capacity_uom or "",
        })

    alerts = []
    for (planned_date, category), agg in bucket.items():
        rule = get_active_capacity(category, planned_date)
        if not rule:
            continue
        max_per_day = flt(rule.get("max_quantity_per_day"))
        if max_per_day <= 0:
            continue
        if agg["planned"] > max_per_day:
            alerts.append({
                "date": planned_date.isoformat() if isinstance(planned_date, date_cls) else str(planned_date),
                "category": category,
                "planned": agg["planned"],
                "capacity": max_per_day,
                "over_by": agg["planned"] - max_per_day,
                "uom": rule.get("uom") or "",
                "orders": agg["orders"],
                "rule_name": rule.get("name"),
            })

    alerts.sort(key=lambda r: (r["date"], r["category"]))
    return alerts


# ──────────────────────────────────────────────────────────────────────────
# Calendar
# ──────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def get_production_calendar_data(year=None, month=None):
    """Return per-date totals + capacities for a month grid.

    Args:
        year: integer year (defaults to today's year).
        month: integer month 1-12 (defaults to today's month).

    Returns:
        {
            "year": int, "month": int,
            "days": [
                {date, totals: {category: planned}, capacities: {category: max},
                 over_categories: [...], status: "Within"|"Over"|"Empty",
                 orders: [{name, category, qty}]}
            ],
            "categories": [...]
        }
    """
    today_date = getdate(today())
    year = int(year) if year else today_date.year
    month = int(month) if month else today_date.month

    if month < 1 or month > 12:
        frappe.throw(_("Month must be between 1 and 12"))

    first_day = date_cls(year, month, 1)
    days_in_month = calendar.monthrange(year, month)[1]
    last_day = date_cls(year, month, days_in_month)

    orders = frappe.get_all(
        "Production Order",
        filters=[
            ["planned_date", ">=", first_day],
            ["planned_date", "<=", last_day],
            ["status", "!=", "Cancelled"],
        ],
        fields=[
            "name", "production_order_number", "planned_date",
            "production_capacity_category", "capacity_quantity", "capacity_uom",
            "item_description", "status",
        ],
        order_by="planned_date asc",
    )

    by_date_cat = defaultdict(lambda: defaultdict(float))
    orders_by_date = defaultdict(list)
    for o in orders:
        d = getdate(o.planned_date)
        category = o.production_capacity_category or "Other"
        qty = flt(o.capacity_quantity)
        by_date_cat[d][category] += qty
        orders_by_date[d].append({
            "name": o.name,
            "production_order_number": o.production_order_number or o.name,
            "category": category,
            "qty": qty,
            "uom": o.capacity_uom or "",
            "item_description": o.item_description or "",
            "status": o.status or "",
        })

    rules_cache = {}

    def _capacity(category, on_date):
        cache_key = (category, on_date.isoformat())
        if cache_key not in rules_cache:
            rules_cache[cache_key] = get_active_capacity(category, on_date)
        return rules_cache[cache_key]

    days = []
    for day_index in range(1, days_in_month + 1):
        d = date_cls(year, month, day_index)
        totals = dict(by_date_cat.get(d, {}))
        capacities = {}
        over_categories = []

        for category in totals.keys():
            rule = _capacity(category, d)
            if rule and flt(rule.get("max_quantity_per_day")) > 0:
                cap = flt(rule.get("max_quantity_per_day"))
                capacities[category] = cap
                if totals[category] > cap:
                    over_categories.append({
                        "category": category,
                        "planned": totals[category],
                        "capacity": cap,
                        "over_by": totals[category] - cap,
                        "uom": rule.get("uom") or "",
                    })

        if over_categories:
            status = "Over"
        elif totals:
            status = "Within"
        else:
            status = "Empty"

        days.append({
            "date": d.isoformat(),
            "day": day_index,
            "totals": totals,
            "capacities": capacities,
            "over_categories": over_categories,
            "status": status,
            "orders": orders_by_date.get(d, []),
        })

    return {
        "year": year,
        "month": month,
        "month_name": calendar.month_name[month],
        "first_weekday": first_day.weekday(),
        "days_in_month": days_in_month,
        "days": days,
        "categories": CATEGORIES,
        "prev_month": _shift_month(year, month, -1),
        "next_month": _shift_month(year, month, 1),
    }


def _shift_month(year, month, delta):
    base = date_cls(year, month, 1)
    shifted = getdate(add_months(base, delta))
    return {"year": shifted.year, "month": shifted.month}


# ──────────────────────────────────────────────────────────────────────────
# Ad-hoc revalidation
# ──────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def evaluate_production_order(name):
    """Re-run capacity evaluation for a Production Order and persist the result."""
    if not name:
        frappe.throw(_("Production Order name is required"))

    doc = frappe.get_doc("Production Order", name)
    evaluate_production_order_capacity(doc)
    doc.db_update()

    return {
        "name": doc.name,
        "capacity_status": doc.capacity_status,
        "capacity_message": doc.capacity_message,
        "production_capacity_category": doc.production_capacity_category,
        "capacity_quantity": doc.capacity_quantity,
    }


# ──────────────────────────────────────────────────────────────────────────
# Dispatch visibility - lets Production see when their output actually
# shipped, not just when a Production Order was raised for it.
# ──────────────────────────────────────────────────────────────────────────


def _attach_dispatch_info(orders):
    """Bulk-attach loading_delivery_note / delivery_note_status onto a list
    of Production Order rows that carry an apc_batch, in one query rather
    than one per row."""
    batch_names = [row.apc_batch for row in orders if row.get("apc_batch")]
    if not batch_names:
        for row in orders:
            row["loading_delivery_note"] = None
            row["delivery_note_status"] = None
        return

    rows = frappe.db.sql(
        """
        SELECT ldb.batch, ldn.name AS loading_delivery_note, ldn.delivery_note_status
        FROM `tabLoading DN Batch` ldb
        INNER JOIN `tabLoading Delivery Note` ldn ON ldn.name = ldb.parent
        WHERE ldb.batch IN %(batches)s
        ORDER BY ldn.modified DESC
        """,
        {"batches": batch_names},
        as_dict=True,
    )
    by_batch = {}
    for r in rows:
        by_batch.setdefault(r.batch, r)  # first hit wins - most recently modified, per ORDER BY

    for row in orders:
        info = by_batch.get(row.get("apc_batch"))
        row["loading_delivery_note"] = info.loading_delivery_note if info else None
        row["delivery_note_status"] = info.delivery_note_status if info else None


@frappe.whitelist()
def get_loading_delivery_notes_for_production_order(production_order):
    """All Loading Delivery Notes that have dispatched (or are dispatching)
    the batch this Production Order fed, most recent first."""
    apc_batch = frappe.db.get_value("Production Order", production_order, "apc_batch")
    if not apc_batch:
        return []

    return frappe.db.sql(
        """
        SELECT ldn.name, ldn.delivery_note_status, ldn.dispatch_confirmed,
               ldn.job_order, ldb.allocated_qty, ldb.dispatched_qty
        FROM `tabLoading DN Batch` ldb
        INNER JOIN `tabLoading Delivery Note` ldn ON ldn.name = ldb.parent
        WHERE ldb.batch = %s
        ORDER BY ldn.modified DESC
        """,
        (apc_batch,),
        as_dict=True,
    )
