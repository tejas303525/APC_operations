# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Console service APIs for loading-bay, gate-control and QC pre-check hubs."""

import frappe
from frappe import _
from frappe.utils import flt, now

from apc_operations.services.delivery_order_service import (
	GATE_READY_STATUSES,
	LOADING_BAY_STATUSES,
	operational_status_tone,
	resolve_transport_context_for_do,
)
from apc_operations.services.console_queue_service import attach_delivery_due_fields


def _lifecycle_in_clause(values: tuple[str, ...]) -> str:
	return ", ".join(frappe.db.escape(v) for v in values)


# ---------------------------------------------------------------------
# Loading Bay Console
# ---------------------------------------------------------------------


@frappe.whitelist()
def get_loading_bay_queue():
	"""DOs at loading bay — QC-cleared LDNs ready for DN issue, plus in-progress loads."""
	from apc_operations.shipping.services.dispatch_flow_service import (
		ensure_ldn_do_link,
		get_dispatch_readiness,
	)

	lifecycle = _lifecycle_in_clause(tuple(LOADING_BAY_STATUSES))
	rows = frappe.db.sql(
		f"""
		SELECT
			do.name              AS delivery_order,
			do.job_order,
			jo.date              AS job_order_delivery_date,
			do.customer,
			do.customer_name,
			do.do_status,
			do.operational_status,
			do.transport_delivery_order_number,
			do.loading_delivery_note,
			do.planned_quantity,
			do.total_qty,
			ldn.name               AS ldn_resolved,
			ldn.dispatch_confirmed,
			ldn.qc_manager_approved,
			ldn.final_qc_clearance,
			ldn.qc_status,
			ldn.qc_report_request,
			ldn.gross_weight,
			ldn.tare_weight,
			ldn.net_weight,
			ldn.weight_variance_status,
			ldn.material_description,
			ldn.quantity           AS ldn_quantity,
			ldn.planned_quantity   AS ldn_planned_quantity,
			ldn.uom                AS ldn_uom,
			ldn.loading_end_time,
			ldn.coa_verified,
			qcr.qc_status          AS qc_report_status,
			qcr.name               AS qc_report_request_name
		FROM `tabDelivery Order` do
		LEFT JOIN `tabJob Order` jo ON jo.name = do.job_order
		LEFT JOIN `tabLoading Delivery Note` ldn
			   ON ldn.name = COALESCE(
					do.loading_delivery_note,
					(
						SELECT l2.name
						FROM `tabLoading Delivery Note` l2
						WHERE l2.job_order = do.job_order
						  AND COALESCE(l2.dispatch_confirmed, 0) = 0
						ORDER BY l2.modified DESC
						LIMIT 1
					)
			   )
		LEFT JOIN `tabQC Report Request` qcr
			   ON qcr.name = COALESCE(
					ldn.qc_report_request,
					(
						SELECT q2.name
						FROM `tabQC Report Request` q2
						WHERE q2.loading_delivery_note = ldn.name
						ORDER BY q2.modified DESC
						LIMIT 1
					)
			   )
		WHERE COALESCE(do.docstatus, 0) < 2
		  AND COALESCE(do.operational_status, '') NOT IN ('Cancelled', 'Gate Out Completed')
		  AND ldn.name IS NOT NULL
		  AND COALESCE(ldn.dispatch_confirmed, 0) = 0
		  AND (
			do.operational_status IN ({lifecycle})
			OR do.do_status IN ('Pre-Check Cleared', 'Loading', 'DN Issued')
			OR ldn.qc_status = 'QC Cleared'
			OR qcr.qc_status = 'QC Cleared'
		  )
		ORDER BY COALESCE(jo.date, '9999-12-31') ASC, do.creation ASC
		LIMIT 100
		""",
		as_dict=True,
	)
	for row in rows:
		if not row.get("loading_delivery_note") and row.get("ldn_resolved"):
			row["loading_delivery_note"] = row["ldn_resolved"]

		link = ensure_ldn_do_link(
			do_name=row.get("delivery_order"),
			ldn_name=row.get("loading_delivery_note"),
			update_modified=False,
		)
		if link:
			row["loading_delivery_note"] = link["loading_delivery_note"]

		row["operational_status_tone"] = operational_status_tone(row.get("operational_status"))
		transport = resolve_transport_context_for_do(row.get("delivery_order"))
		row.update(transport)
		if not row.get("product"):
			row["product"] = row.get("material_description")
		if not row.get("quantity_to_load"):
			row["quantity_to_load"] = (
				flt(row.get("ldn_planned_quantity"))
				or flt(row.get("planned_quantity"))
				or flt(row.get("ldn_quantity"))
				or flt(row.get("total_qty"))
			)
		if not row.get("uom"):
			row["uom"] = row.get("ldn_uom")

		qc_cleared = (row.get("qc_status") or "") == "QC Cleared" or (
			row.get("qc_report_status") or ""
		) == "QC Cleared"
		row["qc_cleared"] = qc_cleared
		row["qc_report_request"] = row.get("qc_report_request_name") or row.get(
			"qc_report_request"
		)

		readiness = get_dispatch_readiness(row["delivery_order"])
		row["dispatch_readiness"] = readiness
		row["can_issue_dn"] = bool(readiness.get("can_issue_dn"))
		if row.get("job_order_delivery_date"):
			row["delivery_due_date"] = row.get("job_order_delivery_date")
		attach_delivery_due_fields(row)
	return rows


