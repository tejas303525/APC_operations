# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Central dispatch workflow validation for the Delivery Order path.

Each ``validate_*`` helper returns a list of error messages. When ``throw=True``
(the default), the first batch of errors is raised as ``frappe.ValidationError``.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt

from apc_operations.shipping.doctype.apc_operations_settings.apc_operations_settings import (
	loading_quantity_tolerance_pct,
	zoho_dispatch_sync_enabled,
)

# Delivery Order operational_status groupings
TRUCK_ARRIVAL_ALLOWED_STATUSES = frozenset({"Issued", "Sent to Security"})
LOADING_START_ALLOWED_STATUSES = frozenset({"QC Pre-check Passed", "Loading Allowed"})
LOADING_COMPLETE_REQUIRED_STATUSES = frozenset({"Loading Started", "Loading Completed"})
WEIGHMENT_ALLOWED_STATUSES = frozenset({"Loading Completed", "Weighment Completed"})
DN_GENERATION_ALLOWED_STATUSES = frozenset(
	{
		"Weighment Completed",
		"Weight Variance Approval Pending",
		"QC Final Pending",
		"Delivery Note Generated",
	}
)
GATE_OUT_READY_STATUSES = frozenset({"Ready for Gate Out", "Delivery Note Generated"})
TERMINAL_DO_STATUSES = frozenset({"Cancelled", "Gate Out Completed"})
BLOCKED_DO_STATUSES = frozenset({"On Hold", "QC Pre-check Failed", "Cancelled"})

# Backward-compatible do_status fallbacks for records not yet backfilled
DO_STATUS_TRUCK_ARRIVAL = frozenset({"Issued", "Pre-Check Pending"})
DO_STATUS_LOADING_ALLOWED = frozenset({"Pre-Check Cleared", "Loading"})

INVALID_LDN_STATUSES = frozenset({"Draft", "Cancelled"})
APPROVED_VARIANCE_STATUSES = frozenset({"Within Tolerance", "Approved"})


def _fail(errors: list[str], throw: bool = True) -> list[str]:
	if throw and errors:
		frappe.throw(_("Dispatch validation failed:") + "<br>" + "<br>".join(f"• {e}" for e in errors))
	return errors


def _do_row(do_name: str) -> dict[str, Any] | None:
	if not do_name or not frappe.db.exists("Delivery Order", do_name):
		return None
	return frappe.db.get_value(
		"Delivery Order",
		do_name,
		[
			"name",
			"job_order",
			"operational_status",
			"do_status",
			"status",
			"docstatus",
			"loading_delivery_note",
			"pre_check_clearance",
			"planned_quantity",
			"gate_entry_no",
		],
		as_dict=True,
	)


def _ldn_row(ldn_name: str) -> dict[str, Any] | None:
	if not ldn_name or not frappe.db.exists("Loading Delivery Note", ldn_name):
		return None
	return frappe.db.get_value(
		"Loading Delivery Note",
		ldn_name,
		[
			"name",
			"job_order",
			"security_inspection",
			"transport_delivery_order",
			"delivery_note_status",
			"dispatch_confirmed",
			"qc_manager_approved",
			"coa_verified",
			"final_qc_clearance",
			"security_final_check",
			"quantity",
			"planned_quantity",
			"tare_weight",
			"gross_weight",
			"net_weight",
			"loading_start_time",
			"loading_end_time",
			"weight_variance_status",
			"vehicle",
			"driver",
			"container_number",
			"seal_number",
		],
		as_dict=True,
	)


def _pcc_row(pcc_name: str) -> dict[str, Any] | None:
	if not pcc_name or not frappe.db.exists("Pre-Check Clearance", pcc_name):
		return None
	return frappe.db.get_value(
		"Pre-Check Clearance",
		pcc_name,
		[
			"name",
			"delivery_order",
			"overall_status",
			"qc_status",
			"security_status",
			"qc_pre_check_status",
		],
		as_dict=True,
	)


def _si_row(si_name: str) -> dict[str, Any] | None:
	if not si_name or not frappe.db.exists("Security Inspection", si_name):
		return None
	return frappe.db.get_value(
		"Security Inspection",
		si_name,
		[
			"name",
			"job_order",
			"vehicle_number",
			"driver_name",
			"driver_phone",
			"driver_license_no",
			"tare_weight",
			"gross_weight",
			"net_weight",
			"loading_start_time",
			"loading_end_time",
			"loading_bay",
			"quantity",
			"seal_number",
			"truck_arrived_notified_qc",
		],
		as_dict=True,
	)


