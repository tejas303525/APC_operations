# Copyright (c) 2026, APC and contributors

import frappe

from apc_operations.shipping.services.import_grn_service import backfill_missing_import_grns


def execute():
	"""Re-run Import GRN backfill for authorized import DOs (idempotent)."""
	if not frappe.db.table_exists("Import GRN"):
		return
	backfill_missing_import_grns(limit=500)
