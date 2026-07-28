# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Print context for Standard Delivery Order (transport / planned qty)."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt

from apc_operations.shipping.services.loading_dn_print_service import (
	is_bulk_packaging,
	is_drum_packaging,
	job_order_packaging_by_item,
	resolve_buyer_party,
)


def _resolve_shipping_booking_name(
	job_order: str | None,
	transport_schedule: str | None,
) -> str | None:
	if transport_schedule:
		sb = frappe.db.get_value("Transport Schedule", transport_schedule, "shipping_booking")
		if sb:
			return sb
	if not job_order:
		return None
	sb = frappe.db.get_value("Job Order", job_order, "shipping_booking")
	if sb:
		return sb
	return frappe.db.get_value(
		"Shipping Booking",
		{"job_order": job_order, "docstatus": ["!=", 2]},
		"name",
		order_by="modified desc",
	)


def _resolve_container_fields(
	si: dict | None,
	transport_schedule: str | None,
	job_order: str | None = None,
) -> tuple[str | None, str | None]:
	container_number = (si or {}).get("container_number") or None
	container_type = (si or {}).get("container_type") or None
	# Legacy rows stored container size/type in container_number — prefer booking ID when that happens.
	if container_number and container_type and container_number.strip() == container_type.strip():
		container_number = None

	if transport_schedule and not container_type:
		container_type = frappe.db.get_value(
			"Transport Schedule", transport_schedule, "container_type"
		)

	sb_name = _resolve_shipping_booking_name(job_order, transport_schedule)
	if sb_name:
		sb = frappe.db.get_value(
			"Shipping Booking",
			sb_name,
			["container_number", "container_type"],
			as_dict=True,
		)
		if sb:
			if not container_number and sb.get("container_number"):
				container_number = sb.container_number
			if not container_type and sb.get("container_type"):
				container_type = sb.container_type

	return (container_number or None), (container_type or None)


def _resolve_packaging_type(do, job_order: str | None) -> str | None:
	packaging_type = (do.packaging_type or do.vehicle_type or "").strip() or None
	if packaging_type or not job_order:
		return packaging_type
	return frappe.db.get_value("Job Order Item", {"parent": job_order}, "packaging_type")


def _resolve_marks_and_packages(
	do,
	*,
	container_number: str | None,
	container_type: str | None,
	packaging_type: str | None,
) -> tuple[str, str]:
	items = do.get("items") or []
	total_packages = sum(int(flt(row.no_of_packages)) for row in items)
	total_containers = sum(int(flt(row.no_of_containers)) for row in items)
	material = (items[0].item_name or items[0].item_code) if items else None

	bulk = is_bulk_packaging(packaging_type, material)
	drums = is_drum_packaging(packaging_type, material) and not bulk
	type_label = (container_type or container_number or packaging_type or "").strip()

	if total_containers > 0:
		marks = container_number or type_label or "-"
		if type_label and type_label != marks:
			kind = f"{total_containers} x {type_label}"
		else:
			suffix = "s" if total_containers > 1 else ""
			kind = f"{total_containers} Container{suffix}"
		return marks, kind

	if drums and total_packages > 0:
		return container_number or "-", f"{total_packages} Drums"

	if bulk:
		return container_number or "-", packaging_type or "Bulk"

	if total_packages > 0:
		label = packaging_type or "Packages"
		return container_number or type_label or "-", f"{total_packages} {label}"

	if packaging_type:
		return container_number or type_label or "-", packaging_type

	if type_label:
		return type_label, type_label

	return "-", "-"