def resolve_ldn_for_do(do_name: str | None) -> str | None:
	do = _do_row(do_name) if do_name else None
	if not do:
		return None
	if do.get("loading_delivery_note"):
		return do["loading_delivery_note"]
	if do.get("job_order"):
		return frappe.db.get_value(
			"Loading Delivery Note",
			{"job_order": do["job_order"], "dispatch_confirmed": 0},
			"name",
			order_by="modified desc",
		)
	return None


def resolve_pcc_for_do(do_name: str | None) -> str | None:
	if not do_name:
		return None
	do = _do_row(do_name)
	if not do:
		return None
	if do.get("pre_check_clearance"):
		return do["pre_check_clearance"]
	return frappe.db.get_value("Pre-Check Clearance", {"delivery_order": do_name}, "name")


def resolve_security_inspection_for_do(do_name: str | None) -> str | None:
	if not do_name:
		return None
	ldn_name = resolve_ldn_for_do(do_name)
	if ldn_name:
		si = frappe.db.get_value("Loading Delivery Note", ldn_name, "security_inspection")
		if si:
			return si
	do = _do_row(do_name)
	if do and do.get("job_order"):
		return frappe.db.get_value(
			"Security Inspection",
			{"job_order": do["job_order"], "docstatus": ["!=", 2]},
			"name",
			order_by="modified desc",
		)
	return None


def _is_do_cancelled(do: dict[str, Any]) -> bool:
	if do.get("docstatus") == 2 or do.get("status") == "Cancelled":
		return True
	op = (do.get("operational_status") or "").strip()
	do_status = (do.get("do_status") or "").strip()
	return op == "Cancelled" or do_status == "Cancelled"


def _operational_status_allows(do: dict[str, Any], allowed: frozenset[str], *, do_status_fallback: frozenset[str] | None = None) -> bool:
	op = (do.get("operational_status") or "Draft").strip()
	if op in allowed:
		return True
	if do_status_fallback and (do.get("do_status") or "").strip() in do_status_fallback:
		return True
	return False


def _loaded_quantity(
	ldn: dict[str, Any] | None,
	si: dict[str, Any] | None,
	*,
	do_name: str | None = None,
) -> float:
	if ldn and flt(ldn.get("quantity")) > 0:
		return flt(ldn["quantity"])
	if si and flt(si.get("quantity")) > 0:
		return flt(si["quantity"])
	if ldn and flt(ldn.get("net_weight")) > 0:
		return flt(ldn["net_weight"])
	if si and flt(si.get("net_weight")) > 0:
		return flt(si["net_weight"])
	return 0.0


def _resolve_driver_for_validation(
	ldn: dict[str, Any] | None,
	si: dict[str, Any] | None,
	do_name: str | None,
) -> str | None:
	if ldn and ldn.get("driver"):
		name = frappe.db.get_value("Driver", ldn["driver"], "driver_name") or ldn["driver"]
		if name:
			return name
	if si and si.get("driver_name"):
		return si["driver_name"]
	if si and si.get("driver"):
		return frappe.db.get_value("Driver", si["driver"], "driver_name") or si["driver"]
	if do_name:
		from apc_operations.services.delivery_order_service import resolve_transport_context_for_do

		ctx = resolve_transport_context_for_do(do_name)
		if ctx.get("driver_name"):
			return ctx["driver_name"]
	return None


def _resolve_vehicle_for_validation(
	ldn: dict[str, Any] | None,
	si: dict[str, Any] | None,
	do_name: str | None,
) -> str | None:
	if ldn and ldn.get("vehicle"):
		return (
			frappe.db.get_value("Vehicle", ldn["vehicle"], "license_plate") or ldn["vehicle"]
		)
	if si and si.get("vehicle_number"):
		return si["vehicle_number"]
	if do_name:
		from apc_operations.services.delivery_order_service import resolve_transport_context_for_do

		ctx = resolve_transport_context_for_do(do_name)
		if ctx.get("truck_number"):
			return ctx["truck_number"]
	return None


def _planned_quantity(do: dict[str, Any] | None, ldn: dict[str, Any] | None) -> float:
	"""Planned quantity in kg for weighbridge variance (commercial UOM converted)."""
	from apc_operations.shipping.services.uom_service import planned_quantity_kg

	return planned_quantity_kg(do=do, ldn=ldn)


