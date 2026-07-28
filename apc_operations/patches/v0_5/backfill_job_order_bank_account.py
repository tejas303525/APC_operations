# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Migrate legacy Job Order bank Select values to Bank Account links."""

from __future__ import annotations

import frappe

_LEGACY_MAP = {
	"HABIB": "HABIB - HABIB",
}


def execute():
	if not frappe.db.table_exists("Job Order"):
		return

	for legacy, bank_account in _LEGACY_MAP.items():
		if not frappe.db.exists("Bank Account", bank_account):
			continue

		frappe.db.sql(
			"""
			UPDATE `tabJob Order`
			SET bank_account = %(bank_account)s
			WHERE IFNULL(bank_account, '') IN ('', %(legacy)s)
			  AND bank = %(legacy)s
			""",
			{"bank_account": bank_account, "legacy": legacy},
		)

		frappe.db.sql(
			"""
			UPDATE `tabJob Order`
			SET bank_account = %(bank_account)s
			WHERE bank_account = %(legacy)s
			""",
			{"bank_account": bank_account, "legacy": legacy},
		)

	# Clear orphaned legacy column values after migration.
	if frappe.db.has_column("Job Order", "bank"):
		frappe.db.sql(
			"""
			UPDATE `tabJob Order`
			SET bank = NULL
			WHERE bank = %(legacy)s AND bank_account = %(bank_account)s
			""",
			{"legacy": legacy, "bank_account": bank_account},
		)

	frappe.db.commit()
