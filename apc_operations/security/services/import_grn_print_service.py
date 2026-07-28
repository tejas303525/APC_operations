# Copyright (c) 2026, APC and contributors
"""Print context for Standard Import GRN."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def get_print_context(grn_name: str) -> dict[str, Any]:
	"""Build print payload for Import GRN (linked DO + transport context)."""
	if not grn_name:
		frappe.throw(_("grn_name is required"))

	grn = frappe.get_doc("Import GRN", grn_name)
	do = None
	do_print: dict[str, Any] = {}
	if grn.delivery_order and frappe.db.exists("Delivery Order", grn.delivery_order):
		do = frappe.get_doc("Delivery Order", grn.delivery_order)
		from apc_operations.shipping.services.delivery_order_print_service import (
			get_print_context as get_do_print_context,
		)

		do_print = get_do_print_context(grn.delivery_order) or {}

	jo_number = None
	jo_date = None
	terms = None
	if grn.job_order and frappe.db.exists("Job Order", grn.job_order):
		jo_row = frappe.db.get_value(
			"Job Order",
			grn.job_order,
			["job_order_number", "date", "terms_of_delivery"],
			as_dict=True,
		)
		if jo_row:
			jo_number = jo_row.job_order_number or grn.job_order
			jo_date = jo_row.date
			terms = jo_row.terms_of_delivery

	supplier_name = grn.supplier_name
	if not supplier_name and grn.supplier:
		supplier_name = frappe.db.get_value("Supplier", grn.supplier, "supplier_name")

	customer_name = grn.customer_name or "APC"
	if not grn.customer_name and grn.customer:
		customer_name = (
			frappe.db.get_value("Customer", grn.customer, "customer_name") or grn.customer
		)

	item_lines: list[dict[str, Any]] = []
	total_expected = 0.0
	total_arrived = 0.0
	uom = ""
	for row in grn.get("items") or []:
		expected = flt(row.qty)
		arrived = flt(row.arrived_qty)
		total_expected += expected
		total_arrived += arrived
		line_uom = row.uom or ""
		if line_uom and not uom:
			uom = line_uom
		expected_display = f"{expected:g} {line_uom}".strip() if expected > 0 else "-"
		arrived_display = f"{arrived:g} {line_uom}".strip() if arrived > 0 else "-"
		item_lines.append(
			{
				"description": row.description or row.item_name or row.item_code,
				"item_code": row.item_code,
				"qty": expected,
				"expected_qty": expected,
				"arrived_qty": arrived,
				"uom": line_uom,
				"qty_display": arrived_display if arrived > 0 else expected_display,
				"expected_qty_display": expected_display,
				"arrived_qty_display": arrived_display,
			}
		)

	if flt(grn.total_expected_qty) > 0:
		total_expected = flt(grn.total_expected_qty)
	if flt(grn.total_arrived_qty) > 0:
		total_arrived = flt(grn.total_arrived_qty)

	pending_qty = max(total_expected - total_arrived, 0)
	total_expected_display = f"{total_expected:g} {uom}".strip() if total_expected > 0 else "-"
	total_arrived_display = f"{total_arrived:g} {uom}".strip() if total_arrived > 0 else "-"
	pending_display = f"{pending_qty:g} {uom}".strip() if pending_qty > 0 else "-"
	total_qty_display = total_arrived_display if total_arrived > 0 else total_expected_display

	return {
		"grn_name": grn.name,
		"grn_status": grn.grn_status,
		"posting_date": grn.posting_date,
		"delivery_order": grn.delivery_order,
		"job_order": grn.job_order,
		"job_order_number": jo_number or grn.job_order,
		"job_order_date": jo_date,
		"terms_of_delivery": terms or (do.terms_of_delivery if do else None),
		"customer_name": customer_name,
		"supplier_name": supplier_name or "-",
		"supplier": grn.supplier,
		"batch_no": grn.batch_no,
		"product": grn.product,
		"destination": do.destination if do else None,
		"port_of_loading": do.port_of_loading if do else None,
		"port_of_discharge": do.port_of_discharge if do else None,
		"remarks": grn.remarks,
		"approved_by": grn.approved_by,
		"approved_on": grn.approved_on,
		"qc_check_time": grn.qc_check_time,
		"security_check_time": grn.security_check_time,
		"zoho_import_receipt_id": grn.zoho_import_receipt_id,
		"item_lines": item_lines,
		"total_expected_qty": total_expected,
		"total_arrived_qty": total_arrived,
		"pending_qty": pending_qty,
		"total_expected_qty_display": total_expected_display,
		"total_arrived_qty_display": total_arrived_display,
		"pending_qty_display": pending_display,
		"receipt_type": grn.receipt_type,
		"is_partial_receipt": bool(grn.is_partial_receipt),
		"total_qty": total_arrived if total_arrived > 0 else total_expected,
		"total_qty_display": total_qty_display,
		"do_print": do_print,
	}
