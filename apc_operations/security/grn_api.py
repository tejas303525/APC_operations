# Copyright (c) 2026, APC and contributors
"""API for Import GRN console."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from apc_operations.shipping.services.import_grn_service import (
	approve_import_grn,
	backfill_missing_import_grns,
	create_import_grn_for_delivery_order,
	get_import_grn_console_counts,
	get_import_grn_detail,
	get_import_grn_queue,
)


@frappe.whitelist()
def get_import_grn_counts() -> dict[str, int]:
	return get_import_grn_console_counts(backfill=True)


@frappe.whitelist()
def get_pending_import_grns() -> list[dict[str, Any]]:
	return get_import_grn_queue(completed=False, backfill=True)


@frappe.whitelist()
def get_completed_import_grns() -> list[dict[str, Any]]:
	return get_import_grn_queue(completed=True, backfill=False)


@frappe.whitelist()
def backfill_import_grns_api() -> dict[str, Any]:
	return backfill_missing_import_grns()


@frappe.whitelist()
def create_import_grn_for_do(
	delivery_order: str,
	pre_check_clearance: str | None = None,
) -> dict[str, Any]:
	return create_import_grn_for_delivery_order(
		delivery_order, pcc_name=pre_check_clearance
	)


@frappe.whitelist()
def get_import_grn_detail_api(name: str) -> dict[str, Any]:
	return get_import_grn_detail(name)


@frappe.whitelist()
def approve_import_grn_api(name: str, remarks: str | None = None) -> dict[str, Any]:
	return approve_import_grn(name, remarks=remarks)
