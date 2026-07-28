# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Sync Delivery Order header and items from a linked Job Order."""

from __future__ import annotations

import frappe
from frappe.utils import flt


def resolve_port_label(value: str | None) -> str | None:
	if not value:
		return None
	if frappe.db.exists("Port", value):
		return frappe.db.get_value("Port", value, "port_name") or value
	return value


def job_order_row(job_order: str) -> dict | None:
	if not job_order or not frappe.db.exists("Job Order", job_order):
		return None
	return frappe.db.get_value(
		"Job Order",
		job_order,
		[
			"name",
			"job_order_number",
			"commercial_movement",
			"customer",
			"customer_name",
			"supplier",
			"supplier_name",
			"terms_of_delivery",
			"port_of_loading",
			"port_of_discharge",
			"mode_of_transport",
		],
		as_dict=True,
	)


def job_order_items_for_delivery_order(job_order: str, *, no_of_containers=None) -> list[dict]:
	rows = frappe.get_all(
		"Job Order Item",
		filters={"parent": job_order},
		fields=[
			"item",
			"item_name",
			"description",
			"quantity",
			"uom",
			"net_weight",
			"planned_product_kg",
			"planned_gross_kg",
			"packaging_qty",
			"packing_unit_type",
		],
		order_by="idx asc",
	)
	items = []
	for row in rows:
		if not row.get("item"):
			continue
		product_kg = flt(row.get("planned_product_kg")) or flt(row.get("net_weight"))
		gross_kg = flt(row.get("planned_gross_kg"))
		item_row = {
			"item_code": row["item"],
			"item_name": row.get("item_name"),
			"description": row.get("description"),
			"qty": row.get("quantity") or 0,
			"uom": row.get("uom") or "Nos",
			"net_weight": product_kg,
			"gross_weight": gross_kg,
			"no_of_packages": int(flt(row.get("packaging_qty"))),
			"packing_unit_type": row.get("packing_unit_type"),
		}
		if no_of_containers:
			item_row["no_of_containers"] = no_of_containers
		items.append(item_row)
	return items


def apply_job_order_to_delivery_order(
	doc,
	*,
	jo: dict | None = None,
	sync_items: bool = False,
) -> None:
	"""Copy Job Order commercial and routing fields onto a Delivery Order."""
	if not doc.get("job_order"):
		return

	jo = jo or job_order_row(doc.job_order)
	if not jo:
		return

	if jo.get("job_order_number"):
		doc.job_order_number = jo["job_order_number"]
	if jo.get("terms_of_delivery"):
		doc.terms_of_delivery = jo["terms_of_delivery"]
	if jo.get("customer") and not doc.get("customer"):
		doc.customer = jo["customer"]
	if jo.get("customer_name"):
		doc.customer_name = jo["customer_name"]
	if jo.get("customer") and not doc.get("buyer"):
		doc.buyer = jo["customer"]

	movement = (jo.get("commercial_movement") or "Export").strip()
	if frappe.db.has_column("Delivery Order", "commercial_movement"):
		doc.commercial_movement = movement
	if movement == "Import":
		if jo.get("supplier") and frappe.db.has_column("Delivery Order", "supplier"):
			doc.supplier = jo.get("supplier")
		if jo.get("supplier_name") and frappe.db.has_column("Delivery Order", "supplier_name"):
			doc.supplier_name = jo.get("supplier_name")

	pol = resolve_port_label(jo.get("port_of_loading"))
	pod = resolve_port_label(jo.get("port_of_discharge"))
	if pol:
		doc.port_of_loading = pol
	if pod:
		doc.port_of_discharge = pod
		if not doc.get("destination"):
			doc.destination = pod

	if sync_items:
		items = job_order_items_for_delivery_order(doc.job_order)
		if items:
			doc.items = []
			for row in items:
				doc.append("items", row)

	_apply_packing_totals_to_delivery_order(doc)


def _apply_packing_totals_to_delivery_order(doc) -> None:
	from apc_operations.shipping.services.packing_calculation_service import (
		sum_job_order_packing_totals,
	)

	if not doc.get("job_order"):
		return
	totals = sum_job_order_packing_totals(doc.job_order)
	if flt(totals.get("planned_product_kg")) > 0:
		doc.planned_product_kg = totals["planned_product_kg"]
	if flt(totals.get("planned_gross_kg")) > 0:
		doc.planned_gross_kg = totals["planned_gross_kg"]
	if int(totals.get("packaging_qty") or 0) > 0:
		doc.expected_packaging_qty = int(totals["packaging_qty"])
	first_pkg = (doc.items or [{}])[0] if doc.items else {}
	if first_pkg.get("packing_unit_type") and not doc.get("packaging_type"):
		doc.packaging_type = first_pkg.get("packing_unit_type")


def terms_of_delivery_for_delivery_order(
	do_name: str | None,
	*,
	job_order: str | None = None,
	stored_terms: str | None = None,
) -> str | None:
	"""Incoterm for consoles: DO value first, else linked Job Order."""
	terms = (stored_terms or "").strip()
	if terms:
		return terms
	jo = job_order
	if not jo and do_name:
		jo = frappe.db.get_value("Delivery Order", do_name, "job_order")
	if not jo:
		return None
	return frappe.db.get_value("Job Order", jo, "terms_of_delivery")
