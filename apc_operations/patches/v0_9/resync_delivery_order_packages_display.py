# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""Re-import Standard Delivery Order after fixing the Marks & Nos./Container No.
	and No. & Kind of Packages columns, which referenced doc/row fields that
	never existed (doc.container_number, doc.package_type/no_and_kind_of_packages,
	row.container_type/package_type). force=True since the record already
	exists - reload_doc silently no-ops on an update without it."""
	frappe.reload_doc("shipping", "print_format", "standard_delivery_order", force=True)
