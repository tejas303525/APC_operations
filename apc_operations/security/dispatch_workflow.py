# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Delivery Order–centric security workflow actions (Phase 4).

Each action validates via ``dispatch_validation_service``, updates Security
Inspection / Loading Delivery Note / Gate Pass, and syncs lifecycle status.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, now, today

from apc_operations.shipping.services.dispatch_lifecycle_service import (
	sync_dispatch_lifecycle_status,
)
from apc_operations.shipping.services.dispatch_validation_service import (
	apply_weight_variance_to_ldn,
	calculate_net_weight,
	resolve_ldn_for_do,
	resolve_pcc_for_do,
	resolve_security_inspection_for_do,
	validate_delivery_note_generation,
	validate_gate_out_allowed,
	validate_loading_completion,
	validate_loading_start_allowed,
	validate_truck_arrival_allowed,
	validate_weight_capture,
)
from apc_operations.security.doctype.security_inspection.security_inspection import (
	DEFAULT_CHECKLIST_ITEMS,
)


def _parse_dt(value):
	if not value:
		return now()
	return frappe.utils.get_datetime(value)


def _do_context(do_name: str) -> dict[str, Any]:
	from apc_operations.shipping.services.dispatch_flow_service import ensure_ldn_do_link

	ensure_ldn_do_link(do_name=do_name, update_modified=False)
	do = frappe.get_doc("Delivery Order", do_name)
	ldn_name = resolve_ldn_for_do(do_name)
	ldn = frappe.get_doc("Loading Delivery Note", ldn_name) if ldn_name else None
	si_name = resolve_security_inspection_for_do(do_name)
	si = frappe.get_doc("Security Inspection", si_name) if si_name else None
	pcc_name = resolve_pcc_for_do(do_name)
	return {"do": do, "ldn": ldn, "si": si, "pcc_name": pcc_name}


def _ensure_security_inspection(do_name: str) -> frappe.model.document.Document:
	ctx = _do_context(do_name)
	if ctx["si"]:
		return ctx["si"]

	do = ctx["do"]
	si = frappe.new_doc("Security Inspection")
	si.job_order = do.job_order
	si.customer = do.customer
	si.inspection_type = "Local Delivery"
	si.inspection_date = today()
	si.security_status = "Pending Checklist"
	si.insert(ignore_permissions=True)

	if not si.checklist_items:
		for idx, label in enumerate(DEFAULT_CHECKLIST_ITEMS, start=1):
			si.append("checklist_items", {"item": label, "sequence": idx, "completed": 0})
		si.save(ignore_permissions=True)

	if ctx["ldn"]:
		ctx["ldn"].security_inspection = si.name
		ctx["ldn"].save(ignore_permissions=True)

	return si


def _coherent_weighment(doc) -> bool:
	gross = flt(getattr(doc, "gross_weight", 0) if hasattr(doc, "gross_weight") else doc.get("gross_weight"))
	tare = flt(getattr(doc, "tare_weight", 0) if hasattr(doc, "tare_weight") else doc.get("tare_weight"))
	return gross > 0 and tare > 0 and gross >= tare


def _sync_ldn_from_si(ldn, si) -> None:
	if not ldn or not si:
		return
	if _coherent_weighment(ldn) and not _coherent_weighment(si):
		return
	if not _coherent_weighment(si):
		return
	weight_fields = {"tare_weight", "gross_weight", "net_weight"}
	for field in (
		"loading_start_time",
		"loading_end_time",
		"loading_bay",
		"tare_weight",
		"gross_weight",
		"net_weight",
		"tare_weight_time",
		"gross_weight_time",
		"weighbridge_slip_no",
		"seal_applied_by",
		"seal_number",
	):
		val = si.get(field)
		if field in weight_fields:
			if flt(val) > 0:
				ldn.set(field, val)
		elif val:
			ldn.set(field, val)
	if flt(si.get("quantity")) > 0:
		ldn.quantity = si.quantity


