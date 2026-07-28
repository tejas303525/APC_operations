# Copyright (c) 2026, APC and contributors
"""Aggregate import receipt totals for partial-arrival GRN Summary."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt

_POSTED_GRN_STATUSES = frozenset({"Approved", "Posted"})


def _job_order_order_quantity(job_order: str) -> float:
	items = frappe.get_all(
		"Job Order Item", filters={"parent": job_order}, fields=["quantity"]
	)
	total = sum(flt(row.quantity) for row in items)
	if total > 0:
		return total
	return 0.0


def _import_grn_arrived_total(grn_name: str) -> float:
	grn = frappe.get_doc("Import GRN", grn_name)
	if flt(grn.total_arrived_qty) > 0:
		return flt(grn.total_arrived_qty)
	return sum(flt(row.arrived_qty) for row in grn.items or [])


def _import_jo_received_quantity(job_order: str) -> float:
	if not job_order or not frappe.db.table_exists("Import GRN"):
		return 0.0
	rows = frappe.get_all(
		"Import GRN",
		filters={
			"job_order": job_order,
			"grn_status": ["in", list(_POSTED_GRN_STATUSES)],
			"commercial_movement": "Import",
		},
		pluck="name",
	)
	return sum(_import_grn_arrived_total(name) for name in rows)


def partial_import_receipt_summary(job_order: str) -> dict[str, Any] | None:
	"""Return receipt totals when JO order qty exceeds posted arrived qty."""
	order_qty = _job_order_order_quantity(job_order)
	received = _import_jo_received_quantity(job_order)
	pending = max(order_qty - received, 0)

	if order_qty <= 0 or received <= 0 or pending <= 0:
		return None

	return {
		"job_order_quantity": order_qty,
		"total_expected_quantity": order_qty,
		"total_received_quantity": received,
		"pending_receipt_quantity": pending,
	}


def latest_posted_import_grn(job_order: str) -> dict[str, Any] | None:
	if not job_order or not frappe.db.table_exists("Import GRN"):
		return None
	rows = frappe.get_all(
		"Import GRN",
		filters={
			"job_order": job_order,
			"grn_status": ["in", list(_POSTED_GRN_STATUSES)],
			"commercial_movement": "Import",
		},
		fields=[
			"name",
			"delivery_order",
			"grn_status",
			"total_expected_qty",
			"total_arrived_qty",
			"pending_qty",
			"receipt_type",
			"is_partial_receipt",
			"posting_date",
			"modified",
		],
		order_by="modified desc",
		limit=1,
	)
	return rows[0] if rows else None


def import_grn_rows_for_job_order(job_order: str) -> list[dict[str, Any]]:
	if not job_order or not frappe.db.table_exists("Import GRN"):
		return []
	return frappe.get_all(
		"Import GRN",
		filters={"job_order": job_order, "commercial_movement": "Import"},
		fields=[
			"name",
			"delivery_order",
			"grn_status",
			"total_expected_qty",
			"total_arrived_qty",
			"pending_qty",
			"receipt_type",
			"is_partial_receipt",
			"posting_date",
		],
		order_by="modified desc",
	)
