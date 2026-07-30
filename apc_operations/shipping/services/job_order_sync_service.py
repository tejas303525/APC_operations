# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe

LINKED_JOB_ORDER_NUMBER_DOCTYPES = (
	"Transport Schedule",
	"Shipping Booking",
	"Delivery Order",
	"Security Draft Delivery Note",
	"Loading Delivery Note",
)


def get_live_job_order_number(job_order: str | None) -> str | None:
	if not job_order:
		return None
	return frappe.db.get_value("Job Order", job_order, "job_order_number")


def sync_job_order_number_to_linked(job_order: str, job_order_number: str | None = None) -> list[str]:
	"""Push the current Job Order number into every linked operational document.

	Returns the list of ``DocType::name`` records that were updated.
	"""
	if not job_order:
		return []

	if job_order_number is None:
		job_order_number = get_live_job_order_number(job_order)

	if not job_order_number:
		return []

	updated: list[str] = []
	for doctype in LINKED_JOB_ORDER_NUMBER_DOCTYPES:
		for name in frappe.get_all(doctype, filters={"job_order": job_order}, pluck="name"):
			if frappe.db.get_value(doctype, name, "job_order_number") == job_order_number:
				continue
			frappe.db.set_value(doctype, name, "job_order_number", job_order_number, update_modified=False)
			updated.append(f"{doctype}::{name}")

	return updated


def attach_live_job_order_numbers(rows: list[dict]) -> None:
	"""Mutate ``rows`` in place, filling ``job_order_number`` from the live Job Order."""
	if not rows:
		return

	job_orders = {row.get("job_order") for row in rows if row.get("job_order")}
	if not job_orders:
		return

	numbers = dict(
		frappe.get_all(
			"Job Order",
			filters={"name": ["in", list(job_orders)]},
			fields=["name", "job_order_number"],
			as_list=True,
		)
	)

	for row in rows:
		jo = row.get("job_order")
		if jo and numbers.get(jo):
			row["job_order_number"] = numbers.get(jo)


def attach_job_order_product_summary(rows: list[dict]) -> None:
	"""Mutate ``rows`` in place, adding ``product_summary``/``packaging_summary``
	(and the ``product``/``packaging_type`` aliases the Transportation console's
	existing ``renderProductPackagingCardRows()`` already reads) from each
	row's linked Job Order's items - one product/packaging line for console
	cards across Shipping, Transportation, Security, and QC, all of which key
	off the same ``job_order`` field.

	``product_summary``: item/product name, e.g. "ETAC" or "ETAC +2 more" for
	a multi-item Job Order.
	``packaging_summary``: packaging type and qty of the first item, e.g.
	"Steel drums x 80".
	"""
	if not rows:
		return

	job_orders = {row.get("job_order") for row in rows if row.get("job_order")}
	if not job_orders:
		return

	items = frappe.get_all(
		"Job Order Item",
		filters={"parent": ["in", list(job_orders)]},
		fields=["parent", "item", "product_name", "packaging_type", "packaging_qty"],
		order_by="parent asc, idx asc",
	)
	by_job_order: dict[str, list] = {}
	for item in items:
		by_job_order.setdefault(item.parent, []).append(item)

	for row in rows:
		jo = row.get("job_order")
		jo_items = by_job_order.get(jo) if jo else None
		if not jo_items:
			row.setdefault("product_summary", None)
			row.setdefault("packaging_summary", None)
			continue

		first = jo_items[0]
		product_summary = first.product_name or first.item
		if len(jo_items) > 1:
			product_summary = f"{product_summary} +{len(jo_items) - 1} more"
		row["product_summary"] = product_summary
		row.setdefault("product", first.product_name or first.item)

		if first.packaging_type:
			row["packaging_summary"] = (
				f"{first.packaging_type} x {int(first.packaging_qty)}"
				if first.packaging_qty
				else first.packaging_type
			)
		else:
			row["packaging_summary"] = None
		row.setdefault("packaging_type", first.packaging_type)
