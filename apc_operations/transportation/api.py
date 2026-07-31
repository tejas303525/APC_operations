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
from frappe.utils import cint, flt, getdate, now_datetime, today

from apc_operations.services import console_status
from apc_operations.services.delivery_order_service import (
	find_delivery_order_for_transport_schedule,
	find_open_delivery_order_for_transport_schedule,
)
from apc_operations.shipping.services.delivery_order_generation_service import (
	get_followup_delivery_order_eligibility,
)
from apc_operations.shipping.services.job_order_sync_service import (
	attach_job_order_product_summary,
	attach_live_job_order_numbers,
)
from apc_operations.shipping.services.partial_dispatch_service import (
	get_active_outward_transport,
	get_partial_dispatch_summary,
	has_issued_loading_delivery_note,
	job_order_dispatched_quantity,
	job_order_order_quantity,
)
from apc_operations.services.console_queue_service import enrich_and_sort_console_queue


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
	"inward_import_leg",
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
				"third_party_loading",
				"third_party_loader",
				"third_party_loading_location",
				"third_party_loading_notes",
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

		movement = frappe.db.get_value("Job Order", jo_name, "commercial_movement") or "Outward"
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


def _do_for_transport_schedule(ts_name: str | None) -> dict[str, Any] | None:
	from apc_operations.services.delivery_order_service import (
		find_delivery_order_for_transport_schedule,
	)

	do_name = find_delivery_order_for_transport_schedule(ts_name)
	if not do_name:
		return None
	return frappe.db.get_value(
		"Delivery Order",
		do_name,
		["name", "status", "docstatus", "posting_date", "customer", "operational_status"],
		as_dict=True,
	)


def _do_for_job_order(jo_name: str) -> dict[str, Any] | None:
	ts = _active_transport_for_job_order(jo_name, "Outward")
	if ts and ts.get("name"):
		do = _do_for_transport_schedule(ts.get("name"))
		if do:
			return do
	from apc_operations.services.delivery_order_service import (
		find_delivery_order_for_job_order_primary,
	)

	do_name = find_delivery_order_for_job_order_primary(jo_name)
	if not do_name:
		return None
	return frappe.db.get_value(
		"Delivery Order",
		do_name,
		["name", "status", "docstatus", "posting_date", "customer", "operational_status"],
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
		if (jo.get("commercial_movement") or "Outward") != "Import":
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
	attach_job_order_product_summary(out)
	return enrich_and_sort_console_queue(out)


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
	do = _do_for_job_order(job_order) or {}
	handoff = {}
	try:
		from apc_operations.shipping.services.import_handoff_service import (
			get_import_handoff_status,
		)

		handoff = get_import_handoff_status(job_order)
	except Exception:
		handoff = {}
	return {
		"job_order": job_order,
		"commercial_movement": jo.get("commercial_movement") or "Import",
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
		"do_name": do.get("name"),
		"do_status": console_status.do_display_label(do),
		"do_status_tone": console_status.do_status_tone(console_status.do_display_label(do)),
		"can_generate_do": console_status.can_generate_delivery_order(ts.get("transport_status")),
		"linked_export_job_order": handoff.get("linked_export_job_order")
		or jo.get("linked_export_job_order"),
		"can_link_export": handoff.get("can_link_export"),
		"can_create_export": handoff.get("can_create_export"),
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

	movement = frappe.db.get_value("Job Order", job_order, "commercial_movement") or "Outward"
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
	attach_live_job_order_numbers(out)
	attach_job_order_product_summary(out)
	return enrich_and_sort_console_queue(out)


@frappe.whitelist()
def get_inward_land_detail(job_order: str) -> dict[str, Any]:
	if not job_order:
		frappe.throw(_("job_order is required"))
	jo = _job_order_summary(job_order)
	ts = _active_transport_for_job_order(job_order, "Inward") or {}
	vd = _resolve_vehicle_driver(ts)
	do = _do_for_transport_schedule(ts.get("name")) or _do_for_job_order(job_order) or {}
	sddn = _sddn_for_transport(ts.get("name")) or {}
	inspection = _security_inspection_for_transport(ts.get("name"))
	qc_status = inspection.get("qc_status") if inspection else None
	movement = (jo.get("commercial_movement") or "Outward").strip()
	handoff = {}
	if movement == "Import":
		try:
			from apc_operations.shipping.services.import_handoff_service import (
				get_import_handoff_status,
			)

			handoff = get_import_handoff_status(job_order)
		except Exception:
			handoff = {}
	return {
		"job_order": job_order,
		"commercial_movement": movement,
		"job_order_number": jo.get("job_order_number") or job_order,
		"customer": jo.get("customer"),
		"customer_name": jo.get("customer_name"),
		"supplier": jo.get("supplier"),
		"supplier_name": jo.get("supplier_name"),
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
		"transport_booking_label": console_status.transport_booking_label(ts.get("transport_status")),
		"transport_booking_tone": console_status.transport_booking_tone(ts.get("transport_status")),
		"is_transport_booked": console_status.is_transport_booked(ts.get("transport_status")),
		"do_name": do.get("name"),
		"do_status": console_status.do_display_label(do),
		"do_status_tone": console_status.do_status_tone(console_status.do_display_label(do)),
		"do_operational_status": do.get("operational_status") if do else None,
		"can_generate_do": console_status.can_generate_delivery_order(ts.get("transport_status")),
		"sddn": sddn.get("name"),
		"sddn_status": console_status.sddn_display_label(sddn.get("security_status")),
		"sddn_status_tone": console_status.sddn_status_tone(sddn.get("security_status")),
		"security_inspection": inspection.get("name") if inspection else None,
		"qc_status": qc_status or "Not Sent",
		"linked_export_job_order": handoff.get("linked_export_job_order")
		or jo.get("linked_export_job_order"),
		"can_link_export": handoff.get("can_link_export"),
		"can_create_export": handoff.get("can_create_export"),
		"remarks": ts.get("material_description") or jo.get("loading_remarks"),
	}


# ---------------------------------------------------------------------------
# Outward — Local Deliveries
# ---------------------------------------------------------------------------


_LOCAL_OUTWARD_TYPES = frozenset({"Local Delivery", "Tanker Delivery", "Trailer Delivery"})


def _filter_stale_outward_type(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
	"""Drop rows whose Transport Schedule.outward_type no longer matches the
	Job Order's CURRENT shipment_type - e.g. a "Local Delivery" leg left
	over from before the Job Order was switched to Export never gets
	updated or cancelled, so it kept showing as a duplicate card under
	Local Deliveries even after an Export Container leg existed."""
	if not rows:
		return rows

	job_orders = {r.get("job_order") for r in rows if r.get("job_order")}
	if not job_orders:
		return rows

	shipment_types = dict(
		frappe.get_all(
			"Job Order",
			filters={"name": ["in", list(job_orders)]},
			fields=["name", "shipment_type"],
			as_list=True,
		)
	)

	out = []
	for row in rows:
		current = shipment_types.get(row.get("job_order")) if row.get("job_order") else None
		outward_type = (row.get("outward_type") or "").strip()
		if current == "Local" and outward_type and outward_type not in _LOCAL_OUTWARD_TYPES:
			continue
		if current == "Export" and outward_type and outward_type != "Export Container":
			continue
		out.append(row)
	return out


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
	return _filter_stale_outward_type(_filter_visible(rows))


@frappe.whitelist()
def get_local_delivery_list() -> list[dict[str, Any]]:
	rows = _outward_rows(["Local Delivery", "Tanker Delivery", "Trailer Delivery"])
	out = []
	for ts in rows:
		sddn = _sddn_for_transport(ts.get("name")) or {}
		do = _do_for_job_order(ts.get("job_order")) if ts.get("job_order") else None
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
				"do_status": console_status.do_display_label(do),
				"do_status_tone": console_status.do_status_tone(console_status.do_display_label(do)),
			}
		)
	attach_live_job_order_numbers(out)
	attach_job_order_product_summary(out)
	return enrich_and_sort_console_queue(out)


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
		"do_operational_status": do.get("operational_status") if do else None,
		"can_generate_do": console_status.can_generate_delivery_order(ts.get("transport_status"))
		and not (do and do.get("name")),
		"third_party_loading": jo.get("third_party_loading"),
		"third_party_loader": jo.get("third_party_loader"),
		"third_party_loading_location": jo.get("third_party_loading_location"),
		"third_party_loading_notes": jo.get("third_party_loading_notes"),
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
	attach_live_job_order_numbers(out)
	attach_job_order_product_summary(out)
	return enrich_and_sort_console_queue(out)


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
		"do_name": do.get("name") if do else None,
		"do_operational_status": do.get("operational_status") if do else None,
		"can_generate_do": console_status.can_generate_delivery_order(ts.get("transport_status"))
		and not (do and do.get("name")),
		"third_party_loading": jo.get("third_party_loading"),
		"third_party_loader": jo.get("third_party_loader"),
		"third_party_loading_location": jo.get("third_party_loading_location"),
		"third_party_loading_notes": jo.get("third_party_loading_notes"),
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
		"partial_followup": _count_partial_delivery_followups(),
		"grn_summary": _count_grn_summary_followups(),
	}