def calculate_net_weight(gross_weight: float, tare_weight: float, *, throw: bool = True) -> float:
	gross = flt(gross_weight)
	tare = flt(tare_weight)
	errors: list[str] = []
	if gross <= 0:
		errors.append(_("Gross weight must be greater than zero."))
	if tare <= 0:
		errors.append(_("Tare weight must be greater than zero."))
	if gross > 0 and tare > 0 and gross < tare:
		errors.append(_("Gross weight must be greater than or equal to tare weight."))
	if errors:
		_fail(errors, throw=throw)
		return 0.0
	return gross - tare


def compute_weight_variance(
	net_weight: float,
	planned_quantity: float,
	tolerance_pct: float | None = None,
) -> dict[str, Any]:
	planned = flt(planned_quantity)
	net = flt(net_weight)
	tolerance = flt(tolerance_pct) if tolerance_pct is not None else loading_quantity_tolerance_pct()
	variance_qty = net - planned if planned > 0 else 0.0
	variance_pct = abs(variance_qty) / planned * 100 if planned > 0 else 0.0
	status = "Within Tolerance"
	if planned > 0 and variance_pct > tolerance:
		status = "Requires Approval"
	return {
		"planned_quantity": planned,
		"net_weight": net,
		"weight_variance_qty": variance_qty,
		"weight_variance_pct": variance_pct,
		"weight_variance_status": status,
		"tolerance_pct": tolerance,
	}


def apply_weight_variance_to_ldn(ldn, do: dict[str, Any] | None = None) -> None:
	"""Compute net weight and variance fields on an in-memory Loading Delivery Note."""
	gross = flt(getattr(ldn, "gross_weight", 0))
	tare = flt(getattr(ldn, "tare_weight", 0))
	if gross > 0 and tare > 0 and gross >= tare:
		if flt(ldn.net_weight) <= 0 or ldn.has_value_changed("gross_weight") or ldn.has_value_changed("tare_weight"):
			ldn.net_weight = calculate_net_weight(gross, tare, throw=False)

	net = flt(ldn.net_weight)
	if net <= 0:
		return

	if do is None and ldn.get("transport_delivery_order"):
		do = frappe.db.get_value(
			"Delivery Order",
			ldn.transport_delivery_order,
			[
				"name",
				"planned_quantity",
				"planned_gross_kg",
				"expected_packaging_qty",
				"total_qty",
				"job_order",
			],
			as_dict=True,
		)

	planned = _planned_quantity(do, ldn)
	if planned <= 0:
		return

	if planned > 0:
		ldn.planned_quantity = planned

	from apc_operations.shipping.services.packing_calculation_service import (
		apply_packing_variance_to_ldn,
	)

	apply_packing_variance_to_ldn(ldn, do=do)

	prev = ldn.get_doc_before_save() if not ldn.is_new() else None
	prev_status = (getattr(prev, "weight_variance_status", None) or "").strip()
	current_status = (ldn.weight_variance_status or "").strip()
	weights_changed = ldn.is_new() or any(
		ldn.has_value_changed(field)
		for field in (
			"net_weight",
			"gross_weight",
			"tare_weight",
			"planned_quantity",
			"loaded_packaging_qty",
			"expected_packaging_qty",
		)
	)

	if prev_status == "Rejected" and not weights_changed:
		return

	if not weights_changed and current_status == "Approved":
		variance = compute_weight_variance(net, planned)
		ldn.weight_variance_qty = variance["weight_variance_qty"]
		ldn.weight_variance_pct = variance["weight_variance_pct"]
		return

	variance = compute_weight_variance(net, planned)
	ldn.weight_variance_qty = variance["weight_variance_qty"]
	ldn.weight_variance_pct = variance["weight_variance_pct"]
	new_status = variance["weight_variance_status"]

	if new_status == "Requires Approval":
		ldn.weight_variance_status = "Requires Approval"
	else:
		ldn.weight_variance_status = "Within Tolerance"

	if ldn.weight_variance_status != "Approved":
		ldn.weight_variance_approved_by = None
		ldn.weight_variance_approved_on = None


