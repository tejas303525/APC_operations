# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Third-party loading: when a Job Order is flagged Third Party Loading, the
buyer/customer's own team loads the truck outside APC's security/QC
checks. The Delivery Order routes straight to QC instead of Security - QC
just records the batch/COA number the third party supplied, then issues to
Security's Loading Bay. Security skips its usual inspection checklist and
weight/package variance capture entirely; the only gate is that QC has
already recorded the third-party batch/COA (see dispatch_validation_service
.validate_delivery_note_generation, which branches on
Delivery Order.third_party_loading).
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, now, today


@frappe.whitelist()
def get_third_party_pending_qc() -> list[dict[str, Any]]:
	"""Delivery Orders flagged Third Party Loading, awaiting QC's batch/COA entry."""
	rows = frappe.get_all(
		"Delivery Order",
		filters={
			"third_party_loading": 1,
			"docstatus": ["<", 2],
			"operational_status": ["not in", ["Cancelled", "Gate Out Completed"]],
			"third_party_qc_entered_by": ["in", ["", None]],
		},
		fields=[
			"name",
			"job_order",
			"job_order_number",
			"customer",
			"customer_name",
			"third_party_loader",
			"posting_date",
			"operational_status",
		],
		order_by="creation asc",
		limit=200,
	)

	from apc_operations.shipping.services.job_order_sync_service import (
		attach_job_order_product_summary,
		attach_live_job_order_numbers,
	)

	attach_live_job_order_numbers(rows)
	attach_job_order_product_summary(rows)
	return rows


@frappe.whitelist()
def submit_third_party_qc_entry(
	delivery_order: str, batch: str, coa: str | None = None
) -> dict[str, Any]:
	"""QC records the real APC Batch/COA the third party's goods correspond
	to (creating either on the spot if they don't already exist - a plain
	Frappe Link field lets QC do that inline) and issues the DO to
	Security's Loading Bay - the sole precondition dispatch_validation_service
	checks for a third-party dispatch.

	Per CLAUDE.md's batch/COA traceability rule (Allocated Batch -> Linked
	COA -> Dispatch COA), a COA that already belongs to a *different* batch
	is rejected rather than silently reattached.
	"""
	if not delivery_order:
		frappe.throw(_("delivery_order is required"))
	if not batch:
		frappe.throw(_("Batch is required."))
	if not frappe.db.exists("APC Batch", batch):
		frappe.throw(_("Batch {0} was not found.").format(batch))

	do = frappe.get_doc("Delivery Order", delivery_order)
	if not do.third_party_loading:
		frappe.throw(_("Delivery Order {0} is not flagged Third Party Loading.").format(delivery_order))

	# A prior entry can be corrected (e.g. QC picked a batch that turns out
	# to already be fully dispatched) as long as dispatch hasn't actually
	# been confirmed yet - once that happens the physical stock movement is
	# real and can no longer be swapped out from under it.
	previous_batch = None
	if do.third_party_qc_entered_by:
		from apc_operations.shipping.services.dispatch_validation_service import (
			resolve_ldn_for_do,
		)

		ldn_name = do.loading_delivery_note or resolve_ldn_for_do(do.name)
		if ldn_name and frappe.db.get_value("Loading Delivery Note", ldn_name, "dispatch_confirmed"):
			frappe.throw(
				_(
					"Dispatch has already been confirmed for {0} - the batch/COA can no longer be changed."
				).format(delivery_order)
			)
		previous_batch = do.third_party_batch

	batch_doc = frappe.get_doc("APC Batch", batch)

	# Fail fast here rather than letting Security discover it later at
	# dispatch-confirm time (confirm_dispatch_and_deduct_stock's
	# already-dispatched guard) - a batch that's already Dispatched or has
	# nothing left can't be reused for another trip.
	if batch_doc.name != previous_batch:
		if batch_doc.stock_status in ("Dispatched", "Rejected", "Cancelled"):
			frappe.throw(
				_("Batch {0} is already {1} and cannot be used for another dispatch.").format(
					batch_doc.batch_number or batch_doc.name, batch_doc.stock_status
				)
			)
		if flt(batch_doc.available_quantity) <= 0 and batch_doc.stock_status != "QC Hold":
			frappe.throw(
				_("Batch {0} has no available quantity left.").format(
					batch_doc.batch_number or batch_doc.name
				)
			)

	coa = (coa or batch_doc.linked_coa or "").strip() or None
	if not coa:
		frappe.throw(_("Select or create a COA for batch {0}.").format(batch))
	if not frappe.db.exists("APC COA", coa):
		frappe.throw(_("COA {0} was not found.").format(coa))

	if batch_doc.linked_coa and batch_doc.linked_coa != coa:
		frappe.throw(
			_("COA {0} does not belong to batch {1} (linked COA is {2}).").format(
				coa, batch, batch_doc.linked_coa
			)
		)
	if not batch_doc.linked_coa:
		batch_doc.db_set("linked_coa", coa, update_modified=False)

	# QC recording this batch/COA *is* the clearance for third-party stock -
	# there's no separate internal lab-testing step for goods that never
	# passed through APC's own production. A freshly quick-created APC Batch
	# otherwise defaults to quality_status "Pending QC" / batch_status
	# "Active", and APC Batch.allocate_quantity() (called when dispatch is
	# confirmed) throws if quality_status isn't Approved/QC Cleared.
	if batch_doc.quality_status not in ("Approved", "QC Cleared"):
		batch_doc.db_set("quality_status", "Approved", update_modified=False)
	if batch_doc.batch_status not in ("Active", "On Hold"):
		batch_doc.db_set("batch_status", "Active", update_modified=False)

	do.third_party_batch = batch
	do.third_party_coa = coa
	do.third_party_qc_entered_by = frappe.session.user
	do.third_party_qc_entered_on = now()
	do.operational_status = "Loading Allowed"
	if frappe.db.has_column("Delivery Order", "do_status"):
		do.do_status = "Loading"
	do.save(ignore_permissions=True)

	ldn_name = _ensure_third_party_loading_dn(do, batch_doc, coa, previous_batch=previous_batch)

	frappe.msgprint(
		_("Third-party batch/COA {0}. {1} is now in Security's Loading Bay queue.").format(
			_("corrected") if previous_batch else _("recorded"), delivery_order
		),
		indicator="green",
		alert=True,
	)
	return {"success": True, "delivery_order": do.name, "loading_delivery_note": ldn_name}


