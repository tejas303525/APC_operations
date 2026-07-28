# Copyright (c) 2026, APC and contributors
"""Import Goods Received Note — created when QC + security pre-check are authorized."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, now, today

_PENDING_GRN_STATUSES = frozenset({"Draft", "Pending Approval"})
_COMPLETED_GRN_STATUSES = frozenset({"Approved", "Posted"})


def resolve_commercial_movement_for_do(do_name: str) -> str:
	"""Return Export or Import for a Delivery Order (DO field, then Job Order)."""
	if not do_name:
		return "Export"
	movement = None
	if frappe.db.has_column("Delivery Order", "commercial_movement"):
		movement = frappe.db.get_value("Delivery Order", do_name, "commercial_movement")
	if (movement or "").strip():
		return movement.strip()
	jo = frappe.db.get_value("Delivery Order", do_name, "job_order")
	if jo and frappe.db.has_column("Job Order", "commercial_movement"):
		movement = frappe.db.get_value("Job Order", jo, "commercial_movement")
	return (movement or "Export").strip()


def _is_import_do(do_name: str) -> bool:
	if not do_name or not frappe.db.exists("Delivery Order", do_name):
		return False
	return resolve_commercial_movement_for_do(do_name) == "Import"


def _pcc_authorized_for_do(do_name: str) -> bool:
	pcc_name = frappe.db.get_value("Delivery Order", do_name, "pre_check_clearance")
	if not pcc_name:
		return False
	return (
		frappe.db.get_value("Pre-Check Clearance", pcc_name, "overall_status") or ""
	).strip() == "Authorized"


def _product_label_from_do(do) -> str | None:
	for row in do.items or []:
		if row.item_name:
			return row.item_name
		if row.item_code:
			return row.item_code
	return None


def ensure_import_grn_for_delivery_order(
	delivery_order: str,
	*,
	pcc_name: str | None = None,
	raise_on_skip: bool = False,
) -> str | None:
	"""Create or return Import GRN when import DO has authorized pre-check."""
	if not delivery_order:
		if raise_on_skip:
			frappe.throw(_("delivery_order is required"))
		return None
	if not frappe.db.exists("Delivery Order", delivery_order):
		if raise_on_skip:
			frappe.throw(_("Delivery Order {0} not found").format(delivery_order))
		return None
	if not _is_import_do(delivery_order):
		if raise_on_skip:
			frappe.throw(_("Import GRN applies only to Import Delivery Orders."))
		return None
	if not _pcc_authorized_for_do(delivery_order):
		if raise_on_skip:
			frappe.throw(
				_(
					"Pre-Check Clearance must be Authorized (QC and Security both Passed) before creating Import GRN."
				)
			)
		return None

	if not frappe.db.table_exists("Import GRN"):
		if raise_on_skip:
			frappe.throw(_("Import GRN DocType is not installed. Run bench migrate."))
		return None

	existing = frappe.db.get_value("Import GRN", {"delivery_order": delivery_order}, "name")
	if existing:
		_link_grn_on_delivery_order(delivery_order, existing)
		return existing

	do = frappe.get_doc("Delivery Order", delivery_order)
	pcc_name = pcc_name or do.pre_check_clearance
	if not pcc_name:
		if raise_on_skip:
			frappe.throw(_("Link a Pre-Check Clearance to this Delivery Order first."))
		return None

	pcc = frappe.get_doc("Pre-Check Clearance", pcc_name)
	if (pcc.overall_status or "").strip() != "Authorized":
		if raise_on_skip:
			frappe.throw(
				_("Pre-Check Clearance {0} is not Authorized yet.").format(pcc.name)
			)
		return None

	# Keep DO movement aligned for legacy rows.
	if frappe.db.has_column("Delivery Order", "commercial_movement"):
		if (do.commercial_movement or "").strip() != "Import":
			frappe.db.set_value(
				"Delivery Order",
				delivery_order,
				"commercial_movement",
				"Import",
				update_modified=False,
			)

	grn = frappe.new_doc("Import GRN")
	grn.delivery_order = delivery_order
	grn.job_order = do.job_order
	grn.pre_check_clearance = pcc.name
	grn.grn_status = "Pending Approval"
	grn.posting_date = do.posting_date or today()
	grn.commercial_movement = "Import"
	grn.customer = do.customer
	grn.customer_name = do.customer_name
	if hasattr(do, "supplier"):
		grn.supplier = do.supplier
	if hasattr(do, "supplier_name"):
		grn.supplier_name = do.supplier_name
	grn.batch_no = pcc.batch_no
	grn.product = _product_label_from_do(do)
	grn.qc_checked_by = pcc.qc_checked_by
	grn.qc_check_time = pcc.qc_check_time
	grn.security_checked_by = pcc.security_checked_by
	grn.security_check_time = pcc.security_check_time

	if not (do.items or []):
		if raise_on_skip:
			frappe.throw(_("Delivery Order has no line items for Import GRN."))
		return None

	for row in do.items or []:
		grn.append(
			"items",
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"description": row.description,
				"qty": row.qty,
				"uom": row.uom,
			},
		)

	try:
		grn.insert(ignore_permissions=True)
	except Exception:
		if raise_on_skip:
			raise
		frappe.log_error(
			frappe.get_traceback(),
			f"Import GRN insert failed for {delivery_order}",
		)
		return None
	_link_grn_on_delivery_order(delivery_order, grn.name)
	return grn.name


def _link_grn_on_delivery_order(delivery_order: str, grn_name: str) -> None:
	if frappe.db.has_column("Delivery Order", "import_grn"):
		frappe.db.set_value(
			"Delivery Order",
			delivery_order,
			"import_grn",
			grn_name,
			update_modified=False,
		)


def maybe_ensure_import_grn_after_precheck_authorized(
	delivery_order: str | None,
	*,
	pcc_name: str | None = None,
) -> str | None:
	if not delivery_order:
		return None
	try:
		return ensure_import_grn_for_delivery_order(
			delivery_order, pcc_name=pcc_name, raise_on_skip=False
		)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"Import GRN Auto-Create failed for {delivery_order}",
		)
		return None


def create_import_grn_for_delivery_order(
	delivery_order: str,
	*,
	pcc_name: str | None = None,
) -> dict[str, Any]:
	"""Whitelisted entry: create or return Import GRN with explicit errors."""
	grn_name = ensure_import_grn_for_delivery_order(
		delivery_order,
		pcc_name=pcc_name,
		raise_on_skip=True,
	)
	return {
		"success": True,
		"import_grn": grn_name,
		"delivery_order": delivery_order,
		"created": bool(grn_name),
	}


def backfill_missing_import_grns(*, limit: int = 500) -> dict[str, Any]:
	"""Create Import GRNs for authorized import DOs that do not have one yet."""
	if not frappe.db.table_exists("Import GRN"):
		return {"created": [], "errors": [], "count": 0}

	if not frappe.db.has_column("Delivery Order", "commercial_movement"):
		return {"created": [], "errors": [], "count": 0}

	rows = frappe.db.sql(
		"""
		SELECT do.name AS delivery_order, do.pre_check_clearance, do.commercial_movement,
			jo.commercial_movement AS jo_movement
		FROM `tabDelivery Order` do
		INNER JOIN `tabPre-Check Clearance` pcc ON pcc.name = do.pre_check_clearance
		LEFT JOIN `tabJob Order` jo ON jo.name = do.job_order
		WHERE do.docstatus < 2
		  AND pcc.overall_status = 'Authorized'
		  AND NOT EXISTS (
			SELECT 1 FROM `tabImport GRN` grn WHERE grn.delivery_order = do.name
		  )
		  AND (
			IFNULL(do.commercial_movement, '') = 'Import'
			OR IFNULL(jo.commercial_movement, '') = 'Import'
		  )
		ORDER BY do.modified DESC
		LIMIT %(limit)s
		""",
		{"limit": int(limit)},
		as_dict=True,
	)

	created: list[str] = []
	errors: list[dict[str, str]] = []
	for row in rows:
		try:
			name = ensure_import_grn_for_delivery_order(
				row.delivery_order,
				pcc_name=row.pre_check_clearance,
				raise_on_skip=True,
			)
			if name:
				created.append(name)
		except Exception as exc:
			errors.append(
				{
					"delivery_order": row.delivery_order,
					"error": str(exc),
				}
			)
			frappe.log_error(
				frappe.get_traceback(),
				f"Import GRN backfill failed for {row.delivery_order}",
			)

	return {"created": created, "errors": errors, "count": len(created)}


def approve_import_grn(grn_name: str, *, remarks: str | None = None) -> dict[str, Any]:
	"""Approve GRN and push Zoho import receipt."""
	if not grn_name:
		frappe.throw(_("grn_name is required"))

	grn = frappe.get_doc("Import GRN", grn_name)
	if grn.grn_status in _COMPLETED_GRN_STATUSES:
		frappe.throw(_("Import GRN {0} is already {1}.").format(grn.name, grn.grn_status))
	if grn.grn_status == "Cancelled":
		frappe.throw(_("Cannot approve a cancelled Import GRN."))

	if not _pcc_authorized_for_do(grn.delivery_order):
		frappe.throw(
			_("QC and Security pre-check must both be passed before approving GRN.")
		)

	if remarks:
		grn.remarks = remarks

	grn.flags.approving_grn = True
	grn.grn_status = "Approved"
	grn.approved_by = frappe.session.user
	grn.approved_on = now()
	grn.save(ignore_permissions=True)

	zoho_result = _post_zoho_receipt(grn)
	if zoho_result.get("success") or zoho_result.get("stub"):
		grn.grn_status = "Posted"
		receipt_id = zoho_result.get("zoho_receipt_id")
		if receipt_id:
			grn.zoho_import_receipt_id = receipt_id
			if grn.job_order and frappe.db.has_column("Job Order", "zoho_import_receipt_id"):
				frappe.db.set_value(
					"Job Order",
					grn.job_order,
					"zoho_import_receipt_id",
					receipt_id,
					update_modified=False,
				)
		grn.save(ignore_permissions=True)

	return {
		"success": True,
		"import_grn": grn.name,
		"grn_status": grn.grn_status,
		"zoho": zoho_result,
		"is_partial_receipt": bool(grn.is_partial_receipt),
		"pending_qty": flt(grn.pending_qty),
		"receipt_type": grn.receipt_type,
	}


def _post_zoho_receipt(grn) -> dict[str, Any]:
	from apc_operations.shipping.services.zoho_import_receipt_sync_service import (
		push_import_receipt_to_zoho,
	)

	return push_import_receipt_to_zoho(grn.delivery_order)


def get_import_grn_queue(
	*, completed: bool = False, limit: int = 200, backfill: bool = True
) -> list[dict[str, Any]]:
	"""List Import GRNs for the console."""
	if backfill and not completed:
		backfill_missing_import_grns(limit=limit)
	statuses = list(_COMPLETED_GRN_STATUSES) if completed else list(_PENDING_GRN_STATUSES)
	rows = frappe.get_all(
		"Import GRN",
		filters={"grn_status": ["in", statuses], "commercial_movement": "Import"},
		fields=[
			"name",
			"delivery_order",
			"job_order",
			"grn_status",
			"customer_name",
			"supplier_name",
			"product",
			"batch_no",
			"posting_date",
			"modified",
			"qc_check_time",
			"security_check_time",
		],
		order_by="modified desc",
		limit=limit,
	)
	out = []
	for row in rows:
		jo_number = None
		if row.job_order:
			jo_number = frappe.db.get_value(
				"Job Order", row.job_order, "job_order_number"
			) or row.job_order
		out.append(
			{
				**row,
				"import_grn": row.name,
				"job_order_number": jo_number,
				"grn_status_tone": _grn_status_tone(row.grn_status),
				"is_partial_receipt": bool(
					frappe.db.get_value("Import GRN", row.name, "is_partial_receipt")
				),
				"receipt_type": frappe.db.get_value("Import GRN", row.name, "receipt_type"),
			}
		)
	return out


def get_import_grn_console_counts(*, backfill: bool = True) -> dict[str, int]:
	if backfill:
		backfill_missing_import_grns(limit=200)
	pending = frappe.db.count(
		"Import GRN",
		{"grn_status": ["in", list(_PENDING_GRN_STATUSES)], "commercial_movement": "Import"},
	)
	completed = frappe.db.count(
		"Import GRN",
		{"grn_status": ["in", list(_COMPLETED_GRN_STATUSES)], "commercial_movement": "Import"},
	)
	return {"pending": pending, "completed": completed}


def get_import_grn_detail(grn_name: str) -> dict[str, Any]:
	if not grn_name:
		frappe.throw(_("grn_name is required"))
	grn = frappe.get_doc("Import GRN", grn_name)
	jo_number = None
	if grn.job_order:
		jo_number = (
			frappe.db.get_value("Job Order", grn.job_order, "job_order_number") or grn.job_order
		)

	handoff = {}
	if grn.job_order:
		from apc_operations.shipping.services.import_handoff_service import (
			get_import_handoff_status,
		)

		try:
			handoff = get_import_handoff_status(grn.job_order) or {}
		except Exception:
			handoff = {}

	return {
		"import_grn": grn.name,
		"name": grn.name,
		"delivery_order": grn.delivery_order,
		"job_order": grn.job_order,
		"job_order_number": jo_number,
		"grn_status": grn.grn_status,
		"grn_status_tone": _grn_status_tone(grn.grn_status),
		"customer_name": grn.customer_name,
		"supplier_name": grn.supplier_name,
		"product": grn.product,
		"batch_no": grn.batch_no,
		"posting_date": grn.posting_date,
		"qc_checked_by": grn.qc_checked_by,
		"qc_check_time": grn.qc_check_time,
		"security_checked_by": grn.security_checked_by,
		"security_check_time": grn.security_check_time,
		"approved_by": grn.approved_by,
		"approved_on": grn.approved_on,
		"zoho_import_receipt_id": grn.zoho_import_receipt_id,
		"remarks": grn.remarks,
		"total_expected_qty": flt(grn.total_expected_qty),
		"total_arrived_qty": flt(grn.total_arrived_qty),
		"pending_qty": flt(grn.pending_qty),
		"receipt_type": grn.receipt_type,
		"is_partial_receipt": bool(grn.is_partial_receipt),
		"items": [
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"qty": row.qty,
				"expected_qty": row.qty,
				"arrived_qty": flt(row.arrived_qty),
				"uom": row.uom,
			}
			for row in grn.items or []
		],
		"can_approve": grn.grn_status in _PENDING_GRN_STATUSES,
		"can_link_export": bool(handoff.get("can_link_export")),
		"can_create_export": bool(handoff.get("can_create_export")),
		"linked_export_job_order": handoff.get("linked_export_job_order"),
		"read_only": grn.grn_status in _COMPLETED_GRN_STATUSES,
	}


def _grn_status_tone(status: str | None) -> str:
	return {
		"Draft": "neutral",
		"Pending Approval": "warn",
		"Approved": "info",
		"Posted": "success",
		"Cancelled": "danger",
	}.get((status or "").strip(), "neutral")
