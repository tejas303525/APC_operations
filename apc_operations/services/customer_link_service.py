# Copyright (c) 2026, APC and contributors
"""Resolve Customer Link fields to valid Customer docnames (not display names)."""

from __future__ import annotations

from typing import Any

import frappe


def resolve_customer_docname(value: str | None) -> str | None:
	"""Return a valid ``Customer.name`` for *value*, or None."""
	if not value:
		return None
	raw = (value or "").strip()
	if not raw:
		return None
	if frappe.db.exists("Customer", raw):
		return raw

	name = frappe.db.get_value("Customer", {"customer_name": raw}, "name")
	if name:
		return name

	rows = frappe.db.sql(
		"""
		SELECT name FROM `tabCustomer`
		WHERE LOWER(customer_name) = LOWER(%s)
		LIMIT 1
		""",
		raw,
	)
	if rows:
		return rows[0][0]
	return None


def get_customer_display_name(customer_docname: str | None) -> str | None:
	if not customer_docname:
		return None
	if not frappe.db.exists("Customer", customer_docname):
		return None
	return frappe.db.get_value("Customer", customer_docname, "customer_name")


def normalize_customer_field(doc, fieldname: str = "customer") -> str | None:
	"""Normalize a Link(Customer) field on *doc* in place. Returns resolved docname or None."""
	current = doc.get(fieldname)
	resolved = resolve_customer_docname(current)
	if resolved:
		if resolved != current:
			doc.set(fieldname, resolved)
		return resolved
	if current:
		doc.set(fieldname, None)
	return None


def resolve_customer_from_job_order(job_order: str | None) -> str | None:
	if not job_order:
		return None
	cust = frappe.db.get_value("Job Order", job_order, "customer")
	return resolve_customer_docname(cust)


def resolve_customer_from_shipping_booking(shipping_booking: str | None) -> str | None:
	if not shipping_booking:
		return None
	cust = frappe.db.get_value("Shipping Booking", shipping_booking, "customer")
	resolved = resolve_customer_docname(cust)
	if resolved:
		return resolved
	jo = frappe.db.get_value("Shipping Booking", shipping_booking, "job_order")
	return resolve_customer_from_job_order(jo)


def resolve_transport_schedule_customer(transport_schedule) -> str | None:
	"""Resolve customer for a Transport Schedule document or name."""
	if isinstance(transport_schedule, str):
		row = frappe.db.get_value(
			"Transport Schedule",
			transport_schedule,
			["customer", "job_order", "shipping_booking"],
			as_dict=True,
		)
		if not row:
			return None
		customer = row.customer
		job_order = row.job_order
		shipping_booking = row.shipping_booking
	else:
		customer = transport_schedule.get("customer") if isinstance(transport_schedule, dict) else transport_schedule.customer
		job_order = transport_schedule.get("job_order") if isinstance(transport_schedule, dict) else transport_schedule.job_order
		shipping_booking = (
			transport_schedule.get("shipping_booking")
			if isinstance(transport_schedule, dict)
			else transport_schedule.shipping_booking
		)

	resolved = resolve_customer_docname(customer)
	if resolved:
		return resolved
	if shipping_booking:
		resolved = resolve_customer_from_shipping_booking(shipping_booking)
		if resolved:
			return resolved
	return resolve_customer_from_job_order(job_order)


def apply_customer_from_sources(transport_doc) -> str | None:
	"""Normalize existing customer or fill from Shipping Booking / Job Order."""
	resolved = resolve_customer_docname(transport_doc.customer)
	if resolved:
		transport_doc.customer = resolved
		return resolved

	if transport_doc.shipping_booking:
		resolved = resolve_customer_from_shipping_booking(transport_doc.shipping_booking)
		if resolved:
			transport_doc.customer = resolved
			return resolved

	if transport_doc.job_order:
		resolved = resolve_customer_from_job_order(transport_doc.job_order)
		if resolved:
			transport_doc.customer = resolved
			return resolved

	if transport_doc.customer and not resolved:
		transport_doc.customer = None
	return None