def _apply_weight_variance(ldn, do) -> None:
	apply_weight_variance_to_ldn(ldn, do)


def _find_or_create_gate_pass(do_name: str, ldn_name: str | None = None) -> frappe.model.document.Document:
	existing = frappe.db.get_value(
		"Gate Pass",
		{
			"delivery_order": do_name,
			"gate_pass_type": "Out",
			"docstatus": ["!=", 2],
			"gate_status": ["!=", "Cancelled"],
		},
		"name",
		order_by="modified desc",
	)
	if existing:
		return frappe.get_doc("Gate Pass", existing)

	do = frappe.get_doc("Delivery Order", do_name)
	gp = frappe.new_doc("Gate Pass")
	gp.gate_pass_type = "Out"
	gp.posting_date = today()
	gp.company = do.company
	gp.customer = do.customer
	gp.delivery_order = do_name
	gp.loading_delivery_note = ldn_name or do.loading_delivery_note
	gp.vehicle_no = "TBD"
	gp.status = "Draft"
	gp.gate_status = "Pending"
	gp.insert(ignore_permissions=True)
	return gp


def mark_truck_arrived(
	delivery_order: str,
	*,
	vehicle_number: str | None = None,
	driver_name: str | None = None,
	driver_license_no: str | None = None,
	trailer_no: str | None = None,
	gate_entry_no: str | None = None,
	truck_arrived_on=None,
) -> dict[str, Any]:
	validate_truck_arrival_allowed(delivery_order)
	if not vehicle_number:
		frappe.throw(_("Vehicle number is required."))
	if not driver_name:
		frappe.throw(_("Driver name is required."))

	arrived_on = _parse_dt(truck_arrived_on)
	si = _ensure_security_inspection(delivery_order)
	si.vehicle_number = vehicle_number
	si.driver_name = driver_name
	if driver_license_no:
		si.driver_license_no = driver_license_no
	if trailer_no:
		si.trailer_no = trailer_no
	si.gate_in_time = arrived_on
	if gate_entry_no:
		si.gate_entry_no = gate_entry_no
	si.save(ignore_permissions=True)

	do = frappe.get_doc("Delivery Order", delivery_order)
	frappe.db.set_value(
		"Delivery Order",
		delivery_order,
		{
			"truck_arrived_on": arrived_on,
			"gate_entry_no": gate_entry_no or do.gate_entry_no,
		},
		update_modified=True,
	)

	status = sync_dispatch_lifecycle_status(delivery_order, update_modified=True)
	return {
		"success": True,
		"delivery_order": delivery_order,
		"security_inspection": si.name,
		"operational_status": status,
	}


def record_gate_in_details(
	delivery_order: str,
	*,
	driver_license_no: str | None = None,
	trailer_no: str | None = None,
	tare_weight: float | None = None,
	tare_weight_time=None,
	weighbridge_slip_no: str | None = None,
) -> dict[str, Any]:
	si = _ensure_security_inspection(delivery_order)
	ctx = _do_context(delivery_order)
	ldn = ctx["ldn"]

	if driver_license_no:
		si.driver_license_no = driver_license_no
	if trailer_no:
		si.trailer_no = trailer_no
	if tare_weight is not None:
		if flt(tare_weight) <= 0:
			frappe.throw(_("Tare weight must be greater than zero."))
		si.tare_weight = flt(tare_weight)
		si.tare_weight_time = _parse_dt(tare_weight_time)
	if weighbridge_slip_no:
		si.weighbridge_slip_no = weighbridge_slip_no
	si.save(ignore_permissions=True)

	if ldn and si.tare_weight:
		_sync_ldn_from_si(ldn, si)
		ldn.save(ignore_permissions=True)

	status = sync_dispatch_lifecycle_status(delivery_order, update_modified=True)
	return {
		"success": True,
		"delivery_order": delivery_order,
		"security_inspection": si.name,
		"operational_status": status,
	}