# ---------------------------------------------------------------------------
# Partial delivery follow-up (always a new transport leg)
# ---------------------------------------------------------------------------

_COMPLETED_TRANSPORT_STATUSES = frozenset({"Delivered", "Completed"})
_ACTIVE_TRANSPORT_STATUSES = frozenset(
	{
		"Draft",
		"Pending Assignment",
		"Scheduled",
		"Vehicle Assigned",
		"Driver Assigned",
		"Dispatched",
		"Picked Up",
		"Gate In",
		"In Transit",
	}
)


def _job_order_order_quantity(job_order: str) -> float:
	return job_order_order_quantity(job_order)


def _job_order_dispatched_quantity(job_order: str) -> float:
	return job_order_dispatched_quantity(job_order)


def _partial_dispatch_summary(job_order: str) -> dict[str, Any] | None:
	return get_partial_dispatch_summary(job_order)


def _latest_outward_transport(job_order: str, statuses: Iterable[str] | None = None) -> dict[str, Any] | None:
	filters: dict[str, Any] = {
		"job_order": job_order,
		"transport_type": "Outward",
		"transport_status": ["!=", "Cancelled"],
	}
	if statuses:
		filters["transport_status"] = ["in", list(statuses)]
	rows = frappe.get_all(
		"Transport Schedule",
		filters=filters,
		fields=_TRANSPORT_FIELDS,
		order_by="modified desc",
		limit=1,
	)
	return rows[0] if rows else None


def _reference_outward_transport_for_followup(job_order: str) -> dict[str, Any] | None:
	"""Prefer a completed leg for copy defaults; fall back to the latest outward leg."""
	return (
		_latest_outward_transport(job_order, _COMPLETED_TRANSPORT_STATUSES)
		or _latest_outward_transport(job_order)
	)