def validate_truck_arrival_allowed(do_name: str, *, throw: bool = True) -> list[str]:
	"""Delivery Order must be issued to Security and not cancelled."""
	errors: list[str] = []
	do = _do_row(do_name)
	if not do:
		return _fail([_("Delivery Order {0} was not found.").format(do_name)], throw=throw)

	if _is_do_cancelled(do):
		errors.append(_("Delivery Order {0} is cancelled.").format(do_name))

	op = (do.get("operational_status") or "Draft").strip()
	if op in BLOCKED_DO_STATUSES:
		errors.append(_("Delivery Order {0} is on hold or blocked (status: {1}).").format(do_name, op))

	if not _operational_status_allows(
		do,
		TRUCK_ARRIVAL_ALLOWED_STATUSES,
		do_status_fallback=DO_STATUS_TRUCK_ARRIVAL,
	):
		errors.append(
			_("Delivery Order {0} is not in a state that allows truck arrival (status: {1}).").format(
				do_name, op or do.get("do_status") or "Draft"
			)
		)
	return _fail(errors, throw=throw)


def validate_qc_precheck_before_loading(do_name: str, *, throw: bool = True) -> list[str]:
	"""QC pre-check must be authorized before loading can start."""
	errors: list[str] = []
	pcc_name = resolve_pcc_for_do(do_name)
	if not pcc_name:
		errors.append(_("No Pre-Check Clearance found for Delivery Order {0}.").format(do_name))
		return _fail(errors, throw=throw)

	pcc = _pcc_row(pcc_name)
	if not pcc:
		errors.append(_("Pre-Check Clearance {0} was not found.").format(pcc_name))
		return _fail(errors, throw=throw)

	if pcc.get("overall_status") != "Authorized":
		qc = pcc.get("qc_status") or "Pending"
		sec = pcc.get("security_status") or "Pending"
		errors.append(
			_("Loading cannot start: QC pre-check not passed. QC: {0}, Security: {1}.").format(qc, sec)
		)
	return _fail(errors, throw=throw)


def validate_loading_start_allowed(do_name: str, *, throw: bool = True) -> list[str]:
	"""Loading may start only after QC pre-check pass and while DO allows loading."""
	errors = validate_qc_precheck_before_loading(do_name, throw=False)
	do = _do_row(do_name)
	if not do:
		errors.append(_("Delivery Order {0} was not found.").format(do_name))
	elif _is_do_cancelled(do):
		errors.append(_("Delivery Order {0} is cancelled.").format(do_name))
	elif not _operational_status_allows(
		do,
		LOADING_START_ALLOWED_STATUSES,
		do_status_fallback=DO_STATUS_LOADING_ALLOWED,
	):
		op = do.get("operational_status") or do.get("do_status") or "Draft"
		errors.append(_("Loading not allowed until QC pre-check is passed (status: {0}).").format(op))
	return _fail(errors, throw=throw)


def validate_loading_completion(do_name: str, *, throw: bool = True) -> list[str]:
	"""Loading completion requires start time, loaded quantity, and vehicle/driver details."""
	errors: list[str] = []
	do = _do_row(do_name)
	ldn_name = resolve_ldn_for_do(do_name)
	ldn = _ldn_row(ldn_name) if ldn_name else None
	si_name = resolve_security_inspection_for_do(do_name)
	si = _si_row(si_name) if si_name else None

	if not ldn_name:
		errors.append(_("No Loading Delivery Note linked to Delivery Order {0}.").format(do_name))

	start_time = (ldn or {}).get("loading_start_time") or (si or {}).get("loading_start_time")
	if not start_time:
		errors.append(_("Loading has not started yet."))

	loaded_qty = _loaded_quantity(ldn, si)
	if loaded_qty <= 0:
		errors.append(_("Loaded quantity must be greater than zero."))

	vehicle = (si or {}).get("vehicle_number")
	driver = (si or {}).get("driver_name")
	if not vehicle:
		errors.append(_("Vehicle number is required before loading can be completed."))
	if not driver:
		errors.append(_("Driver name is required before loading can be completed."))

	if do and not _operational_status_allows(do, LOADING_COMPLETE_REQUIRED_STATUSES | {"Loading Completed", "Weighment Completed"}):
		# Allow completion when loading was started even if status not yet synced
		if not start_time:
			op = do.get("operational_status") or do.get("do_status") or "Draft"
			errors.append(_("Delivery Order {0} is not in a loading state (status: {1}).").format(do_name, op))

	return _fail(errors, throw=throw)


