# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Create Delivery Orders for export and import Job Orders (Path B consoles)."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, today

from apc_operations.services import console_status
from apc_operations.services.delivery_order_service import (
	find_delivery_order_for_job_order_primary,
	find_open_delivery_order_for_job_order,
	link_delivery_order_to_job_order,
)
from apc_operations.shipping.doctype.job_order.job_order import (
	get_primary_transport_type_for_job_order,
)
from apc_operations.shipping.services.partial_dispatch_service import (
	get_active_outward_transport,
	get_partial_dispatch_summary,
	has_issued_loading_delivery_note,
)
from apc_operations.shipping.services.delivery_order_sync_service import (
	job_order_items_for_delivery_order,
)


def _notify_security_team(do_name: str, job_order: str) -> None:
	from frappe.desk.doctype.notification_log.notification_log import (
		enqueue_create_notification,
	)

	user_ids = frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": ["in", ["Security Manager", "Security User"]]},
		fields=["parent"],
		distinct=True,
		pluck="parent",
	)
	if not user_ids:
		return

	jo_number = frappe.db.get_value("Job Order", job_order, "job_order_number") or job_order
	try:
		enqueue_create_notification(
			user_ids,
			{
				"subject": _("Delivery Order {0} issued for {1} - ready for security review").format(
					do_name, jo_number
				),
				"type": "Alert",
				"document_type": "Delivery Order",
				"document_name": do_name,
				"from_user": frappe.session.user,
			},
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Security DO notification")


def _fallback_do_item(*, cargo_description: str | None = None, container_count=None) -> dict:
	"""Minimal DO line when Job Order has no item rows."""
	item_code = frappe.db.get_value("Item", {}, "name")
	if not item_code:
		frappe.throw(_("At least one Item is required to create a Delivery Order."))
	row = {
		"item_code": item_code,
		"description": cargo_description or _("Items per Job Order"),
		"qty": 1,
		"uom": "Nos",
	}
	if container_count:
		row["no_of_containers"] = container_count
	return row


def _resolve_port_label(value: str | None) -> str | None:
	if not value:
		return None
	port_name = frappe.db.get_value("Port", value, "port_name")
	return port_name or value


APC_IMPORT_CUSTOMER_LABEL = "APC"


def _ensure_apc_customer() -> tuple[str, str]:
	"""Import Delivery Orders always use Customer APC (APC as buyer)."""
	name = frappe.db.get_value(
		"Customer", {"customer_name": APC_IMPORT_CUSTOMER_LABEL}, "name"
	)
	if not name:
		name = frappe.db.get_value("Customer", APC_IMPORT_CUSTOMER_LABEL, "name")
	if name:
		display = (
			frappe.db.get_value("Customer", name, "customer_name") or APC_IMPORT_CUSTOMER_LABEL
		)
		return name, display

	override = frappe.db.get_single_value(
		"APC Operations Settings", "default_import_do_customer"
	)
	if override and frappe.db.exists("Customer", override):
		return override, frappe.db.get_value("Customer", override, "customer_name")

	group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	payload = {
		"doctype": "Customer",
		"customer_name": APC_IMPORT_CUSTOMER_LABEL,
		"customer_type": "Company",
	}
	if group:
		payload["customer_group"] = group
	doc = frappe.get_doc(payload)
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	return doc.name, doc.customer_name or APC_IMPORT_CUSTOMER_LABEL


def _resolve_import_delivery_customer(jo: dict[str, Any]) -> tuple[str, str | None]:
	"""Return (customer, customer_name) for an import Delivery Order — always APC."""
	return _ensure_apc_customer()


def _active_transport_row(job_order: str, movement: str) -> dict[str, Any]:
	ttype = get_primary_transport_type_for_job_order(movement)
	rows = frappe.get_all(
		"Transport Schedule",
		filters={
			"job_order": job_order,
			"transport_type": ttype,
			"transport_status": ["!=", "Cancelled"],
		},
		fields=["name", "transport_status", "shipping_booking", "container_count", "cargo_weight"],
		order_by="modified desc",
		limit=1,
	)
	if not rows:
		frappe.throw(
			_("No active {0} Transport Schedule for Job Order {1}").format(ttype, job_order)
		)
	return rows[0]


@frappe.whitelist()
def generate_delivery_order_for_job_order(
	job_order: str,
	*,
	movement: str | None = None,
	auto_issue_to_security: bool = False,
) -> dict[str, Any]:
	"""Create (or return) a Delivery Order for the Job Order's primary transport leg."""
	if not job_order:
		frappe.throw(_("job_order is required"))

	jo = frappe.db.get_value(
		"Job Order",
		job_order,
		[
			"name",
			"job_order_number",
			"commercial_movement",
			"customer",
			"customer_name",
			"supplier",
			"supplier_name",
			"port_of_loading",
			"port_of_discharge",
			"shipping_booking",
			"terms_of_delivery",
			"third_party_loading",
			"third_party_loader",
		],
		as_dict=True,
	)
	if not jo:
		frappe.throw(_("Job Order {0} not found").format(job_order))

	movement = (movement or jo.get("commercial_movement") or "Outward").strip()
	if movement not in ("Outward", "Import"):
		frappe.throw(_("Invalid commercial movement: {0}").format(movement))

	existing_do = find_delivery_order_for_job_order_primary(job_order)
	if existing_do:
		link_delivery_order_to_job_order(existing_do, job_order, update_modified=False)
		if frappe.db.has_column("Delivery Order", "commercial_movement"):
			frappe.db.set_value(
				"Delivery Order",
				existing_do,
				"commercial_movement",
				movement,
				update_modified=False,
			)
		return {
			"delivery_order": existing_do,
			"job_order": job_order,
			"created": False,
			"commercial_movement": movement,
		}

	ts = _active_transport_row(job_order, movement)
	if not console_status.can_generate_delivery_order(ts.get("transport_status")):
		frappe.throw(
			_(
				"Cannot generate Delivery Order: Transport Schedule {0} is in status "
				"'{1}'. Allowed: Vehicle Assigned / Driver Assigned / Scheduled / Dispatched."
			).format(ts.get("name"), ts.get("transport_status") or "-")
		)

	sb_name = ts.get("shipping_booking") or jo.get("shipping_booking")
	sb = (
		frappe.db.get_value(
			"Shipping Booking",
			sb_name,
			["name", "port_of_loading", "port_of_discharge", "cargo_description"],
			as_dict=True,
		)
		if sb_name
		else None
	)

	company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	if not company:
		frappe.throw(_("No default Company configured."))

	pol_label = _resolve_port_label(jo.get("port_of_loading") or (sb and sb.port_of_loading))
	pod_label = _resolve_port_label(jo.get("port_of_discharge") or (sb and sb.port_of_discharge))

	container_count = ts.get("container_count")
	if not container_count and sb_name:
		container_count = frappe.db.get_value("Shipping Booking", sb_name, "container_count")
	if container_count is not None:
		try:
			container_count = int(container_count)
		except (TypeError, ValueError):
			container_count = None

	do = frappe.new_doc("Delivery Order")
	do.naming_series = "DO-.YYYY.-"
	do.job_order = job_order
	do.job_order_number = jo.get("job_order_number")
	do.posting_date = today()
	do.company = company
	do.port_of_loading = pol_label
	do.port_of_discharge = pod_label
	do.destination = pod_label
	do.status = "Draft"
	do.terms_of_delivery = jo.get("terms_of_delivery")
	do.remarks = _("Generated from {0} Job Order {1}").format(movement, job_order)

	is_third_party = bool(jo.get("third_party_loading"))
	do.third_party_loading = 1 if is_third_party else 0
	do.third_party_loader = jo.get("third_party_loader")

	if frappe.db.has_column("Delivery Order", "commercial_movement"):
		do.commercial_movement = movement

	if movement == "Import":
		customer, customer_name = _resolve_import_delivery_customer(jo)
		do.customer = customer
		do.customer_name = customer_name
		if frappe.db.has_column("Delivery Order", "supplier"):
			do.supplier = jo.get("supplier")
		if frappe.db.has_column("Delivery Order", "supplier_name"):
			do.supplier_name = jo.get("supplier_name")
		do.buyer = customer
	else:
		if not jo.get("customer"):
			frappe.throw(_("Export Job Order {0} requires a Customer.").format(job_order))
		do.customer = jo.get("customer")
		do.customer_name = jo.get("customer_name")
		do.buyer = jo.get("customer")

	from apc_operations.shipping.services.delivery_order_sync_service import (
		job_order_items_for_delivery_order,
	)

	items = job_order_items_for_delivery_order(job_order, no_of_containers=container_count)
	if not items:
		items = [
			_fallback_do_item(
				cargo_description=(sb and sb.cargo_description) or None,
				container_count=container_count,
			)
		]

	# Cross-check the transporter-entered "Qty to Load" (Transport Schedule
	# .cargo_weight, see book_transport_schedule) against the Job Order's
	# full quantity. If it's genuinely less, scale the DO down to that
	# amount instead of silently issuing it for the full quantity - once
	# this DO's dispatch gets confirmed, the existing partial-dispatch
	# tracking (get_partial_dispatch_summary, keyed off real confirmed
	# quantity vs order quantity) will naturally surface the shortfall on
	# the follow-up screens on its own, no separate wiring needed here.
	cargo_weight = flt(ts.get("cargo_weight"))
	if cargo_weight > 0:
		full_qty = sum(flt(i.get("qty")) for i in items)
		if full_qty > 0 and cargo_weight < full_qty - 0.0001:
			items = _job_order_items_for_pending_quantity(job_order, cargo_weight)

	for item in items:
		do.append("items", item)

	do.insert(ignore_permissions=True)

	if is_third_party:
		# Third-party loading skips Security entirely - Pre-Check Clearance
		# is a Security+QC dual sign-off mechanism that doesn't apply, and
		# routing goes straight to QC's third-party queue instead.
		do.db_set("operational_status", "Issued", update_modified=False)
		if frappe.db.has_column("Delivery Order", "do_status"):
			do.db_set("do_status", "Issued", update_modified=False)
	else:
		try:
			do._ensure_pre_check_clearance()
		except Exception:
			frappe.log_error(frappe.get_traceback(), "DO Pre-Check creation")

	if auto_issue_to_security and not is_third_party:
		from apc_operations.shipping.services.dispatch_lifecycle_service import (
			mark_do_sent_to_security,
		)

		mark_do_sent_to_security(do.name, update_modified=True)

	if not is_third_party:
		_notify_security_team(do.name, job_order)

	try:
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "Job Order",
				"reference_name": job_order,
				"content": _("Delivery Order generated: {0} ({1})").format(do.name, movement),
			}
		).insert(ignore_permissions=True)
	except Exception:
		pass

	return {
		"delivery_order": do.name,
		"job_order": job_order,
		"created": True,
		"commercial_movement": movement,
	}


