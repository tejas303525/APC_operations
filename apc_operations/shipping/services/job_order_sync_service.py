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
