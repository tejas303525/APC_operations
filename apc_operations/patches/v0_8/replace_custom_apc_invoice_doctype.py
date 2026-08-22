"""The user built an initial "APC Invoice" DocType by hand via the Desk GUI
(New DocType) while we were scoping the invoicing feature together. It's
being superseded here by a proper app-owned DocType (JSON in git, real
controller, child table for line items) so it migrates consistently across
environments like every other business doctype in this app.

Safe to drop and recreate: the GUI version had no generation logic wired to
it yet, so it should always be empty. We only delete it if that holds true -
if it somehow already has records, leave it alone and log instead of
destroying data.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "APC Invoice"):
		return

	doctype = frappe.get_doc("DocType", "APC Invoice")
	if not doctype.custom:
		# Already replaced by the app-owned version in an earlier migrate run.
		return

	if frappe.db.table_exists("APC Invoice"):
		existing_count = frappe.db.count("APC Invoice")
		if existing_count:
			frappe.log_error(
				f"Skipped replacing custom APC Invoice DocType - {existing_count} "
				f"record(s) already exist. Resolve manually before re-running this patch.",
				"replace_custom_apc_invoice_doctype",
			)
			return

	frappe.delete_doc("DocType", "APC Invoice", force=True, ignore_permissions=True)
