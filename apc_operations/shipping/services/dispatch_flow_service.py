# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Delivery Order <-> Loading Delivery Note linking, batch/COA sync, and
dispatch readiness — shared by the security console, QC console, and
dispatch workflow actions.

Not present anywhere in the Cursor-history recovery (confirmed - zero
snapshots), even though 6 call sites across the app already depended on it.
Reconstructed from those call sites: what each function is called with, what
it's expected to return, and the real doctype fields (Loading Delivery
Note.transport_delivery_order / Delivery Order.loading_delivery_note for the
DO<->LDN link, Loading DN Batch / APC Batch.linked_coa for the COA chain per
CLAUDE.md's "Allocated Batch -> Linked COA -> Dispatch COA" rule).
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, now


def _resolve_ldn_for_do(do_name: str | None) -> str | None:
	from apc_operations.shipping.services.dispatch_validation_service import resolve_ldn_for_do

	return resolve_ldn_for_do(do_name)


def _resolve_do_for_ldn(ldn_name: str | None) -> str | None:
	if not ldn_name:
		return None
	do_name = frappe.db.get_value("Loading Delivery Note", ldn_name, "transport_delivery_order")
	if do_name:
		return do_name
	from apc_operations.services.delivery_order_service import resolve_do_for_ldn

	return resolve_do_for_ldn(ldn_name)


def ensure_ldn_do_link(
	*,
	ldn_name: str | None = None,
	do_name: str | None = None,
	update_modified: bool = True,
) -> dict[str, str] | None:
	"""Keep Loading Delivery Note.transport_delivery_order and
	Delivery Order.loading_delivery_note pointed at each other. Either name
	can be omitted and will be resolved from the other."""
	if not ldn_name and not do_name:
		return None

	if not ldn_name and do_name:
		ldn_name = _resolve_ldn_for_do(do_name)
	if not do_name and ldn_name:
		do_name = _resolve_do_for_ldn(ldn_name)

	if not ldn_name or not do_name:
		return None

	if frappe.db.get_value("Loading Delivery Note", ldn_name, "transport_delivery_order") != do_name:
		frappe.db.set_value(
			"Loading Delivery Note", ldn_name, "transport_delivery_order", do_name, update_modified=update_modified
		)

	if frappe.db.has_column("Delivery Order", "loading_delivery_note"):
		if frappe.db.get_value("Delivery Order", do_name, "loading_delivery_note") != ldn_name:
			frappe.db.set_value(
				"Delivery Order", do_name, "loading_delivery_note", ldn_name, update_modified=update_modified
			)

	return {"loading_delivery_note": ldn_name, "delivery_order": do_name}


def sync_ldn_transport_context(
	*,
	ldn_name: str | None = None,
	do_name: str | None = None,
	update_modified: bool = True,
) -> None:
	"""Fill the LDN's vehicle/driver/transportation_request from the Job
	Order's Transport Schedule when the LDN doesn't already have them set
	(e.g. LDN was created before a driver/vehicle was assigned)."""
	if not ldn_name and do_name:
		ldn_name = _resolve_ldn_for_do(do_name)
	if not ldn_name:
		return
	if not do_name:
		do_name = _resolve_do_for_ldn(ldn_name)

	ldn = frappe.db.get_value(
		"Loading Delivery Note",
		ldn_name,
		["job_order", "transportation_request", "vehicle", "driver", "driver_name", "driver_phone"],
		as_dict=True,
	)
	if not ldn:
		return

	job_order = ldn.job_order
	if not job_order and do_name:
		job_order = frappe.db.get_value("Delivery Order", do_name, "job_order")

	ts_name = ldn.transportation_request
	if not ts_name and job_order:
		ts_name = frappe.db.get_value("Job Order", job_order, "transport_schedule")
	if not ts_name:
		return

	ts = frappe.db.get_value(
		"Transport Schedule", ts_name, ["assigned_vehicle", "assigned_driver", "driver_phone"], as_dict=True
	)
	if not ts:
		return

	updates: dict[str, Any] = {}
	if not ldn.transportation_request:
		updates["transportation_request"] = ts_name
	if not ldn.vehicle and ts.assigned_vehicle:
		updates["vehicle"] = ts.assigned_vehicle
	if not ldn.driver and ts.assigned_driver:
		updates["driver"] = ts.assigned_driver
	if not ldn.driver_name and ts.assigned_driver:
		full_name = frappe.db.get_value("Driver", ts.assigned_driver, "full_name")
		if full_name:
			updates["driver_name"] = full_name
	if not ldn.driver_phone and ts.driver_phone:
		updates["driver_phone"] = ts.driver_phone

	if updates:
		frappe.db.set_value("Loading Delivery Note", ldn_name, updates, update_modified=update_modified)