def _has_issued_loading_delivery_note(job_order: str) -> bool:
	return has_issued_loading_delivery_note(job_order)


def _partial_followup_row(jo: dict[str, Any]) -> dict[str, Any] | None:
	dispatch = _partial_dispatch_summary(jo["name"])
	if not dispatch:
		return None

	if not _has_issued_loading_delivery_note(jo["name"]):
		return None

	reference_ts = _reference_outward_transport_for_followup(jo["name"])
	if not reference_ts:
		return None

	active_ts = _latest_outward_transport(jo["name"], _ACTIVE_TRANSPORT_STATUSES)
	completed_ts = _latest_outward_transport(jo["name"], _COMPLETED_TRANSPORT_STATUSES)

	return {
		"name": jo["name"],
		"job_order": jo["name"],
		"job_order_number": jo.get("job_order_number") or jo["name"],
		"customer": jo.get("customer"),
		"customer_name": jo.get("customer_name"),
		"delivery_location": reference_ts.get("delivery_location")
		or reference_ts.get("delivery_address")
		or jo.get("port_of_discharge"),
		"outward_type": reference_ts.get("outward_type"),
		"job_order_quantity": dispatch["job_order_quantity"],
		"total_demand_quantity": dispatch["total_demand_quantity"],
		"total_dispatched_quantity": dispatch["total_dispatched_quantity"],
		"pending_dispatch_quantity": dispatch["pending_dispatch_quantity"],
		"sales_demand": dispatch.get("sales_demand"),
		"last_completed_transport": (completed_ts or reference_ts).get("name"),
		"last_completed_transport_status": (completed_ts or reference_ts).get(
			"transport_status"
		),
		"last_transport_schedule": reference_ts.get("name"),
		"last_transport_status": reference_ts.get("transport_status"),
		"active_transport_schedule": active_ts.get("name") if active_ts else None,
		"active_transport_status": active_ts.get("transport_status") if active_ts else None,
		"followup_needed": flt(dispatch["pending_dispatch_quantity"]) > 0,
	}


def _count_partial_delivery_followups() -> int:
	rows = get_partial_delivery_followup_list(only_actionable=1)
	return len(rows)


@frappe.whitelist()
def get_partial_delivery_followup_list(only_actionable: int | str = 0) -> list[dict[str, Any]]:
	"""Job Orders with partial dispatch after at least one Loading DN is issued."""
	jos = frappe.get_all(
		"Job Order",
		filters={
			"docstatus": ["<", 2],
			"status": ["!=", "Cancelled"],
			"transport_required": 1,
			"commercial_movement": "Outward",
		},
		fields=[
			"name",
			"job_order_number",
			"customer",
			"customer_name",
			"mode_of_transport",
			"port_of_discharge",
			"status",
		],
		order_by="modified desc",
		limit=300,
	)
	out: list[dict[str, Any]] = []
	for jo in jos:
		row = _partial_followup_row(jo)
		if not row:
			continue
		if cint(only_actionable) and not row.get("followup_needed"):
			continue
		out.append(row)
	attach_live_job_order_numbers(out)
	attach_job_order_product_summary(out)
	return enrich_and_sort_console_queue(out)


def _insert_follow_up_transport_schedule(
	jo: frappe.Document,
	*,
	outward_type: str | None = None,
	scheduled_pickup_date: str | None = None,
	scheduled_delivery_date: str | None = None,
	pickup_location: str | None = None,
	delivery_location: str | None = None,
) -> str:
	"""Insert a new Outward Transport Schedule — never reuse an existing leg."""
	reference = _reference_outward_transport_for_followup(jo.name) or {}

	schedule = frappe.new_doc("Transport Schedule")
	schedule.source_document_type = "Job Order"
	schedule.job_order = jo.name
	schedule.customer = jo.customer
	schedule.incoterm = jo.terms_of_delivery
	schedule.port_of_loading = jo.port_of_loading
	schedule.port_of_discharge = jo.port_of_discharge
	schedule.pickup_location = pickup_location or reference.get("pickup_location") or jo.port_of_loading or ""
	schedule.delivery_location = (
		delivery_location or reference.get("delivery_location") or jo.port_of_discharge or ""
	)
	schedule.scheduled_pickup_date = scheduled_pickup_date or jo.date or today()
	schedule.scheduled_delivery_date = scheduled_delivery_date or jo.date or today()
	schedule.transport_status = "Pending Assignment"
	schedule.transport_type = "Outward"
	schedule.outward_type = outward_type or reference.get("outward_type") or jo.get_transport_outward_type()
	if jo.shipping_booking:
		schedule.shipping_booking = jo.shipping_booking
	schedule.material_description = jo.get_material_description()
	schedule.special_instructions = jo.loading_instructions
	schedule.notes = jo.loading_remarks
	schedule.insert(ignore_permissions=True)
	return schedule.name


