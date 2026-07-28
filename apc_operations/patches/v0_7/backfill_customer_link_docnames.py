# Copyright (c) 2026, APC and contributors
"""Fix Customer Link fields stored as customer_name instead of Customer docname."""

import frappe

from apc_operations.services.customer_link_service import (
	backfill_customer_link,
	resolve_transport_schedule_customer,
	sync_sddn_customer_from_transport,
)


_CUSTOMER_DOCTYPES = (
	"Job Order",
	"Shipping Booking",
	"Transport Schedule",
	"Security Draft Delivery Note",
	"Loading Delivery Note",
	"Gate Pass",
	"Security Inspection",
)


def execute():
	updated = 0
	for doctype in _CUSTOMER_DOCTYPES:
		if not frappe.db.table_exists(f"tab{doctype}"):
			continue
		if not frappe.get_meta(doctype).has_field("customer"):
			continue
		filters = {"docstatus": ["!=", 2]} if frappe.get_meta(doctype).has_field("docstatus") else {}
		for row in frappe.get_all(doctype, fields=["name", "customer"], filters=filters):
			if not row.customer:
				continue
			if backfill_customer_link(doctype, row.name, row.customer):
				updated += 1

	# SDDN buyer may be valid while customer is wrong — fix buyer-only rows
	for row in frappe.get_all(
		"Security Draft Delivery Note",
		fields=["name", "buyer", "customer", "transport_schedule"],
	):
		from apc_operations.services.customer_link_service import resolve_customer_docname

		buyer = resolve_customer_docname(row.buyer)
		customer = resolve_customer_docname(row.customer)
		updates = {}
		if buyer and buyer != row.buyer:
			updates["buyer"] = buyer
		if not customer and buyer:
			updates["customer"] = buyer
		if updates:
			frappe.db.set_value(
				"Security Draft Delivery Note",
				row.name,
				updates,
				update_modified=False,
			)
			updated += 1

	ts_filters = {"docstatus": ["!=", 2]} if frappe.get_meta("Transport Schedule").has_field("docstatus") else {}
	for ts in frappe.get_all("Transport Schedule", filters=ts_filters, pluck="name"):
		customer = resolve_transport_schedule_customer(ts)
		if customer:
			sync_sddn_customer_from_transport(ts, customer)

	frappe.db.commit()
	print(f"Backfilled customer links on {updated} document(s).")