@frappe.whitelist()
def get_print_context(do_name: str) -> dict[str, Any]:
	"""Resolve transport, commercial header, and planned quantities for DO print."""
	from apc_operations.services.delivery_order_service import resolve_transport_context_for_do
	from apc_operations.shipping.services.dispatch_validation_service import (
		resolve_security_inspection_for_do,
	)

	do = frappe.get_doc("Delivery Order", do_name)
	transport = resolve_transport_context_for_do(do_name)

	jo = None
	if do.job_order and frappe.db.exists("Job Order", do.job_order):
		jo = frappe.db.get_value(
			"Job Order",
			do.job_order,
			["date", "payment_terms", "job_order_number"],
			as_dict=True,
		)

	si_name = resolve_security_inspection_for_do(do_name)
	si = None
	if si_name:
		si = frappe.db.get_value(
			"Security Inspection",
			si_name,
			[
				"name",
				"container_number",
				"container_type",
				"seal_number",
				"vehicle_number",
				"driver_name",
				"driver_phone",
				"transporter",
			],
			as_dict=True,
		)

	sddn = None
	if do.job_order:
		sddn = frappe.db.get_value(
			"Security Draft Delivery Note",
			{"job_order": do.job_order},
			"name",
		)

	driver_name = transport.get("driver_name") or (si and si.driver_name)
	driver_phone = transport.get("driver_contact") or (si and si.driver_phone)
	vehicle = transport.get("truck_number") or (si and si.vehicle_number)

	transporter = do.transporter
	if not transporter and si and si.transporter:
		transporter = si.transporter
	if not transporter and transport.get("transport_schedule"):
		transporter = frappe.db.get_value(
			"Transport Schedule", transport["transport_schedule"], "transporter"
		)

	total_qty = flt(do.total_qty)
	if total_qty <= 0:
		total_qty = sum(flt(row.qty) for row in (do.items or []))

	uom = ""
	if do.items:
		uoms = {row.uom for row in do.items if row.uom}
		uom = next(iter(uoms)) if len(uoms) == 1 else (do.items[0].uom or "")

	planned_qty_display = "-"
	if total_qty > 0:
		planned_qty_display = f"{total_qty:g} {uom}".strip()

	jo_packaging = job_order_packaging_by_item(do.job_order)
	default_packaging = "-"

	item_lines: list[dict[str, Any]] = []
	for row in do.get("items") or []:
		qty = flt(row.qty)
		line_uom = row.uom or ""
		qty_display = "-"
		if qty > 0:
			qty_display = f"{qty:g} {line_uom}".strip()
		item_lines.append(
			{
				"item_code": row.item_code,
				"description": row.description or row.item_name or row.item_code,
				"qty": qty,
				"uom": line_uom,
				"qty_display": qty_display,
				"net_weight": flt(row.net_weight),
				"package_type": row.get("container_type") or row.get("package_type"),
				"packaging": jo_packaging.get(row.item_code) or default_packaging,
			}
		)

	delivery_date = do.posting_date
	if do.loading_delivery_note:
		ldn_date = frappe.db.get_value(
			"Loading Delivery Note", do.loading_delivery_note, "loading_date"
		)
		if ldn_date:
			delivery_date = ldn_date

	container_number, container_type = _resolve_container_fields(
		si,
		transport.get("transport_schedule"),
		do.job_order,
	)
	packaging_type = _resolve_packaging_type(do, do.job_order)
	if packaging_type:
		default_packaging = packaging_type
		for line in item_lines:
			if line["packaging"] == "-":
				line["packaging"] = packaging_type

	buyer_party = resolve_buyer_party(
		buyer=do.buyer,
		customer=do.customer,
		customer_name=do.customer_name,
		shipping_address=do.get("shipping_address"),
		shipping_address_name=do.get("shipping_address_name"),
	)
	marks_and_nos, no_and_kind_of_packages = _resolve_marks_and_packages(
		do,
		container_number=container_number,
		container_type=container_type,
		packaging_type=packaging_type,
	)

	return {
		"driver_name": driver_name,
		"driver_phone": driver_phone,
		"vehicle": vehicle,
		"transporter": transporter,
		"transport_schedule": transport.get("transport_schedule"),
		"security_inspection": si_name,
		"dispatch_document_no": si_name,
		"dispatched_through": vehicle,
		"container_number": container_number,
		"container_type": container_type,
		"packaging_type": packaging_type,
		"marks_and_nos": marks_and_nos,
		"no_and_kind_of_packages": no_and_kind_of_packages,
		"seal_number": (si and si.seal_number) or None,
		"payment_terms": jo.payment_terms if jo else None,
		"job_order_date": jo.date if jo else None,
		"supplier_ref": sddn or do.get("transport_delivery_order_number"),
		"other_reference": do.get("transport_delivery_order_number") or do.remarks,
		"planned_qty": total_qty,
		"planned_uom": uom,
		"planned_qty_display": planned_qty_display,
		"total_planned_net_kg": flt(do.total_net_weight),
		"loading_delivery_note": do.loading_delivery_note,
		"delivery_date": delivery_date,
		"item_lines": item_lines,
		"buyer_name": buyer_party["buyer_name"],
		"buyer_address": buyer_party["buyer_address"],
	}