def validate_weight_capture(
	do_name: str | None = None,
	*,
	ldn_name: str | None = None,
	gross_weight: float | None = None,
	tare_weight: float | None = None,
	throw: bool = True,
) -> list[str]:
	"""Tare and gross weights must be captured; gross must be >= tare."""
	errors: list[str] = []
	ldn = None
	si = None

	if ldn_name:
		ldn = _ldn_row(ldn_name)
	elif do_name:
		ldn = _ldn_row(resolve_ldn_for_do(do_name))
		si = _si_row(resolve_security_inspection_for_do(do_name))

	tare = flt(tare_weight) if tare_weight is not None else flt((ldn or {}).get("tare_weight") or (si or {}).get("tare_weight"))
	gross = flt(gross_weight) if gross_weight is not None else flt((ldn or {}).get("gross_weight") or (si or {}).get("gross_weight"))

	if tare <= 0:
		errors.append(_("Tare weight must be recorded."))
	if gross <= 0:
		errors.append(_("Gross weight must be recorded."))
	if gross > 0 and tare > 0 and gross < tare:
		errors.append(_("Gross weight must be greater than or equal to tare weight."))

	if not errors:
		calculate_net_weight(gross, tare, throw=throw)
	return _fail(errors, throw=throw)


def validate_weight_variance(ldn_name: str, *, tolerance_pct: float | None = None, throw: bool = False) -> dict[str, Any]:
	"""Compute weight variance against planned quantity. Does not persist fields."""
	ldn = _ldn_row(ldn_name)
	if not ldn:
		_fail([_("Loading Delivery Note {0} was not found.").format(ldn_name)], throw=True)

	do = None
	if ldn.get("transport_delivery_order"):
		do = _do_row(ldn["transport_delivery_order"])

	net = flt(ldn.get("net_weight"))
	if net <= 0 and ldn.get("gross_weight") and ldn.get("tare_weight"):
		net = calculate_net_weight(ldn["gross_weight"], ldn["tare_weight"], throw=False)

	planned = _planned_quantity(do, ldn)
	result = compute_weight_variance(net, planned, tolerance_pct=tolerance_pct)
	result["ldn_name"] = ldn_name
	return result


def validate_supervisor_approval(ldn_name: str, *, throw: bool = True) -> list[str]:
	"""Weight variance must be within tolerance or explicitly approved."""
	errors: list[str] = []
	ldn = _ldn_row(ldn_name)
	if not ldn:
		return _fail([_("Loading Delivery Note {0} was not found.").format(ldn_name)], throw=throw)

	status = (ldn.get("weight_variance_status") or "").strip()
	if not status:
		variance = validate_weight_variance(ldn_name, throw=False)
		status = variance.get("weight_variance_status") or "Within Tolerance"

	if status not in APPROVED_VARIANCE_STATUSES:
		pct = flt(ldn.get("weight_variance_pct"))
		if not pct:
			variance = validate_weight_variance(ldn_name, throw=False)
			pct = flt(variance.get("weight_variance_pct"))
		errors.append(
			_("Weight variance {0:.2f}% exceeds tolerance. Supervisor approval required.").format(pct)
		)
	return _fail(errors, throw=throw)


def validate_coa_required(batch_name: str) -> bool:
	"""Return True when the batch requires a COA for dispatch."""
	if not batch_name or not frappe.db.exists("APC Batch", batch_name):
		return False
	coa_status = frappe.db.get_value("APC Batch", batch_name, "coa_status") or "Not Generated"
	return coa_status != "Not Generated"


def validate_coa_approved(batch_name: str, *, throw: bool = True) -> list[str]:
	"""Batch must have a linked, approved COA when COA is required."""
	errors: list[str] = []
	if not batch_name or not frappe.db.exists("APC Batch", batch_name):
		errors.append(_("Batch {0} was not found.").format(batch_name))
		return _fail(errors, throw=throw)

	if not validate_coa_required(batch_name):
		return []

	batch = frappe.db.get_value(
		"APC Batch",
		batch_name,
		["linked_coa", "batch_number", "coa_status"],
		as_dict=True,
	)
	if not batch or not batch.get("linked_coa"):
		label = batch.get("batch_number") or batch_name if batch else batch_name
		errors.append(_("Batch {0} does not have an approved COA. Dispatch blocked.").format(label))
		return _fail(errors, throw=throw)

	approval = frappe.db.get_value("APC COA", batch["linked_coa"], "approval_status")
	if approval != "Approved":
		errors.append(
			_("COA {0} for batch {1} is not approved.").format(
				batch["linked_coa"], batch.get("batch_number") or batch_name
			)
		)
	return _fail(errors, throw=throw)


