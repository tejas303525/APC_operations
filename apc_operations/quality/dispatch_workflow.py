# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Delivery Order–centric QC workflow actions (Phase 5)."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import now

from apc_operations.shipping.services.dispatch_lifecycle_service import (
	set_delivery_order_operational_status,
	sync_dispatch_lifecycle_status,
)
from apc_operations.shipping.services.dispatch_validation_service import (
	validate_coa_approved,
	validate_coa_required,
	validate_supervisor_approval,
	validate_weight_capture,
)


def get_qc_precheck_queue(limit: int = 100) -> list[dict[str, Any]]:
	"""DOs awaiting QC pre-check, enriched with lifecycle status."""
	return frappe.db.sql(
		"""
		SELECT
			pcc.name              AS pre_check_clearance,
			pcc.delivery_order,
			pcc.job_order,
			pcc.qc_status,
			pcc.qc_pre_check_status,
			pcc.security_status,
			pcc.overall_status,
			pcc.batch_no,
			pcc.coa_status,
			pcc.product_confirmed,
			pcc.tanker_cleanliness,
			pcc.odour_check,
			pcc.qc_remarks,
			pcc.failure_reason,
			do.customer_name,
			do.operational_status,
			do.do_status,
			do.loading_delivery_note,
			do.truck_arrived_on
		FROM `tabPre-Check Clearance` pcc
		INNER JOIN `tabDelivery Order` do ON do.name = pcc.delivery_order
		WHERE do.docstatus < 2
		  AND (
			pcc.qc_status IN ('Pending', 'Failed')
			OR pcc.qc_pre_check_status IN ('Pending', 'On Hold')
			OR do.operational_status IN ('QC Pre-check Pending', 'Truck Arrived', 'On Hold')
		  )
		ORDER BY pcc.modified DESC
		LIMIT %(limit)s
		""",
		{"limit": int(limit)},
		as_dict=True,
	)


def _get_pcc(pre_check_clearance: str) -> frappe.model.document.Document:
	if not pre_check_clearance:
		frappe.throw(_("pre_check_clearance is required"))
	return frappe.get_doc("Pre-Check Clearance", pre_check_clearance)


_VERIFIED_SDDN_STATUSES = frozenset(
	{"Verified", "Approved", "LDN Created", "Gate Out Approved"}
)


def mark_pcc_security_passed(
	pre_check_clearance: str,
	*,
	security_remarks: str | None = None,
	pcc=None,
) -> dict[str, Any]:
	"""Record security pre-check sign-off on the linked PCC."""
	pcc = pcc or _get_pcc(pre_check_clearance)
	if (pcc.security_status or "").strip() == "Passed":
		return {
			"updated": False,
			"pre_check_clearance": pcc.name,
			"overall_status": pcc.overall_status,
		}
	pcc.security_status = "Passed"
	if security_remarks:
		pcc.security_remarks = security_remarks
	pcc.save(ignore_permissions=True)
	if (pcc.overall_status or "").strip() == "Authorized":
		from apc_operations.shipping.services.import_grn_service import (
			maybe_ensure_import_grn_after_precheck_authorized,
		)

		maybe_ensure_import_grn_after_precheck_authorized(
			pcc.delivery_order, pcc_name=pcc.name
		)
	status = _sync_do_from_pcc(pcc)
	return {
		"updated": True,
		"pre_check_clearance": pcc.name,
		"delivery_order": pcc.delivery_order,
		"overall_status": pcc.overall_status,
		"operational_status": status,
	}


def _resolve_do_for_sddn(sddn_name: str) -> str | None:
	from apc_operations.services.delivery_order_service import (
		find_delivery_order_for_job_order_primary,
	)

	jo = frappe.db.get_value("Security Draft Delivery Note", sddn_name, "job_order")
	if not jo:
		return None
	return find_delivery_order_for_job_order_primary(jo)


def sync_pcc_security_after_sddn_verify(
	sddn_name: str,
	*,
	security_remarks: str | None = None,
) -> dict[str, Any] | None:
	"""When SDDN is verified, mirror security sign-off onto Pre-Check Clearance."""
	do_name = _resolve_do_for_sddn(sddn_name)
	if not do_name:
		return None
	pcc_name = frappe.db.get_value("Delivery Order", do_name, "pre_check_clearance")
	if not pcc_name:
		do = frappe.get_doc("Delivery Order", do_name)
		if hasattr(do, "_ensure_pre_check_clearance"):
			do._ensure_pre_check_clearance()
			pcc_name = do.pre_check_clearance
	if not pcc_name:
		return None
	return mark_pcc_security_passed(pcc_name, security_remarks=security_remarks)


