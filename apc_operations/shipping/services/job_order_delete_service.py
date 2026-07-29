# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Cascade delete for Job Order and its operational movement documents.

Only documents that exist *for* this Job Order's outward-movement pipeline
are deleted (Transport Schedule, Shipping Booking, Security Draft Delivery
Note, Security Inspection, Loading Delivery Note, Delivery Order, Import GRN,
Security Dispatch, Transport PO Request, Weighment Slip, QC Report Request).

APC Batch and APC COA are deliberately excluded from deletion even though
they carry a job_order reference: those are real inventory/quality records
that exist independently of any one Job Order (a batch is produced and
QC-approved before ever being allocated to a job), so deleting a Job Order
must never destroy that data - only the reference is cleared.
"""

from __future__ import annotations

import frappe
from frappe import _

# Ordered downstream-first: nothing later in this list should still be
# link-referencing something earlier once deletion starts (force=True on
# delete_doc handles residual link checks regardless, but this keeps the
# order sane).
LINKED_DOCTYPES = (
	"Loading Delivery Note",
	"Delivery Order",
	"Weighment Slip",
	"QC Report Request",
	"Security Inspection",
	"Security Draft Delivery Note",
	"Import GRN",
	"Security Dispatch",
	"Transport PO Request",
	"Transport Schedule",
	"Shipping Booking",
)

# Real inventory/quality records - unlink, never delete.
UNLINK_ONLY_DOCTYPES = (
	"APC Batch",
	"APC COA",
)


def _find_linked(job_order: str) -> list[dict]:
	found = []
	for doctype in LINKED_DOCTYPES:
		if not frappe.db.exists("DocType", doctype) or not frappe.db.has_column(doctype, "job_order"):
			continue
		for name in frappe.get_all(doctype, filters={"job_order": job_order}, pluck="name"):
			found.append({"doctype": doctype, "name": name, "label": f"{doctype}: {name}"})
	return found


def _find_unlink_only(job_order: str) -> list[dict]:
	found = []
	for doctype in UNLINK_ONLY_DOCTYPES:
		if not frappe.db.exists("DocType", doctype) or not frappe.db.has_column(doctype, "job_order"):
			continue
		for name in frappe.get_all(doctype, filters={"job_order": job_order}, pluck="name"):
			found.append({"doctype": doctype, "name": name, "label": f"{doctype}: {name} (kept, will be unlinked)"})
	return found


def get_job_order_delete_preview(job_order: str) -> dict:
	if not job_order or not frappe.db.exists("Job Order", job_order):
		frappe.throw(_("Job Order {0} does not exist.").format(job_order))

	return {
		"job_order": job_order,
		"job_order_number": frappe.db.get_value("Job Order", job_order, "job_order_number"),
		"linked_documents": _find_linked(job_order) + _find_unlink_only(job_order),
	}


def _delete_one(doctype: str, name: str) -> None:
	doc = frappe.get_doc(doctype, name)
	if doc.meta.is_submittable and doc.docstatus.is_submitted():
		doc.cancel()
	frappe.delete_doc(doctype, name, force=True, ignore_permissions=True, ignore_missing=True)


def delete_job_order_with_linked(job_order: str) -> dict:
	if not job_order or not frappe.db.exists("Job Order", job_order):
		frappe.throw(_("Job Order {0} does not exist.").format(job_order))

	linked = _find_linked(job_order)
	deleted_count = 0

	for row in linked:
		_delete_one(row["doctype"], row["name"])
		deleted_count += 1

	for row in _find_unlink_only(job_order):
		frappe.db.set_value(row["doctype"], row["name"], "job_order", None, update_modified=False)

	_delete_one("Job Order", job_order)
	deleted_count += 1

	frappe.db.commit()

	return {"job_order": job_order, "deleted_count": deleted_count}
