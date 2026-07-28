"""APC Operations — QC Console API.

Backend for the QC Console (``/app/qc-console``).

This module exposes the eight whitelisted endpoints listed in
``DESIGN_CONCEPT.md`` Section 9.7. All endpoints read or write through
the Security Inspection compatibility layer (a Security Inspection is
resolved or created so the existing
``QC Report Request -> Security Inspection -> SDDN/LDN/Job Order``
chain remains valid).
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from apc_operations.services import console_status
from apc_operations.services.console_queue_service import (
	attach_delivery_due_fields,
	enrich_and_sort_console_queue,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _attach_primary_coa_to_ldn_row(r: dict[str, Any]) -> None:
	"""Fill coa / coa_status / coa_pdf / batch_number from Loading DN Batch or QCR.

	Scans all batch lines (not only the first) so cards and Completed QC
	reflect a linked COA even when the first line has no COA yet.
	"""
	batch_rows = frappe.get_all(
		"Loading DN Batch",
		filters={"parent": r["name"]},
		fields=["batch", "coa", "allocated_qty"],
		order_by="idx asc",
	)
	r["batch_number"] = batch_rows[0].get("batch") if batch_rows else None
	r["coa"] = None
	r["coa_status"] = None
	r["coa_approval_status"] = None
	r["coa_pdf"] = None
	for br in batch_rows:
		coa_name = br.get("coa")
		if not coa_name:
			continue
		coa_doc = frappe.db.get_value(
			"APC COA",
			coa_name,
			["status", "approval_status", "coa_pdf"],
			as_dict=True,
		)
		if coa_doc:
			r["coa"] = coa_name
			r["coa_status"] = coa_doc.get("status")
			r["coa_approval_status"] = coa_doc.get("approval_status")
			r["coa_pdf"] = coa_doc.get("coa_pdf")
			return
	qcr_name = r.get("qc_report_request")
	if qcr_name:
		coa_name = frappe.db.get_value("QC Report Request", qcr_name, "coa")
		if coa_name:
			coa_doc = frappe.db.get_value(
				"APC COA",
				coa_name,
				["status", "approval_status", "coa_pdf"],
				as_dict=True,
			)
			if coa_doc:
				r["coa"] = coa_name
				r["coa_status"] = coa_doc.get("status")
				r["coa_approval_status"] = coa_doc.get("approval_status")
				r["coa_pdf"] = coa_doc.get("coa_pdf")


def _delivery_order_for_ldn_row(ldn: dict[str, Any]) -> str | None:
	from apc_operations.services.delivery_order_service import (
		find_delivery_order_for_job_order_primary,
		resolve_do_for_ldn,
	)

	if ldn.get("delivery_order"):
		return ldn.get("delivery_order")
	do = resolve_do_for_ldn(ldn.get("name"))
	if do:
		return do
	if ldn.get("job_order"):
		return find_delivery_order_for_job_order_primary(ldn.get("job_order"))
	return None


def _ldn_to_card(ldn: dict[str, Any]) -> dict[str, Any]:
	"""Build a QC card payload from a Loading Delivery Note row."""
	qc_status = ldn.get("qc_status") or "Pending QC"
	coa_label = console_status.coa_display_label(
		{
			"status": ldn.get("coa_status"),
			"approval_status": ldn.get("coa_approval_status"),
			"coa_pdf": ldn.get("coa_pdf"),
		}
	)
	delivery_order = _delivery_order_for_ldn_row(ldn)
	card = {
		"name": delivery_order or ldn.get("name"),
		"delivery_order": delivery_order,
		"ldn": ldn.get("name"),
		"loading_delivery_note": ldn.get("name"),
		"sddn": ldn.get("security_draft_delivery_note"),
		"job_order": ldn.get("job_order"),
		"job_order_number": ldn.get("job_order_number"),
		"customer": ldn.get("customer"),
		"customer_name": ldn.get("customer_name"),
		"product": ldn.get("material_description"),
		"batch_number": ldn.get("batch_number"),
		"coa": ldn.get("coa"),
		"coa_pdf": ldn.get("coa_pdf"),
		"quantity": ldn.get("quantity"),
		"uom": ldn.get("uom"),
		"qc_status": qc_status,
		"qc_status_tone": console_status.qc_status_tone(qc_status),
		"coa_status": coa_label,
		"coa_status_tone": console_status.coa_status_tone(coa_label),
		"modified": ldn.get("modified"),
	}
	return attach_delivery_due_fields(card)


def _list_ldns_with_qc(filters: dict[str, Any], qc_filter: str | None = None) -> list[dict[str, Any]]:
	"""Return LDNs joined to (best-effort) batch + COA info."""
	rows = frappe.get_all(
		"Loading Delivery Note",
		filters=filters,
		fields=[
			"name",
			"security_inspection",
			"security_draft_delivery_note",
			"job_order",
			"job_order_number",
			"customer",
			"customer_name",
			"material_description",
			"quantity",
			"uom",
			"container_number",
			"delivery_note_status",
			"qc_status",
			"qc_report_request",
			"qc_cleared_on",
			"sent_to_qc_on",
			"modified",
		],
		order_by="modified desc",
		limit=500,
	)

	# Augment with batch + COA (any line with a COA wins).
	for r in rows:
		_attach_primary_coa_to_ldn_row(r)

	if qc_filter:
		rows = [r for r in rows if (r.get("qc_status") or "Pending QC") == qc_filter]

	return rows


def _resolve_security_inspection_for_ldn(ldn_name: str) -> str | None:
	"""Return Security Inspection name linked to the LDN, creating it if needed.

	This is the thin compatibility layer described in the design:
	consoles surface the SDDN -> LDN -> QC flow, but writes still go via
	Security Inspection so existing automation continues to work.
	"""
	ldn = frappe.db.get_value(
		"Loading Delivery Note",
		ldn_name,
		[
			"security_inspection",
			"security_draft_delivery_note",
			"job_order",
			"customer",
		],
		as_dict=True,
	)
	if not ldn:
		frappe.throw(_("Loading Delivery Note {0} not found").format(ldn_name))

	if ldn.security_inspection:
		return ldn.security_inspection

	# Try to find an existing inspection that points to the same SDDN/JO.
	si_name = None
	if ldn.security_draft_delivery_note:
		si_name = frappe.db.get_value(
			"Security Inspection",
			{"security_draft_delivery_note": ldn.security_draft_delivery_note},
			"name",
		)
	if not si_name and ldn.job_order:
		si_name = frappe.db.get_value(
			"Security Inspection", {"job_order": ldn.job_order}, "name"
		)

	if si_name:
		frappe.db.set_value(
			"Loading Delivery Note", ldn_name, "security_inspection", si_name, update_modified=False
		)
		return si_name

	return None


def _resolve_qc_report_request(ldn_name: str, batch: str | None = None) -> str:
	"""Find or create a QC Report Request for the given LDN.

	Resolves the Security Inspection compatibility layer and creates a
	new ``QC Report Request`` row if one does not already exist for the
	LDN/batch pair.
	"""
	existing_filters: dict[str, Any] = {"loading_delivery_note": ldn_name}
	if batch:
		existing_filters["batch"] = batch
	qcr = frappe.db.get_value("QC Report Request", existing_filters, "name")
	if qcr:
		return qcr

	si_name = _resolve_security_inspection_for_ldn(ldn_name)
	ldn = frappe.get_doc("Loading Delivery Note", ldn_name)

	from apc_operations.services.delivery_order_service import resolve_do_for_ldn

	doc = frappe.new_doc("QC Report Request")
	doc.security_inspection = si_name
	doc.security_draft_delivery_note = ldn.security_draft_delivery_note
	doc.loading_delivery_note = ldn_name
	doc.job_order = ldn.job_order
	do_name = resolve_do_for_ldn(ldn_name)
	if do_name and hasattr(doc, "delivery_order"):
		doc.delivery_order = do_name
	if batch:
		doc.batch = batch
	doc.requested_by = frappe.session.user
	doc.requested_on = now_datetime()
	doc.qc_status = "Pending QC"
	doc.insert(ignore_permissions=True)
	return doc.name


# ---------------------------------------------------------------------------
# List endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_new_qc_items() -> list[dict[str, Any]]:
	"""LDNs sent to QC where no QC Report Request exists yet."""
	rows = _list_ldns_with_qc(
		filters={
			"delivery_note_status": ["in", ["Pending QC", "Sent to QC"]],
		}
	)
	out = []
	for r in rows:
		if r.get("qc_report_request"):
			continue
		out.append(_ldn_to_card(r))
	return enrich_and_sort_console_queue(out)


@frappe.whitelist()
def get_pending_qc_items() -> list[dict[str, Any]]:
	"""LDNs with an open QC Report Request (qc_status == Pending QC)."""
	rows = _list_ldns_with_qc(
		filters={
			"delivery_note_status": [
				"in",
				[
					"Pending QC",
					"Sent to QC",
					"Batch Allocation Pending",
					"Batch Allocated",
				],
			],
		},
	)
	out = []
	for r in rows:
		if not r.get("qc_report_request"):
			continue
		qc_status = frappe.db.get_value("QC Report Request", r["qc_report_request"], "qc_status")
		if (qc_status or "Pending QC") != "Pending QC":
			continue
		r["qc_status"] = "Pending QC"
		out.append(_ldn_to_card(r))
	return enrich_and_sort_console_queue(out)


@frappe.whitelist()
def get_completed_qc_items() -> list[dict[str, Any]]:
	"""LDNs that are QC-complete (``qc_status`` or ``delivery_note_status``)."""
	by_name: dict[str, dict[str, Any]] = {}
	for rows in (
		_list_ldns_with_qc({"qc_status": "QC Cleared"}),
		_list_ldns_with_qc({"delivery_note_status": "QC Cleared"}),
	):
		for r in rows:
			by_name[r["name"]] = r
	return enrich_and_sort_console_queue([_ldn_to_card(by_name[n]) for n in by_name])


@frappe.whitelist()
def get_rejected_qc_items() -> list[dict[str, Any]]:
	rows = _list_ldns_with_qc(filters={"qc_status": "QC Rejected"})
	return enrich_and_sort_console_queue([_ldn_to_card(r) for r in rows])


# ---------------------------------------------------------------------------
# Delivery Order console queues (Path B — DO as card title)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_new_dos_without_qc() -> list[dict[str, Any]]:
	"""DOs reported to QC — awaiting QC intake (Path B console cards)."""
	from apc_operations.services.delivery_order_service import get_qc_new_dos

	return get_qc_new_dos()


@frappe.whitelist()
def get_pending_qc_dos() -> list[dict[str, Any]]:
	"""DOs with LDN open for QC batch / COA / final approval."""
	from apc_operations.services.delivery_order_service import get_qc_pending_dos

	return get_qc_pending_dos()


@frappe.whitelist()
def get_completed_qc_dos() -> list[dict[str, Any]]:
	"""DOs with QC-cleared / dispatch-confirmed LDN."""
	from apc_operations.services.delivery_order_service import get_qc_completed_dos

	return get_qc_completed_dos()


@frappe.whitelist()
def get_rejected_qc_dos() -> list[dict[str, Any]]:
	return get_rejected_qc_items()


@frappe.whitelist()
def get_qc_console_counts() -> dict[str, int]:
	from apc_operations.services.delivery_order_service import (
		get_qc_completed_dos,
		get_qc_new_dos,
		get_qc_pending_dos,
	)

	return {
		"new": len(get_qc_new_dos()),
		"pending": len(get_qc_pending_dos()),
		"completed": len(get_qc_completed_dos()),
		"rejected": len(get_rejected_qc_items()),
	}


@frappe.whitelist()
def get_qc_do_detail(delivery_order: str) -> dict[str, Any]:
	"""DO-centric detail for QC console (reuses Security DO aggregate + pre-check)."""
	from apc_operations.security.api import get_security_do_detail
	from apc_operations.shipping.doctype.delivery_order.delivery_order import DeliveryOrder

	if not delivery_order:
		frappe.throw(_("delivery_order is required"))

	do = frappe.get_doc("Delivery Order", delivery_order)
	if isinstance(do, DeliveryOrder):
		do._ensure_pre_check_clearance()

	card = get_security_do_detail(delivery_order)
	pcc_name = card.get("pre_check_clearance") or frappe.db.get_value(
		"Delivery Order", delivery_order, "pre_check_clearance"
	)
	card["pre_check_clearance"] = pcc_name
	if pcc_name and frappe.db.exists("Pre-Check Clearance", pcc_name):
		pcc = frappe.db.get_value(
			"Pre-Check Clearance",
			pcc_name,
			[
				"name",
				"qc_status",
				"qc_pre_check_status",
				"security_status",
				"overall_status",
				"product_confirmed",
				"batch_no",
			],
			as_dict=True,
		)
		if pcc:
			card.update(
				{
					"pcc_qc_status": pcc.qc_status,
					"pcc_qc_pre_check_status": pcc.qc_pre_check_status,
					"pcc_security_status": pcc.security_status,
					"pcc_overall_status": pcc.overall_status,
					"pcc_batch_no": pcc.batch_no,
				}
			)
			card["can_pass_precheck"] = (
				pcc.overall_status != "Authorized" and pcc.qc_status != "Passed"
			)
			card["can_fail_precheck"] = pcc.overall_status != "Authorized"
	else:
		card["can_pass_precheck"] = False
		card["can_fail_precheck"] = False

	if pcc_name and frappe.db.exists("Pre-Check Clearance", pcc_name):
		pcc_full = frappe.db.get_value(
			"Pre-Check Clearance",
			pcc_name,
			[
				"product_confirmed",
				"batch_no",
				"coa_status",
				"tanker_cleanliness",
				"odour_check",
				"seal_condition_before_loading",
				"qc_remarks",
				"failure_reason",
			],
			as_dict=True,
		)
		if pcc_full:
			card["pcc_form"] = pcc_full

	sddn_name = card.get("sddn")
	if sddn_name:
		from apc_operations.security.api import get_security_delivery_draft_note_detail

		sddn_detail = get_security_delivery_draft_note_detail(sddn_name)
		card["checklist_items"] = sddn_detail.get("checklist_items") or []
		card["verification"] = sddn_detail.get("verification") or {}
		card["raw_sddn_status"] = sddn_detail.get("raw_security_status")
		card["sddn_truck_number"] = sddn_detail.get("truck_number")
		card["sddn_driver_name"] = sddn_detail.get("driver_name")
		card["sddn_driver_contact"] = sddn_detail.get("driver_contact")
		card["sddn_container_number"] = sddn_detail.get("container_number")
		card["sddn_pickup_location"] = sddn_detail.get("pickup_location")
		card["sddn_destination"] = sddn_detail.get("destination")
		card["sddn_cro_number"] = sddn_detail.get("cro_number")
		verifiable = {
			"Draft",
			"Pending Review",
			"Pending Verification",
			"Sent to Security",
		}
		card["can_verify_sddn"] = (sddn_detail.get("raw_security_status") or "") in verifiable
		card["sddn_read_only"] = not card["can_verify_sddn"]
	else:
		card["checklist_items"] = []
		card["can_verify_sddn"] = False
		card["sddn_read_only"] = True

	card["is_import"] = (card.get("commercial_movement") or "").strip() == "Import"

	return card


# ---------------------------------------------------------------------------
# Detail endpoint
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_qc_item_detail(loading_delivery_note: str) -> dict[str, Any]:
	if not loading_delivery_note:
		frappe.throw(_("loading_delivery_note is required"))

	ldn = frappe.get_doc("Loading Delivery Note", loading_delivery_note)
	sddn_data: dict[str, Any] = {}
	if ldn.security_draft_delivery_note:
		sddn_data = (
			frappe.db.get_value(
				"Security Draft Delivery Note",
				ldn.security_draft_delivery_note,
				[
					"name",
					"security_status",
					"vehicle",
					"driver",
					"transporter",
					"container_type",
					"container_count",
					"transport_schedule",
				],
				as_dict=True,
			)
			or {}
		)

	# Driver + vehicle resolution for modal display
	driver_name = None
	driver_contact = None
	vehicle_number = None
	if sddn_data.get("transport_schedule"):
		ts = frappe.db.get_value(
			"Transport Schedule",
			sddn_data.get("transport_schedule"),
			[
				"assigned_vehicle",
				"assigned_driver",
				"driver_phone",
			],
			as_dict=True,
		) or {}
		if ts.get("assigned_vehicle"):
			vehicle_number = (
				frappe.db.get_value("Vehicle", ts["assigned_vehicle"], "license_plate")
				or ts["assigned_vehicle"]
			)
		if ts.get("assigned_driver"):
			driver_name = (
				frappe.db.get_value("Driver", ts["assigned_driver"], "full_name")
				or ts["assigned_driver"]
			)
		driver_contact = ts.get("driver_phone")

	# Batches + COA chain
	batch_rows = frappe.get_all(
		"Loading DN Batch",
		filters={"parent": ldn.name},
		fields=["batch", "coa", "allocated_qty", "dispatched_qty", "uom"],
		order_by="idx asc",
	)
	for b in batch_rows:
		if b.get("coa"):
			coa = frappe.db.get_value(
				"APC COA", b["coa"], ["status", "approval_status", "coa_pdf"], as_dict=True
			) or {}
			b["coa_label"] = console_status.coa_display_label(coa)
			b["coa_pdf"] = coa.get("coa_pdf")
		else:
			b["coa_label"] = console_status.COA_DISPLAY_PENDING
			b["coa_pdf"] = None

	primary_batch = batch_rows[0].get("batch") if batch_rows else None

	qcr_name = ldn.qc_report_request or frappe.db.get_value(
		"QC Report Request", {"loading_delivery_note": ldn.name}, "name"
	)
	qcr = (
		frappe.db.get_value(
			"QC Report Request",
			qcr_name,
			[
				"name",
				"qc_status",
				"qc_remarks",
				"qc_checked_by",
				"qc_checked_on",
				"coa",
				"batch",
			],
			as_dict=True,
		)
		if qcr_name
		else None
	)

	qc_status = (qcr and qcr.get("qc_status")) or ldn.qc_status or "Pending QC"

	qcr_coa_pdf = None
	qcr_coa_label = None
	if qcr and qcr.get("coa"):
		qcr_coa = frappe.db.get_value(
			"APC COA",
			qcr["coa"],
			["status", "approval_status", "coa_pdf"],
			as_dict=True,
		) or {}
		qcr_coa_pdf = qcr_coa.get("coa_pdf")
		qcr_coa_label = console_status.coa_display_label(qcr_coa)

	do_name = _delivery_order_for_ldn_row(
		{"name": ldn.name, "job_order": ldn.job_order}
	)

	return {
		"delivery_order": do_name,
		"loading_delivery_note": ldn.name,
		"security_draft_delivery_note": ldn.security_draft_delivery_note,
		"job_order": ldn.job_order,
		"job_order_number": getattr(ldn, "job_order_number", None),
		"customer": ldn.customer,
		"customer_name": ldn.customer_name,
		"product": ldn.material_description,
		"quantity": ldn.quantity,
		"uom": ldn.uom,
		"container_number": ldn.container_number,
		"seal_number": ldn.seal_number,
		"vehicle": ldn.vehicle,
		"driver": ldn.driver,
		"vehicle_number": vehicle_number,
		"driver_name": driver_name,
		"driver_contact": driver_contact,
		"batches": batch_rows,
		"primary_batch": primary_batch,
		"qc_report_request": qcr_name,
		"qc_status": qc_status,
		"qc_status_tone": console_status.qc_status_tone(qc_status),
		"qc_remarks": qcr.get("qc_remarks") if qcr else None,
		"qc_checked_by": qcr.get("qc_checked_by") if qcr else None,
		"qc_checked_on": qcr.get("qc_checked_on") if qcr else None,
		"coa": qcr.get("coa") if qcr else None,
		"coa_pdf": qcr_coa_pdf,
		"qcr_coa_label": qcr_coa_label,
		"ldn_status_label": console_status.ldn_display_label(ldn.delivery_note_status),
		"ldn_status_tone": console_status.ldn_status_tone(ldn.delivery_note_status),
		"sddn_status_label": console_status.sddn_display_label(sddn_data.get("security_status")),
		"sddn_status_tone": console_status.sddn_status_tone(sddn_data.get("security_status")),
		"notes": ldn.notes,
	}


# ---------------------------------------------------------------------------
# COA lookup + approval (QC Console)
# ---------------------------------------------------------------------------


def _coa_name_for_ldn_batch(ldn_name: str, batch: str | None) -> str | None:
	if not batch:
		return None
	if ldn_name:
		row = frappe.db.get_value(
			"Loading DN Batch",
			{"parent": ldn_name, "batch": batch},
			"coa",
		)
		if row:
			return row
	return frappe.db.get_value("APC Batch", batch, "linked_coa")


@frappe.whitelist()
def get_coa_for_qc_batch(loading_delivery_note: str, batch: str | None = None) -> dict[str, Any]:
	"""Return APC COA linked to this LDN batch line or to the APC Batch."""
	if not loading_delivery_note:
		frappe.throw(_("loading_delivery_note is required"))
	if not batch:
		return {"coa": None}
	name = _coa_name_for_ldn_batch(loading_delivery_note, batch)
	if not name:
		return {"coa": None}
	row = (
		frappe.db.get_value(
			"APC COA",
			name,
			["name", "status", "approval_status", "coa_pdf", "batch"],
			as_dict=True,
		)
		or {}
	)
	row["coa"] = row.pop("name", None) or name
	row["label"] = console_status.coa_display_label(
		{
			"status": row.get("status"),
			"approval_status": row.get("approval_status"),
			"coa_pdf": row.get("coa_pdf"),
		}
	)
	return row


@frappe.whitelist()
def set_coa_approval_from_qc(
	coa: str,
	decision: str,
	remarks: str | None = None,
	rejection_reason: str | None = None,
) -> dict[str, Any]:
	"""QC user approves or rejects an APC COA from the QC Console."""
	if not coa:
		frappe.throw(_("coa is required"))
	decision = (decision or "").strip()
	if decision not in {"Approved", "Rejected"}:
		frappe.throw(_("decision must be Approved or Rejected"))

	doc = frappe.get_doc("APC COA", coa)
	if decision == "Approved":
		doc.status = "Approved"
		doc.approved_by = frappe.session.user
		doc.approved_on = now_datetime()
		if remarks:
			doc.qc_remarks = remarks
	else:
		doc.status = "Rejected"
		doc.rejected_by = frappe.session.user
		doc.rejected_date = now_datetime()
		doc.rejection_reason = rejection_reason or remarks or ""
		if remarks:
			doc.qc_remarks = remarks
	doc.save(ignore_permissions=True)
	return {
		"coa": doc.name,
		"approval_status": doc.approval_status,
		"status": doc.status,
	}


# ---------------------------------------------------------------------------
# QC submission + COA generation
# ---------------------------------------------------------------------------


@frappe.whitelist()
def submit_qc_for_loading_delivery_note(
	loading_delivery_note: str,
	batch: str | None = None,
	qc_status: str = "QC Cleared",
	qc_remarks: str | None = None,
	generate_coa: bool | int | str = True,
) -> dict[str, Any]:
	"""Write QC results for an LDN through the Security Inspection compat layer."""
	if not loading_delivery_note:
		frappe.throw(_("loading_delivery_note is required"))
	if qc_status not in {"Pending QC", "QC Cleared", "QC Rejected"}:
		frappe.throw(_("Invalid qc_status: {0}").format(qc_status))

	generate_coa_flag = str(generate_coa).lower() not in {"0", "false", "no", ""}

	qcr_name = _resolve_qc_report_request(loading_delivery_note, batch)
	qcr = frappe.get_doc("QC Report Request", qcr_name)

	qcr.qc_status = qc_status
	if qc_remarks is not None:
		qcr.qc_remarks = qc_remarks
	qcr.qc_checked_by = frappe.session.user
	qcr.qc_checked_on = now_datetime()
	if batch and not qcr.batch:
		qcr.batch = batch
	qcr.save(ignore_permissions=True)

	# Update LDN status mirror
	ldn = frappe.get_doc("Loading Delivery Note", loading_delivery_note)
	ldn.qc_status = qc_status
	ldn.qc_report_request = qcr.name
	if qc_status == "QC Cleared":
		ldn.delivery_note_status = "QC Cleared"
		ldn.qc_cleared_by = frappe.session.user
		ldn.qc_cleared_on = now_datetime()
	elif qc_status == "QC Rejected":
		ldn.delivery_note_status = "QC Rejected"
	ldn.save(ignore_permissions=True)

	coa_name = None
	if qc_status == "QC Cleared" and generate_coa_flag:
		coa_name = _create_coa_via_helper(qcr.name)

	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Comment",
			"reference_doctype": "Loading Delivery Note",
			"reference_name": ldn.name,
			"content": _("QC submitted: status={0}").format(qc_status),
		}
	).insert(ignore_permissions=True)

	return {
		"qc_report_request": qcr.name,
		"coa": coa_name,
		"qc_status": qc_status,
	}


@frappe.whitelist()
def generate_coa_for_qc(qc_report_request: str) -> dict[str, Any]:
	"""Idempotently create an APC COA from a cleared QC Report Request."""
	if not qc_report_request:
		frappe.throw(_("qc_report_request is required"))
	coa_name = _create_coa_via_helper(qc_report_request)
	return {"qc_report_request": qc_report_request, "coa": coa_name}


@frappe.whitelist()
def upload_coa_for_qc(qc_report_request: str, file_url: str) -> dict[str, Any]:
	"""Attach an uploaded COA PDF and mark the COA as Uploaded."""
	if not qc_report_request or not file_url:
		frappe.throw(_("qc_report_request and file_url are required"))

	qcr = frappe.get_doc("QC Report Request", qc_report_request)
	coa_name = qcr.coa or _create_coa_via_helper(qc_report_request)
	if not coa_name:
		frappe.throw(_("Unable to resolve or create COA for QC Report Request {0}").format(qc_report_request))

	coa = frappe.get_doc("APC COA", coa_name)
	coa.coa_pdf = file_url
	if coa.status in ("Draft", "Pending Testing", "Passed"):
		coa.status = "Approved"
	if coa.approval_status != "Approved":
		coa.approval_status = "Approved"
	coa.save(ignore_permissions=True)

	if qcr.loading_delivery_note:
		frappe.db.set_value(
			"Loading Delivery Note",
			qcr.loading_delivery_note,
			"coa_verified",
			1,
			update_modified=False,
		)
		frappe.db.set_value(
			"Loading Delivery Note",
			qcr.loading_delivery_note,
			"coa_verified_by",
			frappe.session.user,
			update_modified=False,
		)
		frappe.db.set_value(
			"Loading Delivery Note",
			qcr.loading_delivery_note,
			"coa_verified_on",
			now_datetime(),
			update_modified=False,
		)

	return {"coa": coa.name, "coa_pdf": coa.coa_pdf}


def _create_coa_via_helper(qcr_name: str) -> str | None:
	from apc_operations.inventory.doctype.apc_coa.apc_coa import create_apc_coa_from_qc

	return create_apc_coa_from_qc(qcr_name)


# ---------------------------------------------------------------------------
# Delivery Order dispatch workflow (Phase 5 — Path B)
# ---------------------------------------------------------------------------


def _dispatch_workflow_response(result: dict) -> dict:
	return result


@frappe.whitelist()
def get_qc_precheck_queue(limit=100):
	from apc_operations.quality.dispatch_workflow import get_qc_precheck_queue as _queue

	return _dispatch_workflow_response(_queue(limit=int(limit)))


@frappe.whitelist()
def submit_qc_precheck(
	pre_check_clearance,
	result,
	product_confirmed=None,
	batch_no=None,
	coa_status=None,
	tanker_cleanliness=None,
	odour_check=None,
	seal_condition_before_loading=None,
	qc_remarks=None,
	failure_reason=None,
):
	from apc_operations.quality.dispatch_workflow import submit_qc_precheck as _submit

	return _dispatch_workflow_response(
		_submit(
			pre_check_clearance,
			result,
			product_confirmed=product_confirmed,
			batch_no=batch_no,
			coa_status=coa_status,
			tanker_cleanliness=tanker_cleanliness,
			odour_check=odour_check,
			seal_condition_before_loading=seal_condition_before_loading,
			qc_remarks=qc_remarks,
			failure_reason=failure_reason,
		)
	)


@frappe.whitelist()
def put_qc_on_hold(pre_check_clearance, hold_reason):
	from apc_operations.quality.dispatch_workflow import put_qc_on_hold as _hold

	return _dispatch_workflow_response(_hold(pre_check_clearance, hold_reason))


@frappe.whitelist()
def fail_qc_precheck(pre_check_clearance, failure_reason):
	from apc_operations.quality.dispatch_workflow import fail_qc_precheck as _fail

	return _dispatch_workflow_response(_fail(pre_check_clearance, failure_reason))


@frappe.whitelist()
def link_batch_to_precheck(pre_check_clearance, batch_no):
	from apc_operations.quality.dispatch_workflow import link_batch_to_precheck as _link

	return _dispatch_workflow_response(_link(pre_check_clearance, batch_no))


@frappe.whitelist()
def verify_coa_for_batch(loading_delivery_note, batch):
	from apc_operations.quality.dispatch_workflow import verify_coa_for_batch as _verify

	return _dispatch_workflow_response(_verify(loading_delivery_note, batch))


@frappe.whitelist()
def submit_final_qc_clearance(loading_delivery_note, qc_remarks=None):
	from apc_operations.quality.dispatch_workflow import submit_final_qc_clearance as _submit

	return _dispatch_workflow_response(_submit(loading_delivery_note, qc_remarks=qc_remarks))


@frappe.whitelist()
def qc_manager_approve_dispatch(loading_delivery_note):
	from apc_operations.quality.dispatch_workflow import qc_manager_approve_dispatch as _approve

	return _dispatch_workflow_response(_approve(loading_delivery_note))