def maybe_sync_pcc_security_from_verified_sddn(pcc) -> dict[str, Any] | None:
	"""If SDDN is already verified, align PCC security_status without a separate form save."""
	if (pcc.security_status or "").strip() == "Passed":
		return None
	if not pcc.delivery_order:
		return None
	jo = frappe.db.get_value("Delivery Order", pcc.delivery_order, "job_order")
	if not jo:
		return None
	sddn_name = frappe.db.get_value(
		"Security Draft Delivery Note",
		{"job_order": jo},
		"name",
		order_by="modified desc",
	)
	if not sddn_name:
		return None
	sddn_status = frappe.db.get_value(
		"Security Draft Delivery Note", sddn_name, "security_status"
	)
	if (sddn_status or "").strip() not in _VERIFIED_SDDN_STATUSES:
		return None
	return mark_pcc_security_passed(pcc.name, pcc=pcc)


def _sync_do_from_pcc(pcc) -> str | None:
	if not pcc.delivery_order:
		return None
	if pcc.overall_status == "Authorized":
		return sync_dispatch_lifecycle_status(pcc.delivery_order, update_modified=True)
	if pcc.qc_pre_check_status == "On Hold" or pcc.overall_status == "Blocked":
		if pcc.qc_pre_check_status == "On Hold":
			return set_delivery_order_operational_status(
				pcc.delivery_order, "On Hold", force=True, update_modified=True
			)
		if pcc.qc_status == "Failed" or pcc.qc_pre_check_status == "Failed":
			return set_delivery_order_operational_status(
				pcc.delivery_order, "QC Pre-check Failed", force=True, update_modified=True
			)
	return sync_dispatch_lifecycle_status(pcc.delivery_order, update_modified=True)


def submit_qc_precheck(
	pre_check_clearance: str,
	result: str,
	*,
	product_confirmed: int | bool | None = None,
	batch_no: str | None = None,
	coa_status: str | None = None,
	tanker_cleanliness: str | None = None,
	odour_check: str | None = None,
	seal_condition_before_loading: str | None = None,
	qc_remarks: str | None = None,
	failure_reason: str | None = None,
) -> dict[str, Any]:
	result = (result or "").strip()
	if result not in {"Passed", "Failed", "On Hold"}:
		frappe.throw(_("result must be Passed, Failed, or On Hold"))

	pcc = _get_pcc(pre_check_clearance)
	if result == "Failed" and not failure_reason and not qc_remarks:
		frappe.throw(_("Failure reason is required when failing pre-check."))

	if product_confirmed is not None:
		pcc.product_confirmed = 1 if product_confirmed else 0
	if batch_no:
		link_batch_to_precheck(pre_check_clearance, batch_no, pcc=pcc)
	if coa_status:
		pcc.coa_status = coa_status
	if tanker_cleanliness:
		pcc.tanker_cleanliness = tanker_cleanliness
	if odour_check:
		pcc.odour_check = odour_check
	if seal_condition_before_loading:
		pcc.seal_condition_before_loading = seal_condition_before_loading
	if qc_remarks:
		pcc.qc_remarks = qc_remarks
	if failure_reason:
		pcc.failure_reason = failure_reason

	if result == "On Hold":
		pcc.qc_pre_check_status = "On Hold"
		pcc.qc_status = "Pending"
		if not pcc.block_reason:
			pcc.block_reason = failure_reason or qc_remarks or _("QC pre-check on hold")
	else:
		pcc.qc_status = result
		pcc.qc_pre_check_status = result

	pcc.save(ignore_permissions=True)
	if result == "Passed":
		maybe_sync_pcc_security_from_verified_sddn(pcc)
		pcc.reload()
		if (pcc.overall_status or "").strip() == "Authorized":
			from apc_operations.shipping.services.import_grn_service import (
				maybe_ensure_import_grn_after_precheck_authorized,
			)

			maybe_ensure_import_grn_after_precheck_authorized(
				pcc.delivery_order, pcc_name=pcc.name
			)
	status = _sync_do_from_pcc(pcc)
	return {
		"success": True,
		"pre_check_clearance": pcc.name,
		"delivery_order": pcc.delivery_order,
		"overall_status": pcc.overall_status,
		"operational_status": status,
		"is_import": bool(
			pcc.delivery_order
			and frappe.db.get_value(
				"Delivery Order", pcc.delivery_order, "commercial_movement"
			)
			== "Import"
		),
	}


def put_qc_on_hold(pre_check_clearance: str, hold_reason: str) -> dict[str, Any]:
	if not hold_reason:
		frappe.throw(_("Hold reason is required."))
	return submit_qc_precheck(
		pre_check_clearance,
		"On Hold",
		failure_reason=hold_reason,
		qc_remarks=hold_reason,
	)


def fail_qc_precheck(pre_check_clearance: str, failure_reason: str) -> dict[str, Any]:
	if not failure_reason:
		frappe.throw(_("Failure reason is required."))
	return submit_qc_precheck(
		pre_check_clearance,
		"Failed",
		failure_reason=failure_reason,
	)


