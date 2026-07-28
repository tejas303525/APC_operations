# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Roll up sea freight and inland transport costs for a Job Order."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt


def get_logistics_cost_summary(job_order: str) -> dict[str, Any]:
	"""Build structured logistics cost data for Job Order UI and print."""
	if not job_order:
		return {}

	jo = frappe.db.get_value(
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
			"date",
			"status",
			"terms_of_delivery",
			"mode_of_transport",
			"port_of_loading",
			"port_of_discharge",
			"payment_terms",
			"pi_number",
			"bank_account",
			"currency",
			"freight_borne_by",
			"transport_arranged_by",
			"shipping_arranged_by",
			"insurance_borne_by",
			"insurance_required",
			"risk_transfer_point",
			"transport_schedule",
			"shipping_booking",
		],
		as_dict=True,
	)
	if not jo:
		return {}

	items = frappe.get_all(
		"Job Order Item",
		filters={"parent": job_order},
		fields=["item", "item_name", "quantity", "uom", "packaging", "packaging_type"],
		order_by="idx asc",
	)

	shipping_bookings = _shipping_bookings_for_job_order(job_order, jo.get("shipping_booking"))
	transport_schedules = _transport_schedules_for_job_order(job_order)

	totals_by_currency: dict[str, dict[str, float]] = {}
	for sb in shipping_bookings:
		cur = sb.get("currency") or jo.get("currency") or "AED"
		bucket = totals_by_currency.setdefault(cur, {"sea_freight": 0, "thc": 0, "tluc": 0, "export_declaration": 0, "transport": 0, "fuel": 0, "additional": 0})
		bucket["sea_freight"] += flt(sb.get("total_freight_charges"))
		bucket["thc"] += flt(sb.get("thc"))
		bucket["tluc"] += flt(sb.get("tluc"))
		bucket["export_declaration"] += flt(sb.get("export_declaration"))

	for ts in transport_schedules:
		cur = ts.get("currency") or jo.get("currency") or "AED"
		bucket = totals_by_currency.setdefault(cur, {"sea_freight": 0, "thc": 0, "tluc": 0, "export_declaration": 0, "transport": 0, "fuel": 0, "additional": 0})
		bucket["transport"] += flt(ts.get("transport_charges"))
		bucket["fuel"] += flt(ts.get("fuel_cost"))
		bucket["additional"] += flt(ts.get("additional_charges"))

	for cur, bucket in totals_by_currency.items():
		bucket["grand_total"] = sum(bucket.values())

	return {
		"job_order": jo,
		"job_order_items": items,
		"shipping_bookings": shipping_bookings,
		"transport_schedules": transport_schedules,
		"totals_by_currency": totals_by_currency,
		"multi_currency": len(totals_by_currency) > 1,
	}


def _shipping_bookings_for_job_order(job_order: str, primary_sb: str | None) -> list[dict]:
	names = set(
		frappe.get_all(
			"Shipping Booking",
			filters={"job_order": job_order, "docstatus": ["!=", 2]},
			pluck="name",
		)
	)
	if primary_sb:
		names.add(primary_sb)

	rows = []
	for name in sorted(names):
		sb = frappe.db.get_value(
			"Shipping Booking",
			name,
			[
				"name",
				"shipping_line",
				"vessel_name",
				"container_count",
				"container_type",
				"freight_rate",
				"total_freight_charges",
				"currency",
				"thc",
				"tluc",
				"export_declaration",
				"port_of_loading",
				"port_of_discharge",
				"cro_number",
			],
			as_dict=True,
		)
		if not sb:
			continue
		sb["sea_charges_total"] = (
			flt(sb.get("total_freight_charges"))
			+ flt(sb.get("thc"))
			+ flt(sb.get("tluc"))
			+ flt(sb.get("export_declaration"))
		)
		rows.append(sb)
	return rows


def _transport_schedules_for_job_order(job_order: str) -> list[dict]:
	rows = frappe.get_all(
		"Transport Schedule",
		filters={"job_order": job_order, "docstatus": ["!=", 2]},
		fields=[
			"name",
			"transport_type",
			"outward_type",
			"transport_status",
			"transporter",
			"assigned_vehicle",
			"assigned_driver",
			"transport_charges",
			"fuel_cost",
			"additional_charges",
			"total_cost",
			"currency",
			"transport_po_request",
			"scheduled_pickup_date",
			"pickup_location",
			"delivery_location",
		],
		order_by="modified desc",
	)
	for ts in rows:
		if ts.get("transporter"):
			ts["transporter_name"] = frappe.db.get_value(
				"Transporter", ts["transporter"], "company_name"
			) or ts["transporter"]
		if ts.get("assigned_vehicle"):
			ts["vehicle_display"] = (
				frappe.db.get_value("Vehicle", ts["assigned_vehicle"], "plate_number")
				or ts["assigned_vehicle"]
			)
		if ts.get("assigned_driver"):
			ts["driver_display"] = (
				frappe.db.get_value("Driver", ts["assigned_driver"], "full_name")
				or ts["assigned_driver"]
			)
	return rows


