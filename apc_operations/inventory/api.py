# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Whitelisted API endpoints powering the Stock Console page."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

_ADJUST_ROLES = {"Shipping Manager", "System Manager"}


def _stock_console_permission_check():
	roles = set(frappe.get_roles(frappe.session.user))
	allowed = {"Shipping Manager", "Shipping User", "Shipping Coordinator", "System Manager"}
	if not roles.intersection(allowed):
		frappe.throw(_("Not permitted to view the Stock Console."), frappe.PermissionError)


@frappe.whitelist()
def get_stock_console_data():
	"""Dashboard KPIs + per-product stock summary for the Stock Console page."""
	_stock_console_permission_check()

	rows = frappe.db.sql(
		"""
		SELECT
			item.name AS product,
			item.item_name,
			IFNULL(SUM(b.batch_quantity - IFNULL(b.dispatched_quantity, 0)), 0) AS stock_in_hand,
			IFNULL(SUM(b.allocated_quantity), 0) AS reserved_qty,
			IFNULL(SUM(b.available_quantity), 0) AS free_qty
		FROM `tabItem` item
		LEFT JOIN `tabAPC Batch` b ON b.product = item.name AND b.batch_status != 'Cancelled'
		WHERE item.disabled = 0 AND item.is_sales_item = 1
		GROUP BY item.name
		ORDER BY item.item_name
		""",
		as_dict=True,
	)

	transit_rows = frappe.db.sql(
		"""
		SELECT bt.product, SUM(ldb.dispatched_qty) AS qty
		FROM `tabLoading DN Batch` ldb
		INNER JOIN `tabLoading Delivery Note` ldn ON ldn.name = ldb.parent
		INNER JOIN `tabAPC Batch` bt ON bt.name = ldb.batch
		LEFT JOIN `tabJob Order` jo ON jo.name = ldn.job_order
		LEFT JOIN `tabTransport Schedule` ts ON ts.name = jo.transport_schedule
		WHERE ldn.dispatch_confirmed = 1
		  AND (ts.transport_status IS NULL OR ts.transport_status NOT IN ('Delivered', 'Completed', 'Cancelled'))
		GROUP BY bt.product
		""",
		as_dict=True,
	)
	transit_by_product = {r.product: flt(r.qty) for r in transit_rows}

	for row in rows:
		row["in_transit"] = transit_by_product.get(row.product, 0.0)

	kpis = {
		"total_products": len(rows),
		"total_stock_in_hand": sum(flt(r.stock_in_hand) for r in rows),
		"total_reserved": sum(flt(r.reserved_qty) for r in rows),
		"total_free": sum(flt(r.free_qty) for r in rows),
		"total_in_transit": sum(flt(r.get("in_transit")) for r in rows),
	}

	return {"kpis": kpis, "products": rows}


@frappe.whitelist()
def get_batch_detail_for_product(product):
	"""Batch-level rows for one product, each with the Job Order(s) its
	reserved quantity is held against - the reservation traceability
	sales staff need, not just a free-floating aggregate number."""
	_stock_console_permission_check()

	batches = frappe.get_all(
		"APC Batch",
		filters={"product": product, "batch_status": ["!=", "Cancelled"]},
		fields=[
			"name", "batch_number", "manufacturing_date", "warehouse",
			"batch_quantity", "available_quantity", "allocated_quantity",
			"dispatched_quantity", "quality_status", "batch_status", "uom",
		],
		order_by="manufacturing_date asc, creation asc",
	)
	if not batches:
		return []

	batch_names = [b.name for b in batches]
	reservations = frappe.db.sql(
		"""
		SELECT
			bad.batch,
			bad.remaining_quantity,
			bad.allocated_quantity,
			bad.dispatched_quantity,
			sd.name AS sales_demand,
			sd.customer,
			cust.customer_name,
			jo.name AS job_order,
			jo.job_order_number
		FROM `tabAPC Batch Allocation Detail` bad
		INNER JOIN `tabAPC Batch Allocation` alloc ON alloc.name = bad.parent
		LEFT JOIN `tabAPC Sales Demand` sd ON sd.name = alloc.sales_demand
		LEFT JOIN `tabCustomer` cust ON cust.name = sd.customer
		LEFT JOIN `tabJob Order` jo ON jo.sales_demand = sd.name
		WHERE bad.batch IN %(batches)s
		  AND bad.status NOT IN ('Released', 'Cancelled')
		  AND bad.remaining_quantity > 0
		ORDER BY bad.creation
		""",
		{"batches": batch_names},
		as_dict=True,
	)

	by_batch = {}
	for r in reservations:
		by_batch.setdefault(r.batch, []).append(r)

	for b in batches:
		b["reservations"] = by_batch.get(b.name, [])

	return batches