def get_sddn_customer_display(sddn) -> dict[str, Any]:
	"""Customer fields for Security Console / API (valid link + display name)."""
	if isinstance(sddn, dict):
		customer = sddn.get("customer")
		buyer = sddn.get("buyer")
		job_order = sddn.get("job_order")
		transport_schedule = sddn.get("transport_schedule")
	else:
		customer = sddn.customer
		buyer = sddn.buyer
		job_order = sddn.job_order
		transport_schedule = sddn.transport_schedule

	docname = resolve_customer_docname(customer)
	if not docname:
		docname = resolve_customer_docname(buyer)
	if not docname and transport_schedule:
		docname = resolve_transport_schedule_customer(transport_schedule)
	if not docname and job_order:
		docname = resolve_customer_from_job_order(job_order)

	display = get_customer_display_name(docname) if docname else None
	if not display and customer and not docname:
		display = customer

	return {
		"customer": docname,
		"customer_name": display,
	}


def ensure_transport_schedule_customer_db(transport_schedule_name: str) -> str | None:
	"""Persist a valid Customer docname on Transport Schedule when the DB value is wrong."""
	if not transport_schedule_name:
		return None
	resolved = resolve_transport_schedule_customer(transport_schedule_name)
	if not resolved:
		return None
	stored = frappe.db.get_value("Transport Schedule", transport_schedule_name, "customer")
	if stored != resolved:
		frappe.db.set_value(
			"Transport Schedule",
			transport_schedule_name,
			"customer",
			resolved,
			update_modified=False,
		)
	return resolved


def ensure_sddn_customer_links(sddn, *, fix_transport: bool = True) -> str | None:
	"""Normalize SDDN customer/buyer in memory (and optionally fix linked Transport Schedule)."""
	if fix_transport and sddn.get("transport_schedule"):
		ensure_transport_schedule_customer_db(sddn.transport_schedule)

	customer = resolve_customer_docname(sddn.get("customer"))
	if not customer:
		customer = resolve_customer_docname(sddn.get("buyer"))
	if not customer and sddn.get("transport_schedule"):
		customer = resolve_transport_schedule_customer(sddn.transport_schedule)
	if not customer and sddn.get("job_order"):
		customer = resolve_customer_from_job_order(sddn.job_order)

	if customer:
		sddn.customer = customer
		if not resolve_customer_docname(sddn.get("buyer")):
			sddn.buyer = customer
	else:
		sddn.customer = None

	return customer


def sync_sddn_customer_from_transport(
	transport_schedule_name: str,
	customer_docname: str | None = None,
) -> None:
	"""Backfill SDDN customer/buyer when transport has a valid Customer link."""
	if not transport_schedule_name:
		return
	if not customer_docname:
		customer_docname = resolve_transport_schedule_customer(transport_schedule_name)
	if not customer_docname or not frappe.db.exists("Customer", customer_docname):
		return

	sddn_name = frappe.db.get_value(
		"Security Draft Delivery Note",
		{"transport_schedule": transport_schedule_name},
		"name",
	)
	if not sddn_name:
		return

	updates = {}
	current_customer = frappe.db.get_value("Security Draft Delivery Note", sddn_name, "customer")
	current_buyer = frappe.db.get_value("Security Draft Delivery Note", sddn_name, "buyer")
	if not resolve_customer_docname(current_customer):
		updates["customer"] = customer_docname
	if not resolve_customer_docname(current_buyer):
		updates["buyer"] = customer_docname
	if updates:
		frappe.db.set_value(
			"Security Draft Delivery Note",
			sddn_name,
			updates,
			update_modified=False,
		)


def backfill_customer_link(doctype: str, name: str, customer_value: str | None) -> bool:
	"""Fix one document's customer field; returns True if updated."""
	if not customer_value:
		return False
	resolved = resolve_customer_docname(customer_value)
	if not resolved:
		meta = frappe.get_meta(doctype)
		if meta.has_field("job_order"):
			jo = frappe.db.get_value(doctype, name, "job_order")
			resolved = resolve_customer_from_job_order(jo)
		if not resolved and meta.has_field("transport_schedule"):
			ts = frappe.db.get_value(doctype, name, "transport_schedule")
			resolved = resolve_transport_schedule_customer(ts) if ts else None
		if not resolved and meta.has_field("shipping_booking"):
			sb = frappe.db.get_value(doctype, name, "shipping_booking")
			resolved = resolve_customer_from_shipping_booking(sb) if sb else None

	if resolved and resolved != customer_value:
		frappe.db.set_value(doctype, name, "customer", resolved, update_modified=False)
		return True
	if not resolved and customer_value:
		frappe.db.set_value(doctype, name, "customer", None, update_modified=False)
		return True
	return False