def _job_order_items_for_pending_quantity(job_order: str, pending_qty: float) -> list[dict]:
	"""Scale Job Order lines to the remaining partial-dispatch quantity."""
	items = job_order_items_for_delivery_order(job_order)
	pending_qty = flt(pending_qty)
	if pending_qty <= 0:
		frappe.throw(_("Pending dispatch quantity must be greater than zero."))

	if not items:
		return [{**_fallback_do_item(), "qty": pending_qty}]

	order_qty = sum(flt(row.get("qty")) for row in items)
	if order_qty <= 0:
		order_qty = pending_qty

	ratio = pending_qty / order_qty
	scaled: list[dict] = []
	for row in items:
		line_qty = flt(row.get("qty")) * ratio
		if line_qty <= 0:
			continue
		scaled.append({**row, "qty": line_qty})

	if not scaled:
		first = dict(items[0])
		first["qty"] = pending_qty
		scaled = [first]
	return scaled


def get_followup_delivery_order_eligibility(
	job_order: str,
	*,
	transport_schedule: str | None = None,
) -> dict[str, Any]:
	"""Whether a partial follow-up Delivery Order can be issued (same rules as export DO)."""
	summary = get_partial_dispatch_summary(job_order)
	if not summary:
		return {
			"eligible": False,
			"can_issue_followup_do": False,
			"reason": _("No remaining partial-dispatch quantity for this Job Order."),
		}

	if not has_issued_loading_delivery_note(job_order):
		return {
			"eligible": False,
			"can_issue_followup_do": False,
			"reason": _("At least one Loading Delivery Note must exist before follow-up DO."),
		}

	ts = None
	if transport_schedule:
		ts = frappe.db.get_value(
			"Transport Schedule",
			transport_schedule,
			[
				"name",
				"transport_status",
				"shipping_booking",
				"container_count",
				"job_order",
				"transport_type",
			],
			as_dict=True,
		)
		if not ts or ts.get("job_order") != job_order:
			frappe.throw(
				_("Transport Schedule {0} is not linked to Job Order {1}.").format(
					transport_schedule, job_order
				)
			)
		if (ts.get("transport_type") or "").strip() != "Outward":
			frappe.throw(_("Follow-up Delivery Order requires an outward Transport Schedule."))

	if not ts:
		ts = get_active_outward_transport(job_order)

	if not ts:
		return {
			"eligible": True,
			"can_issue_followup_do": False,
			"needs_followup_transport": True,
			"pending_dispatch_quantity": summary["pending_dispatch_quantity"],
			"reason": _("Schedule a follow-up transport leg before issuing a Delivery Order."),
		}

	open_do = find_open_delivery_order_for_job_order(job_order)
	if open_do:
		return {
			"eligible": True,
			"can_issue_followup_do": False,
			"transport_schedule": ts.get("name"),
			"transport_status": ts.get("transport_status"),
			"do_name": open_do,
			"pending_dispatch_quantity": summary["pending_dispatch_quantity"],
			"reason": _(
				"Delivery Order {0} is still open. Complete or gate out the current trip first."
			).format(open_do),
		}

	transport_booked = console_status.can_generate_delivery_order(ts.get("transport_status"))
	result = {
		"eligible": True,
		"can_issue_followup_do": transport_booked,
		"needs_transport_booking": not transport_booked,
		"transport_schedule": ts.get("name"),
		"transport_status": ts.get("transport_status"),
		"pending_dispatch_quantity": summary["pending_dispatch_quantity"],
		"job_order_quantity": summary["job_order_quantity"],
		"total_dispatched_quantity": summary["total_dispatched_quantity"],
	}
	if not transport_booked:
		result["reason"] = _(
			"Book the follow-up transport (vehicle / driver assigned) before issuing DO."
		)
	return result