def notify_qc_truck_arrived(delivery_order: str) -> dict[str, Any]:
	ctx = _do_context(delivery_order)
	if not ctx["do"].truck_arrived_on:
		frappe.throw(_("Truck arrival must be recorded before notifying QC."))
	if not ctx["pcc_name"]:
		frappe.throw(_("No Pre-Check Clearance found for Delivery Order {0}.").format(delivery_order))

	si = _ensure_security_inspection(delivery_order)
	si.truck_arrived_notified_qc = 1
	si.truck_arrived_notified_qc_on = now()
	si.save(ignore_permissions=True)

	status = sync_dispatch_lifecycle_status(delivery_order, update_modified=True)

	roles = ["Quality Manager", "Quality User"]
	users = frappe.get_all(
		"Has Role",
		filters={"role": ["in", roles], "parenttype": "User"},
		pluck="parent",
	)
	for user in users[:20]:
		frappe.publish_realtime(
			"apc_qc_precheck_pending",
			{"delivery_order": delivery_order, "pre_check_clearance": ctx["pcc_name"]},
			user=user,
		)

	return {
		"success": True,
		"delivery_order": delivery_order,
		"pre_check_clearance": ctx["pcc_name"],
		"operational_status": status,
	}


def record_tare_weight(
	delivery_order: str,
	*,
	tare_weight: float,
	tare_weight_time=None,
	weighbridge_slip_no: str | None = None,
) -> dict[str, Any]:
	return record_gate_in_details(
		delivery_order,
		tare_weight=tare_weight,
		tare_weight_time=tare_weight_time,
		weighbridge_slip_no=weighbridge_slip_no,
	)


def start_loading(
	delivery_order: str,
	*,
	loading_bay: str,
	loader_name: str | None = None,
	loading_supervisor: str | None = None,
) -> dict[str, Any]:
	validate_loading_start_allowed(delivery_order)
	if not loading_bay:
		frappe.throw(_("Loading bay is required."))

	si = _ensure_security_inspection(delivery_order)
	ctx = _do_context(delivery_order)
	ldn = ctx["ldn"]
	if not ldn:
		frappe.throw(_("No Loading Delivery Note linked to Delivery Order {0}.").format(delivery_order))

	started = now()
	si.loading_bay = loading_bay
	si.loading_start_time = started
	if loader_name:
		si.loader_name = loader_name
	if loading_supervisor:
		si.loading_supervisor = loading_supervisor
	si.save(ignore_permissions=True)

	ldn.loading_bay = loading_bay
	ldn.loading_start_time = started
	if ldn.delivery_note_status not in ("Loading Completed", "Dispatch Confirmed", "Completed"):
		ldn.delivery_note_status = "Batch Allocated"
	ldn.save(ignore_permissions=True)

	status = sync_dispatch_lifecycle_status(delivery_order, update_modified=True)
	return {
		"success": True,
		"delivery_order": delivery_order,
		"loading_delivery_note": ldn.name,
		"operational_status": status,
	}


def complete_loading(
	delivery_order: str,
	*,
	loaded_quantity: float,
	loading_end_time=None,
) -> dict[str, Any]:
	if flt(loaded_quantity) <= 0:
		frappe.throw(_("Loaded quantity must be greater than zero."))

	si = _ensure_security_inspection(delivery_order)
	ctx = _do_context(delivery_order)
	ldn = ctx["ldn"]
	if not si.loading_start_time and not (ldn and ldn.loading_start_time):
		started = now()
		si.loading_start_time = started
		if ldn:
			ldn.loading_start_time = started
			if not ldn.loading_bay:
				ldn.loading_bay = "Bay 1"

	ended = _parse_dt(loading_end_time)
	si.loading_end_time = ended
	si.quantity = flt(loaded_quantity)
	si.save(ignore_permissions=True)

	if ldn:
		ldn.loading_end_time = ended
		ldn.quantity = flt(loaded_quantity)
		ldn.delivery_note_status = "Loading Completed"
		ldn.save(ignore_permissions=True)

	validate_loading_completion(delivery_order)
	status = sync_dispatch_lifecycle_status(delivery_order, update_modified=True)
	return {
		"success": True,
		"delivery_order": delivery_order,
		"loaded_quantity": flt(loaded_quantity),
		"operational_status": status,
	}


