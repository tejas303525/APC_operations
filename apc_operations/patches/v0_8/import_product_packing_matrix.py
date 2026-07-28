# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Import APC Product Packing Profile rows from bundled CSV (idempotent)."""

import frappe


def execute():
	if not frappe.db.exists("DocType", "APC Product Packing Profile"):
		return

	from apc_operations.shipping.services.packing_matrix_import_service import (
		replace_packing_matrix_from_csv,
	)

	result = replace_packing_matrix_from_csv()
	frappe.logger("apc_operations").info(
		"Packing matrix import: created=%s skipped=%s tare=%s errors=%s",
		result.get("created"),
		result.get("skipped"),
		result.get("tare_created"),
		len(result.get("errors") or []),
	)
