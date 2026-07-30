# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Persist Delivery Order dispatch lifecycle status (``operational_status``)."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, now

from apc_operations.shipping.services.dispatch_validation_service import (
	resolve_ldn_for_do,
	resolve_pcc_for_do,
	resolve_security_inspection_for_do,
	validate_weight_variance,
)

DISPATCH_LIFECYCLE_STATUSES = (
	"Draft",
	"Issued",
	"Sent to Security",
	"Truck Arrived",
	"QC Pre-check Pending",
	"QC Pre-check Passed",
	"QC Pre-check Failed",
	"Loading Allowed",
	"Loading Started",
	"Loading Completed",
	"Weighment Completed",
	"Weight Variance Approval Pending",
	"QC Final Pending",
	"Delivery Note Generated",
	"Ready for Gate Out",
	"Gate Out Completed",
	"On Hold",
	"Cancelled",
)

TERMINAL_LIFECYCLE_STATUSES = frozenset({"Cancelled", "Gate Out Completed"})

# Statuses at or beyond dispatch-confirmed. Stock is already deducted here,
# so a DO in one of these statuses no longer needs to block a follow-up leg
# for the same Job Order - the truck's physical gate-out can happen later.
DISPATCH_CONFIRMED_STATUSES = frozenset(
	{"Delivery Note Generated", "Ready for Gate Out", "Gate Out Completed"}
)

# Explicit API transitions (Phase 4+) — recompute sync bypasses this graph.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
	"Draft": frozenset({"Issued", "Sent to Security", "Cancelled"}),
	"Issued": frozenset({"Sent to Security", "Truck Arrived", "Cancelled", "On Hold"}),
	"Sent to Security": frozenset({"Truck Arrived", "Cancelled", "On Hold"}),
	"Truck Arrived": frozenset({"QC Pre-check Pending", "Cancelled", "On Hold"}),
	"QC Pre-check Pending": frozenset(
		{"QC Pre-check Passed", "QC Pre-check Failed", "On Hold", "Cancelled"}
	),
	"QC Pre-check Passed": frozenset({"Loading Allowed", "On Hold", "Cancelled"}),
	"QC Pre-check Failed": frozenset({"On Hold", "Cancelled", "QC Pre-check Pending"}),
	"Loading Allowed": frozenset({"Loading Started", "On Hold", "Cancelled"}),
	"Loading Started": frozenset({"Loading Completed", "On Hold", "Cancelled"}),
	"Loading Completed": frozenset({"Weighment Completed", "On Hold", "Cancelled"}),
	"Weighment Completed": frozenset(
		{"Weight Variance Approval Pending", "QC Final Pending", "On Hold", "Cancelled"}
	),
	"Weight Variance Approval Pending": frozenset({"QC Final Pending", "On Hold", "Cancelled"}),
	"QC Final Pending": frozenset({"Delivery Note Generated", "On Hold", "Cancelled"}),
	"Delivery Note Generated": frozenset({"Ready for Gate Out", "On Hold", "Cancelled"}),
	"Ready for Gate Out": frozenset({"Gate Out Completed", "On Hold", "Cancelled"}),
	"On Hold": frozenset(
		{
			"Issued",
			"Sent to Security",
			"Truck Arrived",
			"QC Pre-check Pending",
			"QC Pre-check Passed",
			"Loading Allowed",
			"Loading Started",
			"Loading Completed",
			"Weighment Completed",
			"QC Final Pending",
			"Delivery Note Generated",
			"Ready for Gate Out",
			"Cancelled",
		}
	),
	"Gate Out Completed": frozenset(),
	"Cancelled": frozenset(),
}

LIFECYCLE_TO_DO_STATUS = {
	"Draft": "Draft",
	"Issued": "Issued",
	"Sent to Security": "Issued",
	"Truck Arrived": "Pre-Check Pending",
	"QC Pre-check Pending": "Pre-Check Pending",
	"QC Pre-check Passed": "Pre-Check Pending",
	"QC Pre-check Failed": "Pre-Check Pending",
	"Loading Allowed": "Pre-Check Cleared",
	"Loading Started": "Loading",
	"Loading Completed": "Loading",
	"Weighment Completed": "Loading",
	"Weight Variance Approval Pending": "Loading",
	"QC Final Pending": "Loading",
	"Delivery Note Generated": "DN Issued",
	"Ready for Gate Out": "DN Issued",
	"Gate Out Completed": "Completed",
	"On Hold": "Pre-Check Pending",
	"Cancelled": "Cancelled",
}