@frappe.whitelist()
def generate_followup_delivery_order_for_job_order(
	job_order: str,
	*,
	transport_schedule: str | None = None,
	quantity: float | None = None,
) -> dict[str, Any]:
	"""Create a follow-up export Delivery Order for the remaining partial-dispatch qty.

	``quantity``: optional override when even this follow-up leg can't carry
	the full remaining amount (e.g. another split is needed later) - capped
	at the actual pending quantity, defaults to all of it.
	"""
	if not job_order:
		frappe.throw(_("job_order is required"))

	eligibility = get_followup_delivery_order_eligibility(
		job_order, transport_schedule=transport_schedule
	)
	if not eligibility.get("can_issue_followup_do"):
		frappe.throw(eligibility.get("reason") or _("Follow-up Delivery Order cannot be issued."))

	ts_name = eligibility["transport_schedule"]
	ts = frappe.db.get_value(
		"Transport Schedule",
		ts_name,
		["name", "transport_status", "shipping_booking", "container_count", "transporter"],
		as_dict=True,
	)
	summary = get_partial_dispatch_summary(job_order)
	pending_qty = flt(summary["pending_dispatch_quantity"])
	if quantity is not None and flt(quantity) > 0:
		pending_qty = min(flt(quantity), pending_qty)

	jo = frappe.db.get_value(
		"Job Order",
		job_order,
		[
			"name",
			"job_order_number",
			"commercial_movement",
			"customer",
			"customer_name",
			"port_of_loading",
			"port_of_discharge",
			"shipping_booking",
			"terms_of_delivery",
			"third_party_loading",
			"third_party_loader",
		],
		as_dict=True,
	)
	if not jo:
		frappe.throw(_("Job Order {0} not found").format(job_order))

	movement = (jo.get("commercial_movement") or "Outward").strip()
	if movement != "Outward":
		frappe.throw(_("Follow-up Delivery Orders are supported for Outward Job Orders only."))

	sb_name = ts.get("shipping_booking") or jo.get("shipping_booking")
	sb = (
		frappe.db.get_value(
			"Shipping Booking",
			sb_name,
			["name", "port_of_loading", "port_of_discharge", "cargo_description"],
			as_dict=True,
		)
		if sb_name
		else None
	)

	company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	if not company:
		frappe.throw(_("No default Company configured."))

	pol_label = _resolve_port_label(jo.get("port_of_loading") or (sb and sb.port_of_loading))
	pod_label = _resolve_port_label(jo.get("port_of_discharge") or (sb and sb.port_of_discharge))

	container_count = ts.get("container_count")
	if not container_count and sb_name:
		container_count = frappe.db.get_value("Shipping Booking", sb_name, "container_count")

	do = frappe.new_doc("Delivery Order")
	do.naming_series = "DO-.YYYY.-"
	do.job_order = job_order
	do.job_order_number = jo.get("job_order_number")
	do.posting_date = today()
	do.company = company
	do.port_of_loading = pol_label
	do.port_of_discharge = pod_label
	do.destination = pod_label
	do.status = "Draft"
	do.terms_of_delivery = jo.get("terms_of_delivery")
	do.remarks = _(
		"Follow-up Delivery Order for partial dispatch ({0} remaining). Transport: {1}"
	).format(pending_qty, ts_name)

	is_third_party = bool(jo.get("third_party_loading"))
	do.third_party_loading = 1 if is_third_party else 0
	do.third_party_loader = jo.get("third_party_loader")

	if frappe.db.has_column("Delivery Order", "commercial_movement"):
		do.commercial_movement = movement
	if frappe.db.has_column("Delivery Order", "planned_quantity"):
		do.planned_quantity = pending_qty
	if ts.get("transporter") and frappe.db.has_column("Delivery Order", "transporter"):
		do.transporter = ts.get("transporter")

	if not jo.get("customer"):
		frappe.throw(_("Export Job Order {0} requires a Customer.").format(job_order))
	do.customer = jo.get("customer")
	do.customer_name = jo.get("customer_name")
	do.buyer = jo.get("customer")

	for item in _job_order_items_for_pending_quantity(job_order, pending_qty):
		do.append("items", item)

	do.insert(ignore_permissions=True)

	if is_third_party:
		# Same as the primary DO path - third-party loading skips Security
		# entirely, so Pre-Check Clearance (a Security+QC dual sign-off
		# mechanism) doesn't apply here either.
		do.db_set("operational_status", "Issued", update_modified=False)
		if frappe.db.has_column("Delivery Order", "do_status"):
			do.db_set("do_status", "Issued", update_modified=False)
	else:
		try:
			do._ensure_pre_check_clearance()
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Follow-up DO Pre-Check creation")

	try:
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "Job Order",
				"reference_name": job_order,
				"content": _("Follow-up Delivery Order generated: {0} (pending {1})").format(
					do.name, pending_qty
				),
			}
		).insert(ignore_permissions=True)
	except Exception:
		pass

	return {
		"delivery_order": do.name,
		"job_order": job_order,
		"transport_schedule": ts_name,
		"created": True,
		"is_follow_up_do": True,
		"pending_dispatch_quantity": pending_qty,
		"commercial_movement": movement,
	}