def link_batch_to_precheck(
	pre_check_clearance: str,
	batch_no: str,
	*,
	pcc=None,
) -> dict[str, Any]:
	if not batch_no:
		frappe.throw(_("batch_no is required"))
	if not frappe.db.exists("APC Batch", batch_no):
		frappe.throw(_("Batch {0} was not found.").format(batch_no))

	batch = frappe.db.get_value(
		"APC Batch",
		batch_no,
		["batch_status", "quality_status", "stock_status", "linked_coa", "coa_status"],
		as_dict=True,
	)
	if batch.get("batch_status") in {"Blocked", "Cancelled", "Expired"}:
		frappe.throw(_("Batch {0} is {1} and cannot be used.").format(batch_no, batch.batch_status))
	if batch.get("quality_status") in {"QC Rejected", "Rejected"}:
		frappe.throw(_("Batch {0} is rejected and cannot be used for pre-check.").format(batch_no))
	if batch.get("stock_status") in {"Rejected", "Cancelled"}:
		frappe.throw(_("Batch {0} stock status is {1}.").format(batch_no, batch.stock_status))

	pcc = pcc or _get_pcc(pre_check_clearance)
	pcc.batch_no = batch_no
	if batch.get("linked_coa"):
		approval = frappe.db.get_value("APC COA", batch.linked_coa, "approval_status")
		if approval == "Approved":
			pcc.coa_status = "Approved"
		else:
			pcc.coa_status = "Present"
	elif batch.get("coa_status") == "Not Generated":
		pcc.coa_status = "Missing"
	else:
		pcc.coa_status = "Present"

	if pcc.name and pcc.has_value_changed("batch_no"):
		pcc.save(ignore_permissions=True)

	return {
		"success": True,
		"pre_check_clearance": pcc.name,
		"batch_no": batch_no,
		"coa_status": pcc.coa_status,
	}


def verify_coa_for_batch(loading_delivery_note: str, batch: str) -> dict[str, Any]:
	if not loading_delivery_note or not batch:
		frappe.throw(_("loading_delivery_note and batch are required"))

	validate_coa_approved(batch)
	ldn = frappe.get_doc("Loading Delivery Note", loading_delivery_note)

	for row in ldn.batch_allocations or []:
		if row.batch == batch and not row.coa:
			linked_coa = frappe.db.get_value("APC Batch", batch, "linked_coa")
			if linked_coa:
				row.coa = linked_coa

	all_verified = True
	for row in ldn.batch_allocations or []:
		if not row.batch:
			continue
		if validate_coa_required(row.batch):
			if not row.coa:
				all_verified = False
				continue
			approval = frappe.db.get_value("APC COA", row.coa, "approval_status")
			if approval != "Approved":
				all_verified = False

	if all_verified:
		ldn.coa_verified = 1
		ldn.coa_verified_by = frappe.session.user
		ldn.coa_verified_on = now()
		ldn.delivery_note_status = "COA Attached"
		ldn.save(ignore_permissions=True)

	do_name = ldn.transport_delivery_order
	status = sync_dispatch_lifecycle_status(do_name, update_modified=True) if do_name else None

	return {
		"success": True,
		"loading_delivery_note": loading_delivery_note,
		"batch": batch,
		"coa_verified": ldn.coa_verified,
		"operational_status": status,
	}


def submit_final_qc_clearance(
	loading_delivery_note: str,
	qc_remarks: str | None = None,
) -> dict[str, Any]:
	ldn = frappe.get_doc("Loading Delivery Note", loading_delivery_note)
	do_name = ldn.transport_delivery_order

	if not ldn.loading_end_time:
		frappe.throw(_("Loading must be completed before final QC clearance."))
	if do_name:
		validate_weight_capture(do_name=do_name)
		validate_supervisor_approval(ldn.name)

	for row in ldn.batch_allocations or []:
		if row.batch and validate_coa_required(row.batch):
			validate_coa_approved(row.batch)

	ldn.final_qc_clearance = 1
	ldn.final_qc_clearance_by = frappe.session.user
	ldn.final_qc_clearance_on = now()
	ldn.qc_status = "QC Cleared"
	updates = {
		"final_qc_clearance": 1,
		"final_qc_clearance_by": frappe.session.user,
		"final_qc_clearance_on": now(),
		"qc_status": "QC Cleared",
	}
	if qc_remarks:
		updates["notes"] = (ldn.notes or "") + f"\n{qc_remarks}"
	frappe.db.set_value("Loading Delivery Note", ldn.name, updates, update_modified=True)

	status = sync_dispatch_lifecycle_status(do_name, update_modified=True) if do_name else None
	return {
		"success": True,
		"loading_delivery_note": loading_delivery_note,
		"operational_status": status,
	}


def qc_manager_approve_dispatch(loading_delivery_note: str) -> dict[str, Any]:
	ldn = frappe.get_doc("Loading Delivery Note", loading_delivery_note)
	if not ldn.final_qc_clearance:
		frappe.throw(_("Final QC clearance must be completed before QC Manager approval."))

	result = ldn.qc_manager_approve()
	status = None
	if ldn.transport_delivery_order:
		status = sync_dispatch_lifecycle_status(ldn.transport_delivery_order, update_modified=True)

	return {
		"success": True,
		"loading_delivery_note": loading_delivery_note,
		"dispatch_result": result,
		"operational_status": status,
	}