@frappe.whitelist()
def get_partial_delivery_followup_detail(job_order: str) -> dict[str, Any]:
	if not job_order:
		frappe.throw(_("job_order is required"))

	jo = _job_order_summary(job_order)
	row = _partial_followup_row(jo)
	if not row:
		frappe.throw(
			_("Job Order {0} is not eligible for partial delivery follow-up transport.").format(
				job_order
			)
		)

	completed_ts = _latest_outward_transport(job_order, _COMPLETED_TRANSPORT_STATUSES)
	reference_ts = _reference_outward_transport_for_followup(job_order) or {}
	vd = _resolve_vehicle_driver(completed_ts or reference_ts)

	active_ts = get_active_outward_transport(job_order) or {}
	ts_vd = _resolve_vehicle_driver(active_ts) if active_ts else {}
	sddn = _sddn_for_transport(active_ts.get("name")) or {}

	leg_do_name = find_delivery_order_for_transport_schedule(active_ts.get("name"))
	open_do_name = find_open_delivery_order_for_transport_schedule(active_ts.get("name"))
	do = None
	if leg_do_name:
		do = frappe.db.get_value(
			"Delivery Order",
			leg_do_name,
			["name", "status", "docstatus", "posting_date", "customer", "operational_status"],
			as_dict=True,
		)

	eligibility = get_followup_delivery_order_eligibility(
		job_order, transport_schedule=active_ts.get("name")
	)
	do_label = console_status.do_display_label(do)
	transport_booked = console_status.can_generate_delivery_order(active_ts.get("transport_status"))
	can_issue_standard_do = bool(
		active_ts.get("name") and transport_booked and not leg_do_name
	)
	can_issue_followup = bool(eligibility.get("can_issue_followup_do"))
	pending_qty = flt(row.get("pending_dispatch_quantity"))
	is_partial_remaining = pending_qty > 0 and pending_qty < flt(
		row.get("job_order_quantity") or row.get("total_demand_quantity")
	)

	return {
		**row,
		"terms_of_delivery": jo.get("terms_of_delivery"),
		"commercial_movement": jo.get("commercial_movement") or "Outward",
		"scheduled_pickup_date": (completed_ts or reference_ts).get("scheduled_pickup_date"),
		"scheduled_delivery_date": (completed_ts or reference_ts).get("scheduled_delivery_date"),
		"last_vehicle_number": vd.get("vehicle_number"),
		"last_driver_name": vd.get("driver_name"),
		"transport_schedule": active_ts.get("name"),
		"transport_status": active_ts.get("transport_status"),
		"transport_booking_label": console_status.transport_booking_label(
			active_ts.get("transport_status")
		),
		"transport_booking_tone": console_status.transport_booking_tone(
			active_ts.get("transport_status")
		),
		"is_transport_booked": console_status.is_transport_booked(active_ts.get("transport_status")),
		"vehicle_number": ts_vd.get("vehicle_number"),
		"driver_name": ts_vd.get("driver_name"),
		"driver_contact": ts_vd.get("driver_contact"),
		"sddn": sddn.get("name"),
		"sddn_status": console_status.sddn_display_label(sddn.get("security_status")),
		"sddn_status_tone": console_status.sddn_status_tone(sddn.get("security_status")),
		"do_name": do.get("name") if do else None,
		"do_operational_status": (do.get("operational_status") if do else None),
		"do_status": do_label,
		"do_status_tone": console_status.do_status_tone(do_label),
		"can_issue_followup_do": can_issue_followup,
		"can_generate_do": can_issue_standard_do or can_issue_followup,
		"use_followup_do_issue": is_partial_remaining and can_issue_followup,
		"followup_do_reason": eligibility.get("reason"),
		"needs_followup_transport": bool(eligibility.get("needs_followup_transport")),
		"needs_transport_booking": bool(eligibility.get("needs_transport_booking")),
		"third_party_loading": jo.get("third_party_loading"),
		"third_party_loader": jo.get("third_party_loader"),
		"third_party_loading_location": jo.get("third_party_loading_location"),
		"third_party_loading_notes": jo.get("third_party_loading_notes"),
	}


@frappe.whitelist()
def create_partial_delivery_followup_transport(
	job_order: str,
	outward_type: str | None = None,
	scheduled_pickup_date: str | None = None,
	scheduled_delivery_date: str | None = None,
	pickup_location: str | None = None,
	delivery_location: str | None = None,
	transporter: str | None = None,
	assigned_vehicle: str | None = None,
	assigned_driver: str | None = None,
	driver_phone: str | None = None,
	third_party_loading: int | str | None = None,
	third_party_loader: str | None = None,
	third_party_loading_location: str | None = None,
	third_party_loading_notes: str | None = None,
) -> dict[str, Any]:
	"""Create a new transport leg for partial delivery follow-up (never reuses completed schedule)."""
	if not job_order:
		frappe.throw(_("job_order is required"))

	jo = frappe.get_doc("Job Order", job_order)
	jo.check_permission("write")

	if not _partial_dispatch_summary(job_order):
		frappe.throw(_("This Job Order has no remaining partial-dispatch quantity."))

	if not _has_issued_loading_delivery_note(job_order):
		frappe.throw(
			_("At least one Loading Delivery Note must be issued before scheduling partial follow-up.")
		)

	reference_ts = _reference_outward_transport_for_followup(job_order)
	if not reference_ts:
		frappe.throw(_("At least one outward transport schedule is required before scheduling follow-up."))

	from apc_operations.shipping.transport_events import TRANSPORT_TO_JOB_ORDER_STATUS

	ts_name = _insert_follow_up_transport_schedule(
		jo,
		outward_type=outward_type,
		scheduled_pickup_date=scheduled_pickup_date,
		scheduled_delivery_date=scheduled_delivery_date,
		pickup_location=pickup_location,
		delivery_location=delivery_location,
	)

	jo.db_set("transport_schedule", ts_name, update_modified=False)
	ts_status = frappe.db.get_value("Transport Schedule", ts_name, "transport_status")
	mapped = TRANSPORT_TO_JOB_ORDER_STATUS.get(ts_status, "Pending Booking")
	jo.db_set("transport_status", mapped, update_modified=False)
	if jo.status != "Cancelled":
		jo.db_set("status", "In Progress", update_modified=False)

	if transporter or assigned_vehicle or assigned_driver or driver_phone or third_party_loading is not None:
		book_transport_schedule(
			ts_name,
			transporter=transporter,
			assigned_vehicle=assigned_vehicle,
			assigned_driver=assigned_driver,
			driver_phone=driver_phone,
			third_party_loading=third_party_loading,
			third_party_loader=third_party_loader,
			third_party_loading_location=third_party_loading_location,
			third_party_loading_notes=third_party_loading_notes,
		)
		ts_status = frappe.db.get_value("Transport Schedule", ts_name, "transport_status")

	vd = _resolve_vehicle_driver(
		frappe.db.get_value(
			"Transport Schedule",
			ts_name,
			["assigned_vehicle", "assigned_driver", "driver_phone"],
			as_dict=True,
		)
		or {}
	)
	return {
		"job_order": job_order,
		"job_order_number": jo.job_order_number or job_order,
		"transport_schedule": ts_name,
		"transport_status": ts_status,
		"transport_booking_label": console_status.transport_booking_label(ts_status),
		"driver_name": vd.get("driver_name"),
		"vehicle_number": vd.get("vehicle_number"),
		"is_follow_up_leg": True,
	}