def find_open_import_delivery_order_for_job_order(job_order: str) -> str | None:
	"""Latest Import Delivery Order for a Job Order that still blocks a follow-up leg.

	Import has no loading/dispatch step to key off of the way Outward does
	(``DISPATCH_CONFIRMED_STATUSES``) - the real "this receipt leg is done"
	signal is QC+Security precheck reaching Authorized AND its Import GRN
	actually existing. A DO short of either is still open.
	"""
	rows = frappe.get_all(
		"Delivery Order",
		filters={
			"job_order": job_order,
			"commercial_movement": "Import",
			"docstatus": ["!=", 2],
		},
		fields=["name", "operational_status", "pre_check_clearance"],
		order_by="modified desc",
	)
	for row in rows:
		if (row.get("operational_status") or "").strip() == "Cancelled":
			continue
		pcc_authorized = bool(row.get("pre_check_clearance")) and (
			frappe.db.get_value(
				"Pre-Check Clearance", row["pre_check_clearance"], "overall_status"
			)
			== "Authorized"
		)
		if not pcc_authorized:
			return row["name"]
		if not frappe.db.exists("Import GRN", {"delivery_order": row["name"]}):
			return row["name"]
	return None


def get_followup_import_delivery_order_eligibility(
	job_order: str,
	*,
	transport_schedule: str | None = None,
) -> dict[str, Any]:
	"""Whether a partial-receipt follow-up Import Delivery Order can be issued."""
	if not job_order:
		frappe.throw(_("job_order is required"))

	movement = frappe.db.get_value("Job Order", job_order, "commercial_movement")
	if (movement or "").strip() != "Import":
		frappe.throw(_("Follow-up Import Delivery Orders apply to Import Job Orders only."))

	from apc_operations.shipping.services.import_grn_receipt_summary_service import (
		partial_import_receipt_summary,
	)

	receipt = partial_import_receipt_summary(job_order) or {}

	ts = None
	if transport_schedule:
		ts = frappe.db.get_value(
			"Transport Schedule",
			transport_schedule,
			["name", "transport_status", "job_order", "transport_type"],
			as_dict=True,
		)
		if not ts or ts.get("job_order") != job_order:
			frappe.throw(
				_("Transport Schedule {0} is not linked to Job Order {1}.").format(
					transport_schedule, job_order
				)
			)
		if (ts.get("transport_type") or "").strip() != "Inward":
			frappe.throw(_("Follow-up Import Delivery Order requires an Inward Transport Schedule."))

	if not ts:
		rows = frappe.get_all(
			"Transport Schedule",
			filters={
				"job_order": job_order,
				"transport_type": "Inward",
				"transport_status": ["!=", "Cancelled"],
			},
			fields=["name", "transport_status"],
			order_by="modified desc",
			limit=1,
		)
		ts = rows[0] if rows else None

	if not ts:
		return {
			"eligible": True,
			"can_issue_followup_do": False,
			"needs_followup_transport": True,
			"pending_receipt_quantity": receipt.get("pending_receipt_quantity"),
			"reason": _("Schedule a follow-up inward transport leg before issuing a Delivery Order."),
		}

	open_do = find_open_import_delivery_order_for_job_order(job_order)
	if open_do:
		return {
			"eligible": True,
			"can_issue_followup_do": False,
			"transport_schedule": ts.get("name"),
			"transport_status": ts.get("transport_status"),
			"do_name": open_do,
			"pending_receipt_quantity": receipt.get("pending_receipt_quantity"),
			"reason": _(
				"Delivery Order {0} is still awaiting QC/Security precheck or its Import GRN. "
				"Complete that before issuing a follow-up."
			).format(open_do),
		}

	transport_booked = console_status.can_generate_delivery_order(ts.get("transport_status"))
	result = {
		"eligible": True,
		"can_issue_followup_do": transport_booked,
		"needs_transport_booking": not transport_booked,
		"transport_schedule": ts.get("name"),
		"transport_status": ts.get("transport_status"),
		"pending_receipt_quantity": receipt.get("pending_receipt_quantity"),
	}
	if not transport_booked:
		result["reason"] = _(
			"Book the follow-up transport (vehicle / driver assigned) before issuing DO."
		)
	return result