@frappe.whitelist()
def issue_loading_dn(delivery_order):
	"""Loading-bay "Issue DN" action via validated dispatch workflow."""
	from apc_operations.security.dispatch_workflow import request_delivery_note_generation

	return request_delivery_note_generation(delivery_order)


# ---------------------------------------------------------------------
# Gate Control Console
# ---------------------------------------------------------------------


@frappe.whitelist()
def get_gate_control_queue():
	"""Outward gate passes with lifecycle-aware traffic-light status."""
	rows = frappe.db.sql(
		f"""
		SELECT
			gp.name              AS gate_pass,
			gp.vehicle_no,
			gp.driver_name,
			gp.delivery_order,
			gp.gate_status,
			gp.released_on,
			do.do_status,
			do.operational_status,
			do.loading_delivery_note,
			ldn.dispatch_confirmed,
			ldn.qc_manager_approved,
			ldn.final_qc_clearance,
			ldn.security_final_check,
			ldn.coa_verified,
			ldn.weight_variance_status
		FROM `tabGate Pass` gp
		LEFT JOIN `tabDelivery Order` do ON do.name = gp.delivery_order
		LEFT JOIN `tabLoading Delivery Note` ldn ON ldn.name = COALESCE(gp.loading_delivery_note, do.loading_delivery_note)
		WHERE gp.gate_pass_type = 'Out'
		  AND COALESCE(gp.gate_status, 'Pending') != 'Cancelled'
		ORDER BY gp.modified DESC
		LIMIT 100
		""",
		as_dict=True,
	)

	for r in rows:
		if r.gate_status == "Released":
			r["traffic_light"] = "released"
		elif not r.loading_delivery_note:
			r["traffic_light"] = "red"
		elif (r.operational_status or "") in GATE_READY_STATUSES:
			r["traffic_light"] = "green"
		elif (
			r.dispatch_confirmed
			and r.qc_manager_approved
			and r.final_qc_clearance
			and r.security_final_check
			and (r.weight_variance_status or "Within Tolerance") in ("Within Tolerance", "Approved")
		):
			r["traffic_light"] = "green"
		else:
			r["traffic_light"] = "amber"
		r["operational_status_tone"] = operational_status_tone(r.get("operational_status"))
	return rows


@frappe.whitelist()
def release_gate(gate_pass):
	"""Mark the Gate Pass as Released using central gate-out validation."""
	from apc_operations.shipping.services.dispatch_validation_service import validate_gate_out_allowed

	gp = frappe.get_doc("Gate Pass", gate_pass)
	if not gp.delivery_order:
		frappe.throw(_("Gate Pass has no linked Delivery Order."))

	gp.gate_status = "Draft"
	gp.released_on = now()
	gp.released_by = frappe.session.user
	gp.gate_out_time = now()
	gp.gate_out_approved_by = frappe.session.user
	validate_gate_out_allowed(gp, for_release=True)
	gp.save(ignore_permissions=False)

	from apc_operations.shipping.services.dispatch_lifecycle_service import (
		sync_dispatch_lifecycle_from_gate_pass,
	)

	sync_dispatch_lifecycle_from_gate_pass(gp, update_modified=False)
	return {"success": True, "gate_pass": gp.name, "released_on": gp.released_on}


# ---------------------------------------------------------------------
# QC Pre-Check Console
# ---------------------------------------------------------------------


@frappe.whitelist()
def get_qc_precheck_queue():
	"""Pre-check tickets awaiting QC action, enriched with DO lifecycle status."""
	from apc_operations.quality.dispatch_workflow import get_qc_precheck_queue as _queue

	return _queue()


@frappe.whitelist()
def qc_precheck_mark(pre_check_clearance, status, remarks=None):
	"""One-click pass / fail from the QC pre-check console."""
	from apc_operations.quality.dispatch_workflow import submit_qc_precheck

	result = "Passed" if status == "Passed" else "Failed"
	return submit_qc_precheck(
		pre_check_clearance,
		result,
		qc_remarks=remarks,
		failure_reason=remarks if result == "Failed" else None,
	)


@frappe.whitelist()
def qc_manager_approve_dn(loading_delivery_note):
	"""QC Manager DN-COA binding approval via dispatch workflow."""
	from apc_operations.quality.dispatch_workflow import qc_manager_approve_dispatch

	return qc_manager_approve_dispatch(loading_delivery_note)