@frappe.whitelist()
def create_partial_delivery_followup_transport_and_issue_do(
	job_order: str,
	outward_type: str | None = None,
	scheduled_pickup_date: str | None = None,
	scheduled_delivery_date: str | None = None,
	pickup_location: str | None = None,
	delivery_location: str | None = None,
	transporter: str | None = None,
	assigned_vehicle: str | None = None,
	assigned_driver: str | None = None,
	driver_phone: str | None = None,
	third_party_loading: int | str | None = None,
	third_party_loader: str | None = None,
	third_party_loading_location: str | None = None,
	third_party_loading_notes: str | None = None,
	quantity: float | None = None,
) -> dict[str, Any]:
	"""One-click "Schedule Follow-up Trip": creates the new transport leg for
	the remaining quantity AND immediately issues its Delivery Order in the
	same call, instead of requiring the user to separately find the new leg
	on the Local Deliveries / Export Containers screen and issue it from
	there - which also made the follow-up leg look like a confusing
	duplicate card on that screen with nothing left to do on it.

	Uses generate_followup_delivery_order_for_job_order() - NOT the plain
	generate_delivery_order_for_job_order() - because a Job Order can only
	ever have one "primary" DO; calling the plain generator here just
	found and silently returned whatever DO already existed for the job
	order (e.g. an older, unrelated dispatch) instead of creating a new one
	tied to this fresh leg.

	Only attempts DO issuance when vehicle/driver/transporter (or
	third-party loading) was actually supplied in this call, since that's
	what makes the fresh leg's Transport Schedule bookable enough for
	generate_followup_delivery_order_for_job_order() to accept it.

	Checks follow-up eligibility (is the prior DO still open?) BEFORE
	creating anything - a Transport Schedule here also cascades a Security
	Draft DN and Transport PO Request via
	TransportSchedule.on_update -> ensure_outward_follow_up_records(), so a
	blocked attempt used to leave that whole trio behind with no DO ever
	attached. Retrying after being blocked would silently pile up
	duplicates instead of surfacing the error.
	"""
	from apc_operations.services.delivery_order_service import (
		find_open_delivery_order_for_job_order,
	)

	open_do = find_open_delivery_order_for_job_order(job_order)
	if open_do:
		frappe.throw(
			_(
				"Delivery Order {0} is still open (dispatch not yet confirmed). "
				"Confirm its dispatch before scheduling another follow-up leg."
			).format(open_do)
		)

	result = create_partial_delivery_followup_transport(
		job_order,
		outward_type=outward_type,
		scheduled_pickup_date=scheduled_pickup_date,
		scheduled_delivery_date=scheduled_delivery_date,
		pickup_location=pickup_location,
		delivery_location=delivery_location,
		transporter=transporter,
		assigned_vehicle=assigned_vehicle,
		assigned_driver=assigned_driver,
		driver_phone=driver_phone,
		third_party_loading=third_party_loading,
		third_party_loader=third_party_loader,
		third_party_loading_location=third_party_loading_location,
		third_party_loading_notes=third_party_loading_notes,
	)

	do_result = None
	do_error = None
	if transporter or assigned_vehicle or assigned_driver or third_party_loading is not None:
		if console_status.can_generate_delivery_order(result.get("transport_status")):
			from apc_operations.shipping.services.delivery_order_generation_service import (
				generate_followup_delivery_order_for_job_order,
			)

			try:
				do_result = generate_followup_delivery_order_for_job_order(
					job_order, transport_schedule=result.get("transport_schedule"), quantity=quantity
				)
			except Exception as e:
				frappe.log_error(frappe.get_traceback(), f"Follow-up DO issue failed for {job_order}")
				do_error = str(e) or _(
					"Follow-up leg was created, but issuing the Delivery Note failed. Issue it manually."
				)
		else:
			do_error = _(
				"Follow-up leg was created, but its status ({0}) isn't bookable yet - issue the "
				"Delivery Note manually once it is."
			).format(result.get("transport_status"))

	result["delivery_order_result"] = do_result
	result["delivery_order_error"] = do_error
	return result


# ---------------------------------------------------------------------------
# Import GRN Summary — partial import receipt follow-up (new inward leg)
# ---------------------------------------------------------------------------


