"""APC Operations — Security Console API.

Backend for the Security Console (``/app/security-console``).

Implements the 14 whitelisted endpoints described in
``DESIGN_CONCEPT.md`` Section 8.7. All write paths use a compatibility
layer around ``Security Inspection`` so the existing
``Transport Schedule -> SDDN -> Security Inspection -> LDN/QC``
automation continues to work even when the user only interacts with
the new console.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from apc_operations.security.doctype.security_inspection.security_inspection import (
	DEFAULT_CHECKLIST_ITEMS,
)
from apc_operations.services import console_status
from apc_operations.shipping.doctype.gate_pass.gate_pass import (
	resolve_delivery_order_for_gate_pass_display,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_vehicle_driver_from_transport(ts_name: str | None) -> dict[str, Any]:
	out: dict[str, Any] = {
		"vehicle_number": None,
		"driver_name": None,
		"driver_contact": None,
		"pickup_location": None,
		"destination": None,
		"transport_status": None,
		"container_number": None,
	}
	if not ts_name:
		return out
	ts = (
		frappe.db.get_value(
			"Transport Schedule",
			ts_name,
			[
				"assigned_vehicle",
				"assigned_driver",
				"transporter",
				"driver_phone",
				"pickup_location",
				"delivery_location",
				"pickup_address",
				"delivery_address",
				"transport_status",
				"container_type",
				"shipping_booking",
			],
			as_dict=True,
		)
		or {}
	)
	if ts.get("assigned_vehicle"):
		out["vehicle_number"] = (
			frappe.db.get_value("Vehicle", ts["assigned_vehicle"], "license_plate")
			or ts["assigned_vehicle"]
		)
	if ts.get("assigned_driver"):
		out["driver_name"] = (
			frappe.db.get_value("Driver", ts["assigned_driver"], "full_name")
			or ts["assigned_driver"]
		)
	out["driver_contact"] = ts.get("driver_phone")
	out["pickup_location"] = ts.get("pickup_location") or ts.get("pickup_address")
	out["destination"] = ts.get("delivery_location") or ts.get("delivery_address")
	out["transport_status"] = ts.get("transport_status")
	out["container_number"] = ts.get("container_type")
	out["shipping_booking"] = ts.get("shipping_booking")
	return out


def _sddn_card(row: dict[str, Any]) -> dict[str, Any]:
	resolved = _resolve_vehicle_driver_from_transport(row.get("transport_schedule"))
	cro_number = None
	if resolved.get("shipping_booking"):
		cro_number = frappe.db.get_value(
			"Shipping Booking", resolved["shipping_booking"], "cro_number"
		)
	return {
		"name": row.get("name"),
		"sddn": row.get("name"),
		"job_order": row.get("job_order"),
		"job_order_number": row.get("job_order_number") or row.get("job_order"),
		"customer": row.get("customer"),
		"buyer": row.get("buyer"),
		"transport_schedule": row.get("transport_schedule"),
		"cro_number": cro_number,
		"container_number": resolved.get("container_number"),
		"truck_number": resolved.get("vehicle_number"),
		"driver_name": resolved.get("driver_name"),
		"driver_contact": resolved.get("driver_contact"),
		"pickup_location": resolved.get("pickup_location"),
		"destination": resolved.get("destination"),
		"transport_status": resolved.get("transport_status"),
		"security_status": console_status.sddn_display_label(row.get("security_status")),
		"security_status_tone": console_status.sddn_status_tone(row.get("security_status")),
		"raw_security_status": row.get("security_status"),
		"gate_out_status": row.get("gate_out_status"),
	}


def _checklist_template() -> list[dict[str, Any]]:
	"""Return a fresh copy of the default checklist (no `completed` yet).

	Used when an SDDN has no linked Security Inspection so the UI can still
	render and let the user tick items.  Submitting via the verify endpoint
	will lazily create the Security Inspection and persist the rows.
	"""
	return [
		{
			"name": None,
			"checklist_item": item["checklist_item"],
			"required": int(item.get("required", 0)),
			"completed": 0,
			"remarks": "",
		}
		for item in DEFAULT_CHECKLIST_ITEMS
	]


def _find_security_inspection_for_sddn(sddn_doc) -> str | None:
	if not sddn_doc.transport_schedule:
		return None
	return frappe.db.get_value(
		"Security Inspection",
		{"transportation_request": sddn_doc.transport_schedule},
		"name",
	)


def _get_checklist_for_sddn(sddn_doc) -> list[dict[str, Any]]:
	"""Return checklist rows for the SDDN's Security Inspection if one exists,
	otherwise the default template."""
	si_name = _find_security_inspection_for_sddn(sddn_doc)
	if not si_name:
		return _checklist_template()

	rows = frappe.get_all(
		"Security Checklist",
		filters={"parent": si_name, "parenttype": "Security Inspection"},
		fields=["name", "checklist_item", "required", "completed", "remarks", "idx"],
		order_by="idx asc",
	)
	if not rows:
		return _checklist_template()
	return [
		{
			"name": r.get("name"),
			"checklist_item": r.get("checklist_item"),
			"required": int(r.get("required") or 0),
			"completed": int(r.get("completed") or 0),
			"remarks": r.get("remarks") or "",
		}
		for r in rows
	]


def _persist_checklist_to_inspection(si_name: str, checklist: list[dict[str, Any]]):
	"""Update Security Checklist child rows for a Security Inspection.

	Matches incoming rows to existing rows by ``name`` (when supplied) so the
	stored grid order is preserved.  Rows without a matching name (e.g. when
	the SDDN was viewed against the default template before the SI existed)
	are matched by ``checklist_item`` text.
	"""
	if not checklist:
		return

	si = frappe.get_doc("Security Inspection", si_name)
	by_name = {row.name: row for row in si.checklist_items}
	by_item = {(row.checklist_item or "").strip(): row for row in si.checklist_items}

	for payload in checklist:
		row = None
		row_name = payload.get("name")
		if row_name and row_name in by_name:
			row = by_name[row_name]
		else:
			item_text = (payload.get("checklist_item") or "").strip()
			if item_text and item_text in by_item:
				row = by_item[item_text]
		if not row:
			continue
		row.completed = 1 if payload.get("completed") else 0
		remarks = payload.get("remarks")
		if remarks is not None:
			row.remarks = remarks

	si.save(ignore_permissions=True)


def _resolve_or_create_security_inspection(sddn_doc) -> str:
	"""Return Security Inspection name, creating one tied to the SDDN if needed."""
	if not sddn_doc.transport_schedule:
		frappe.throw(_("SDDN has no Transport Schedule"))

	existing = frappe.db.get_value(
		"Security Inspection",
		{"transportation_request": sddn_doc.transport_schedule},
		"name",
	)
	if existing:
		return existing

	ts = frappe.db.get_value(
		"Transport Schedule",
		sddn_doc.transport_schedule,
		[
			"name",
			"job_order",
			"shipping_booking",
			"customer",
			"customer_name",
			"outward_type",
			"assigned_vehicle",
			"assigned_driver",
			"transporter",
			"driver_phone",
			"container_type",
			"material_description",
			"cargo_weight",
		],
		as_dict=True,
	)
	if not ts:
		frappe.throw(_("Transport Schedule {0} not found").format(sddn_doc.transport_schedule))

	si = frappe.new_doc("Security Inspection")
	si.job_order = ts.job_order
	si.transportation_request = ts.name
	si.shipping_booking = ts.shipping_booking
	si.customer = ts.customer
	si.customer_name = ts.customer_name
	si.inspection_type = (
		"Export Container" if ts.outward_type == "Export Container" else "Local Delivery"
	)
	si.inspection_date = today()
	si.security_status = "Draft"
	si.vehicle = ts.assigned_vehicle
	si.driver = ts.assigned_driver
	si.transporter = ts.transporter
	if ts.assigned_vehicle:
		si.vehicle_number = (
			frappe.db.get_value("Vehicle", ts.assigned_vehicle, "license_plate")
			or ts.assigned_vehicle
		)
	if ts.assigned_driver:
		si.driver_name = (
			frappe.db.get_value("Driver", ts.assigned_driver, "full_name")
			or ts.assigned_driver
		)
	si.driver_phone = ts.driver_phone
	si.container_number = ts.container_type
	si.container_type = ts.container_type
	si.material_description = ts.material_description
	si.gross_weight = ts.cargo_weight
	si.insert(ignore_permissions=True, ignore_links=True)
	return si.name


# ---------------------------------------------------------------------------
# Pending / Verified SDDN queues
# ---------------------------------------------------------------------------


_SDDN_FIELDS = [
	"name",
	"transport_schedule",
	"job_order",
	"job_order_number",
	"customer",
	"buyer",
	"security_status",
	"gate_out_status",
	"sent_to_security_on",
]


_PENDING_STATUSES = ("Draft", "Pending Review", "Pending Verification", "Sent to Security")
_VERIFIED_STATUSES = ("Verified", "Approved", "LDN Created", "Sent to QC", "Completed")


@frappe.whitelist()
def get_pending_security_delivery_draft_notes():
	rows = frappe.get_all(
		"Security Draft Delivery Note",
		filters={"security_status": ["in", _PENDING_STATUSES]},
		fields=_SDDN_FIELDS,
		order_by="modified desc",
		limit=400,
	)
	return [_sddn_card(r) for r in rows]


@frappe.whitelist()
def get_verified_security_delivery_draft_notes():
	rows = frappe.get_all(
		"Security Draft Delivery Note",
		filters={"security_status": ["in", _VERIFIED_STATUSES]},
		fields=_SDDN_FIELDS,
		order_by="modified desc",
		limit=400,
	)
	# Annotate with LDN status
	out = []
	for r in rows:
		card = _sddn_card(r)
		ldn_name = frappe.db.get_value(
			"Loading Delivery Note",
			{"security_draft_delivery_note": r["name"]},
			["name", "delivery_note_status"],
			as_dict=True,
		)
		if ldn_name:
			card["loading_delivery_note"] = ldn_name.get("name")
			card["ldn_status"] = console_status.ldn_display_label(
				ldn_name.get("delivery_note_status")
			)
			card["ldn_status_tone"] = console_status.ldn_status_tone(
				ldn_name.get("delivery_note_status")
			)
		else:
			card["loading_delivery_note"] = None
			card["ldn_status"] = "Not Created"
			card["ldn_status_tone"] = "neutral"
		out.append(card)
	return out


@frappe.whitelist()
def get_security_delivery_draft_note_detail(name: str):
	if not name:
		frappe.throw(_("name is required"))
	sddn = frappe.get_doc("Security Draft Delivery Note", name)
	resolved = _resolve_vehicle_driver_from_transport(sddn.transport_schedule)
	cro_number = None
	if resolved.get("shipping_booking"):
		cro_number = frappe.db.get_value(
			"Shipping Booking", resolved["shipping_booking"], "cro_number"
		)
	ldn_name = frappe.db.get_value(
		"Loading Delivery Note",
		{"security_draft_delivery_note": sddn.name},
		"name",
	)
	# Verification flags parsed from notes (JSON-encoded) if present.
	verification = {}
	if sddn.security_notes:
		try:
			verification = json.loads(sddn.security_notes) or {}
		except Exception:
			verification = {"raw_notes": sddn.security_notes}

	return {
		"sddn": sddn.name,
		"job_order": sddn.job_order,
		"job_order_number": sddn.job_order_number,
		"customer": sddn.customer,
		"buyer": sddn.buyer,
		"transport_schedule": sddn.transport_schedule,
		"cro_number": cro_number,
		"container_number": resolved.get("container_number"),
		"truck_number": resolved.get("vehicle_number"),
		"driver_name": resolved.get("driver_name"),
		"driver_contact": resolved.get("driver_contact"),
		"pickup_location": resolved.get("pickup_location"),
		"destination": resolved.get("destination"),
		"transport_status": resolved.get("transport_status"),
		"security_status": console_status.sddn_display_label(sddn.security_status),
		"raw_security_status": sddn.security_status,
		"security_status_tone": console_status.sddn_status_tone(sddn.security_status),
		"gate_out_status": sddn.gate_out_status,
		"loading_delivery_note": ldn_name,
		"verification": verification,
		"sent_to_security_on": sddn.get("sent_to_security_on"),
		"security_inspection": _find_security_inspection_for_sddn(sddn),
		"checklist_items": _get_checklist_for_sddn(sddn),
	}


# ---------------------------------------------------------------------------
# Verify / hold / reject
# ---------------------------------------------------------------------------


def _persist_verification(sddn, payload: dict):
	checks = {
		"truck_verified": bool(payload.get("truck_verified")),
		"driver_verified": bool(payload.get("driver_verified")),
		"container_verified": bool(payload.get("container_verified")),
		"verified_by": frappe.session.user,
		"verified_on": str(now_datetime()),
	}
	if payload.get("remarks"):
		checks["remarks"] = payload["remarks"]
	existing = {}
	if sddn.security_notes:
		try:
			existing = json.loads(sddn.security_notes) or {}
		except Exception:
			existing = {"prior_notes": sddn.security_notes}
	existing.update(checks)
	sddn.security_notes = json.dumps(existing, default=str)


@frappe.whitelist()
def verify_security_delivery_draft_note(name: str, checks=None, checklist=None):
	if not name:
		frappe.throw(_("name is required"))
	payload = checks
	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except Exception:
			payload = {"remarks": payload}
	payload = payload or {}

	checklist_payload = checklist
	if isinstance(checklist_payload, str):
		try:
			checklist_payload = json.loads(checklist_payload)
		except Exception:
			checklist_payload = []
	if not isinstance(checklist_payload, list):
		checklist_payload = []

	# Enforce required-item completion against the canonical template so the
	# user cannot bypass it by trimming the payload client-side.
	completed_by_text = {
		(row.get("checklist_item") or "").strip(): bool(row.get("completed"))
		for row in checklist_payload
	}
	missing_required = []
	for tmpl in DEFAULT_CHECKLIST_ITEMS:
		if not tmpl.get("required"):
			continue
		item_text = tmpl["checklist_item"].strip()
		if not completed_by_text.get(item_text):
			missing_required.append(tmpl["checklist_item"])
	if missing_required:
		frappe.throw(
			_(
				"All required checklist items must be completed before the SDDN can be verified."
				"<br><br>Pending items:<br>- {0}"
			).format("<br>- ".join(missing_required))
		)

	sddn = frappe.get_doc("Security Draft Delivery Note", name)
	_persist_verification(sddn, payload)
	sddn.security_status = "Verified"
	sddn.gate_out_status = "Approved for Gate Out"
	sddn.save(ignore_permissions=True)

	# Compatibility layer: ensure Security Inspection exists, persist
	# checklist, and advance its status.
	si_name = _resolve_or_create_security_inspection(sddn)
	_persist_checklist_to_inspection(si_name, checklist_payload)
	si = frappe.get_doc("Security Inspection", si_name)
	if si.security_status in ("Draft", "Pending Review", "Pending Checklist"):
		si.security_status = "Checklist Completed"
		si.save(ignore_permissions=True)

	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Comment",
			"reference_doctype": "Security Draft Delivery Note",
			"reference_name": sddn.name,
			"content": _("SDDN verified — checklist completed and truck/driver/container confirmed."),
		}
	).insert(ignore_permissions=True)

	return get_security_delivery_draft_note_detail(name)


@frappe.whitelist()
def save_security_checklist(name: str, checklist=None):
	"""Persist checklist progress without verifying the SDDN.

	Lets the user save partial checklist state and come back later.
	"""
	if not name:
		frappe.throw(_("name is required"))
	checklist_payload = checklist
	if isinstance(checklist_payload, str):
		try:
			checklist_payload = json.loads(checklist_payload)
		except Exception:
			checklist_payload = []
	if not isinstance(checklist_payload, list):
		checklist_payload = []

	sddn = frappe.get_doc("Security Draft Delivery Note", name)
	si_name = _resolve_or_create_security_inspection(sddn)
	_persist_checklist_to_inspection(si_name, checklist_payload)
	return get_security_delivery_draft_note_detail(name)


@frappe.whitelist()
def hold_security_delivery_draft_note(name: str, reason: str | None = None):
	if not name:
		frappe.throw(_("name is required"))
	sddn = frappe.get_doc("Security Draft Delivery Note", name)
	sddn.security_status = "On Hold"
	if reason:
		_persist_verification(sddn, {"remarks": reason, "hold_reason": reason})
	sddn.save(ignore_permissions=True)
	return get_security_delivery_draft_note_detail(name)


@frappe.whitelist()
def reject_security_delivery_draft_note(name: str, reason: str | None = None):
	if not name:
		frappe.throw(_("name is required"))
	sddn = frappe.get_doc("Security Draft Delivery Note", name)
	sddn.security_status = "Rejected"
	if reason:
		_persist_verification(sddn, {"remarks": reason, "reject_reason": reason})
	sddn.save(ignore_permissions=True)
	return get_security_delivery_draft_note_detail(name)


# ---------------------------------------------------------------------------
# Create LDN + send to QC
# ---------------------------------------------------------------------------


@frappe.whitelist()
def create_loading_delivery_note(sddn: str):
	if not sddn:
		frappe.throw(_("sddn is required"))
	sddn_doc = frappe.get_doc("Security Draft Delivery Note", sddn)

	if sddn_doc.security_status not in ("Verified", "Approved", "LDN Created"):
		frappe.throw(
			_(
				"SDDN must be in status 'Verified' before creating a Loading Delivery Note. "
				"Current status: {0}"
			).format(sddn_doc.security_status)
		)

	existing = frappe.db.get_value(
		"Loading Delivery Note",
		{"security_draft_delivery_note": sddn_doc.name},
		"name",
	)
	if existing:
		if sddn_doc.security_status != "LDN Created":
			sddn_doc.security_status = "LDN Created"
			sddn_doc.save(ignore_permissions=True)
		return {"loading_delivery_note": existing, "sddn": sddn_doc.name}

	si_name = _resolve_or_create_security_inspection(sddn_doc)
	si = frappe.get_doc("Security Inspection", si_name)

	# Prefer the existing controller method when possible — it handles
	# downstream FIFO batch allocation.
	try:
		res = si.create_loading_delivery_note()
		ldn_name = res.get("loading_delivery_note") if isinstance(res, dict) else None
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Security Console LDN creation")
		ldn_name = None

	if not ldn_name:
		# Fallback: create LDN directly.
		ldn_doc = frappe.new_doc("Loading Delivery Note")
		ldn_doc.security_inspection = si.name
		ldn_doc.security_draft_delivery_note = sddn_doc.name
		ldn_doc.job_order = sddn_doc.job_order
		ldn_doc.customer = sddn_doc.customer
		ldn_doc.buyer = sddn_doc.buyer
		ldn_doc.vehicle = sddn_doc.vehicle
		ldn_doc.driver = sddn_doc.driver
		ldn_doc.material_description = sddn_doc.material_description
		ldn_doc.quantity = sddn_doc.quantity
		ldn_doc.uom = sddn_doc.uom
		ldn_doc.loading_date = today()
		ldn_doc.delivery_note_status = "Pending QC"
		ldn_doc.qc_status = "Pending QC"
		ldn_doc.insert(ignore_permissions=True)
		ldn_name = ldn_doc.name
		si.loading_delivery_note = ldn_doc.name
		if si.security_status not in ("Loading DN Created", "Reported to QC"):
			si.security_status = "Loading DN Created"
		si.save(ignore_permissions=True)

	# Link LDN back to SDDN even if the controller-created LDN missed it.
	frappe.db.set_value(
		"Loading Delivery Note",
		ldn_name,
		"security_draft_delivery_note",
		sddn_doc.name,
		update_modified=False,
	)

	sddn_doc.security_status = "LDN Created"
	sddn_doc.save(ignore_permissions=True)

	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Comment",
			"reference_doctype": "Security Draft Delivery Note",
			"reference_name": sddn_doc.name,
			"content": _("Loading Delivery Note created: {0}").format(ldn_name),
		}
	).insert(ignore_permissions=True)

	try:
		from apc_operations.services.delivery_order_service import sync_from_ldn

		sync_from_ldn(ldn_name)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "LDN Delivery Order link sync")

	return {"loading_delivery_note": ldn_name, "sddn": sddn_doc.name}


@frappe.whitelist()
def send_loading_delivery_note_to_qc(ldn: str):
	if not ldn:
		frappe.throw(_("ldn is required"))
	ldn_doc = frappe.get_doc("Loading Delivery Note", ldn)

	updates = {
		"delivery_note_status": "Pending QC",
		"qc_status": "Pending QC",
		"sent_to_qc_on": now_datetime(),
	}
	for k, v in updates.items():
		setattr(ldn_doc, k, v)
	ldn_doc.save(ignore_permissions=True)

	# Compatibility layer: trigger Security Inspection.report_to_qc so QC
	# Report Request gets created if one does not already exist.
	qc_request_name = ldn_doc.qc_report_request
	if not qc_request_name and ldn_doc.security_inspection:
		try:
			si = frappe.get_doc("Security Inspection", ldn_doc.security_inspection)
			# Move SI to a status that allows report_to_qc, if needed.
			if si.security_status not in ("Checklist Completed", "Loading DN Created"):
				si.security_status = "Loading DN Created"
				si.save(ignore_permissions=True)
			res = si.report_to_qc()
			qc_request_name = res.get("qc_report_request") if isinstance(res, dict) else None
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Security Console send_loading_delivery_note_to_qc")

	if not qc_request_name:
		# Fallback: create QC Report Request directly.
		qc_doc = frappe.new_doc("QC Report Request")
		qc_doc.security_inspection = ldn_doc.security_inspection
		qc_doc.security_draft_delivery_note = ldn_doc.security_draft_delivery_note
		qc_doc.loading_delivery_note = ldn_doc.name
		qc_doc.job_order = ldn_doc.job_order
		from apc_operations.services.delivery_order_service import resolve_do_for_ldn

		do_name = resolve_do_for_ldn(ldn_doc.name)
		if do_name and hasattr(qc_doc, "delivery_order"):
			qc_doc.delivery_order = do_name
		qc_doc.requested_by = frappe.session.user
		qc_doc.requested_on = now_datetime()
		qc_doc.qc_status = "Pending QC"
		qc_doc.insert(ignore_permissions=True)
		qc_request_name = qc_doc.name
		frappe.db.set_value(
			"Loading Delivery Note",
			ldn_doc.name,
			"qc_report_request",
			qc_request_name,
			update_modified=False,
		)

	if ldn_doc.security_draft_delivery_note:
		frappe.db.set_value(
			"Security Draft Delivery Note",
			ldn_doc.security_draft_delivery_note,
			"security_status",
			"Sent to QC",
			update_modified=True,
		)

	try:
		from apc_operations.services.delivery_order_service import sync_from_ldn

		sync_from_ldn(ldn_doc.name)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Send to QC Delivery Order sync")

	return {"loading_delivery_note": ldn_doc.name, "qc_report_request": qc_request_name}


# ---------------------------------------------------------------------------
# Gate Pass queue
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_gate_pass_queue():
	rows = frappe.get_all(
		"Gate Pass",
		filters={"docstatus": ["!=", 2], "status": ["in", ["Draft", "Submitted", "In Transit"]]},
		fields=[
			"name",
			"gate_pass_type",
			"posting_date",
			"vehicle_no",
			"driver_name",
			"driver_phone",
			"customer",
			"customer_name",
			"delivery_order",
			"status",
		],
		order_by="modified desc",
		limit=200,
	)
	out = []
	for r in rows:
		out.append(
			{
				"name": r.get("name"),
				"gate_pass": r.get("name"),
				"gate_pass_type": r.get("gate_pass_type"),
				"vehicle_no": r.get("vehicle_no"),
				"driver_name": r.get("driver_name"),
				"driver_phone": r.get("driver_phone"),
				"customer": r.get("customer"),
				"customer_name": r.get("customer_name"),
				"delivery_order": r.get("delivery_order")
				or resolve_delivery_order_for_gate_pass_display(r.get("name")),
				"status": r.get("status"),
				"status_tone": "info" if r.get("status") == "In Transit" else "neutral",
			}
		)
	return out


@frappe.whitelist()
def get_gate_pass_detail(name: str):
	if not name:
		frappe.throw(_("name is required"))
	gp = frappe.get_doc("Gate Pass", name)
	delivery_order = gp.delivery_order or resolve_delivery_order_for_gate_pass_display(gp)
	return {
		"gate_pass": gp.name,
		"gate_pass_type": gp.gate_pass_type,
		"posting_date": gp.posting_date,
		"posting_time": gp.posting_time,
		"vehicle_no": gp.vehicle_no,
		"driver_name": gp.driver_name,
		"driver_phone": gp.driver_phone,
		"customer": gp.customer,
		"customer_name": gp.customer_name,
		"delivery_order": delivery_order,
		"bill_of_lading": gp.bill_of_lading,
		"status": gp.status,
		"items": [
			{
				"item_code": it.get("item_code"),
				"qty": it.get("qty"),
				"uom": it.get("uom"),
			}
			for it in gp.items or []
		],
	}


@frappe.whitelist()
def create_gate_pass_for_security_console(security_inspection: str):
	"""Create Gate Pass from Security Console (SDDN/LDN modals). Delegates to Security Inspection."""
	if not security_inspection:
		frappe.throw(_("security_inspection is required"))
	si = frappe.get_doc("Security Inspection", security_inspection)
	return si.create_gate_pass()


@frappe.whitelist()
def mark_gate_in(gate_pass: str):
	if not gate_pass:
		frappe.throw(_("gate_pass is required"))
	gp = frappe.get_doc("Gate Pass", gate_pass)
	gp.gate_pass_type = "In"
	if gp.status in ("Draft",):
		gp.status = "Submitted"
	gp.save(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Comment",
			"reference_doctype": "Gate Pass",
			"reference_name": gp.name,
			"content": _("Gate In recorded"),
		}
	).insert(ignore_permissions=True)
	return get_gate_pass_detail(gate_pass)


@frappe.whitelist()
def mark_gate_out(gate_pass: str):
	if not gate_pass:
		frappe.throw(_("gate_pass is required"))
	gp = frappe.get_doc("Gate Pass", gate_pass)
	gp.gate_pass_type = "Out"
	gp.status = "In Transit"
	gp.save(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Comment",
			"reference_doctype": "Gate Pass",
			"reference_name": gp.name,
			"content": _("Gate Out recorded"),
		}
	).insert(ignore_permissions=True)
	return get_gate_pass_detail(gate_pass)


# ---------------------------------------------------------------------------
# Loading DN queue
# ---------------------------------------------------------------------------


_LDN_FIELDS = [
	"name",
	"security_draft_delivery_note",
	"security_inspection",
	"transportation_request",
	"job_order",
	"job_order_number",
	"customer",
	"customer_name",
	"delivery_note_status",
	"qc_status",
	"container_number",
	"material_description",
	"quantity",
	"uom",
	"vehicle",
	"driver",
	"loading_date",
	"sent_to_qc_on",
	"coa_verified",
	"qc_report_request",
]


@frappe.whitelist()
def get_loading_dn_queue():
	rows = frappe.get_all(
		"Loading Delivery Note",
		filters={"docstatus": ["!=", 2]},
		fields=_LDN_FIELDS,
		order_by="modified desc",
		limit=400,
	)
	out = []
	for r in rows:
		coa_label = console_status.coa_display_label(
			{
				"coa_pdf": None,
				"status": None,
				"approval_status": None,
			}
		)
		out.append(
			{
				"name": r.get("name"),
				"loading_delivery_note": r.get("name"),
				"sddn": r.get("security_draft_delivery_note"),
				"job_order": r.get("job_order"),
				"job_order_number": r.get("job_order_number") or r.get("job_order"),
				"customer": r.get("customer"),
				"customer_name": r.get("customer_name"),
				"qc_status": r.get("qc_status") or "Pending QC",
				"qc_status_tone": console_status.qc_status_tone(r.get("qc_status")),
				"ldn_status": console_status.ldn_display_label(r.get("delivery_note_status")),
				"ldn_status_tone": console_status.ldn_status_tone(r.get("delivery_note_status")),
				"coa_status": "Generated" if r.get("coa_verified") else coa_label,
				"coa_status_tone": "success" if r.get("coa_verified") else "warn",
			}
		)
	return out


@frappe.whitelist()
def get_loading_dn_detail(name: str):
	if not name:
		frappe.throw(_("name is required"))
	ldn = frappe.get_doc("Loading Delivery Note", name)
	batch_rows = frappe.get_all(
		"Loading DN Batch",
		filters={"parent": name},
		fields=["batch", "coa", "allocated_qty", "dispatched_qty", "uom"],
	)
	primary_batch = batch_rows[0]["batch"] if batch_rows else None
	primary_coa = batch_rows[0]["coa"] if batch_rows else None

	driver_name = None
	vehicle_number = None
	if ldn.vehicle:
		vehicle_number = (
			frappe.db.get_value("Vehicle", ldn.vehicle, "license_plate") or ldn.vehicle
		)
	if ldn.driver:
		driver_name = frappe.db.get_value("Driver", ldn.driver, "full_name") or ldn.driver

	return {
		"loading_delivery_note": ldn.name,
		"sddn": ldn.security_draft_delivery_note,
		"security_inspection": ldn.security_inspection,
		"transportation_request": ldn.transportation_request,
		"job_order": ldn.job_order,
		"job_order_number": ldn.job_order_number or ldn.job_order,
		"customer": ldn.customer,
		"customer_name": ldn.customer_name,
		"container_number": ldn.container_number,
		"vehicle": ldn.vehicle,
		"driver": ldn.driver,
		"vehicle_number": vehicle_number,
		"driver_name": driver_name,
		"product": ldn.material_description,
		"quantity": ldn.quantity,
		"uom": ldn.uom,
		"batch_number": primary_batch,
		"primary_coa": primary_coa,
		"qc_status": ldn.qc_status or "Pending QC",
		"qc_status_tone": console_status.qc_status_tone(ldn.qc_status),
		"ldn_status": console_status.ldn_display_label(ldn.delivery_note_status),
		"ldn_status_tone": console_status.ldn_status_tone(ldn.delivery_note_status),
		"coa_status": "Generated" if ldn.coa_verified else "Pending",
		"coa_status_tone": "success" if ldn.coa_verified else "warn",
		"qc_report_request": ldn.qc_report_request,
		"sent_to_qc_on": ldn.get("sent_to_qc_on"),
		"notes": ldn.notes,
	}


# ---------------------------------------------------------------------------
# Delivery Order console queues (Path B)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_security_console_counts():
	from apc_operations.services.delivery_order_service import get_security_console_counts

	return get_security_console_counts()


@frappe.whitelist()
def get_security_new_dos():
	from apc_operations.services.delivery_order_service import get_security_new_dos

	return get_security_new_dos()


@frappe.whitelist()
def get_security_pending_dos():
	from apc_operations.services.delivery_order_service import get_security_pending_dos

	return get_security_pending_dos()


@frappe.whitelist()
def get_security_in_progress_dos():
	from apc_operations.services.delivery_order_service import get_security_in_progress_dos

	return get_security_in_progress_dos()


@frappe.whitelist()
def get_security_completed_dos():
	from apc_operations.services.delivery_order_service import get_security_completed_dos

	return get_security_completed_dos()


@frappe.whitelist()
def get_security_do_detail(delivery_order: str):
	"""Aggregate DO + SDDN + LDN + gate for Security console detail modal."""
	if not delivery_order:
		frappe.throw(_("delivery_order is required"))

	from apc_operations.services.delivery_order_service import _enrich_do_row

	row = frappe.db.get_value(
		"Delivery Order",
		delivery_order,
		[
			"name",
			"customer",
			"customer_name",
			"job_order",
			"job_order_number",
			"status",
			"docstatus",
			"posting_date",
			"modified",
			"terms_of_delivery",
			"destination",
			"port_of_loading",
			"port_of_discharge",
		],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Delivery Order {0} not found").format(delivery_order))

	card = _enrich_do_row(row)
	sddn_detail = None
	if card.get("sddn"):
		sddn_detail = get_security_delivery_draft_note_detail(card["sddn"])

	ldn_detail = None
	if card.get("loading_delivery_note"):
		ldn_detail = get_loading_dn_detail(card["loading_delivery_note"])

	gate_detail = None
	if card.get("gate_pass"):
		gate_detail = get_gate_pass_detail(card["gate_pass"])

	card["sddn_detail"] = sddn_detail
	card["ldn_detail"] = ldn_detail
	card["gate_pass_detail"] = gate_detail
	card["read_only"] = card.get("operational_status") in ("QC Cleared", "Completed")
	return card
