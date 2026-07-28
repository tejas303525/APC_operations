# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Print context for Standard Transport PO — live charges from Transport Schedule."""

from __future__ import annotations

import frappe
from frappe.utils import flt


@frappe.whitelist()
def get_print_context(transport_po_name: str) -> dict:
	doc = frappe.get_doc("Transport PO Request", transport_po_name)
	ts_name = doc.transport_schedule
	ts = {}
	if ts_name:
		ts = frappe.db.get_value(
			"Transport Schedule",
			ts_name,
			[
				"name",
				"transport_charges",
				"fuel_cost",
				"additional_charges",
				"total_cost",
				"currency",
				"driver_phone",
				"gate_cutoff",
			],
			as_dict=True,
		) or {}

	transport_charges = flt(ts.get("transport_charges") if ts else doc.transport_charges)
	fuel_cost = flt(ts.get("fuel_cost") if ts else doc.fuel_cost)
	additional_charges = flt(ts.get("additional_charges") if ts else doc.additional_charges)
	total_cost = flt(ts.get("total_cost") if ts else doc.total_transport_cost)
	currency = (ts.get("currency") if ts else doc.currency) or "AED"

	transporter_name = ""
	if doc.transporter:
		transporter_name = frappe.db.get_value("Transporter", doc.transporter, "company_name") or doc.transporter

	vehicle_display = doc.vehicle or ""
	if doc.vehicle:
		vehicle_display = frappe.db.get_value("Vehicle", doc.vehicle, "plate_number") or doc.vehicle

	driver_display = doc.driver or ""
	if doc.driver:
		driver_display = frappe.db.get_value("Driver", doc.driver, "full_name") or doc.driver

	jo_number = doc.job_order
	if doc.job_order:
		jo_number = (
			frappe.db.get_value("Job Order", doc.job_order, "job_order_number") or doc.job_order
		)

	return {
		"transport_charges": transport_charges,
		"fuel_cost": fuel_cost,
		"additional_charges": additional_charges,
		"total_cost": total_cost or (transport_charges + fuel_cost + additional_charges),
		"currency": currency,
		"transporter_name": transporter_name,
		"vehicle_display": vehicle_display,
		"driver_display": driver_display,
		"job_order_number": jo_number,
		"driver_phone": ts.get("driver_phone") if ts else None,
	}