def get_logistics_cost_html_for_job_order(job_order: str) -> str:
	"""Return HTML for the Job Order form (HTML field is not stored in DB)."""
	if not job_order or not frappe.db.exists("Job Order", job_order):
		return "<p class='text-muted'>No logistics cost data.</p>"
	return build_logistics_cost_html(get_logistics_cost_summary(job_order))


def refresh_job_order_logistics_display(job_order: str) -> None:
	"""No-op: HTML fields are rendered client-side, not persisted."""
	return


def build_logistics_cost_html(summary: dict[str, Any]) -> str:
	if not summary or not summary.get("job_order"):
		return "<p class='text-muted'>No logistics cost data.</p>"

	jo = summary["job_order"]
	lines = [
		"<div class='apc-logistics-cost-summary'>",
		"<p><b>Computed from linked Shipping Booking(s) and Transport Schedule(s).</b> "
		"Amounts stay in original currency; no FX conversion.</p>",
	]

	sb_rows = summary.get("shipping_bookings") or []
	if sb_rows:
		lines.append("<h5>Sea / shipping charges</h5><table class='table table-bordered table-sm'><thead><tr>"
			"<th>Booking</th><th>Freight</th><th>THC</th><th>TLUC</th><th>ED</th><th>Sea total</th><th>CCY</th></tr></thead><tbody>")
		for sb in sb_rows:
			lines.append(
				f"<tr><td>{frappe.utils.escape_html(sb.get('name') or '')}</td>"
				f"<td>{_fmt(sb.get('total_freight_charges'))}</td>"
				f"<td>{_fmt(sb.get('thc'))}</td>"
				f"<td>{_fmt(sb.get('tluc'))}</td>"
				f"<td>{_fmt(sb.get('export_declaration'))}</td>"
				f"<td><b>{_fmt(sb.get('sea_charges_total'))}</b></td>"
				f"<td>{frappe.utils.escape_html(sb.get('currency') or '-')}</td></tr>"
			)
		lines.append("</tbody></table>")
	else:
		lines.append("<p class='text-muted'>No Shipping Booking linked.</p>")

	ts_rows = summary.get("transport_schedules") or []
	if ts_rows:
		lines.append("<h5>Inland transport</h5><table class='table table-bordered table-sm'><thead><tr>"
			"<th>Schedule</th><th>Type</th><th>Transport</th><th>Fuel</th><th>Additional</th><th>Total</th><th>CCY</th></tr></thead><tbody>")
		for ts in ts_rows:
			lines.append(
				f"<tr><td>{frappe.utils.escape_html(ts.get('name') or '')}</td>"
				f"<td>{frappe.utils.escape_html((ts.get('transport_type') or '') + ' / ' + (ts.get('outward_type') or '-'))}</td>"
				f"<td>{_fmt(ts.get('transport_charges'))}</td>"
				f"<td>{_fmt(ts.get('fuel_cost'))}</td>"
				f"<td>{_fmt(ts.get('additional_charges'))}</td>"
				f"<td><b>{_fmt(ts.get('total_cost'))}</b></td>"
				f"<td>{frappe.utils.escape_html(ts.get('currency') or '-')}</td></tr>"
			)
		lines.append("</tbody></table>")
	else:
		lines.append("<p class='text-muted'>No Transport Schedule linked.</p>")

	totals = summary.get("totals_by_currency") or {}
	if totals:
		lines.append("<h5>Totals by currency</h5><table class='table table-bordered table-sm'><thead><tr>"
			"<th>Currency</th><th>Sea freight</th><th>THC</th><th>TLUC</th><th>ED</th>"
			"<th>Transport</th><th>Fuel</th><th>Additional</th><th>Grand total</th></tr></thead><tbody>")
		for cur, bucket in sorted(totals.items()):
			lines.append(
				f"<tr><td><b>{frappe.utils.escape_html(cur)}</b></td>"
				f"<td>{_fmt(bucket.get('sea_freight'))}</td>"
				f"<td>{_fmt(bucket.get('thc'))}</td>"
				f"<td>{_fmt(bucket.get('tluc'))}</td>"
				f"<td>{_fmt(bucket.get('export_declaration'))}</td>"
				f"<td>{_fmt(bucket.get('transport'))}</td>"
				f"<td>{_fmt(bucket.get('fuel'))}</td>"
				f"<td>{_fmt(bucket.get('additional'))}</td>"
				f"<td><b>{_fmt(bucket.get('grand_total'))}</b></td></tr>"
			)
		lines.append("</tbody></table>")

	lines.append(
		f"<p class='text-muted small'>Freight borne by: <b>{frappe.utils.escape_html(jo.get('freight_borne_by') or '-')}</b> · "
		f"Inland transport by: <b>{frappe.utils.escape_html(jo.get('transport_arranged_by') or '-')}</b></p>"
	)
	lines.append("</div>")
	return "".join(lines)


def _fmt(value) -> str:
	return frappe.format_value(flt(value), {"fieldtype": "Currency"})