def _latest_inward_transport(
	job_order: str, statuses: Iterable[str] | None = None
) -> dict[str, Any] | None:
	filters: dict[str, Any] = {
		"job_order": job_order,
		"transport_type": "Inward",
		"transport_status": ["!=", "Cancelled"],
	}
	if statuses:
		filters["transport_status"] = ["in", list(statuses)]
	rows = frappe.get_all(
		"Transport Schedule",
		filters=filters,
		fields=_TRANSPORT_FIELDS,
		order_by="modified desc",
		limit=1,
	)
	return rows[0] if rows else None


def _reference_inward_transport_for_followup(job_order: str) -> dict[str, Any] | None:
	"""Prefer a completed inward leg for copy defaults; fall back to the latest inward leg."""
	return (
		_latest_inward_transport(job_order, _COMPLETED_TRANSPORT_STATUSES)
		or _latest_inward_transport(job_order)
	)


def _grn_summary_row(jo: dict[str, Any]) -> dict[str, Any] | None:
	from apc_operations.shipping.services.import_grn_receipt_summary_service import (
		import_grn_rows_for_job_order,
		latest_posted_import_grn,
		partial_import_receipt_summary,
	)

	receipt = partial_import_receipt_summary(jo["name"])
	if not receipt:
		return None

	reference_ts = _reference_inward_transport_for_followup(jo["name"])
	if not reference_ts:
		return None

	active_ts = _latest_inward_transport(jo["name"], _ACTIVE_TRANSPORT_STATUSES)
	completed_ts = _latest_inward_transport(jo["name"], _COMPLETED_TRANSPORT_STATUSES)
	last_grn = latest_posted_import_grn(jo["name"]) or {}

	return {
		"name": jo["name"],
		"job_order": jo["name"],
		"job_order_number": jo.get("job_order_number") or jo["name"],
		"supplier": jo.get("supplier"),
		"supplier_name": jo.get("supplier_name"),
		"port_of_discharge": jo.get("port_of_discharge"),
		"job_order_quantity": receipt["job_order_quantity"],
		"total_expected_quantity": receipt["total_expected_quantity"],
		"total_received_quantity": receipt["total_received_quantity"],
		"pending_receipt_quantity": receipt["pending_receipt_quantity"],
		"last_posted_grn": last_grn.get("name"),
		"last_grn_receipt_type": last_grn.get("receipt_type"),
		"last_completed_transport": (completed_ts or reference_ts).get("name"),
		"last_completed_transport_status": (completed_ts or reference_ts).get(
			"transport_status"
		),
		"last_transport_schedule": reference_ts.get("name"),
		"last_transport_status": reference_ts.get("transport_status"),
		"last_inward_import_leg": reference_ts.get("inward_import_leg") or "Initial Import Leg",
		"active_transport_schedule": active_ts.get("name") if active_ts else None,
		"active_transport_status": active_ts.get("transport_status") if active_ts else None,
		"active_inward_import_leg": active_ts.get("inward_import_leg") if active_ts else None,
		"followup_needed": flt(receipt["pending_receipt_quantity"]) > 0,
		"grn_count": len(import_grn_rows_for_job_order(jo["name"])),
	}


def _count_grn_summary_followups() -> int:
	rows = get_grn_summary_list(only_actionable=1)
	return len(rows)


@frappe.whitelist()
def get_grn_summary_list(only_actionable: int | str = 0) -> list[dict[str, Any]]:
	"""Import Job Orders with partial posted GRN receipt and balance pending."""
	jos = frappe.get_all(
		"Job Order",
		filters={
			"docstatus": ["<", 2],
			"status": ["!=", "Cancelled"],
			"commercial_movement": "Import",
		},
		fields=[
			"name",
			"job_order_number",
			"supplier",
			"supplier_name",
			"mode_of_transport",
			"port_of_discharge",
			"status",
		],
		order_by="modified desc",
		limit=300,
	)
	out: list[dict[str, Any]] = []
	for jo in jos:
		row = _grn_summary_row(jo)
		if not row:
			continue
		if cint(only_actionable) and not row.get("followup_needed"):
			continue
		out.append(row)
	attach_live_job_order_numbers(out)
	attach_job_order_product_summary(out)
	return enrich_and_sort_console_queue(out)


def _insert_import_partial_receipt_followup_transport(
	jo: frappe.Document,
	*,
	scheduled_pickup_date: str | None = None,
	scheduled_delivery_date: str | None = None,
	pickup_location: str | None = None,
	delivery_location: str | None = None,
	pending_quantity: float | None = None,
) -> str:
	"""Insert a new Inward Import follow-up Transport Schedule leg."""
	from apc_operations.shipping.services.import_grn_receipt_summary_service import (
		partial_import_receipt_summary,
	)

	receipt = partial_import_receipt_summary(jo.name) or {}
	pending_qty = pending_quantity if pending_quantity is not None else receipt.get(
		"pending_receipt_quantity"
	)
	reference = _reference_inward_transport_for_followup(jo.name) or {}

	schedule = frappe.new_doc("Transport Schedule")
	schedule.source_document_type = "Job Order"
	schedule.job_order = jo.name
	schedule.customer = jo.customer
	if jo.supplier:
		schedule.supplier = (
			frappe.db.get_value("Supplier", jo.supplier, "supplier_name") or jo.supplier
		)
	schedule.incoterm = jo.terms_of_delivery
	schedule.port_of_loading = jo.port_of_loading
	schedule.port_of_discharge = jo.port_of_discharge
	schedule.pickup_location = pickup_location or reference.get("pickup_location") or jo.port_of_loading or ""
	schedule.delivery_location = (
		delivery_location or reference.get("delivery_location") or jo.port_of_discharge or ""
	)
	schedule.scheduled_pickup_date = scheduled_pickup_date or jo.date or today()
	schedule.scheduled_delivery_date = scheduled_delivery_date or jo.date or today()
	schedule.transport_status = "Pending Assignment"
	schedule.transport_type = "Inward"
	schedule.inward_import_leg = "Partial Import Follow-up"
	schedule.material_description = jo.get_material_description()
	schedule.special_instructions = _(
		"[Import Partial Receipt Follow-up] Schedule inward import transport for remaining {0} units."
	).format(pending_qty or "?")
	schedule.notes = _(
		"Import GRN Summary follow-up — distinct partial import inward leg for Job Order {0}."
	).format(jo.job_order_number or jo.name)
	if pending_qty:
		schedule.cargo_weight = flt(pending_qty)
	if jo.shipping_booking:
		schedule.shipping_booking = jo.shipping_booking
	schedule.insert(ignore_permissions=True)
	return schedule.name


