# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Link cleared import Job Orders to export Job Orders for onward sales."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import today



def _import_job_row(job_order: str) -> dict[str, Any]:
	jo = frappe.db.get_value(
		"Job Order",
		job_order,
		[
			"name",
			"commercial_movement",
			"linked_export_job_order",
			"supplier",
			"supplier_name",
			"terms_of_delivery",
			"mode_of_transport",
			"port_of_loading",
			"port_of_discharge",
		],
		as_dict=True,
	)
	if not jo:
		frappe.throw(_("Job Order {0} not found").format(job_order))
	if (jo.get("commercial_movement") or "").strip() != "Import":
		frappe.throw(_("Job Order {0} is not an Import movement.").format(job_order))
	return jo


def _handoff_ready(job_order: str) -> bool:
	"""True when import security + QC pre-check path is far enough for export handoff."""
	if frappe.db.get_value("Job Order", job_order, "linked_export_job_order"):
		return False

	from apc_operations.services.delivery_order_service import (
		find_delivery_order_for_job_order_primary,
	)

	do_name = find_delivery_order_for_job_order_primary(job_order)
	if not do_name:
		return False

	op = frappe.db.get_value("Delivery Order", do_name, "operational_status") or ""
	if op in {
		"QC Pre-check Passed",
		"Loading Allowed",
		"Sent to QC",
		"QC In Progress",
		"QC Cleared",
		"Completed",
	}:
		return True

	pcc = frappe.db.get_value("Delivery Order", do_name, "pre_check_clearance")
	if pcc:
		qc_status = frappe.db.get_value("Pre-Check Clearance", pcc, "qc_status")
		if qc_status == "Passed":
			return True

	qcr_rows = frappe.get_all(
		"QC Report Request",
		filters={"job_order": job_order},
		fields=["qc_status"],
		order_by="modified desc",
		limit=1,
	)
	if qcr_rows:
		return qcr_rows[0].get("qc_status") in ("QC Cleared", "Pending QC")
	return False


@frappe.whitelist()
def get_import_handoff_status(job_order: str) -> dict[str, Any]:
	jo = _import_job_row(job_order)
	ready = _handoff_ready(job_order)
	export_jo = jo.get("linked_export_job_order")
	return {
		"job_order": job_order,
		"ready_for_handoff": ready,
		"linked_export_job_order": export_jo,
		"can_link_export": ready and not export_jo,
		"can_create_export": ready and not export_jo,
	}


@frappe.whitelist()
def link_import_to_export_job_order(import_job_order: str, export_job_order: str) -> dict[str, Any]:
	if not import_job_order or not export_job_order:
		frappe.throw(_("import_job_order and export_job_order are required"))

	_import_job_row(import_job_order)

	if not frappe.db.exists("Job Order", export_job_order):
		frappe.throw(_("Export Job Order {0} not found").format(export_job_order))

	export_movement = frappe.db.get_value(
		"Job Order", export_job_order, "commercial_movement"
	)
	if (export_movement or "Export") != "Export":
		frappe.throw(_("Job Order {0} must be an Export movement.").format(export_job_order))

	if not _handoff_ready(import_job_order):
		frappe.throw(
			_(
				"Import Job Order {0} is not ready for export handoff. "
				"Complete security review and QC pre-check first."
			).format(import_job_order)
		)

	frappe.db.set_value(
		"Job Order",
		import_job_order,
		"linked_export_job_order",
		export_job_order,
		update_modified=True,
	)
	if frappe.db.has_column("Job Order", "source_import_job_order"):
		frappe.db.set_value(
			"Job Order",
			export_job_order,
			"source_import_job_order",
			import_job_order,
			update_modified=False,
		)

	return get_import_handoff_status(import_job_order)


@frappe.whitelist()
def create_export_job_order_from_import(
	import_job_order: str,
	customer: str | None = None,
	terms_of_delivery: str | None = None,
) -> dict[str, Any]:
	"""Create an export Job Order from a cleared import Job Order and link them."""
	jo = _import_job_row(import_job_order)

	if jo.get("linked_export_job_order"):
		return {
			"import_job_order": import_job_order,
			"export_job_order": jo["linked_export_job_order"],
			"created": False,
		}

	if not _handoff_ready(import_job_order):
		frappe.throw(
			_(
				"Import Job Order {0} is not ready for export handoff. "
				"Complete security review and QC pre-check first."
			).format(import_job_order)
		)

	if not customer:
		frappe.throw(_("customer is required when creating an export Job Order from import."))

	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} not found").format(customer))

	import_doc = frappe.get_doc("Job Order", import_job_order)
	export = frappe.new_doc("Job Order")
	export.commercial_movement = "Export"
	export.customer = customer
	export.date = today()
	export.status = "Draft"
	export.terms_of_delivery = terms_of_delivery or import_doc.terms_of_delivery or "FOB"
	export.mode_of_transport = import_doc.mode_of_transport or "Sea"
	export.port_of_loading = import_doc.port_of_loading
	export.port_of_discharge = import_doc.port_of_discharge
	if frappe.db.has_column("Job Order", "source_import_job_order"):
		export.source_import_job_order = import_job_order

	for row in import_doc.items or []:
		export.append(
			"items",
			{
				"item": row.item,
				"item_name": row.item_name,
				"description": row.description,
				"quantity": row.quantity,
				"uom": row.uom,
				"net_weight": row.net_weight,
			},
		)

	export.insert(ignore_permissions=True)

	frappe.db.set_value(
		"Job Order",
		import_job_order,
		"linked_export_job_order",
		export.name,
		update_modified=True,
	)

	return {
		"import_job_order": import_job_order,
		"export_job_order": export.name,
		"created": True,
	}