def _do_snapshot(do_name: str) -> dict[str, Any] | None:
	if not do_name or not frappe.db.exists("Delivery Order", do_name):
		return None
	return frappe.db.get_value(
		"Delivery Order",
		do_name,
		[
			"name",
			"docstatus",
			"status",
			"operational_status",
			"do_status",
			"loading_delivery_note",
			"pre_check_clearance",
			"truck_arrived_on",
			"sent_to_security_on",
			"issued_on",
			"commercial_movement",
		],
		as_dict=True,
	)


def _gate_pass_released_for_do(do_name: str) -> bool:
	return bool(
		frappe.db.exists(
			"Gate Pass",
			{
				"delivery_order": do_name,
				"gate_status": "Released",
				"docstatus": ["!=", 2],
			},
		)
	)


def _pcc_on_hold(pcc: dict[str, Any] | None) -> bool:
	if not pcc:
		return False
	if pcc.get("overall_status") == "Blocked":
		return True
	return (pcc.get("qc_pre_check_status") or "").strip() == "On Hold"


def _pcc_failed(pcc: dict[str, Any] | None) -> bool:
	if not pcc:
		return False
	if pcc.get("overall_status") == "Blocked":
		return pcc.get("qc_status") == "Failed" or pcc.get("security_status") == "Failed"
	return (pcc.get("qc_pre_check_status") or "").strip() == "Failed"


def _loading_times(ldn: dict[str, Any] | None, si: dict[str, Any] | None) -> tuple[Any, Any]:
	start = (ldn or {}).get("loading_start_time") or (si or {}).get("loading_start_time")
	end = (ldn or {}).get("loading_end_time") or (si or {}).get("loading_end_time")
	return start, end


def _weights_captured(ldn: dict[str, Any] | None, si: dict[str, Any] | None) -> bool:
	tare = flt((ldn or {}).get("tare_weight") or (si or {}).get("tare_weight"))
	gross = flt((ldn or {}).get("gross_weight") or (si or {}).get("gross_weight"))
	return tare > 0 and gross > 0 and gross >= tare