def _ensure_third_party_loading_dn(
	do, batch_doc, coa: str, *, previous_batch: str | None = None
) -> str:
	from apc_operations.services.batch_allocation import _coa_number, _product_name
	from apc_operations.shipping.services.dispatch_flow_service import (
		ensure_ldn_do_link,
		sync_ldn_transport_context,
	)
	from apc_operations.shipping.services.dispatch_validation_service import resolve_ldn_for_do
	from apc_operations.shipping.services.uom_service import apply_commercial_fields

	existing = resolve_ldn_for_do(do.name)
	if existing and not frappe.db.exists("Loading Delivery Note", existing):
		# Delivery Order.loading_delivery_note pointed at a since-deleted LDN
		# (e.g. manual cleanup that missed clearing the back-reference) -
		# fall back to creating a fresh one instead of erroring.
		frappe.db.set_value("Delivery Order", do.name, "loading_delivery_note", None, update_modified=False)
		existing = None
	if existing:
		ldn = frappe.get_doc("Loading Delivery Note", existing)
	else:
		ldn = frappe.new_doc("Loading Delivery Note")
		ldn.job_order = do.job_order
		ldn.transport_delivery_order = do.name
		ldn.customer = do.customer
		ldn.buyer = do.buyer or do.customer
		if do.job_order:
			jo_doc = frappe.get_cached_doc("Job Order", do.job_order)
			if hasattr(jo_doc, "get_material_description"):
				ldn.material_description = jo_doc.get_material_description()
		ldn.loading_date = today()
		apply_commercial_fields(ldn, job_order=do.job_order, do_name=do.name, force_uom=True)
		if not ldn.quantity:
			ldn.quantity = do.get("planned_quantity")

	if previous_batch and previous_batch != batch_doc.name:
		ldn.batch_allocations = [r for r in ldn.batch_allocations if r.batch != previous_batch]

	existing_row = next((r for r in ldn.batch_allocations if r.batch == batch_doc.name), None)
	if not existing_row:
		ldn.append(
			"batch_allocations",
			{
				"batch": batch_doc.name,
				"batch_number": batch_doc.batch_number or batch_doc.name,
				"product": batch_doc.product,
				"product_name": _product_name(batch_doc.product),
				"uom": batch_doc.uom,
				"manufacturing_date": batch_doc.manufacturing_date,
				"allocated_qty": flt(batch_doc.batch_quantity) or flt(do.get("planned_quantity")) or 0,
				"coa": coa,
				"coa_number": _coa_number(coa),
			},
		)

	ldn.delivery_note_status = "QC Cleared"
	ldn.qc_status = "QC Cleared"
	# Third-party loading has no Security Inspection / weight capture of its
	# own, and the third-party COA never went through APC's internal
	# approval workflow - dispatch_validation_service skips those checks
	# for third_party_loading DOs. Marking QC clearance/manager-approval
	# done here too keeps the LDN's own record consistent for anyone
	# reading it directly, and matters functionally too:
	# dispatch_lifecycle_service.sync_dispatch_lifecycle_status() only
	# advances a dispatch-confirmed LDN past "QC Final Pending" once both
	# final_qc_clearance AND qc_manager_approved are set - without the
	# latter, the DO stays stuck showing in the QC console's "Pending"
	# queue forever even after the Delivery Note is issued.
	ldn.final_qc_clearance = 1
	ldn.final_qc_clearance_by = frappe.session.user
	ldn.final_qc_clearance_on = now()
	ldn.qc_manager_approved = 1
	ldn.qc_manager_approved_by = frappe.session.user
	ldn.qc_manager_approved_on = now()
	ldn.save(ignore_permissions=True)

	ensure_ldn_do_link(ldn_name=ldn.name, do_name=do.name, update_modified=False)
	sync_ldn_transport_context(ldn_name=ldn.name, do_name=do.name, update_modified=False)
	return ldn.name
