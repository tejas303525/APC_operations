# Copyright (c) 2026, APC and contributors

import frappe

from apc_operations.shipping.services.import_grn_service import backfill_missing_import_grns


def execute():
	if not frappe.db.has_column("Delivery Order", "import_grn"):
		frappe.db.sql(
			"ALTER TABLE `tabDelivery Order` ADD COLUMN `import_grn` varchar(140) DEFAULT NULL"
		)

	if not frappe.db.table_exists("Import GRN"):
		return

	backfill_missing_import_grns(limit=500)