def record_gross_weight(
	delivery_order: str,
	*,
	gross_weight: float,
	gross_weight_time=None,
) -> dict[str, Any]:
	if flt(gross_weight) <= 0:
		frappe.throw(_("Gross weight must be greater than zero."))

	si = _ensure_security_inspection(delivery_order)
	ctx = _do_context(delivery_order)
	ldn = ctx["ldn"]
	do = ctx["do"]

	if not si.loading_end_time and not (ldn and ldn.loading_end_time):
		frappe.throw(_("Loading must be completed before recording gross weight."))

	captured = _parse_dt(gross_weight_time)
	si.gross_weight = flt(gross_weight)
	si.gross_weight_time = captured
	if si.tare_weight:
		si.net_weight = calculate_net_weight(si.gross_weight, si.tare_weight)
	si.save(ignore_permissions=True)

	if ldn:
		ldn.gross_weight = si.gross_weight
		ldn.gross_weight_time = captured
		if ldn.tare_weight or si.tare_weight:
			tare = flt(ldn.tare_weight) or flt(si.tare_weight)
			ldn.tare_weight = tare
			ldn.net_weight = calculate_net_weight(ldn.gross_weight, tare)
		if flt(ldn.quantity) <= 0 and flt(ldn.net_weight) > 0:
			ldn.quantity = flt(ldn.net_weight)
			si.quantity = ldn.quantity
			si.save(ignore_permissions=True)
		_apply_weight_variance(ldn, do)
		ldn.save(ignore_permissions=True)

	from apc_operations.shipping.services.dispatch_flow_service import sync_ldn_transport_context

	sync_ldn_transport_context(do_name=delivery_order, update_modified=False)

	validate_weight_capture(do_name=delivery_order)
	status = sync_dispatch_lifecycle_status(delivery_order, update_modified=True)
	return {
		"success": True,
		"delivery_order": delivery_order,
		"net_weight": flt((ldn and ldn.net_weight) or si.net_weight),
		"weight_variance_status": (ldn and ldn.weight_variance_status) or "Within Tolerance",
		"operational_status": status,
	}


def record_package_count(
	delivery_order: str,
	*,
	loaded_packaging_qty: int,
) -> dict[str, Any]:
	"""Package Count method: security directly enters the physical count
	loaded, cross-checked against the Job Order's expected_packaging_qty.
	Bypasses the (unused in practice) per-batch Loading Entry auto-sum."""
	if flt(loaded_packaging_qty) <= 0:
		frappe.throw(_("Loaded packaging quantity must be greater than zero."))

	ctx = _do_context(delivery_order)
	ldn = ctx["ldn"]
	do = ctx["do"]
	if not ldn:
		frappe.throw(_("No Loading Delivery Note linked to Delivery Order {0}.").format(delivery_order))

	ldn.loaded_packaging_qty = int(flt(loaded_packaging_qty))
	_apply_weight_variance(ldn, do)
	ldn.save(ignore_permissions=True)

	status = sync_dispatch_lifecycle_status(delivery_order, update_modified=True)
	return {
		"success": True,
		"delivery_order": delivery_order,
		"loaded_packaging_qty": ldn.loaded_packaging_qty,
		"expected_packaging_qty": ldn.expected_packaging_qty,
		"package_variance_status": ldn.package_variance_status,
		"operational_status": status,
	}


def record_seal_details(
	delivery_order: str,
	*,
	seal_number: str,
	seal_applied_by: str | None = None,
) -> dict[str, Any]:
	if not seal_number:
		frappe.throw(_("Seal number is required."))

	si = _ensure_security_inspection(delivery_order)
	ctx = _do_context(delivery_order)
	ldn = ctx["ldn"]

	si.seal_number = seal_number
	if seal_applied_by:
		si.seal_applied_by = seal_applied_by
	si.save(ignore_permissions=True)

	if ldn:
		ldn.seal_number = seal_number
		if seal_applied_by:
			ldn.seal_applied_by = seal_applied_by
		ldn.save(ignore_permissions=True)

	status = sync_dispatch_lifecycle_status(delivery_order, update_modified=True)
	return {"success": True, "delivery_order": delivery_order, "operational_status": status}