def compute_dispatch_lifecycle_status(do_name: str) -> str:
	"""Derive the persisted dispatch lifecycle status from linked documents."""
	do = _do_snapshot(do_name)
	if not do:
		return "Draft"

	if do.get("docstatus") == 2 or (do.get("status") or "").strip() == "Cancelled":
		return "Cancelled"
	if (do.get("operational_status") or "").strip() == "Cancelled":
		return "Cancelled"

	if _gate_pass_released_for_do(do_name):
		ldn_name = resolve_ldn_for_do(do_name)
		if ldn_name:
			ldn = frappe.db.get_value(
				"Loading Delivery Note",
				ldn_name,
				["security_final_check", "qc_manager_approved", "final_qc_clearance"],
				as_dict=True,
			)
			if (
				ldn
				and ldn.get("security_final_check")
				and ldn.get("qc_manager_approved")
				and ldn.get("final_qc_clearance")
			):
				return "Gate Out Completed"
		# Released gate pass but preconditions not met — fall through to normal lifecycle

	ldn_name = resolve_ldn_for_do(do_name)
	ldn = None
	if ldn_name:
		ldn = frappe.db.get_value(
			"Loading Delivery Note",
			ldn_name,
			[
				"name",
				"dispatch_confirmed",
				"delivery_note_status",
				"final_qc_clearance",
				"qc_manager_approved",
				"security_final_check",
				"coa_verified",
				"loading_start_time",
				"loading_end_time",
				"tare_weight",
				"gross_weight",
				"net_weight",
				"weight_variance_status",
				"quantity",
			],
			as_dict=True,
		)

	pcc_name = resolve_pcc_for_do(do_name)
	pcc = None
	if pcc_name:
		pcc = frappe.db.get_value(
			"Pre-Check Clearance",
			pcc_name,
			[
				"overall_status",
				"qc_status",
				"security_status",
				"qc_pre_check_status",
			],
			as_dict=True,
		)

	# Security Inspection is an Outward, loading-bay-specific concept
	# (created from a Security Draft DN's checklist during dispatch).
	# resolve_security_inspection_for_do() falls back to a job-order-wide
	# lookup, not scoped to a specific DO/leg - on a Job Order that has any
	# outward-flavored Security Inspection at all, that fallback would
	# wrongly attach it to an unrelated Import DO and permanently cap its
	# computed status at "Sent to Security", since Import never has an LDN
	# to satisfy the `if not ldn: return "Sent to Security"` branch below.
	# Import DOs advance purely off Pre-Check Clearance instead.
	si_name = (
		resolve_security_inspection_for_do(do_name)
		if (do.get("commercial_movement") or "").strip() != "Import"
		else None
	)
	si = None
	if si_name:
		si = frappe.db.get_value(
			"Security Inspection",
			si_name,
			[
				"loading_start_time",
				"loading_end_time",
				"tare_weight",
				"gross_weight",
				"quantity",
				"truck_arrived_notified_qc",
			],
			as_dict=True,
		)

	if _pcc_on_hold(pcc):
		return "On Hold"

	# Security inspection / QC intake before loading stages
	if si_name:
		si_meta = frappe.db.get_value(
			"Security Inspection",
			si_name,
			["security_status", "qc_status", "qc_report_request"],
			as_dict=True,
		)
		if si_meta:
			if (si_meta.get("security_status") or "") == "Reported to QC":
				if not ldn or not ldn.get("dispatch_confirmed"):
					return "QC Pre-check Pending"
			elif (si_meta.get("security_status") or "") in (
				"Checklist Completed",
				"Loading DN Created",
			):
				if not ldn:
					return "Sent to Security"

	if ldn:
		if ldn.get("dispatch_confirmed"):
			if not ldn.get("final_qc_clearance") or not ldn.get("qc_manager_approved"):
				return "QC Final Pending"
			if ldn.get("security_final_check"):
				return "Ready for Gate Out"
			return "Delivery Note Generated"

		if _weights_captured(ldn, si):
			variance_status = (ldn.get("weight_variance_status") or "").strip()
			if not variance_status and ldn_name:
				variance_status = validate_weight_variance(ldn_name, throw=False).get(
					"weight_variance_status", "Within Tolerance"
				)
			if variance_status == "Requires Approval":
				return "Weight Variance Approval Pending"
			if not ldn.get("final_qc_clearance") or not ldn.get("qc_manager_approved"):
				return "QC Final Pending"
			return "Weighment Completed"

	loading_start, loading_end = _loading_times(ldn, si)
	if loading_end:
		return "Loading Completed"
	if loading_start:
		return "Loading Started"

	if pcc and pcc.get("overall_status") == "Authorized":
		return "Loading Allowed"
	if pcc and (pcc.get("qc_status") or "").strip() == "Passed" and not _pcc_failed(pcc):
		return "QC Pre-check Passed"
	if pcc and _pcc_failed(pcc):
		return "QC Pre-check Failed"

	if si and si.get("truck_arrived_notified_qc"):
		return "QC Pre-check Pending"
	if do.get("truck_arrived_on"):
		return "Truck Arrived"

	if do.get("sent_to_security_on"):
		return "Sent to Security"

	jo = do.get("job_order") or frappe.db.get_value("Delivery Order", do_name, "job_order")
	if jo:
		sddn_status = frappe.db.get_value(
			"Security Draft Delivery Note",
			{"job_order": jo},
			"security_status",
			order_by="modified desc",
		)
		if sddn_status in ("Sent to Security", "Pending Review", "Pending Verification", "Draft"):
			return "Sent to Security"

	if do.get("docstatus") == 1 or (do.get("do_status") or "") in ("Issued", "Pre-Check Pending"):
		return "Issued"

	return "Draft"


def map_lifecycle_to_do_status(lifecycle_status: str) -> str:
	return LIFECYCLE_TO_DO_STATUS.get(lifecycle_status, "Draft")