def validate_delivery_note_generation(ldn_name: str, *, throw: bool = True) -> list[str]:
	"""All preconditions for DN generation / dispatch confirmation."""
	from apc_operations.shipping.services.dispatch_flow_service import sync_ldn_transport_context

	sync_ldn_transport_context(ldn_name=ldn_name, update_modified=False)

	errors: list[str] = []
	ldn = _ldn_row(ldn_name)
	if not ldn:
		return _fail([_("Loading Delivery Note {0} was not found.").format(ldn_name)], throw=throw)

	if ldn.get("dispatch_confirmed"):
		errors.append(_("Dispatch already confirmed for {0}.").format(ldn_name))
		return _fail(errors, throw=throw)

	do_name = ldn.get("transport_delivery_order")
	do = _do_row(do_name) if do_name else None
	si = _si_row(ldn.get("security_inspection")) if ldn.get("security_inspection") else None
	if do_name and not si:
		si = _si_row(resolve_security_inspection_for_do(do_name))

	if (ldn.get("delivery_note_status") or "").strip() in INVALID_LDN_STATUSES:
		errors.append(_("Loading Delivery Note {0} is in an invalid state.").format(ldn_name))

	if not ldn.get("loading_end_time") and not (si or {}).get("loading_end_time"):
		errors.append(_("Loading not completed. Loading end time is required before generating the Delivery Note."))

	loaded_qty = _loaded_quantity(ldn, si, do_name=do_name)
	if loaded_qty <= 0:
		errors.append(_("Loaded quantity is required before generating the Delivery Note."))

	batch_rows = frappe.get_all(
		"Loading DN Batch",
		filters={"parent": ldn_name, "parenttype": "Loading Delivery Note"},
		fields=["name", "batch", "batch_number", "coa"],
	)
	if not batch_rows:
		errors.append(_("No batch rows found. Run FIFO allocation before generating the Delivery Note."))

	vehicle = _resolve_vehicle_for_validation(ldn, si, do_name)
	driver = _resolve_driver_for_validation(ldn, si, do_name)
	if not vehicle:
		errors.append(_("Vehicle details are missing."))
	if not driver:
		errors.append(_("Driver details are missing."))

	errors.extend(validate_weight_capture(ldn_name=ldn_name, throw=False))
	errors.extend(validate_supervisor_approval(ldn_name, throw=False))

	for row in batch_rows:
		if not row.get("batch"):
			errors.append(_("A batch allocation row is missing a batch reference."))
			continue
		errors.extend(validate_coa_approved(row["batch"], throw=False))

	if do and _is_do_cancelled(do):
		errors.append(_("Delivery Order {0} has been cancelled.").format(do_name))

	errors.extend(_validate_qc_and_security_signoff(ldn, si, do_name=do_name, throw=False))

	return _fail(errors, throw=throw)


def _validate_qc_and_security_signoff(
	ldn: dict[str, Any] | None,
	si: dict[str, Any] | None,
	*,
	do_name: str | None = None,
	throw: bool = False,
) -> list[str]:
	"""QC clearance, COA, and security final check required before dispatch confirm."""
	errors: list[str] = []
	if not ldn:
		return errors

	if not ldn.get("final_qc_clearance"):
		errors.append(_("QC final clearance is required before confirming dispatch."))
	if not ldn.get("qc_manager_approved"):
		errors.append(_("QC Manager approval is required before confirming dispatch."))
	if not ldn.get("security_final_check"):
		errors.append(_("Security final exit check must be completed before confirming dispatch."))

	if do_name:
		si_name = (si or {}).get("name") or resolve_security_inspection_for_do(do_name)
		if si_name:
			si_status = frappe.db.get_value("Security Inspection", si_name, "security_status")
			if si_status not in ("Reported to QC", "Loading DN Created", "QC Cleared", "Completed"):
				errors.append(_("Security checklist must be completed and reported to QC first."))

	if not ldn.get("coa_verified"):
		batch_rows = frappe.get_all(
			"Loading DN Batch",
			filters={"parent": ldn["name"], "parenttype": "Loading Delivery Note"},
			fields=["batch"],
		)
		coa_required = any(validate_coa_required(row["batch"]) for row in batch_rows if row.get("batch"))
		if coa_required:
			errors.append(_("COA must be verified for all dispatched batches before confirming dispatch."))

	return _fail(errors, throw=throw)