def security_final_check(delivery_order: str) -> dict[str, Any]:
	ctx = _do_context(delivery_order)
	ldn = ctx["ldn"]
	if not ldn:
		frappe.throw(_("No Loading Delivery Note linked to Delivery Order {0}.").format(delivery_order))
	if not ldn.dispatch_confirmed:
		frappe.throw(_("Delivery Note must be generated before security final check."))
	if not ldn.final_qc_clearance:
		frappe.throw(_("QC final clearance must be completed before security final check."))
	if not ldn.qc_manager_approved:
		frappe.throw(_("QC Manager approval is required before security final check."))

	ldn.security_final_check = 1
	ldn.security_final_check_by = frappe.session.user
	ldn.security_final_check_on = now()
	ldn.save(ignore_permissions=True)

	status = sync_dispatch_lifecycle_status(delivery_order, update_modified=True)
	return {
		"success": True,
		"delivery_order": delivery_order,
		"operational_status": status,
	}


def request_delivery_note_generation(delivery_order: str) -> dict[str, Any]:
	ctx = _do_context(delivery_order)
	ldn = ctx["ldn"]
	if not ldn:
		frappe.throw(_("No Loading Delivery Note linked to Delivery Order {0}.").format(delivery_order))

	validate_delivery_note_generation(ldn.name)

	from apc_operations.services.batch_allocation import confirm_dispatch_and_deduct_stock

	result = confirm_dispatch_and_deduct_stock(ldn.name)
	status = sync_dispatch_lifecycle_status(delivery_order, update_modified=True)
	return {
		"success": True,
		"delivery_order": delivery_order,
		"loading_delivery_note": ldn.name,
		"operational_status": status,
		"dispatch_result": result,
	}


def mark_delivery_order_gate_out(
	delivery_order: str,
	gate_pass: str | None = None,
) -> dict[str, Any]:
	ctx = _do_context(delivery_order)
	ldn = ctx["ldn"]
	gp = frappe.get_doc("Gate Pass", gate_pass) if gate_pass else _find_or_create_gate_pass(
		delivery_order, ldn.name if ldn else None
	)

	if not gp.delivery_order:
		gp.delivery_order = delivery_order
	if ldn and not gp.loading_delivery_note:
		gp.loading_delivery_note = ldn.name
	if ctx["si"]:
		if ctx["si"].vehicle_number:
			gp.vehicle_no = ctx["si"].vehicle_number
		if ctx["si"].driver_name:
			gp.driver_name = ctx["si"].driver_name

	gp.gate_status = "Draft"
	gp.gate_out_time = now()
	gp.gate_out_approved_by = frappe.session.user
	if not gp.gate_in_time and ctx["do"].truck_arrived_on:
		gp.gate_in_time = ctx["do"].truck_arrived_on

	validate_gate_out_allowed(gp, for_release=True)
	gp.save(ignore_permissions=True)

	status = sync_dispatch_lifecycle_status(delivery_order, update_modified=True)
	return {
		"success": True,
		"delivery_order": delivery_order,
		"gate_pass": gp.name,
		"operational_status": status,
	}


def approve_weight_variance(delivery_order: str) -> dict[str, Any]:
	ctx = _do_context(delivery_order)
	ldn = ctx.get("ldn")
	if not ldn:
		frappe.throw(_("No Loading Delivery Note linked to Delivery Order {0}.").format(delivery_order))

	result = ldn.approve_weight_variance()
	return {
		"success": True,
		"delivery_order": delivery_order,
		"loading_delivery_note": ldn.name,
		"weight_variance_status": ldn.weight_variance_status,
		"operational_status": result.get("operational_status"),
	}
