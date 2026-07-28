# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Partial outward dispatch totals and follow-up transport eligibility."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt

_COMPLETED_TRANSPORT_STATUSES = frozenset({"Delivered", "Completed", "Cancelled"})


def job_order_order_quantity(job_order: str) -> float:
	"""Total quantity on Job Order lines (or Sales Demand fallback)."""
	items = frappe.get_all(
		"Job Order Item", filters={"parent": job_order}, fields=["quantity"]
	)
	total = sum(flt(row.quantity) for row in items)
	if total > 0:
		return total

	sales_demand = frappe.db.get_value("Job Order", job_order, "sales_demand")
	if sales_demand:
		return flt(
			frappe.db.get_value("APC Sales Demand", sales_demand, "total_demand_quantity")
		)
	return 0.0


def job_order_dispatched_quantity(job_order: str) -> float:
	"""Dispatched qty from confirmed Loading DNs; Sales Demand as fallback."""
	dispatched = flt(
		frappe.db.sql(
			"""
			SELECT COALESCE(
				SUM(COALESCE(b.dispatched_qty, b.allocated_qty, 0)),
				0
			)
			FROM `tabLoading DN Batch` b
			INNER JOIN `tabLoading Delivery Note` ldn ON ldn.name = b.parent
			WHERE ldn.job_order = %s
			  AND ldn.dispatch_confirmed = 1
			  AND ldn.docstatus != 2
			""",
			job_order,
		)[0][0]
	)
	if dispatched > 0:
		return dispatched

	sales_demand = frappe.db.get_value("Job Order", job_order, "sales_demand")
	if sales_demand:
		return flt(
			frappe.db.get_value("APC Sales Demand", sales_demand, "total_dispatched_quantity")
		)
	return 0.0


def get_partial_dispatch_summary(job_order: str) -> dict[str, Any] | None:
	"""Return dispatch totals when order qty exceeds confirmed dispatched qty."""
	order_qty = job_order_order_quantity(job_order)
	dispatched = job_order_dispatched_quantity(job_order)
	pending = max(order_qty - dispatched, 0)

	if order_qty <= 0 or dispatched <= 0 or pending <= 0:
		return None

	sales_demand = frappe.db.get_value("Job Order", job_order, "sales_demand")
	sd_status = None
	if sales_demand:
		sd_status = frappe.db.get_value("APC Sales Demand", sales_demand, "status")

	return {
		"sales_demand": sales_demand,
		"sales_demand_status": sd_status,
		"job_order_quantity": order_qty,
		"total_demand_quantity": order_qty,
		"total_dispatched_quantity": dispatched,
		"pending_dispatch_quantity": pending,
	}


def has_issued_loading_delivery_note(job_order: str) -> bool:
	return bool(
		frappe.db.exists(
			"Loading Delivery Note",
			{"job_order": job_order, "docstatus": ["<", 2]},
		)
	)


def get_active_outward_transport(job_order: str) -> dict[str, Any] | None:
	"""Latest outward transport leg that is not completed or cancelled."""
	rows = frappe.get_all(
		"Transport Schedule",
		filters={
			"job_order": job_order,
			"transport_type": "Outward",
			"transport_status": ["not in", list(_COMPLETED_TRANSPORT_STATUSES)],
		},
		fields=[
			"name",
			"transport_status",
			"shipping_booking",
			"container_count",
			"scheduled_pickup_date",
			"scheduled_delivery_date",
			"delivery_location",
			"delivery_address",
			"assigned_vehicle",
			"assigned_driver",
			"driver_phone",
			"transporter",
			"outward_type",
		],
		order_by="modified desc",
		limit=1,
	)
	return rows[0] if rows else None