def validate_gate_out_allowed(gate_pass, *, throw: bool = True, for_release: bool = False) -> list[str]:
	"""Gate out requires confirmed DN, QC approvals, weights, and security final check."""
	if isinstance(gate_pass, str):
		gate_pass = frappe.get_doc("Gate Pass", gate_pass)

	errors: list[str] = []
	if not for_release and (gate_pass.gate_status or "").strip() != "Released":
		return []

	do_name = gate_pass.delivery_order
	if not do_name:
		errors.append(_("No Delivery Order linked to this Gate Pass."))
		return _fail(errors, throw=throw)

	do = _do_row(do_name)
	if not do:
		errors.append(_("Delivery Order {0} was not found.").format(do_name))
		return _fail(errors, throw=throw)

	if _is_do_cancelled(do):
		errors.append(_("Delivery Order {0} has been cancelled.").format(do_name))

	ldn_name = gate_pass.get("loading_delivery_note") or do.get("loading_delivery_note")
	if not ldn_name:
		errors.append(_("No Loading Delivery Note for Delivery Order {0}.").format(do_name))
		return _fail(errors, throw=throw)

	ldn = _ldn_row(ldn_name)
	if not ldn:
		errors.append(_("Loading Delivery Note {0} was not found.").format(ldn_name))
		return _fail(errors, throw=throw)

	if (ldn.get("delivery_note_status") or "").strip() in INVALID_LDN_STATUSES:
		errors.append(_("Loading Delivery Note {0} is in an invalid state.").format(ldn_name))

	if not ldn.get("dispatch_confirmed"):
		errors.append(_("Dispatch not confirmed. Generate Delivery Note first."))

	if not ldn.get("final_qc_clearance"):
		errors.append(_("QC final clearance after loading has not been given."))

	if not ldn.get("qc_manager_approved"):
		errors.append(_("QC Manager approval required before gate out."))

	if not ldn.get("security_final_check"):
		errors.append(_("Security final exit check must be completed."))

	errors.extend(validate_weight_capture(ldn_name=ldn_name, throw=False))
	errors.extend(validate_supervisor_approval(ldn_name, throw=False))

	if not ldn.get("coa_verified"):
		batch_rows = frappe.get_all(
			"Loading DN Batch",
			filters={"parent": ldn_name, "parenttype": "Loading Delivery Note"},
			fields=["batch"],
		)
		coa_required = any(validate_coa_required(row["batch"]) for row in batch_rows if row.get("batch"))
		if coa_required:
			errors.append(_("COA not verified for all dispatched batches."))

	return _fail(errors, throw=throw)


def validate_zoho_invoice_allowed(ldn_name: str, *, throw: bool = True) -> list[str]:
	"""Zoho invoice should trigger only after dispatch, QC approval, COA, and gate release."""
	errors: list[str] = []
	if not zoho_dispatch_sync_enabled():
		return []

	ldn = _ldn_row(ldn_name)
	if not ldn:
		return _fail([_("Loading Delivery Note {0} was not found.").format(ldn_name)], throw=throw)

	if not ldn.get("dispatch_confirmed"):
		errors.append(_("Dispatch not confirmed. Zoho invoice blocked."))

	if not ldn.get("qc_manager_approved"):
		errors.append(_("QC Manager approval required before Zoho invoice."))

	batch_rows = frappe.get_all(
		"Loading DN Batch",
		filters={"parent": ldn_name, "parenttype": "Loading Delivery Note"},
		fields=["batch"],
	)
	coa_required = any(validate_coa_required(row["batch"]) for row in batch_rows if row.get("batch"))
	if coa_required and not ldn.get("coa_verified"):
		errors.append(_("COA not verified. Zoho invoice blocked."))

	do_name = ldn.get("transport_delivery_order")
	gate_released = False
	if do_name:
		gate_released = bool(
			frappe.db.exists(
				"Gate Pass",
				{
					"delivery_order": do_name,
					"gate_status": "Released",
					"docstatus": ["!=", 2],
				},
			)
		)
	if not gate_released:
		errors.append(_("Gate out is not completed. Zoho invoice blocked until gate release."))

	return _fail(errors, throw=throw)
