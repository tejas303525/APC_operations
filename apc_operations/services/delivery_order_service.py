# Copyright (c) 2026, APC and contributors
"""Delivery Order operational status and console card helpers (Path B)."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt
from apc_operations.services import console_status
from apc_operations.shipping.doctype.gate_pass.gate_pass import (
	_DO_COMMENT_PATTERN,
	find_delivery_order_for_job_order,
)
from apc_operations.shipping.services.dispatch_lifecycle_service import (
	DISPATCH_LIFECYCLE_STATUSES,
	compute_dispatch_lifecycle_status,
)
from apc_operations.services.console_queue_service import (
	attach_delivery_due_fields,
	sort_console_queue,
)

# Legacy Path A pipeline labels (SDDN/LDN derived — kept for fallback display only)
LEGACY_PIPELINE_STATUSES = frozenset(
	{
		"Pending Security",
		"Security In Progress",
		"Ready for Loading",
		"Loading In Progress",
		"Sent to QC",
		"QC In Progress",
		"QC Cleared",
		"Completed",
	}
)

# Path B lifecycle groupings for security console queues
SECURITY_NEW_STATUSES = frozenset({"Draft", "Issued", "Sent to Security", "QC Pre-check Pending"})
SECURITY_PENDING_STATUSES = frozenset(
	{"Truck Arrived", "QC Pre-check Failed", "On Hold"}
)
SECURITY_IN_PROGRESS_STATUSES = frozenset(
	{
		"QC Pre-check Passed",
		"Loading Allowed",
		"Loading Started",
		"Loading Completed",
		"Weighment Completed",
		"Weight Variance Approval Pending",
		"QC Final Pending",
	}
)
SECURITY_COMPLETED_STATUSES = frozenset(
	{"Delivery Note Generated", "Ready for Gate Out", "Gate Out Completed"}
)
LOADING_BAY_STATUSES = frozenset(
	{
		"Loading Allowed",
		"Loading Started",
		"Loading Completed",
		"Weighment Completed",
		"Weight Variance Approval Pending",
		"QC Final Pending",
	}
)
GATE_READY_STATUSES = frozenset({"Ready for Gate Out"})
TERMINAL_CONSOLE_STATUSES = frozenset({"Gate Out Completed", "Cancelled"})

# SDDN status groupings (raw DB values)
SDDN_PENDING = frozenset(
	{"Draft", "Pending Review", "Pending Verification", "Sent to Security"}
)
SDDN_VERIFIED = frozenset(
	{"Verified", "Approved", "LDN Created", "Sent to QC", "Completed"}
)

OPERATIONAL_STATUSES = (
	"Pending Security",
	"Security In Progress",
	"Ready for Loading",
	"Loading In Progress",
	"Sent to QC",
	"QC In Progress",
	"QC Cleared",
	"Completed",
	"Cancelled",
)

_DO_FIELDS = [
	"name",
	"customer",
	"customer_name",
	"commercial_movement",
	"supplier",
	"supplier_name",
	"job_order",
	"job_order_number",
	"status",
	"docstatus",
	"posting_date",
	"modified",
	"operational_status",
	"do_status",
	"loading_delivery_note",
]


def find_delivery_order_for_job_order_primary(job_order: str | None) -> str | None:
	"""Prefer direct ``job_order`` link; fall back to comment/remarks heuristics."""
	if not job_order:
		return None
	if frappe.db.has_column("Delivery Order", "job_order"):
		name = frappe.db.get_value(
			"Delivery Order",
			{"job_order": job_order, "docstatus": ["!=", 2]},
			"name",
			order_by="modified desc",
		)
		if name:
			return name
	return find_delivery_order_for_job_order(job_order)


def find_delivery_order_for_transport_schedule(
	transport_schedule: str | None,
) -> str | None:
	"""Return the Delivery Order linked to a transport leg (1:1 with its SDDN)."""
	if not transport_schedule:
		return None

	if frappe.db.has_column("Delivery Order", "transport_schedule"):
		do_name = frappe.db.get_value(
			"Delivery Order",
			{"transport_schedule": transport_schedule, "docstatus": ["!=", 2]},
			"name",
			order_by="modified desc",
		)
		if do_name:
			return do_name

	sddn = frappe.db.get_value(
		"Transport Schedule", transport_schedule, "security_draft_delivery_note"
	)
	if not sddn:
		sddn = frappe.db.get_value(
			"Security Draft Delivery Note",
			{"transport_schedule": transport_schedule},
			"name",
			order_by="modified desc",
		)
	if sddn:
		ldn_do = frappe.db.get_value(
			"Loading Delivery Note",
			{
				"security_draft_delivery_note": sddn,
				"transport_delivery_order": ["is", "set"],
			},
			"transport_delivery_order",
			order_by="modified desc",
		)
		if ldn_do:
			return ldn_do

	# Follow-up DOs store the transport leg in remarks.
	jo = frappe.db.get_value("Transport Schedule", transport_schedule, "job_order")
	if jo:
		rows = frappe.get_all(
			"Delivery Order",
			filters={"job_order": jo, "docstatus": ["!=", 2]},
			fields=["name", "remarks"],
			order_by="creation desc",
		)
		for row in rows:
			remarks = row.get("remarks") or ""
			if f"Transport: {transport_schedule}" in remarks:
				return row["name"]
	return None


def find_open_delivery_order_for_transport_schedule(
	transport_schedule: str | None,
) -> str | None:
	"""Return a non-terminal Delivery Order for this transport leg, if any."""
	do_name = find_delivery_order_for_transport_schedule(transport_schedule)
	if not do_name:
		return None

	from apc_operations.shipping.services.dispatch_lifecycle_service import (
		TERMINAL_LIFECYCLE_STATUSES,
	)

	status = (
		frappe.db.get_value("Delivery Order", do_name, "operational_status") or ""
	).strip()
	if status in TERMINAL_LIFECYCLE_STATUSES:
		return None
	return do_name


def find_open_delivery_order_for_job_order(job_order: str | None) -> str | None:
	"""Return the latest Delivery Order for a Job Order that still blocks a
	follow-up leg, if any.

	A prior DO stops blocking once it reaches a terminal status OR once its
	dispatch is confirmed (``Delivery Note Generated`` onward) - stock is
	already deducted at that point, so the next trip doesn't need to wait
	for the truck to physically gate out.
	"""
	if not job_order or not frappe.db.has_column("Delivery Order", "job_order"):
		return None

	from apc_operations.shipping.services.dispatch_lifecycle_service import (
		DISPATCH_CONFIRMED_STATUSES,
		TERMINAL_LIFECYCLE_STATUSES,
	)

	non_blocking = TERMINAL_LIFECYCLE_STATUSES | DISPATCH_CONFIRMED_STATUSES

	rows = frappe.get_all(
		"Delivery Order",
		filters={"job_order": job_order, "docstatus": ["!=", 2]},
		fields=["name", "operational_status"],
		order_by="modified desc",
	)
	for row in rows:
		status = (row.get("operational_status") or "").strip()
		if status not in non_blocking:
			return row["name"]
	return None


def link_delivery_order_to_job_order(
	do_name: str,
	job_order: str | None,
	transport_schedule: str | None = None,
	*,
	update_modified: bool = False,
) -> None:
	"""Set Job Order and transport leg on an existing Delivery Order."""
	if not do_name or not frappe.db.exists("Delivery Order", do_name):
		return
	payload: dict[str, Any] = {}
	if job_order and frappe.db.has_column("Delivery Order", "job_order"):
		payload["job_order"] = job_order
	if transport_schedule and frappe.db.has_column("Delivery Order", "transport_schedule"):
		current_ts = frappe.db.get_value("Delivery Order", do_name, "transport_schedule")
		if not current_ts or current_ts == transport_schedule:
			payload["transport_schedule"] = transport_schedule
	if payload:
		frappe.db.set_value(
			"Delivery Order", do_name, payload, update_modified=update_modified
		)


def link_child_documents_on_do(
	do_name: str,
	*,
	sddn: str | None = None,
	ldn: str | None = None,
	update_modified: bool = False,
) -> None:
	"""No-op: SDDN/LDN are resolved via Job Order, not stored on Delivery Order."""
	return


def resolve_do_for_sddn(sddn_name: str) -> str | None:
	row = frappe.db.get_value(
		"Security Draft Delivery Note",
		sddn_name,
		["job_order", "transport_schedule"],
		as_dict=True,
	)
	if not row:
		return None
	if row.get("transport_schedule"):
		do = find_delivery_order_for_transport_schedule(row["transport_schedule"])
		if do:
			link_delivery_order_to_job_order(
				do,
				row.get("job_order"),
				row["transport_schedule"],
				update_modified=False,
			)
			return do
	return None


def resolve_do_for_ldn(ldn_name: str) -> str | None:
	ldn = frappe.db.get_value(
		"Loading Delivery Note",
		ldn_name,
		["job_order", "security_draft_delivery_note", "transport_delivery_order"],
		as_dict=True,
	)
	if not ldn:
		return None
	if ldn.get("transport_delivery_order"):
		return ldn["transport_delivery_order"]
	if ldn.get("security_draft_delivery_note"):
		do = resolve_do_for_sddn(ldn["security_draft_delivery_note"])
		if do:
			return do
	if ldn.get("job_order"):
		return find_delivery_order_for_job_order_primary(ldn["job_order"])
	return None


def compute_operational_status(
	do_name: str,
	*,
	sddn_status: str | None = None,
	ldn_status: str | None = None,
	ldn_qc_status: str | None = None,
	shipping_status: str | None = None,
	docstatus: int | None = None,
) -> str:
	"""Derive console operational_status from linked documents."""
	if docstatus == 2 or shipping_status == "Cancelled":
		return "Cancelled"
	if shipping_status == "Delivered":
		return "Completed"

	if do_name and not (sddn_status or ldn_status):
		jo = frappe.db.get_value("Delivery Order", do_name, "job_order")
		if jo:
			sddn, ldn = _linked_docs_for_job_order(jo, do_name)
			if sddn and not sddn_status:
				sddn_status = frappe.db.get_value(
					"Security Draft Delivery Note", sddn, "security_status"
				)
			if ldn and not ldn_status:
				ldn_row = frappe.db.get_value(
					"Loading Delivery Note",
					ldn,
					["delivery_note_status", "qc_status"],
					as_dict=True,
				)
				if ldn_row:
					ldn_status = ldn_row.get("delivery_note_status")
					ldn_qc_status = ldn_qc_status or ldn_row.get("qc_status")

	if ldn_qc_status == "QC Rejected":
		return "QC In Progress"
	if ldn_qc_status == "QC Cleared" or ldn_status in {
		"QC Cleared",
		"COA Attached",
		"Ready for Receivables",
		"Reported to Receivables",
		"Loading Completed",
		"Completed",
	}:
		return "QC Cleared"
	if ldn_status in {"Pending QC", "Sent to QC"} or sddn_status == "Sent to QC":
		return "Sent to QC" if not ldn_qc_status or ldn_qc_status == "Pending QC" else "QC In Progress"
	if ldn_status and ldn_status not in {"Draft", "Cancelled"}:
		return "Loading In Progress"
	if sddn_status in SDDN_VERIFIED:
		return "Ready for Loading"
	if sddn_status in SDDN_PENDING or sddn_status:
		return "Security In Progress"
	return "Pending Security"


def resolve_console_operational_status(
	do_name: str,
	do_row: dict[str, Any] | None = None,
	*,
	sddn_status: str | None = None,
	ldn_status: str | None = None,
	ldn_qc_status: str | None = None,
	shipping_status: str | None = None,
	docstatus: int | None = None,
) -> str:
	"""Recompute lifecycle for consoles; fall back to legacy pipeline labels."""
	if do_name and frappe.db.exists("Delivery Order", do_name):
		computed = compute_dispatch_lifecycle_status(do_name)
		if computed:
			return computed

	persisted = ((do_row or {}).get("operational_status") or "").strip()
	if persisted in DISPATCH_LIFECYCLE_STATUSES:
		return persisted

	return compute_operational_status(
		do_name,
		sddn_status=sddn_status,
		ldn_status=ldn_status,
		ldn_qc_status=ldn_qc_status,
		shipping_status=shipping_status,
		docstatus=docstatus,
	)


def _linked_docs_for_job_order(
	job_order: str | None,
	do_name: str | None = None,
) -> tuple[str | None, str | None]:
	if not job_order:
		return None, None
	sddn = frappe.db.get_value(
		"Security Draft Delivery Note",
		{"job_order": job_order},
		"name",
		order_by="modified desc",
	)
	ldn = None
	if do_name:
		ldn = frappe.db.get_value("Delivery Order", do_name, "loading_delivery_note")
	if not ldn and job_order:
		ldn = frappe.db.get_value(
			"Loading Delivery Note",
			{"job_order": job_order, "dispatch_confirmed": 0},
			"name",
			order_by="modified desc",
		)
	if not ldn and sddn:
		ldn = frappe.db.get_value(
			"Loading Delivery Note",
			{"security_draft_delivery_note": sddn},
			"name",
		)
	if not ldn and do_name:
		ldn = frappe.db.get_value(
			"Loading Delivery Note",
			{"transport_delivery_order": do_name},
			"name",
			order_by="modified desc",
		)
	return sddn, ldn


def _product_context_from_job_order(job_order: str | None) -> dict[str, Any]:
	"""Product, quantity, and UOM from Job Order Item rows (commercial source of truth)."""
	result: dict[str, Any] = {
		"product": None,
		"quantity_to_load": None,
		"uom": None,
	}
	if not job_order or not frappe.db.exists("Job Order", job_order):
		return result

	rows = frappe.get_all(
		"Job Order Item",
		filters={"parent": job_order},
		fields=["item", "item_name", "quantity", "net_weight", "uom"],
		order_by="idx asc",
		limit=10,
	)
	if not rows:
		return result

	labels: list[str] = []
	total_qty = 0.0
	total_net = 0.0
	uom = None
	for row in rows:
		label = (row.get("item_name") or row.get("item") or "").strip()
		if label:
			labels.append(label)
		total_qty += flt(row.get("quantity"))
		total_net += flt(row.get("net_weight"))
		if not uom and row.get("uom"):
			uom = row.get("uom")

	if labels:
		result["product"] = ", ".join(labels)
	if total_qty > 0:
		result["quantity_to_load"] = total_qty
	elif total_net > 0:
		result["quantity_to_load"] = total_net
	result["uom"] = uom
	return result


def sync_delivery_order_operational_status(
	do_name: str,
	*,
	update_modified: bool = False,
) -> str | None:
	"""Persist lifecycle status on the Delivery Order."""
	if not do_name or not frappe.db.exists("Delivery Order", do_name):
		return None
	from apc_operations.shipping.services.dispatch_lifecycle_service import (
		sync_dispatch_lifecycle_status,
	)

	return sync_dispatch_lifecycle_status(do_name, update_modified=update_modified)


def sync_from_sddn(sddn_name: str) -> None:
	do = resolve_do_for_sddn(sddn_name)
	if do:
		sync_delivery_order_operational_status(do, update_modified=False)


def sync_from_ldn(ldn_name: str) -> None:
	do = resolve_do_for_ldn(ldn_name)
	if do:
		from apc_operations.shipping.services.dispatch_flow_service import (
			ensure_ldn_do_link,
			sync_ldn_batch_from_qc_report,
		)

		ensure_ldn_do_link(ldn_name=ldn_name, do_name=do, update_modified=False)
		sync_ldn_batch_from_qc_report(ldn_name)
		sync_delivery_order_operational_status(do, update_modified=False)


def sync_from_qcr(qcr_name: str) -> None:
	ldn = frappe.db.get_value("QC Report Request", qcr_name, "loading_delivery_note")
	if ldn:
		sync_from_ldn(ldn)


def resolve_transport_context_for_do(do_name: str | None) -> dict[str, Any]:
	"""Truck, driver, product, and qty for console views.

	Product priority: Security Inspection (if set) → Job Order items → Delivery Order items → LDN.
	"""
	out: dict[str, Any] = {
		"truck_number": None,
		"driver_name": None,
		"driver_contact": None,
		"product": None,
		"quantity_to_load": None,
		"uom": None,
		"transport_schedule": None,
	}
	if not do_name or not frappe.db.exists("Delivery Order", do_name):
		return out

	do = frappe.db.get_value(
		"Delivery Order",
		do_name,
		["job_order", "planned_quantity", "total_qty"],
		as_dict=True,
	)
	if not do:
		return out

	ts_name = None
	if do.get("job_order"):
		ts_name = frappe.db.get_value("Job Order", do.job_order, "transport_schedule")

	sddn, ldn = _linked_docs_for_job_order(do.get("job_order"), do_name)
	if not ts_name and sddn:
		ts_name = frappe.db.get_value(
			"Security Draft Delivery Note", sddn, "transport_schedule"
		)
	out["transport_schedule"] = ts_name

	if ts_name:
		ts = frappe.db.get_value(
			"Transport Schedule",
			ts_name,
			["assigned_vehicle", "assigned_driver", "driver_phone"],
			as_dict=True,
		)
		if ts:
			if ts.get("assigned_vehicle"):
				out["truck_number"] = (
					frappe.db.get_value("Vehicle", ts["assigned_vehicle"], "license_plate")
					or ts["assigned_vehicle"]
				)
			if ts.get("assigned_driver"):
				out["driver_name"] = (
					frappe.db.get_value("Driver", ts["assigned_driver"], "full_name")
					or ts["assigned_driver"]
				)
			out["driver_contact"] = ts.get("driver_phone")

	from apc_operations.shipping.services.dispatch_validation_service import (
		resolve_security_inspection_for_do,
	)

	si_name = resolve_security_inspection_for_do(do_name)
	if si_name:
		si = frappe.db.get_value(
			"Security Inspection",
			si_name,
			[
				"vehicle_number",
				"driver_name",
				"driver_phone",
				"quantity",
				"uom",
				"material_description",
			],
			as_dict=True,
		)
		if si:
			out["truck_number"] = si.get("vehicle_number") or out["truck_number"]
			out["driver_name"] = si.get("driver_name") or out["driver_name"]
			out["driver_contact"] = si.get("driver_phone") or out["driver_contact"]
			if si.get("material_description"):
				out["product"] = si["material_description"]
			if flt(si.get("quantity")) > 0:
				out["quantity_to_load"] = flt(si["quantity"])
			if si.get("uom"):
				out["uom"] = si["uom"]

	if do.get("job_order"):
		jo_ctx = _product_context_from_job_order(do["job_order"])
		if jo_ctx.get("product"):
			out["product"] = jo_ctx["product"]
		if jo_ctx.get("quantity_to_load") and not out.get("quantity_to_load"):
			out["quantity_to_load"] = jo_ctx["quantity_to_load"]
		if jo_ctx.get("uom") and not out.get("uom"):
			out["uom"] = jo_ctx["uom"]

	items = frappe.get_all(
		"Delivery Order Item",
		filters={"parent": do_name},
		fields=["item_code", "item_name", "qty", "uom"],
		order_by="idx asc",
		limit=5,
	)
	if items and not out.get("product"):
		out["product"] = ", ".join(
			(r.get("item_name") or r.get("item_code") or "") for r in items if r
		)
	if items and not out.get("quantity_to_load"):
		out["quantity_to_load"] = sum(flt(r.get("qty")) for r in items)
	if items and not out.get("uom"):
		out["uom"] = items[0].get("uom")

	if not out.get("quantity_to_load"):
		out["quantity_to_load"] = flt(do.get("planned_quantity")) or flt(do.get("total_qty"))

	if ldn:
		ldn_row = frappe.db.get_value(
			"Loading Delivery Note",
			ldn,
			["quantity", "planned_quantity", "uom", "material_description"],
			as_dict=True,
		)
		if ldn_row:
			if ldn_row.get("material_description") and not out.get("product"):
				out["product"] = ldn_row["material_description"]
			if not out.get("quantity_to_load"):
				out["quantity_to_load"] = flt(ldn_row.get("planned_quantity")) or flt(
					ldn_row.get("quantity")
				)
			out["uom"] = out.get("uom") or ldn_row.get("uom")

	return out


def _enrich_do_row(do_row: dict[str, Any]) -> dict[str, Any]:
	"""Build a console card payload from a Delivery Order row."""
	do_name = do_row.get("name")
	jo = do_row.get("job_order")
	sddn, ldn = _linked_docs_for_job_order(jo, do_name)

	sddn_status_raw = None
	if sddn:
		sddn_status_raw = frappe.db.get_value(
			"Security Draft Delivery Note", sddn, "security_status"
		)

	ldn_status_raw = None
	ldn_qc_status = None
	if ldn:
		ldn_row = frappe.db.get_value(
			"Loading Delivery Note",
			ldn,
			["delivery_note_status", "qc_status", "qc_report_request"],
			as_dict=True,
		)
		if ldn_row:
			ldn_status_raw = ldn_row.get("delivery_note_status")
			ldn_qc_status = ldn_row.get("qc_status")

	operational = resolve_console_operational_status(
		do_name,
		do_row,
		sddn_status=sddn_status_raw,
		ldn_status=ldn_status_raw,
		ldn_qc_status=ldn_qc_status,
		shipping_status=do_row.get("status"),
		docstatus=do_row.get("docstatus"),
	)
	legacy_pipeline = None
	if operational in LEGACY_PIPELINE_STATUSES:
		legacy_pipeline = operational

	from apc_operations.shipping.services.delivery_order_sync_service import (
		terms_of_delivery_for_delivery_order,
	)

	terms_of_delivery = terms_of_delivery_for_delivery_order(
		do_name,
		job_order=jo,
		stored_terms=do_row.get("terms_of_delivery"),
	)

	card = {
		"name": do_name,
		"delivery_order": do_name,
		"job_order": jo,
		"job_order_number": do_row.get("job_order_number")
		or (frappe.db.get_value("Job Order", jo, "job_order_number") if jo else None),
		"terms_of_delivery": terms_of_delivery,
		"customer": do_row.get("customer"),
		"customer_name": do_row.get("customer_name"),
		"commercial_movement": do_row.get("commercial_movement")
		or (
			frappe.db.get_value("Job Order", jo, "commercial_movement") if jo else None
		),
		"supplier_name": do_row.get("supplier_name"),
		"operational_status": operational,
		"operational_status_tone": operational_status_tone(operational),
		"legacy_pipeline_status": legacy_pipeline,
		"do_status": do_row.get("do_status"),
		"do_shipping_status": do_row.get("status"),
		"do_shipping_status_label": console_status.do_display_label(do_row),
		"do_shipping_status_tone": console_status.do_status_tone(
			console_status.do_display_label(do_row)
		),
		"sddn": sddn,
		"sddn_status": console_status.sddn_display_label(sddn_status_raw),
		"sddn_status_tone": console_status.sddn_status_tone(sddn_status_raw),
		"raw_sddn_status": sddn_status_raw,
		"loading_delivery_note": ldn,
		"ldn": ldn,
		"ldn_status": console_status.ldn_display_label(ldn_status_raw),
		"ldn_status_tone": console_status.ldn_status_tone(ldn_status_raw),
		"qc_status": ldn_qc_status,
		"qc_status_tone": console_status.qc_status_tone(ldn_qc_status),
		"posting_date": do_row.get("posting_date"),
		"modified": do_row.get("modified"),
		**resolve_transport_context_for_do(do_name),
	}
	return attach_delivery_due_fields(card)


def operational_status_tone(status: str | None) -> str:
	lifecycle_tones = {
		"Draft": "neutral",
		"Issued": "neutral",
		"Sent to Security": "neutral",
		"Truck Arrived": "info",
		"QC Pre-check Pending": "warn",
		"QC Pre-check Passed": "info",
		"QC Pre-check Failed": "danger",
		"Loading Allowed": "info",
		"Loading Started": "info",
		"Loading Completed": "info",
		"Weighment Completed": "info",
		"Weight Variance Approval Pending": "warn",
		"QC Final Pending": "warn",
		"Delivery Note Generated": "success",
		"Ready for Gate Out": "success",
		"Gate Out Completed": "success",
		"On Hold": "danger",
		"Cancelled": "danger",
	}
	if status in lifecycle_tones:
		return lifecycle_tones[status]
	return {
		"Pending Security": "neutral",
		"Security In Progress": "warn",
		"Ready for Loading": "info",
		"Loading In Progress": "info",
		"Sent to QC": "info",
		"QC In Progress": "warn",
		"QC Cleared": "success",
		"Completed": "success",
		"Cancelled": "danger",
	}.get(status or "", "neutral")


def _card_in_lifecycle_group(card: dict[str, Any], group: frozenset[str]) -> bool:
	op = (card.get("operational_status") or "").strip()
	return op in group


def _card_matches_legacy(card: dict[str, Any], legacy_labels: frozenset[str]) -> bool:
	op = (card.get("operational_status") or "").strip()
	return op in legacy_labels


def _list_delivery_orders(
	filters: dict[str, Any] | list | None = None,
	*,
	limit: int = 400,
) -> list[dict[str, Any]]:
	if not frappe.db.has_column("Delivery Order", "job_order"):
		return []
	rows = frappe.get_all(
		"Delivery Order",
		filters=filters or {"docstatus": ["!=", 2]},
		fields=_DO_FIELDS,
		order_by="modified desc",
		limit=limit,
	)
	return [_enrich_do_row(r) for r in rows]


def _sort_do_console_queue(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
	return sort_console_queue(cards)


def _ldn_dispatch_confirmed(ldn_name: str | None) -> bool:
	if not ldn_name:
		return False
	return bool(frappe.db.get_value("Loading Delivery Note", ldn_name, "dispatch_confirmed"))


def _ldn_fully_confirmed(ldn_name: str | None) -> bool:
	"""True when dispatch was confirmed with QC + security sign-off."""
	if not ldn_name:
		return False
	row = frappe.db.get_value(
		"Loading Delivery Note",
		ldn_name,
		["dispatch_confirmed", "final_qc_clearance", "qc_manager_approved", "security_final_check"],
		as_dict=True,
	)
	if not row or not row.get("dispatch_confirmed"):
		return False
	return bool(
		row.get("final_qc_clearance")
		and row.get("qc_manager_approved")
		and row.get("security_final_check")
	)


def get_security_new_dos() -> list[dict[str, Any]]:
	"""Issued / sent-to-security DOs awaiting SDDN review and Report to QC."""
	out = []
	for card in _list_delivery_orders():
		op = card.get("operational_status")
		ldn = card.get("loading_delivery_note") or card.get("ldn")
		if _ldn_fully_confirmed(ldn):
			continue
		if _card_in_lifecycle_group(card, SECURITY_NEW_STATUSES):
			out.append(card)
		elif op in LEGACY_PIPELINE_STATUSES and op in ("Pending Security", "Security In Progress"):
			if not _ldn_dispatch_confirmed(ldn):
				out.append(card)
		elif (
			not card.get("sddn")
			and op not in TERMINAL_CONSOLE_STATUSES
			and not _ldn_dispatch_confirmed(ldn)
		):
			out.append(card)
	return _sort_do_console_queue(out)


def get_security_pending_dos() -> list[dict[str, Any]]:
	"""Truck on site awaiting QC pre-check / security clearance."""
	return _sort_do_console_queue(
		[
		c
		for c in _list_delivery_orders()
		if _card_in_lifecycle_group(c, SECURITY_PENDING_STATUSES)
		or (
			_card_matches_legacy(c, {"Security In Progress", "Pending Security"})
			and c.get("raw_sddn_status") in SDDN_PENDING
		)
	]
	)


def get_security_in_progress_dos() -> list[dict[str, Any]]:
	"""Loading, weighment, and QC final stages before DN generation."""
	return _sort_do_console_queue(
		[
		c
		for c in _list_delivery_orders()
		if _card_in_lifecycle_group(c, SECURITY_IN_PROGRESS_STATUSES)
		or (
			_card_in_lifecycle_group(c, {"QC Pre-check Pending"})
			and c.get("loading_delivery_note")
		)
		or _card_matches_legacy(
			c,
			{"Ready for Loading", "Loading In Progress", "Sent to QC", "QC In Progress"},
		)
	]
	)


def get_security_completed_dos() -> list[dict[str, Any]]:
	"""Dispatch confirmed with QC + security sign-off, or gate out."""
	out = []
	for c in _list_delivery_orders():
		ldn = c.get("loading_delivery_note") or c.get("ldn")
		if _ldn_fully_confirmed(ldn):
			out.append(c)
			continue
		if _card_in_lifecycle_group(c, SECURITY_COMPLETED_STATUSES):
			out.append(c)
		elif _card_matches_legacy(c, {"QC Cleared", "Completed"}):
			out.append(c)
	return _sort_do_console_queue(out)


def _pcc_for_do(do_name: str) -> dict[str, Any] | None:
	"""Pre-Check Clearance snapshot for a Delivery Order, if linked."""
	if not do_name:
		return None
	pcc_name = frappe.db.get_value("Delivery Order", do_name, "pre_check_clearance")
	if not pcc_name:
		return None
	return frappe.db.get_value(
		"Pre-Check Clearance",
		pcc_name,
		[
			"name",
			"qc_status",
			"qc_pre_check_status",
			"security_status",
			"overall_status",
		],
		as_dict=True,
	)


def do_awaiting_qc_precheck(card: dict[str, Any]) -> bool:
	"""True when the DO still belongs on QC Console → New (QC pre-check not completed)."""
	do_name = card.get("delivery_order") or card.get("name")
	if not do_name:
		return True
	pcc = _pcc_for_do(do_name)
	if not pcc:
		return True
	if (pcc.get("qc_status") or "").strip() == "Passed":
		return False
	if (pcc.get("qc_pre_check_status") or "").strip() == "Passed":
		return False
	return True


def do_qc_precheck_passed_pending_followup(card: dict[str, Any]) -> bool:
	"""True when QC pre-check passed but security, LDN QC, or import handoff remains."""
	do_name = card.get("delivery_order") or card.get("name")
	if not do_name:
		return False
	pcc = _pcc_for_do(do_name)
	if not pcc or (pcc.get("qc_status") or "").strip() != "Passed":
		return False

	if (pcc.get("overall_status") or "").strip() != "Authorized":
		return True

	ldn = card.get("loading_delivery_note") or card.get("ldn")
	if ldn and not _ldn_fully_confirmed(ldn):
		return True

	movement = (card.get("commercial_movement") or "").strip()
	if movement == "Import":
		# Once the Import GRN exists, QC's own work on this DO is done -
		# whether it also needs linking to a downstream re-export Job Order
		# is a separate handoff concern (surfaced elsewhere as a reminder),
		# not something that should keep this DO stuck in "Pending" forever
		# for a plain receipt that was never going to have one.
		if not frappe.db.exists("Import GRN", {"delivery_order": do_name}):
			return True
	return False


def get_qc_new_dos() -> list[dict[str, Any]]:
	"""DOs reported to QC — awaiting QC intake (mirrors Security after Report to QC)."""
	out = []
	for card in _list_delivery_orders():
		if not do_awaiting_qc_precheck(card):
			continue
		op = card.get("operational_status")
		if op == "QC Pre-check Pending":
			out.append(card)
			continue
		if _card_matches_legacy(card, {"Sent to QC"}):
			out.append(card)
			continue

		if (card.get("commercial_movement") or "").strip() == "Import":
			# Import has no physical loading-bay Security Inspection step -
			# QC and Security both act independently, directly off the DO's
			# Pre-Check Clearance, the moment the DO is issued (unlike
			# Outward, which requires Security's checklist to report the
			# truck to QC first). Gating on an SI record here would mean an
			# Import DO never surfaces to QC at all.
			ldn = card.get("loading_delivery_note") or card.get("ldn")
			if op not in ("Gate Out Completed", "Cancelled", "QC Pre-check Failed") and not _ldn_fully_confirmed(ldn):
				out.append(card)
			continue

		jo = card.get("job_order")
		if not jo:
			continue
		si_status = frappe.db.get_value(
			"Security Inspection",
			{"job_order": jo, "docstatus": ["!=", 2]},
			"security_status",
			order_by="modified desc",
		)
		if si_status == "Reported to QC" and not _ldn_fully_confirmed(
			card.get("loading_delivery_note") or card.get("ldn")
		):
			out.append(card)
	return _sort_do_console_queue(out)


def get_qc_pending_dos() -> list[dict[str, Any]]:
	"""DOs with open QC work on LDN (loading, batch, COA, final QC)."""
	seen: set[str] = set()
	out = []
	for card in _list_delivery_orders():
		do_name = card.get("delivery_order") or card.get("name")
		if do_qc_precheck_passed_pending_followup(card) and do_name and do_name not in seen:
			seen.add(do_name)
			out.append(card)
			continue
		op = card.get("operational_status")
		if op in SECURITY_IN_PROGRESS_STATUSES or op in {
			"QC Final Pending",
			"Weight Variance Approval Pending",
			"QC Pre-check Passed",
		}:
			ldn = card.get("loading_delivery_note") or card.get("ldn")
			if ldn and not _ldn_fully_confirmed(ldn):
				if do_name and do_name in seen:
					continue
				if do_name:
					seen.add(do_name)
				out.append(card)
	return _sort_do_console_queue(out)


def get_qc_completed_dos() -> list[dict[str, Any]]:
	"""DOs with QC-cleared / dispatch-ready LDN."""
	return get_security_completed_dos()


def get_completed_delivery_notes_count() -> int:
	return frappe.db.count(
		"Loading Delivery Note",
		{
			"docstatus": ["!=", 2],
			"dispatch_confirmed": 1,
		},
	)


def get_security_console_counts() -> dict[str, int]:
	return {
		"new": len(get_security_new_dos()),
		"pending": len(get_security_pending_dos()),
		"in_progress": len(get_security_in_progress_dos()),
		"completed": len(get_security_completed_dos()),
		"completed_delivery_notes": get_completed_delivery_notes_count(),
	}


def backfill_delivery_order_links_from_comments() -> int:
	"""Link existing DOs to Job Orders via Comment trail; returns rows updated."""
	if not frappe.db.has_column("Delivery Order", "job_order"):
		return 0
	updated = 0
	rows = frappe.get_all(
		"Comment",
		filters={
			"reference_doctype": "Job Order",
			"comment_type": "Comment",
		},
		fields=["reference_name", "content"],
		order_by="creation desc",
		limit=5000,
	)
	seen_jo: set[str] = set()
	for row in rows:
		jo = row.get("reference_name")
		if not jo or jo in seen_jo:
			continue
		content = (row.get("content") or "").strip()
		m = _DO_COMMENT_PATTERN.search(content)
		if not m:
			continue
		do_name = m.group(1).strip()
		if not frappe.db.exists("Delivery Order", do_name):
			continue
		current = frappe.db.get_value("Delivery Order", do_name, "job_order")
		if current:
			seen_jo.add(jo)
			continue
		ts = frappe.db.get_value(
			"Transport Schedule",
			{"job_order": jo, "transport_status": ["!=", "Cancelled"]},
			"name",
			order_by="modified desc",
		)
		link_delivery_order_to_job_order(do_name, jo, ts, update_modified=False)
		sync_delivery_order_operational_status(do_name, update_modified=False)
		seen_jo.add(jo)
		updated += 1
	return updated
