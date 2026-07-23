"""APC Operations — Transportation Console API.

Backend for the Transportation Console (``/app/transportation-console``).

Implements the 11 whitelisted endpoints described in
``DESIGN_CONCEPT.md`` Section 6.10:

	get_inward_import_list, get_inward_import_detail, update_inward_import_tracking,
	get_inward_land_list, get_inward_land_detail,
	get_local_delivery_list, get_local_delivery_detail,
	get_export_container_list, get_export_container_detail,
	get_transportation_pending_counts,
	create_security_delivery_draft_note,
	send_security_delivery_draft_note_to_security
"""

from __future__ import annotations

from typing import Any, Iterable

import frappe
from frappe import _
from frappe.utils import now_datetime

from apc_operations.services import console_status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_TRANSPORT_FIELDS = [
	"name",
	"job_order",
	"job_order_number",
	"customer",
	"customer_name",
	"transport_status",
	"transport_type",
	"outward_type",
	"scheduled_pickup_date",
	"scheduled_delivery_date",
	"pickup_location",
	"pickup_address",
	"delivery_location",
	"delivery_address",
	"assigned_vehicle",
	"assigned_driver",
	"transporter",
	"driver_phone",
	"shipping_booking",
	"container_type",
	"container_count",
	"cro_number",
	"cro_date",
	"cutoff_date",
	"gate_cutoff",
	"pull_out_date",
	"security_draft_delivery_note",
	"material_description",
]


def _resolve_vehicle_driver(ts: dict[str, Any]) -> dict[str, Any]:
	"""Resolve Link fields on Transport Schedule into modal-friendly strings."""
	vehicle_number = None
	driver_name = None
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
	return {
		"vehicle_number": vehicle_number,
		"driver_name": driver_name,
		"driver_contact": ts.get("driver_phone"),
	}


def _shipping_booking_summary(sb_name: str | None) -> dict[str, Any]:
	if not sb_name:
		return {}
	return (
		frappe.db.get_value(
			"Shipping Booking",
			sb_name,
			[
				"name",
				"shipping_line",
				"port_of_loading",
				"port_of_discharge",
				"vessel_name",
				"vessel_date",
				"vessel_status",
				"cro_number",
				"cro_date",
				"cro_status",
				"cutoff_date",
				"si_cutoff",
				"gate_cutoff",
				"pull_out_date",
				"container_type",
				"container_count",
				"cargo_description",
				"thc",
				"tluc",
				"export_declaration",
			],
			as_dict=True,
		)
		or {}
	)


def _job_order_summary(jo_name: str) -> dict[str, Any]:
	return (
		frappe.db.get_value(
			"Job Order",
			jo_name,
			[
				"name",
				"job_order_number",
				"commercial_movement",
				"customer",
				"customer_name",
				"supplier",
				"supplier_name",
				"date",
				"status",
				"terms_of_delivery",
				"mode_of_transport",
				"port_of_loading",
				"port_of_discharge",
				"transport_schedule",
				"shipping_booking",
				"transport_status",
				"shipping_status",
				"booking_requirement",
				"loading_remarks",
			],
			as_dict=True,
		)
		or {}
	)


def _display_job_order(value: Any, fallback: str | None = None) -> str:
	"""Return the human-readable job order number when available."""
	jo_name = value if isinstance(value, str) else None
	if not jo_name:
		return fallback or ""
	number = frappe.db.get_value("Job Order", jo_name, "job_order_number")
	return number or jo_name


def _active_transport_for_job_order(
	jo_name: str, transport_type: str | None = None
) -> dict[str, Any] | None:
	"""Latest non-cancelled Transport Schedule for a Job Order.

	When ``transport_type`` is omitted, use the Job Order's ``commercial_movement``
	to pick the primary leg (Outward for Export, Inward for Import).
	"""
	if transport_type:
		ttype = transport_type
	else:
		from apc_operations.shipping.doctype.job_order.job_order import (
			get_primary_transport_type_for_job_order,
		)

		movement = frappe.db.get_value("Job Order", jo_name, "commercial_movement") or "Export"
		ttype = get_primary_transport_type_for_job_order(movement)

	rows = frappe.get_all(
		"Transport Schedule",
		filters={
			"job_order": jo_name,
			"transport_status": ["!=", "Cancelled"],
			"transport_type": ttype,
		},
		fields=_TRANSPORT_FIELDS,
		order_by="modified desc",
		limit=1,
	)
	return rows[0] if rows else None