@frappe.whitelist()
def adjust_batch_stock(batch, adjustment_qty, reason):
	"""Manual +/- correction to a batch's quantity (found extra stock,
	wastage, damage, physical count reconciliation). Restricted to
	Shipping Manager / System Manager - a plain Shipping User can view
	reservations but not alter quantities. Logged as a comment on the
	batch for an audit trail rather than a silent field update."""
	roles = set(frappe.get_roles(frappe.session.user))
	if not roles.intersection(_ADJUST_ROLES):
		frappe.throw(
			_("Only a Shipping Manager or System Manager can adjust batch quantities."),
			frappe.PermissionError,
		)

	adjustment_qty = flt(adjustment_qty)
	if adjustment_qty == 0:
		frappe.throw(_("Adjustment quantity cannot be zero."))
	if not (reason or "").strip():
		frappe.throw(_("A reason is required for stock adjustments."))

	batch_doc = frappe.get_doc("APC Batch", batch)

	if adjustment_qty < 0 and abs(adjustment_qty) > flt(batch_doc.available_quantity):
		frappe.throw(
			_("Cannot subtract {0}: only {1} is free/unreserved on batch {2}.").format(
				abs(adjustment_qty), batch_doc.available_quantity, batch
			)
		)

	new_batch_qty = flt(batch_doc.batch_quantity) + adjustment_qty
	new_available_qty = flt(batch_doc.available_quantity) + adjustment_qty

	batch_doc.db_set("batch_quantity", new_batch_qty, update_modified=False)
	batch_doc.db_set("available_quantity", new_available_qty, update_modified=False)

	sign = "+" if adjustment_qty > 0 else ""
	batch_doc.add_comment(
		"Comment",
		_("Manual stock adjustment by {0}: {1}{2} {3} - {4}. New available: {5}").format(
			frappe.session.user, sign, adjustment_qty, batch_doc.uom or "", reason, new_available_qty
		),
	)

	return {
		"batch": batch,
		"new_batch_quantity": new_batch_qty,
		"new_available_quantity": new_available_qty,
	}


@frappe.whitelist()
def add_opening_stock(product, quantity, warehouse=None, manufacturing_date=None, remarks=None):
	"""Seed real stock for a product that has no batch tracked yet - creates
	a new APC Batch on the spot rather than requiring staff to go through
	Production or understand batch mechanics just to enter a stock-take
	number. Marked Approved/Available immediately (this is verified physical
	count, not something awaiting QC), so it's usable by FIFO reservation
	right away. Same role restriction as adjust_batch_stock - this is
	still a quantity-altering action."""
	roles = set(frappe.get_roles(frappe.session.user))
	if not roles.intersection(_ADJUST_ROLES):
		frappe.throw(
			_("Only a Shipping Manager or System Manager can add opening stock."),
			frappe.PermissionError,
		)

	quantity = flt(quantity)
	if quantity <= 0:
		frappe.throw(_("Quantity must be greater than zero."))

	batch = frappe.new_doc("APC Batch")
	batch.product = product
	batch.batch_quantity = quantity
	batch.available_quantity = quantity
	batch.allocated_quantity = 0
	batch.manufacturing_date = manufacturing_date or frappe.utils.today()
	batch.warehouse = warehouse
	batch.batch_status = "Active"
	batch.quality_status = "Approved"
	batch.stock_status = "Available"
	batch.insert(ignore_permissions=True)

	batch.add_comment(
		"Comment",
		_("Opening stock entered by {0}: {1}{2}").format(
			frappe.session.user, quantity, f" - {remarks}" if remarks else ""
		),
	)

	return {"batch": batch.name, "available_quantity": quantity}