@frappe.whitelist()
def generate_followup_import_delivery_order_for_job_order(
	job_order: str,
	*,
	transport_schedule: str | None = None,
	quantity: float | None = None,
) -> dict[str, Any]:
	"""Create a follow-up Import Delivery Order for a partial-receipt inward leg.

	Mirrors generate_followup_delivery_order_for_job_order (Outward) - a Job
	Order's primary Import DO generator (try_auto_issue_import_delivery_order
	-> generate_delivery_order_for_job_order) just finds and returns whatever
	Import DO already exists, so a second inward leg needs this dedicated
	generator to get its own new DO instead of silently reusing the first.
	"""
	if not job_order:
		frappe.throw(_("job_order is required"))

	eligibility = get_followup_import_delivery_order_eligibility(
		job_order, transport_schedule=transport_schedule
	)
	if not eligibility.get("can_issue_followup_do"):
		frappe.throw(
			eligibility.get("reason") or _("Follow-up Import Delivery Order cannot be issued.")
		)

	ts_name = eligibility["transport_schedule"]

	from apc_operations.shipping.services.import_grn_receipt_summary_service import (
		partial_import_receipt_summary,
	)

	receipt = partial_import_receipt_summary(job_order) or {}
	pending_qty = flt(receipt.get("pending_receipt_quantity"))
	if quantity is not None and flt(quantity) > 0 and pending_qty > 0:
		pending_qty = min(flt(quantity), pending_qty)

	jo = frappe.db.get_value(
		"Job Order",
		job_order,
		[
			"name",
			"job_order_number",
			"commercial_movement",
			"supplier",
			"supplier_name",
			"port_of_loading",
			"port_of_discharge",
			"shipping_booking",
			"terms_of_delivery",
		],
		as_dict=True,
	)
	if not jo:
		frappe.throw(_("Job Order {0} not found").format(job_order))
	if (jo.get("commercial_movement") or "").strip() != "Import":
		frappe.throw(_("Follow-up Import Delivery Orders are supported for Import Job Orders only."))

	company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	if not company:
		frappe.throw(_("No default Company configured."))

	pol_label = _resolve_port_label(jo.get("port_of_loading"))
	pod_label = _resolve_port_label(jo.get("port_of_discharge"))
	customer, customer_name = _ensure_apc_customer()

	do = frappe.new_doc("Delivery Order")
	do.naming_series = "DO-.YYYY.-"
	do.job_order = job_order
	do.job_order_number = jo.get("job_order_number")
	do.posting_date = today()
	do.company = company
	do.port_of_loading = pol_label
	do.port_of_discharge = pod_label
	do.destination = pod_label
	do.status = "Draft"
	do.terms_of_delivery = jo.get("terms_of_delivery")
	do.remarks = _(
		"Follow-up Import Delivery Order for partial receipt ({0} remaining). Transport: {1}"
	).format(pending_qty, ts_name)
	do.customer = customer
	do.customer_name = customer_name
	do.buyer = customer
	if frappe.db.has_column("Delivery Order", "supplier"):
		do.supplier = jo.get("supplier")
	if frappe.db.has_column("Delivery Order", "supplier_name"):
		do.supplier_name = jo.get("supplier_name")
	if frappe.db.has_column("Delivery Order", "commercial_movement"):
		do.commercial_movement = "Import"
	if frappe.db.has_column("Delivery Order", "planned_quantity"):
		do.planned_quantity = pending_qty

	items = (
		_job_order_items_for_pending_quantity(job_order, pending_qty)
		if pending_qty > 0
		else job_order_items_for_delivery_order(job_order)
	)
	if not items:
		items = [_fallback_do_item()]
	for item in items:
		do.append("items", item)

	do.insert(ignore_permissions=True)

	try:
		do._ensure_pre_check_clearance()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Follow-up Import DO Pre-Check creation")

	from apc_operations.shipping.services.dispatch_lifecycle_service import (
		mark_do_sent_to_security,
	)

	mark_do_sent_to_security(do.name, update_modified=True)

	try:
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "Job Order",
				"reference_name": job_order,
				"content": _("Follow-up Import Delivery Order generated: {0} (pending {1})").format(
					do.name, pending_qty
				),
			}
		).insert(ignore_permissions=True)
	except Exception:
		pass

	return {
		"delivery_order": do.name,
		"job_order": job_order,
		"transport_schedule": ts_name,
		"created": True,
		"is_follow_up_do": True,
		"pending_receipt_quantity": pending_qty,
		"commercial_movement": "Import",
	}


