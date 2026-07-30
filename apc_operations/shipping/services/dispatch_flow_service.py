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
	yet (e.g. a simple single-batch dispatch).

	Also backfills coa_number/product_name/batch_number - these are
	fetch_from fields that only populate via client-side onchange, never for
	rows appended server-side, so a row can have `coa` set correctly while
	`coa_number` stays blank (silently drops the COA off print formats that
	only read coa_number)."""
	if not ldn_name or not frappe.db.exists("Loading Delivery Note", ldn_name):
		return

	from apc_operations.services.batch_allocation import _coa_number, _product_name

	rows = frappe.get_all(
		"Loading DN Batch",
		filters={"parent": ldn_name, "parenttype": "Loading Delivery Note"},
		fields=["name", "batch", "coa", "coa_number", "product", "product_name", "batch_number"],
	)

	if not rows:
		qcr_batch, qcr_coa = frappe.db.get_value(
			"QC Report Request", {"loading_delivery_note": ldn_name}, ["batch", "coa"]
		) or (None, None)
		if qcr_batch:
			ldn = frappe.get_doc("Loading Delivery Note", ldn_name)
			batch_doc = frappe.db.get_value(
				"APC Batch", qcr_batch, ["product", "batch_quantity", "manufacturing_date", "uom"], as_dict=True
			)
			coa = qcr_coa or frappe.db.get_value("APC Batch", qcr_batch, "linked_coa")
			product = batch_doc.product if batch_doc else None
			ldn.append(
				"batch_allocations",
				{
					"batch": qcr_batch,
					"batch_number": qcr_batch,
					"coa": coa,
					"coa_number": _coa_number(coa),
					"product": product,
					"product_name": _product_name(product),
					"uom": batch_doc.uom if batch_doc else None,
					"manufacturing_date": batch_doc.manufacturing_date if batch_doc else None,
					"allocated_qty": flt(batch_doc.batch_quantity) if batch_doc else 0,
				},
			)
			ldn.save(ignore_permissions=True)
		return

	for row in rows:
		updates = {}
		if not row.coa and row.batch:
			linked_coa = frappe.db.get_value("APC Batch", row.batch, "linked_coa")
			if linked_coa:
				updates["coa"] = linked_coa
				row.coa = linked_coa
		if row.coa and not row.coa_number:
			coa_number = _coa_number(row.coa)
			if coa_number:
				updates["coa_number"] = coa_number
		if row.product and not row.product_name:
			product_name = _product_name(row.product)
			if product_name:
				updates["product_name"] = product_name
		if row.batch and not row.batch_number:
			updates["batch_number"] = row.batch
		if updates:
			frappe.db.set_value("Loading DN Batch", row.name, updates, update_modified=False)


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
	"""Read-only checklist of what's still blocking dispatch for a Delivery
	Order - drives the Loading Bay Console's readiness widget.

	Return shape is a hard contract with security_console.js's
	_renderDispatchReadiness(): {steps: [{label, done, detail}], blocking,
	can_issue_dn, loading_delivery_note}. An empty/missing `steps` list makes
	the console show "No Loading DN linked" regardless of `blocking` or
	`ready` — a shape mismatch here silently reads as that message even when
	an LDN *is* linked.
	"""
	ldn_name = _resolve_ldn_for_do(delivery_order)
	if not ldn_name:
		return {
			"delivery_order": delivery_order,
			"loading_delivery_note": None,
			"steps": [],
			"blocking": [],
			"can_issue_dn": False,
		}

	do = frappe.db.get_value(
		"Delivery Order",
		delivery_order,
		["third_party_loading", "third_party_batch", "third_party_coa"],
		as_dict=True,
	) or {}
	if do.get("third_party_loading"):
		# Loading happened outside APC's own checks - the only thing this
		# DO needs before Security can issue the Delivery Note is QC having
		# recorded what the third party supplied.
		entered = bool(do.get("third_party_batch") and do.get("third_party_coa"))
		dispatch_confirmed = bool(
			frappe.db.get_value("Loading Delivery Note", ldn_name, "dispatch_confirmed")
		)
		return {
			"delivery_order": delivery_order,
			"loading_delivery_note": ldn_name,
			"weight_variance_method": None,
			"third_party_loading": True,
			"steps": [
				{"label": _("Loading DN created"), "done": True},
				{"label": _("QC entered third-party batch/COA"), "done": entered},
			],
			"blocking": [_("Dispatch already confirmed.")] if dispatch_confirmed else [],
			"can_issue_dn": entered and not dispatch_confirmed,
		}

	ldn = frappe.db.get_value(
		"Loading Delivery Note",
		ldn_name,
		[
			"name",
			"coa_verified",
			"qc_manager_approved",
			"dispatch_confirmed",
			"delivery_note_status",
			"loading_start_time",
			"loading_end_time",
			"tare_weight",
			"gross_weight",
			"net_weight",
			"weight_variance_method",
			"expected_packaging_qty",
			"loaded_packaging_qty",
			"package_variance_status",
		],
		as_dict=True,
	) or {}

	has_batches = bool(
		frappe.db.exists("Loading DN Batch", {"parent": ldn_name, "parenttype": "Loading Delivery Note"})
	)
	is_package_count = ldn.get("weight_variance_method") == "Package Count"

	steps = [
		{"label": _("Loading DN created"), "done": True},
		{"label": _("Batch & COA synced"), "done": has_batches},
		{"label": _("COA verified"), "done": bool(ldn.get("coa_verified"))},
		{"label": _("Loading completed"), "done": bool(ldn.get("loading_start_time") and ldn.get("loading_end_time"))},
	]
	if is_package_count:
		steps.append(
			{
				"label": _("Package count matches Job Order"),
				"done": bool(
					flt(ldn.get("expected_packaging_qty"))
					and flt(ldn.get("loaded_packaging_qty"))
					and flt(ldn.get("expected_packaging_qty")) == flt(ldn.get("loaded_packaging_qty"))
				),
			}
		)
	else:
		steps.extend(
			[
				{"label": _("Tare weight recorded"), "done": bool(flt(ldn.get("tare_weight")))},
				{"label": _("Gross weight recorded"), "done": bool(flt(ldn.get("gross_weight")))},
				{"label": _("Net weight captured"), "done": bool(flt(ldn.get("net_weight")))},
			]
		)
	steps.append({"label": _("QC manager approved"), "done": bool(ldn.get("qc_manager_approved"))})

	blocking: list[str] = []
	if ldn.get("dispatch_confirmed"):
		blocking.append(_("Dispatch already confirmed."))

	can_issue_dn = all(s["done"] for s in steps) and not ldn.get("dispatch_confirmed")

	return {
		"delivery_order": delivery_order,
		"loading_delivery_note": ldn_name,
		"delivery_note_status": ldn.get("delivery_note_status"),
		"weight_variance_method": ldn.get("weight_variance_method") or "Weighbridge",
		"steps": steps,
		"blocking": blocking,
		"can_issue_dn": can_issue_dn,
	}