@frappe.whitelist()
def get_grn_summary_detail(job_order: str) -> dict[str, Any]:
	if not job_order:
		frappe.throw(_("job_order is required"))

	jo = _job_order_summary(job_order)
	row = _grn_summary_row(jo)
	if not row:
		frappe.throw(
			_("Job Order {0} is not eligible for Import GRN Summary follow-up.").format(job_order)
		)

	from apc_operations.shipping.services.import_grn_receipt_summary_service import (
		import_grn_rows_for_job_order,
	)

	completed_ts = _latest_inward_transport(job_order, _COMPLETED_TRANSPORT_STATUSES)
	reference_ts = _reference_inward_transport_for_followup(job_order) or {}
	vd = _resolve_vehicle_driver(completed_ts or reference_ts)
	return {
		**row,
		"commercial_movement": jo.get("commercial_movement") or "Import",
		"terms_of_delivery": jo.get("terms_of_delivery"),
		"scheduled_pickup_date": (completed_ts or reference_ts).get("scheduled_pickup_date"),
		"scheduled_delivery_date": (completed_ts or reference_ts).get("scheduled_delivery_date"),
		"last_vehicle_number": vd.get("vehicle_number"),
		"last_driver_name": vd.get("driver_name"),
		"import_grns": import_grn_rows_for_job_order(job_order),
	}


@frappe.whitelist()
def create_import_partial_receipt_followup_transport(
	job_order: str,
	scheduled_pickup_date: str | None = None,
	scheduled_delivery_date: str | None = None,
	pickup_location: str | None = None,
	delivery_location: str | None = None,
	transporter: str | None = None,
	assigned_vehicle: str | None = None,
	assigned_driver: str | None = None,
	driver_phone: str | None = None,
) -> dict[str, Any]:
	"""Create a new inward import transport leg for partial GRN receipt follow-up."""
	if not job_order:
		frappe.throw(_("job_order is required"))

	jo = frappe.get_doc("Job Order", job_order)
	jo.check_permission("write")

	if (jo.commercial_movement or "").strip() != "Import":
		frappe.throw(_("Import GRN Summary follow-up applies only to Import Job Orders."))

	from apc_operations.shipping.services.import_grn_receipt_summary_service import (
		partial_import_receipt_summary,
	)

	if not partial_import_receipt_summary(job_order):
		frappe.throw(_("This Job Order has no remaining partial-import receipt quantity."))

	if not _reference_inward_transport_for_followup(job_order):
		frappe.throw(_("At least one inward import transport schedule is required before scheduling follow-up."))

	from apc_operations.shipping.transport_events import TRANSPORT_TO_JOB_ORDER_STATUS

	receipt = partial_import_receipt_summary(job_order) or {}
	ts_name = _insert_import_partial_receipt_followup_transport(
		jo,
		scheduled_pickup_date=scheduled_pickup_date,
		scheduled_delivery_date=scheduled_delivery_date,
		pickup_location=pickup_location,
		delivery_location=delivery_location,
		pending_quantity=receipt.get("pending_receipt_quantity"),
	)

	jo.db_set("transport_schedule", ts_name, update_modified=False)
	ts_status = frappe.db.get_value("Transport Schedule", ts_name, "transport_status")
	mapped = TRANSPORT_TO_JOB_ORDER_STATUS.get(ts_status, "Pending Booking")
	jo.db_set("transport_status", mapped, update_modified=False)
	if jo.status != "Cancelled":
		jo.db_set("status", "In Progress", update_modified=False)

	if transporter or assigned_vehicle or assigned_driver or driver_phone:
		book_transport_schedule(
			ts_name,
			transporter=transporter,
			assigned_vehicle=assigned_vehicle,
			assigned_driver=assigned_driver,
			driver_phone=driver_phone,
		)
		ts_status = frappe.db.get_value("Transport Schedule", ts_name, "transport_status")

	vd = _resolve_vehicle_driver(
		frappe.db.get_value(
			"Transport Schedule",
			ts_name,
			["assigned_vehicle", "assigned_driver", "driver_phone"],
			as_dict=True,
		)
		or {}
	)
	return {
		"job_order": job_order,
		"job_order_number": jo.job_order_number or job_order,
		"transport_schedule": ts_name,
		"transport_status": ts_status,
		"transport_booking_label": console_status.transport_booking_label(ts_status),
		"inward_import_leg": "Partial Import Follow-up",
		"commercial_movement": "Import",
		"driver_name": vd.get("driver_name"),
		"vehicle_number": vd.get("vehicle_number"),
		"pending_receipt_quantity": receipt.get("pending_receipt_quantity"),
		"is_import_partial_follow_up": True,
	}