def transition_allowed(current: str, new: str, *, force: bool = False) -> bool:
	if force or current == new:
		return True
	if current in TERMINAL_LIFECYCLE_STATUSES:
		return False
	return new in ALLOWED_TRANSITIONS.get(current, frozenset())


def set_delivery_order_operational_status(
	do_name: str,
	new_status: str,
	*,
	force: bool = False,
	update_modified: bool = False,
	comment: str | None = None,
) -> str:
	"""Apply an explicit lifecycle transition."""
	if new_status not in DISPATCH_LIFECYCLE_STATUSES:
		frappe.throw(_("Invalid operational status: {0}").format(new_status))

	current = frappe.db.get_value("Delivery Order", do_name, "operational_status") or "Draft"
	if not transition_allowed(current, new_status, force=force):
		frappe.throw(_("Cannot change Delivery Order status from {0} to {1}.").format(current, new_status))

	return _apply_lifecycle_status(do_name, new_status, update_modified=update_modified, comment=comment)


def sync_dispatch_lifecycle_status(
	do_name: str,
	*,
	update_modified: bool = False,
	force: bool = True,
) -> str | None:
	"""Recompute lifecycle status from linked documents and persist it."""
	if not do_name or not frappe.db.exists("Delivery Order", do_name):
		return None

	new_status = compute_dispatch_lifecycle_status(do_name)
	current = frappe.db.get_value("Delivery Order", do_name, "operational_status") or "Draft"
	if current in TERMINAL_LIFECYCLE_STATUSES and not force:
		return current
	if current == new_status:
		return current

	return _apply_lifecycle_status(
		do_name,
		new_status,
		update_modified=update_modified,
		comment=f"Status synced to {new_status}",
	)


def _apply_lifecycle_status(
	do_name: str,
	new_status: str,
	*,
	update_modified: bool = False,
	comment: str | None = None,
) -> str:
	do_status = map_lifecycle_to_do_status(new_status)
	frappe.db.set_value(
		"Delivery Order",
		do_name,
		{
			"operational_status": new_status,
			"do_status": do_status,
		},
		update_modified=update_modified,
	)
	if comment:
		try:
			doc = frappe.get_doc("Delivery Order", do_name)
			doc.add_comment("Info", comment)
		except Exception:
			pass
	return new_status


def mark_do_sent_to_security(do_name: str, *, update_modified: bool = False) -> None:
	"""Explicit helper for transport/security issuance."""
	values = {"sent_to_security_on": now()}
	if not frappe.db.get_value("Delivery Order", do_name, "operational_status"):
		values["operational_status"] = "Sent to Security"
	frappe.db.set_value("Delivery Order", do_name, values, update_modified=update_modified)
	sync_dispatch_lifecycle_status(do_name, update_modified=update_modified)


def mark_do_truck_arrived(do_name: str, *, update_modified: bool = False) -> None:
	frappe.db.set_value(
		"Delivery Order",
		do_name,
		{"truck_arrived_on": now()},
		update_modified=update_modified,
	)
	sync_dispatch_lifecycle_status(do_name, update_modified=update_modified)


def sync_dispatch_lifecycle_from_ldn(ldn_name: str, *, update_modified: bool = False) -> None:
	do_name = frappe.db.get_value("Loading Delivery Note", ldn_name, "transport_delivery_order")
	if not do_name:
		from apc_operations.services.delivery_order_service import resolve_do_for_ldn

		do_name = resolve_do_for_ldn(ldn_name)
	if do_name:
		sync_dispatch_lifecycle_status(do_name, update_modified=update_modified)


def sync_dispatch_lifecycle_from_pcc(pcc_name: str, *, update_modified: bool = False) -> None:
	do_name = frappe.db.get_value("Pre-Check Clearance", pcc_name, "delivery_order")
	if do_name:
		sync_dispatch_lifecycle_status(do_name, update_modified=update_modified)


def sync_dispatch_lifecycle_from_gate_pass(gate_pass, *, update_modified: bool = False) -> None:
	do_name = gate_pass.delivery_order if hasattr(gate_pass, "delivery_order") else None
	if not do_name and isinstance(gate_pass, str):
		do_name = frappe.db.get_value("Gate Pass", gate_pass, "delivery_order")
	if do_name:
		sync_dispatch_lifecycle_status(do_name, update_modified=update_modified)