def _do_for_job_order(jo_name: str) -> dict[str, Any] | None:
	from apc_operations.services.delivery_order_service import (
		find_delivery_order_for_job_order_primary,
	)

	do_name = find_delivery_order_for_job_order_primary(jo_name)
	if not do_name:
		return None
	return frappe.db.get_value(
		"Delivery Order",
		do_name,
		["name", "status", "docstatus", "posting_date", "customer"],
		as_dict=True,
	)


def _sddn_for_transport(ts_name: str | None) -> dict[str, Any] | None:
	if not ts_name:
		return None
	rows = frappe.get_all(
		"Security Draft Delivery Note",
		filters={"transport_schedule": ts_name},
		fields=["name", "security_status", "gate_out_status", "sent_to_security_on"],
		order_by="modified desc",
		limit=1,
	)
	return rows[0] if rows else None


def _security_inspection_for_transport(ts_name: str | None) -> dict[str, Any] | None:
	if not ts_name:
		return None
	rows = frappe.get_all(
		"Security Inspection",
		filters={"transportation_request": ts_name, "docstatus": ["!=", 2]},
		fields=["name", "security_status", "qc_status", "qc_report_request"],
		order_by="modified desc",
		limit=1,
	)
	return rows[0] if rows else None


def _filter_visible(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
	return console_status.filter_visible_transport_statuses(list(rows))


# ---------------------------------------------------------------------------
# Inward Import
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_inward_import_list() -> list[dict[str, Any]]:
	"""Inward Import = Sea-mode Job Orders with inward transport."""
	jos = frappe.get_all(
		"Job Order",
		filters={"status": ["!=", "Cancelled"]},
		fields=[
			"name",
			"job_order_number",
			"commercial_movement",
			"customer",
			"customer_name",
			"date",
			"mode_of_transport",
			"port_of_loading",
			"port_of_discharge",
			"shipping_booking",
			"transport_schedule",
			"transport_status",
			"shipping_status",
			"terms_of_delivery",
		],
		order_by="modified desc",
		limit=200,
	)

	out = []
	for jo in jos:
		if (jo.get("mode_of_transport") or "") != "Sea":
			continue
		if (jo.get("commercial_movement") or "Export") != "Import":
			continue
		# Filter to inward (heuristic: incoterm in EXW/FCA/FOB from APC POV
		# is outward; for now use the existing transport_type via TS).
		ts = _active_transport_for_job_order(jo["name"], "Inward")
		if not ts or (ts.get("transport_type") or "") != "Inward":
			continue
		sb = _shipping_booking_summary(jo.get("shipping_booking"))
		docs_label = console_status.docs_status_label(ts.get("transport_status"))
		vessel_label = console_status.vessel_status_label(sb.get("vessel_status"))
		out.append(
			{
				"name": jo["name"],
				"job_order": jo["name"],
				"job_order_number": jo.get("job_order_number") or jo["name"],
				"customer": jo.get("customer"),
				"customer_name": jo.get("customer_name"),
				"eta": ts.get("scheduled_delivery_date"),
				"docs_status": docs_label,
				"docs_status_tone": console_status.docs_status_tone(docs_label),
				"vessel_status": vessel_label,
				"vessel_status_tone": console_status.vessel_status_tone(vessel_label),
				"transport_status": ts.get("transport_status"),
				"container_number": ts.get("container_type"),
			}
		)
	return out


@frappe.whitelist()
def get_inward_import_detail(job_order: str) -> dict[str, Any]:
	if not job_order:
		frappe.throw(_("job_order is required"))
	jo = _job_order_summary(job_order)
	ts = _active_transport_for_job_order(job_order, "Inward") or {}
	sb = _shipping_booking_summary(jo.get("shipping_booking"))
	docs_label = console_status.docs_status_label(ts.get("transport_status"))
	raw_vessel_status = sb.get("vessel_status") or "In Transit"
	vessel_label = console_status.vessel_status_label(raw_vessel_status)
	vd = _resolve_vehicle_driver(ts)
	sddn = _sddn_for_transport(ts.get("name")) or {}
	inspection = _security_inspection_for_transport(ts.get("name"))
	qc_status = inspection.get("qc_status") if inspection else None
	return {
		"job_order": job_order,
		"job_order_number": jo.get("job_order_number") or job_order,
		"customer": jo.get("customer"),
		"customer_name": jo.get("customer_name"),
		"supplier": jo.get("supplier"),
		"supplier_name": jo.get("supplier_name"),
		"eta": ts.get("scheduled_delivery_date"),
		"port_of_loading": jo.get("port_of_loading") or sb.get("port_of_loading"),
		"port_of_discharge": jo.get("port_of_discharge") or sb.get("port_of_discharge"),
		"shipping_booking": jo.get("shipping_booking"),
		"transport_schedule": ts.get("name"),
		"vessel_name": sb.get("vessel_name"),
		"container_number": ts.get("container_type"),
		"vehicle_number": vd["vehicle_number"],
		"driver_name": vd["driver_name"],
		"driver_contact": vd["driver_contact"],
		"docs_status": docs_label,
		"docs_status_tone": console_status.docs_status_tone(docs_label),
		"vessel_status": vessel_label,
		"vessel_status_value": raw_vessel_status,
		"vessel_status_tone": console_status.vessel_status_tone(vessel_label),
		"vessel_cleared": raw_vessel_status == "Cleared",
		"transport_status": ts.get("transport_status"),
		"transport_booking_label": console_status.transport_booking_label(ts.get("transport_status")),
		"transport_booking_tone": console_status.transport_booking_tone(ts.get("transport_status")),
		"is_transport_booked": console_status.is_transport_booked(ts.get("transport_status")),
		"sddn": sddn.get("name"),
		"sddn_status": console_status.sddn_display_label(sddn.get("security_status")),
		"sddn_status_tone": console_status.sddn_status_tone(sddn.get("security_status")),
		"security_inspection": inspection.get("name") if inspection else None,
		"qc_status": qc_status or "Not Sent",
		"remarks": jo.get("loading_remarks"),
		"cutoff_date": sb.get("cutoff_date") or ts.get("cutoff_date"),
	}


@frappe.whitelist()
def update_inward_import_tracking(
	job_order: str,
	vessel_status: str | None = None,
	eta: str | None = None,
	cutoff_date: str | None = None,
	remarks: str | None = None,
) -> dict[str, Any]:
	"""Update import vessel tracking without full Shipping Booking validation.

	Uses server-side ``frappe.db.set_value`` so placeholder bookings (Tracking)
	are not blocked by export-oriented mandatory fields.
	"""
	if not job_order:
		frappe.throw(_("job_order is required"))

	movement = frappe.db.get_value("Job Order", job_order, "commercial_movement") or "Export"
	if movement != "Import":
		frappe.throw(_("Job Order {0} is not an Import movement.").format(job_order))

	mode = frappe.db.get_value("Job Order", job_order, "mode_of_transport") or ""
	if mode != "Sea":
		frappe.throw(_("Inward Import tracking applies only to sea Import Job Orders."))

	allowed_vessel = {"", "In Transit", "Berthed", "Cleared"}
	if vessel_status is not None and vessel_status not in allowed_vessel:
		frappe.throw(_("Invalid vessel status: {0}").format(vessel_status))

	sb_name = frappe.db.get_value("Job Order", job_order, "shipping_booking")
	if vessel_status and sb_name:
		frappe.db.set_value(
			"Shipping Booking",
			sb_name,
			"vessel_status",
			vessel_status,
			update_modified=True,
		)

	ts_row = _active_transport_for_job_order(job_order, "Inward")
	if eta and ts_row and ts_row.get("name"):
		frappe.db.set_value(
			"Transport Schedule",
			ts_row["name"],
			"scheduled_delivery_date",
			eta,
			update_modified=True,
		)

	if cutoff_date and sb_name:
		frappe.db.set_value(
			"Shipping Booking",
			sb_name,
			"cutoff_date",
			cutoff_date,
			update_modified=True,
		)
		if ts_row and ts_row.get("name"):
			frappe.db.set_value(
				"Transport Schedule",
				ts_row["name"],
				"cutoff_date",
				cutoff_date,
				update_modified=True,
			)

	if remarks is not None:
		frappe.db.set_value(
			"Job Order",
			job_order,
			"loading_remarks",
			remarks,
			update_modified=True,
		)

	if vessel_status == "Cleared" and ts_row and ts_row.get("name"):
		ts_doc = frappe.get_doc("Transport Schedule", ts_row["name"])
		ts_doc.ensure_inward_follow_up_records()

	return get_inward_import_detail(job_order)


# ---------------------------------------------------------------------------
# Inward Land
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_inward_land_list() -> list[dict[str, Any]]:
	rows = frappe.get_all(
		"Transport Schedule",
		filters={"transport_type": "Inward", "transport_status": ["!=", "Cancelled"]},
		fields=_TRANSPORT_FIELDS,
		order_by="modified desc",
		limit=200,
	)
	rows = _filter_visible(rows)
	out = []
	for ts in rows:
		# Drop sea-mode inward (handled by Inward Import).
		jo_mode = frappe.db.get_value("Job Order", ts.get("job_order"), "mode_of_transport") if ts.get("job_order") else None
		if jo_mode == "Sea":
			continue
		vd = _resolve_vehicle_driver(ts)
		out.append(
			{
				"name": ts.get("job_order") or ts["name"],
				"job_order": ts.get("job_order"),
				"job_order_number": ts.get("job_order_number") or ts.get("job_order") or ts["name"],
				"customer": ts.get("customer"),
				"customer_name": ts.get("customer_name"),
				"pull_out_date": ts.get("pull_out_date") or ts.get("scheduled_pickup_date"),
				"origin": ts.get("pickup_location") or ts.get("pickup_address"),
				"destination": ts.get("delivery_location") or ts.get("delivery_address"),
				"transport_status": ts.get("transport_status"),
				"transport_status_tone": console_status.transport_booking_tone(ts.get("transport_status")),
				"vehicle_number": vd["vehicle_number"],
				"driver_name": vd["driver_name"],
			}
		)
	return out


@frappe.whitelist()
def get_inward_land_detail(job_order: str) -> dict[str, Any]:
	if not job_order:
		frappe.throw(_("job_order is required"))
	jo = _job_order_summary(job_order)
	ts = _active_transport_for_job_order(job_order, "Inward") or {}
	vd = _resolve_vehicle_driver(ts)
	return {
		"job_order": job_order,
		"job_order_number": jo.get("job_order_number") or job_order,
		"customer": jo.get("customer"),
		"customer_name": jo.get("customer_name"),
		"transport_schedule": ts.get("name"),
		"pull_out_date": ts.get("pull_out_date") or ts.get("scheduled_pickup_date"),
		"origin": ts.get("pickup_location") or ts.get("pickup_address"),
		"destination": ts.get("delivery_location") or ts.get("delivery_address"),
		"current_location": ts.get("pickup_location"),
		"vehicle": ts.get("assigned_vehicle"),
		"vehicle_number": vd["vehicle_number"],
		"driver": ts.get("assigned_driver"),
		"driver_name": vd["driver_name"],
		"driver_contact": vd["driver_contact"],
		"transport_status": ts.get("transport_status"),
		"transport_status_tone": console_status.transport_booking_tone(ts.get("transport_status")),
		"remarks": ts.get("material_description"),
	}


# ---------------------------------------------------------------------------
# Outward — Local Deliveries
# ---------------------------------------------------------------------------


def _outward_rows(outward_type_filter: str | list[str] | None = None) -> list[dict[str, Any]]:
	filters: dict[str, Any] = {
		"transport_type": "Outward",
		"transport_status": ["!=", "Cancelled"],
	}
	if outward_type_filter:
		filters["outward_type"] = (
			["in", outward_type_filter] if isinstance(outward_type_filter, list) else outward_type_filter
		)
	rows = frappe.get_all(
		"Transport Schedule",
		filters=filters,
		fields=_TRANSPORT_FIELDS,
		order_by="modified desc",
		limit=400,
	)
	return _filter_visible(rows)


@frappe.whitelist()
def get_local_delivery_list() -> list[dict[str, Any]]:
	rows = _outward_rows(["Local Delivery", "Tanker Delivery", "Trailer Delivery"])
	out = []
	for ts in rows:
		sddn = _sddn_for_transport(ts.get("name")) or {}
		out.append(
			{
				"name": ts.get("job_order") or ts["name"],
				"job_order": ts.get("job_order"),
				"job_order_number": ts.get("job_order_number") or ts.get("job_order") or ts["name"],
				"customer": ts.get("customer"),
				"customer_name": ts.get("customer_name"),
				"delivery_location": ts.get("delivery_location") or ts.get("delivery_address"),
				"scheduled_delivery_date": ts.get("scheduled_delivery_date"),
				"transport_status": ts.get("transport_status"),
				"transport_booking_label": console_status.transport_booking_label(ts.get("transport_status")),
				"transport_booking_tone": console_status.transport_booking_tone(ts.get("transport_status")),
				"sddn_status": console_status.sddn_display_label(sddn.get("security_status")),
				"sddn_status_tone": console_status.sddn_status_tone(sddn.get("security_status")),
				"sddn": sddn.get("name"),
			}
		)
	return out


@frappe.whitelist()
def get_local_delivery_detail(job_order: str) -> dict[str, Any]:
	if not job_order:
		frappe.throw(_("job_order is required"))
	jo = _job_order_summary(job_order)
	ts = _active_transport_for_job_order(job_order, "Outward") or {}
	vd = _resolve_vehicle_driver(ts)
	sddn = _sddn_for_transport(ts.get("name")) or {}
	do = _do_for_job_order(job_order) or {}
	return {
		"job_order": job_order,
		"job_order_number": jo.get("job_order_number") or job_order,
		"customer": jo.get("customer"),
		"customer_name": jo.get("customer_name"),
		"delivery_location": ts.get("delivery_location") or ts.get("delivery_address"),
		"scheduled_delivery_date": ts.get("scheduled_delivery_date"),
		"transport_schedule": ts.get("name"),
		"vehicle_number": vd["vehicle_number"],
		"driver_name": vd["driver_name"],
		"driver_contact": vd["driver_contact"],
		"transport_status": ts.get("transport_status"),
		"transport_booking_label": console_status.transport_booking_label(ts.get("transport_status")),
		"transport_booking_tone": console_status.transport_booking_tone(ts.get("transport_status")),
		"is_transport_booked": console_status.is_transport_booked(ts.get("transport_status")),
		"sddn": sddn.get("name"),
		"sddn_status": console_status.sddn_display_label(sddn.get("security_status")),
		"sddn_status_tone": console_status.sddn_status_tone(sddn.get("security_status")),
		"do_status": console_status.do_display_label(do),
		"do_status_tone": console_status.do_status_tone(console_status.do_display_label(do)),
		"do_name": do.get("name"),
	}


# ---------------------------------------------------------------------------
# Outward — Export Containers
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_export_container_list() -> list[dict[str, Any]]:
	rows = _outward_rows("Export Container")
	out = []
	for ts in rows:
		sb = _shipping_booking_summary(ts.get("shipping_booking"))
		sddn = _sddn_for_transport(ts.get("name")) or {}
		do = _do_for_job_order(ts.get("job_order")) if ts.get("job_order") else None
		out.append(
			{
				"name": ts.get("job_order") or ts["name"],
				"job_order": ts.get("job_order"),
				"job_order_number": ts.get("job_order_number") or ts.get("job_order") or ts["name"],
				"customer": ts.get("customer"),
				"customer_name": ts.get("customer_name"),
				"cro_number": sb.get("cro_number") or ts.get("cro_number"),
				"shipping_line": sb.get("shipping_line"),
				"pol": sb.get("port_of_loading"),
				"pod": sb.get("port_of_discharge"),
				"transport_status": ts.get("transport_status"),
				"transport_booking_label": console_status.transport_booking_label(ts.get("transport_status")),
				"transport_booking_tone": console_status.transport_booking_tone(ts.get("transport_status")),
				"sddn_status": console_status.sddn_display_label(sddn.get("security_status")),
				"sddn_status_tone": console_status.sddn_status_tone(sddn.get("security_status")),
				"do_status": console_status.do_display_label(do),
				"do_status_tone": console_status.do_status_tone(console_status.do_display_label(do)),
				"sddn": sddn.get("name"),
			}
		)
	return out


@frappe.whitelist()
def get_export_container_detail(job_order: str) -> dict[str, Any]:
	if not job_order:
		frappe.throw(_("job_order is required"))
	jo = _job_order_summary(job_order)
	ts = _active_transport_for_job_order(job_order, "Outward") or {}
	sb = _shipping_booking_summary(ts.get("shipping_booking") or jo.get("shipping_booking"))
	vd = _resolve_vehicle_driver(ts)
	sddn = _sddn_for_transport(ts.get("name")) or {}
	do = _do_for_job_order(job_order) or {}
	return {
		"job_order": job_order,
		"job_order_number": jo.get("job_order_number") or job_order,
		"customer": jo.get("customer"),
		"customer_name": jo.get("customer_name"),
		"shipping_booking": sb.get("name"),
		"cro_number": sb.get("cro_number"),
		"cro_date": sb.get("cro_date"),
		"shipping_line": sb.get("shipping_line"),
		"pol": sb.get("port_of_loading"),
		"pod": sb.get("port_of_discharge"),
		"vessel": sb.get("vessel_name"),
		"vessel_status": console_status.vessel_status_label(sb.get("vessel_status")),
		"vessel_status_tone": console_status.vessel_status_tone(sb.get("vessel_status")),
		"etd": sb.get("vessel_date"),
		"si_cutoff": sb.get("si_cutoff"),
		"gate_cutoff": sb.get("gate_cutoff"),
		"pull_out_date": sb.get("pull_out_date"),
		"container_number": ts.get("container_type"),
		"container_type": ts.get("container_type"),
		"transport_schedule": ts.get("name"),
		"transport_status": ts.get("transport_status"),
		"transport_booking_label": console_status.transport_booking_label(ts.get("transport_status")),
		"transport_booking_tone": console_status.transport_booking_tone(ts.get("transport_status")),
		"is_transport_booked": console_status.is_transport_booked(ts.get("transport_status")),
		"can_generate_do": console_status.can_generate_delivery_order(ts.get("transport_status")),
		"vehicle_number": vd["vehicle_number"],
		"driver_name": vd["driver_name"],
		"driver_contact": vd["driver_contact"],
		"sddn": sddn.get("name"),
		"sddn_status": console_status.sddn_display_label(sddn.get("security_status")),
		"sddn_status_tone": console_status.sddn_status_tone(sddn.get("security_status")),
		"do_status": console_status.do_display_label(do),
		"do_status_tone": console_status.do_status_tone(console_status.do_display_label(do)),
		"do_name": do.get("name"),
	}


# ---------------------------------------------------------------------------
# Pending counts
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_transportation_pending_counts() -> dict[str, int]:
	pending_transport = frappe.db.count(
		"Transport Schedule",
		filters={
			"transport_type": "Outward",
			"transport_status": ["in", ["Draft", "Pending Assignment"]],
		},
	)
	pending_sddn = frappe.db.count(
		"Security Draft Delivery Note",
		filters={"security_status": ["in", ["Draft", "Pending Review", "Pending Verification"]]},
	)
	# Pending DOs: export rows with transport booked but no Delivery Order per JO.
	export_rows = _outward_rows("Export Container")
	pending_do = 0
	seen_jo: set[str] = set()
	for ts in export_rows:
		if not console_status.is_transport_booked(ts.get("transport_status")):
			continue
		jo = ts.get("job_order")
		if not jo or jo in seen_jo:
			continue
		seen_jo.add(jo)
		if not _do_for_job_order(jo):
			pending_do += 1
	return {
		"transport": pending_transport,
		"do": pending_do,
		"sddn": pending_sddn,
	}


# ---------------------------------------------------------------------------
# Book / re-book Transport Schedule (assignment + pricing)
# ---------------------------------------------------------------------------


_BOOKING_DETAIL_FIELDS = [
	"name",
	"transport_status",
	"shipping_booking",
	"transporter",
	"assigned_vehicle",
	"assigned_driver",
	"driver_phone",
	"transport_charges",
	"fuel_cost",
	"additional_charges",
	"currency",
	"total_cost",
	"gate_cutoff",
	"cutoff_date",
]


@frappe.whitelist()
def get_transport_schedule_booking_detail(name: str) -> dict[str, Any]:
	"""Pre-populate the 'Book Transport' dialog.

	Returns the assignment + pricing fields currently on the Transport
	Schedule plus the derived booking label/tone so the dialog can show
	whether it's an initial booking or an edit.
	"""
	if not name:
		frappe.throw(_("name is required"))

	ts = frappe.db.get_value(
		"Transport Schedule", name, _BOOKING_DETAIL_FIELDS, as_dict=True
	)
	if not ts:
		frappe.throw(_("Transport Schedule {0} not found").format(name))

	vd = _resolve_vehicle_driver(ts)
	sb_name = ts.get("shipping_booking")
	sb_si_cutoff = None
	sb_gate_cutoff = None
	if sb_name:
		bk = frappe.db.get_value(
			"Shipping Booking",
			sb_name,
			["si_cutoff", "gate_cutoff"],
			as_dict=True,
		)
		if bk:
			sb_si_cutoff = bk.get("si_cutoff")
			sb_gate_cutoff = bk.get("gate_cutoff")
	# Transporter autonames from company_name, so ``ts.transporter`` already
	# IS the human-readable transporter name — no separate lookup needed.

	return {
		"name": ts.get("name"),
		"transport_status": ts.get("transport_status"),
		"transport_booking_label": console_status.transport_booking_label(
			ts.get("transport_status")
		),
		"transport_booking_tone": console_status.transport_booking_tone(
			ts.get("transport_status")
		),
		"is_transport_booked": console_status.is_transport_booked(
			ts.get("transport_status")
		),
		"transporter": ts.get("transporter"),
		"transporter_name": ts.get("transporter"),
		"assigned_vehicle": ts.get("assigned_vehicle"),
		"vehicle_number": vd["vehicle_number"],
		"assigned_driver": ts.get("assigned_driver"),
		"driver_name": vd["driver_name"],
		"driver_phone": ts.get("driver_phone"),
		"shipping_booking": sb_name,
		"si_cutoff": sb_si_cutoff,
		"gate_cutoff": ts.get("gate_cutoff") or sb_gate_cutoff,
		"cutoff_date": ts.get("cutoff_date"),
		"transport_charges": ts.get("transport_charges"),
		"fuel_cost": ts.get("fuel_cost"),
		"additional_charges": ts.get("additional_charges"),
		"currency": ts.get("currency") or "USD",
		"total_cost": ts.get("total_cost"),
	}


_BOOKING_WRITABLE_FIELDS = [
	"transporter",
	"assigned_vehicle",
	"assigned_driver",
	"driver_phone",
	"gate_cutoff",
	"transport_charges",
	"fuel_cost",
	"additional_charges",
	"currency",
]


@frappe.whitelist()
def book_transport_schedule(
	transport_schedule: str,
	transporter: str | None = None,
	assigned_vehicle: str | None = None,
	assigned_driver: str | None = None,
	driver_phone: str | None = None,
	transport_charges: float | None = None,
	fuel_cost: float | None = None,
	additional_charges: float | None = None,
	currency: str | None = None,
	si_cutoff: str | None = None,
	gate_cutoff: str | None = None,
) -> dict[str, Any]:
	"""Book (or re-book) transport assignment + pricing for a Transport Schedule.

	The Transport Schedule controller's ``update_status_from_assignment``
	auto-flips ``transport_status`` from Draft / Pending Assignment up to
	Vehicle Assigned / Driver Assigned / Scheduled depending on which of
	(assigned_vehicle, assigned_driver, transporter) become non-empty.
	The downstream hooks (``transport_events.on_transport_update``) then
	sync the new status to Job Order + Shipping Booking.

	We require at least one of vehicle / driver / transporter on first
	booking, unless the caller only updates SI/Gate cutoffs (when a Shipping
	Booking is linked), Gate cutoff on the Transport Schedule, or driver
	contact. If the TS is already booked we accept pricing-only edits.
	"""
	if not transport_schedule:
		frappe.throw(_("transport_schedule is required"))

	current_status = frappe.db.get_value(
		"Transport Schedule", transport_schedule, "transport_status"
	)
	if not current_status:
		frappe.throw(
			_("Transport Schedule {0} not found").format(transport_schedule)
		)
	if current_status == "Cancelled":
		frappe.throw(_("Cannot book a cancelled Transport Schedule."))

	already_booked = console_status.is_transport_booked(current_status)

	sb_name_for_cutoffs = frappe.db.get_value(
		"Transport Schedule", transport_schedule, "shipping_booking"
	)
	cutoff_updates: dict[str, Any] = {}
	if sb_name_for_cutoffs:
		if si_cutoff is not None and str(si_cutoff).strip() != "":
			cutoff_updates["si_cutoff"] = si_cutoff
		if gate_cutoff is not None and str(gate_cutoff).strip() != "":
			cutoff_updates["gate_cutoff"] = gate_cutoff

	if sb_name_for_cutoffs and cutoff_updates:
		sb_doc = frappe.get_doc("Shipping Booking", sb_name_for_cutoffs)
		sb_doc.update(cutoff_updates)
		sb_doc.save()

	if not already_booked and not any(
		[transporter, assigned_vehicle, assigned_driver]
	):
		has_aux = bool(cutoff_updates) or (
			gate_cutoff is not None and str(gate_cutoff).strip() != ""
		) or (driver_phone is not None)
		if not has_aux:
			frappe.throw(
				_(
					"Set at least one of Vehicle, Driver, or Transporter to book this transport."
				)
			)

	# Build payload — only forward fields the caller actually included so
	# callers can do pricing-only or assignment-only updates without
	# clobbering the other half.
	provided = {
		"transporter": transporter,
		"assigned_vehicle": assigned_vehicle,
		"assigned_driver": assigned_driver,
		"transport_charges": transport_charges,
		"fuel_cost": fuel_cost,
		"additional_charges": additional_charges,
		"currency": currency,
	}
	if driver_phone is not None:
		provided["driver_phone"] = driver_phone
	if gate_cutoff is not None and str(gate_cutoff).strip() != "":
		provided["gate_cutoff"] = gate_cutoff

	payload: dict[str, Any] = {}
	for k, v in provided.items():
		if k == "driver_phone":
			if driver_phone is not None:
				payload[k] = v
			continue
		if v is not None and v != "":
			payload[k] = v

	if payload or cutoff_updates:
		# IMPORTANT: ``frappe.db.set_value`` (server-side Python) is a raw
		# SQL update — it does NOT fire ``before_save`` / ``validate``, so
		# ``update_status_from_assignment`` never runs and the booking stays
		# stuck at "Pending Assignment". We need ``doc.save()`` to trigger
		# the full controller pipeline (validate → before_save → on_update),
		# which is what flips the TS status and cascades to JO + Shipping
		# Booking via the transport_events hook.
		doc = frappe.get_doc("Transport Schedule", transport_schedule)
		if payload:
			doc.update(payload)
		doc.save()
		new_status = doc.transport_status
	else:
		new_status = current_status

	return {
		"transport_schedule": transport_schedule,
		"transport_status": new_status,
		"transport_booking_label": console_status.transport_booking_label(new_status),
		"transport_booking_tone": console_status.transport_booking_tone(new_status),
		"is_transport_booked": console_status.is_transport_booked(new_status),
	}


# ---------------------------------------------------------------------------
# Create + send SDDN
# ---------------------------------------------------------------------------


@frappe.whitelist()
def create_security_delivery_draft_note(job_order: str) -> dict[str, Any]:
	"""Create (or fetch) the SDDN for the active Transport Schedule of a Job Order."""
	if not job_order:
		frappe.throw(_("job_order is required"))

	movement = frappe.db.get_value("Job Order", job_order, "commercial_movement") or "Export"
	transport_type = "Inward" if movement == "Import" else "Outward"
	ts_row = _active_transport_for_job_order(job_order, transport_type)
	if not ts_row:
		frappe.throw(
			_("No active {0} Transport Schedule found for Job Order {1}").format(
				transport_type, job_order
			)
		)
	if movement == "Import" and transport_type == "Inward":
		sb_name = frappe.db.get_value("Job Order", job_order, "shipping_booking")
		if sb_name:
			vessel_status = frappe.db.get_value("Shipping Booking", sb_name, "vessel_status")
			if (vessel_status or "").strip() != "Cleared":
				frappe.throw(
					_(
						"Set Shipping Booking vessel status to Cleared before creating "
						"the security draft for this import."
					)
				)
	if not ts_row.get("assigned_vehicle") or not ts_row.get("assigned_driver"):
		frappe.throw(
			_(
				"Vehicle and Driver must be assigned on Transport Schedule {0} before creating the SDDN."
			).format(ts_row["name"])
		)

	ts_doc = frappe.get_doc("Transport Schedule", ts_row["name"])
	sddn_name = ts_doc.create_security_draft_delivery_note()

	if sddn_name:
		try:
			frappe.get_doc(
				{
					"doctype": "Comment",
					"comment_type": "Comment",
					"reference_doctype": "Job Order",
					"reference_name": job_order,
					"content": _("SDDN created: {0}").format(sddn_name),
				}
			).insert(ignore_permissions=True)
		except Exception:
			pass

	return {
		"sddn": sddn_name,
		"transport_schedule": ts_doc.name,
		"job_order": job_order,
	}


@frappe.whitelist()
def send_security_delivery_draft_note_to_security(sddn: str) -> dict[str, Any]:
	if not sddn:
		frappe.throw(_("sddn is required"))
	if not frappe.db.exists("Security Draft Delivery Note", sddn):
		frappe.throw(_("SDDN {0} not found").format(sddn))

	frappe.db.set_value(
		"Security Draft Delivery Note",
		sddn,
		{
			"security_status": "Sent to Security",
			"sent_to_security_on": now_datetime(),
		},
		update_modified=True,
	)

	try:
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "Security Draft Delivery Note",
				"reference_name": sddn,
				"content": _("SDDN sent to Security"),
			}
		).insert(ignore_permissions=True)
	except Exception:
		pass

	return {
		"sddn": sddn,
		"security_status": "Sent to Security",
	}