@frappe.whitelist()
def create_import_partial_receipt_followup_transport_and_issue_do(
	job_order: str,
	scheduled_pickup_date: str | None = None,
	scheduled_delivery_date: str | None = None,
	pickup_location: str | None = None,
	delivery_location: str | None = None,
	transporter: str | None = None,
	assigned_vehicle: str | None = None,
	assigned_driver: str | None = None,
	driver_phone: str | None = None,
	quantity: float | None = None,
) -> dict[str, Any]:
	"""One-click "Schedule Follow-up Trip" for Import GRN partial receipts:
	creates the new inward leg for the remaining receipt quantity AND
	immediately issues its Import Delivery Order in the same call, mirroring
	create_partial_delivery_followup_transport_and_issue_do (Outward) -
	instead of requiring a separate "Book Transport" step and leaving the
	user to guess whether a DO/Pre-Check Clearance actually got created.

	Checks follow-up eligibility BEFORE creating anything - a Transport
	Schedule here also cascades a Security Draft DN and Transport PO
	Request via TransportSchedule.on_update -> ensure_inward_follow_up_records(),
	so a blocked attempt would otherwise leave that trio behind with no DO
	ever attached (the exact bug already fixed on the Outward side).
	"""
	from apc_operations.shipping.services.delivery_order_generation_service import (
		find_open_import_delivery_order_for_job_order,
		generate_followup_import_delivery_order_for_job_order,
	)

	open_do = find_open_import_delivery_order_for_job_order(job_order)
	if open_do:
		frappe.throw(
			_(
				"Delivery Order {0} is still awaiting QC/Security precheck or its Import GRN. "
				"Complete that before scheduling another follow-up leg."
			).format(open_do)
		)

	result = create_import_partial_receipt_followup_transport(
		job_order,
		scheduled_pickup_date=scheduled_pickup_date,
		scheduled_delivery_date=scheduled_delivery_date,
		pickup_location=pickup_location,
		delivery_location=delivery_location,
		transporter=transporter,
		assigned_vehicle=assigned_vehicle,
		assigned_driver=assigned_driver,
		driver_phone=driver_phone,
	)

	do_result = None
	do_error = None
	if transporter or assigned_vehicle or assigned_driver:
		if console_status.can_generate_delivery_order(result.get("transport_status")):
			try:
				do_result = generate_followup_import_delivery_order_for_job_order(
					job_order, transport_schedule=result.get("transport_schedule"), quantity=quantity
				)
			except Exception as e:
				frappe.log_error(frappe.get_traceback(), f"Follow-up Import DO issue failed for {job_order}")
				do_error = str(e) or _(
					"Follow-up leg was created, but issuing the Delivery Note failed. Issue it manually."
				)
		else:
			do_error = _(
				"Follow-up leg was created, but its status ({0}) isn't bookable yet - issue the "
				"Delivery Order manually once it is."
			).format(result.get("transport_status"))

	result["delivery_order_result"] = do_result
	result["delivery_order_error"] = do_error
	return result


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
	"cargo_weight",
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
		"qty_to_load": ts.get("cargo_weight"),
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
	qty_to_load: float | None = None,
	third_party_loading: int | str | None = None,
	third_party_loader: str | None = None,
	third_party_loading_location: str | None = None,
	third_party_loading_notes: str | None = None,
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
	if qty_to_load is not None and flt(qty_to_load) > 0:
		# Reuse cargo_weight - already the established "how much this leg
		# carries" field on the import partial-receipt-followup path, just
		# never wired up for the primary/outward booking path until now.
		provided["cargo_weight"] = flt(qty_to_load)

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

	if third_party_loading is not None:
		job_order = frappe.db.get_value("Transport Schedule", transport_schedule, "job_order")
		if job_order:
			jo_updates: dict[str, Any] = {"third_party_loading": cint(third_party_loading)}
			if third_party_loader is not None:
				jo_updates["third_party_loader"] = third_party_loader
			if third_party_loading_location is not None:
				jo_updates["third_party_loading_location"] = third_party_loading_location
			if third_party_loading_notes is not None:
				jo_updates["third_party_loading_notes"] = third_party_loading_notes
			frappe.db.set_value("Job Order", job_order, jo_updates, update_modified=False)

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

	movement = frappe.db.get_value("Job Order", job_order, "commercial_movement") or "Outward"
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
	from apc_operations.services.delivery_order_service import resolve_do_for_sddn
	from apc_operations.shipping.services.dispatch_lifecycle_service import (
		mark_do_sent_to_security,
	)
	do_name = resolve_do_for_sddn(sddn)
	if do_name:
		mark_do_sent_to_security(do_name)

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


@frappe.whitelist()
def ensure_transport_po_for_schedule(transport_schedule: str) -> dict[str, Any]:
	"""Get-or-create the Transport PO Request for a Transport Schedule, for
	the console's "Print Transport PO" action. Wraps the existing
	Transport Schedule.create_transport_po_request() (already used by
	ensure_outward_follow_up_records()) - this whitelisted entry point for
	it never existed even though the console JS has called it all along."""
	if not transport_schedule:
		frappe.throw(_("transport_schedule is required"))

	doc = frappe.get_doc("Transport Schedule", transport_schedule)
	tpo_name = doc.create_transport_po_request()
	return {"transport_schedule": transport_schedule, "transport_po_request": tpo_name}