def try_auto_issue_import_delivery_order(
	job_order: str | None,
	*,
	transport_schedule: str | None = None,
) -> str | None:
	"""Auto-create import DO when inward transport is booked and vessel is cleared."""
	if not job_order:
		return None

	movement = frappe.db.get_value("Job Order", job_order, "commercial_movement") or "Outward"
	if movement != "Import":
		return None

	mode = frappe.db.get_value("Job Order", job_order, "mode_of_transport") or ""
	if mode == "Sea":
		sb = frappe.db.get_value("Job Order", job_order, "shipping_booking")
		if sb:
			vessel_status = frappe.db.get_value("Shipping Booking", sb, "vessel_status") or ""
			if vessel_status.strip() != "Cleared":
				return None

	if transport_schedule:
		ts = frappe.db.get_value(
			"Transport Schedule",
			transport_schedule,
			["assigned_vehicle", "assigned_driver", "transport_status"],
			as_dict=True,
		)
		if not ts or not ts.get("assigned_vehicle") or not ts.get("assigned_driver"):
			return None
		if ts.get("transport_status") not in (
			"Scheduled",
			"Vehicle Assigned",
			"Driver Assigned",
		):
			return None

	existing = find_delivery_order_for_job_order_primary(job_order)
	if existing:
		return existing

	result = generate_delivery_order_for_job_order(
		job_order,
		movement="Import",
		auto_issue_to_security=True,
	)
	return result.get("delivery_order")
