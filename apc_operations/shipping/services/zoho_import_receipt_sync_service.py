# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Zoho Books import receipt / stock-in integration point (stub).

Finance and inventory of record remain in Zoho Books. This module logs
intended purchase-receive actions after import QC pre-check passes.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _

from apc_operations.shipping.doctype.apc_operations_settings.apc_operations_settings import (
	zoho_dispatch_stub_only,
	zoho_dispatch_sync_enabled,
)
from apc_operations.zoho.integration import log_sync


@frappe.whitelist()
def push_import_receipt_to_zoho(delivery_order: str) -> dict[str, Any]:
	"""Post import stock receipt to Zoho Books (stub until API credentials exist)."""
	if not delivery_order:
		frappe.throw(_("delivery_order is required"))

	if not frappe.db.exists("Delivery Order", delivery_order):
		frappe.throw(_("Delivery Order {0} not found").format(delivery_order))

	movement = "Outward"
	if frappe.db.has_column("Delivery Order", "commercial_movement"):
		movement = (
			frappe.db.get_value("Delivery Order", delivery_order, "commercial_movement")
			or "Outward"
		)
	if movement != "Import":
		return {"success": False, "skipped": True, "reason": "not-import-do"}

	jo = frappe.db.get_value("Delivery Order", delivery_order, "job_order")
	payload = _build_receipt_payload(delivery_order, jo)

	if not zoho_dispatch_sync_enabled():
		log_sync(
			sync_type="Import Receipt",
			sync_status="Skipped",
			apc_document_type="Delivery Order",
			apc_document=delivery_order,
			request_data=payload,
			error_message="zoho-sync-disabled",
		)
		return {"success": False, "skipped": True, "reason": "zoho-sync-disabled"}

	stub_id = f"STUB-RCPT-{delivery_order}"
	if zoho_dispatch_stub_only():
		log_sync(
			sync_type="Import Receipt",
			sync_status="Success",
			zoho_id=stub_id,
			apc_document_type="Delivery Order",
			apc_document=delivery_order,
			request_data=payload,
			response_data={"stub": True, "zoho_receipt_id": stub_id},
		)
	else:
		log_sync(
			sync_type="Import Receipt",
			sync_status="Pending",
			apc_document_type="Delivery Order",
			apc_document=delivery_order,
			request_data=payload,
			error_message="Zoho Books purchase-receive API not configured",
		)
		return {
			"success": False,
			"reason": "api-not-configured",
			"message": _("Zoho import receipt API is not configured yet."),
		}

	if jo and frappe.db.has_column("Job Order", "zoho_import_receipt_id"):
		frappe.db.set_value(
			"Job Order",
			jo,
			"zoho_import_receipt_id",
			stub_id,
			update_modified=False,
		)

	return {"success": True, "zoho_receipt_id": stub_id, "stub": True}


def maybe_push_import_receipt_after_precheck(delivery_order: str | None) -> None:
	"""Called when import QC pre-check passes."""
	if not delivery_order:
		return
	try:
		push_import_receipt_to_zoho(delivery_order)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Zoho Import Receipt Push")


def _build_receipt_payload(delivery_order: str, job_order: str | None) -> dict[str, Any]:
	do = frappe.get_doc("Delivery Order", delivery_order)
	items = []
	for row in do.items or []:
		items.append(
			{
				"item_code": row.item_code,
				"description": row.description,
				"qty": row.qty,
				"uom": row.uom,
			}
		)

	pcc_batch = None
	if do.pre_check_clearance:
		pcc_batch = frappe.db.get_value(
			"Pre-Check Clearance", do.pre_check_clearance, "batch_no"
		)

	return {
		"delivery_order": delivery_order,
		"job_order": job_order,
		"supplier": getattr(do, "supplier", None),
		"batch_no": pcc_batch,
		"items": items,
		"operation": "import_receipt",
	}