def sync_ldn_batch_from_qc_report(ldn_name: str) -> None:
	"""Fill missing COA links on the LDN's batch allocations from each
	batch's own linked COA (CLAUDE.md: Allocated Batch -> Linked COA ->
	Dispatch COA). Also seeds a single allocation row from the linked QC
	Report Request's batch/coa when the LDN has no allocation rows at all
	yet (e.g. a simple single-batch dispatch)."""
	if not ldn_name or not frappe.db.exists("Loading Delivery Note", ldn_name):
		return

	rows = frappe.get_all(
		"Loading DN Batch",
		filters={"parent": ldn_name, "parenttype": "Loading Delivery Note"},
		fields=["name", "batch", "coa"],
	)

	if not rows:
		qcr_batch, qcr_coa = frappe.db.get_value(
			"QC Report Request", {"loading_delivery_note": ldn_name}, ["batch", "coa"]
		) or (None, None)
		if qcr_batch:
			ldn = frappe.get_doc("Loading Delivery Note", ldn_name)
			batch_doc = frappe.db.get_value(
				"APC Batch", qcr_batch, ["item", "item_name", "batch_qty", "manufacturing_date", "uom"], as_dict=True
			)
			ldn.append(
				"batch_allocations",
				{
					"batch": qcr_batch,
					"coa": qcr_coa or frappe.db.get_value("APC Batch", qcr_batch, "linked_coa"),
					"product": batch_doc.item if batch_doc else None,
					"product_name": batch_doc.item_name if batch_doc else None,
					"uom": batch_doc.uom if batch_doc else None,
					"manufacturing_date": batch_doc.manufacturing_date if batch_doc else None,
					"allocated_qty": flt(batch_doc.batch_qty) if batch_doc else 0,
				},
			)
			ldn.save(ignore_permissions=True)
		return

	for row in rows:
		if row.coa or not row.batch:
			continue
		linked_coa = frappe.db.get_value("APC Batch", row.batch, "linked_coa")
		if linked_coa:
			frappe.db.set_value("Loading DN Batch", row.name, "coa", linked_coa, update_modified=False)


def verify_ldn_coas(ldn_name: str) -> bool:
	"""Set coa_verified=1 on the LDN when every batch allocation row has a
	COA and that COA is Approved. Returns whether it's now verified."""
	if not ldn_name or not frappe.db.exists("Loading Delivery Note", ldn_name):
		return False

	rows = frappe.get_all(
		"Loading DN Batch",
		filters={"parent": ldn_name, "parenttype": "Loading Delivery Note"},
		fields=["batch", "coa"],
	)
	if not rows:
		return False

	all_approved = True
	for row in rows:
		if not row.coa:
			all_approved = False
			break
		if frappe.db.get_value("APC COA", row.coa, "approval_status") != "Approved":
			all_approved = False
			break

	if all_approved:
		frappe.db.set_value(
			"Loading Delivery Note",
			ldn_name,
			{
				"coa_verified": 1,
				"coa_verified_by": frappe.session.user,
				"coa_verified_on": now(),
			},
			update_modified=False,
		)
	return all_approved


@frappe.whitelist()
def get_dispatch_readiness(delivery_order: str) -> dict[str, Any]:
	"""Read-only summary of what's still blocking dispatch for a Delivery
	Order - used to drive a "ready to dispatch" indicator/checklist."""
	blockers: list[str] = []
	ldn_name = _resolve_ldn_for_do(delivery_order)
	if not ldn_name:
		blockers.append(_("No Loading Delivery Note linked yet."))
		return {"delivery_order": delivery_order, "loading_delivery_note": None, "ready": False, "blockers": blockers}

	ldn = frappe.db.get_value(
		"Loading Delivery Note",
		ldn_name,
		["net_weight", "coa_verified", "qc_manager_approved", "dispatch_confirmed", "delivery_note_status"],
		as_dict=True,
	) or {}

	if not flt(ldn.get("net_weight")):
		blockers.append(_("Net weight not captured."))
	if not ldn.get("coa_verified"):
		blockers.append(_("COA not verified."))
	if not ldn.get("qc_manager_approved"):
		blockers.append(_("QC manager approval pending."))
	if ldn.get("dispatch_confirmed"):
		blockers.append(_("Dispatch already confirmed."))

	return {
		"delivery_order": delivery_order,
		"loading_delivery_note": ldn_name,
		"delivery_note_status": ldn.get("delivery_note_status"),
		"ready": not blockers,
		"blockers": blockers,
	}
