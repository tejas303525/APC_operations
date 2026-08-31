"""Invoice generation for outward dispatch.

An APC Invoice is generated once, at the moment a Loading Delivery Note's
dispatch is confirmed (see batch_allocation.confirm_dispatch_and_deduct_stock).
Job Order is the single source of truth for the commercial numbers - this
module reads Job Order's already-computed custom_subtotal/custom_vat_amount/
custom_grand_total rather than recalculating VAT independently, so the
invoice can never drift from what the Job Order form shows.
"""

import frappe
from frappe.utils import flt, today


def get_customer_address_block(customer):
	"""Best-effort address/phone/fax/TRN text for a customer, read live from
	master data (Customer.customer_primary_address, falling back to any
	Address linked to the customer if no primary address is set).

	Returns a dict of blanks if no address is linked - callers must never
	fail just because address master data is incomplete. This is called
	fresh every time (invoice/LDN before_print) rather than cached on the
	document, so a document always reflects the customer's current address
	instead of a stale one-time snapshot."""
	blank = {
		"address_line": "",
		"phone": "",
		"fax": "",
		"emirate": "",
		"country": "UAE",
		"trn": "",
	}

	if not customer:
		return blank

	trn = frappe.db.get_value("Customer", customer, "tax_id") or ""

	address_name = frappe.db.get_value("Customer", customer, "customer_primary_address")
	if not address_name:
		address_name = frappe.db.get_value(
			"Dynamic Link",
			{"link_doctype": "Customer", "link_name": customer, "parenttype": "Address"},
			"parent",
			order_by="modified desc",
		)

	if not address_name:
		return {**blank, "trn": trn}

	addr = frappe.db.get_value(
		"Address",
		address_name,
		["address_line1", "address_line2", "city", "state", "country", "phone", "fax"],
		as_dict=True,
	)
	if not addr:
		return {**blank, "trn": trn}

	line_parts = [p for p in [addr.address_line1, addr.address_line2, addr.city] if p]
	return {
		"address_line": ", ".join(line_parts),
		"phone": addr.phone or "",
		"fax": addr.fax or "",
		"emirate": addr.state or "",
		"country": addr.country or "UAE",
		"trn": trn,
	}


def generate_invoice_for_loading_dn(loading_dn_name: str) -> str:
	"""Create (or return the existing) APC Invoice for a Loading Delivery Note.

	Idempotent - if an invoice already exists for this Loading DN, it is
	returned as-is rather than duplicated (dispatch confirmation should
	never be blocked or double-invoiced on retry).
	"""
	existing = frappe.db.exists("APC Invoice", {"loading_delivery_note": loading_dn_name})
	if existing:
		return existing

	ldn = frappe.get_doc("Loading Delivery Note", loading_dn_name)
	if not ldn.job_order:
		frappe.throw(frappe._("Cannot generate invoice: Loading Delivery Note {0} has no Job Order linked.").format(loading_dn_name))

	jo = frappe.get_doc("Job Order", ldn.job_order)

	is_mainland = bool(jo.get("custom_mainland_uae_sale_vat_applicable"))
	invoice_type = "Tax Invoice" if is_mainland else "International Invoice"

	payment_terms_label = ""
	if jo.payment_terms:
		payment_terms_label = frappe.db.get_value("Payment Terms Template", jo.payment_terms, "template_name") or jo.payment_terms

	port_of_loading = ""
	if jo.port_of_loading:
		port_of_loading = frappe.db.get_value("Port", jo.port_of_loading, "port_name") or jo.port_of_loading

	port_of_discharge = ""
	if jo.port_of_discharge:
		port_of_discharge = frappe.db.get_value("Port", jo.port_of_discharge, "port_name") or jo.port_of_discharge

	addr = get_customer_address_block(jo.customer)

	inv = frappe.new_doc("APC Invoice")
	inv.invoice_type = invoice_type
	inv.status = "Issued"
	inv.mainland_uae_sale = 1 if is_mainland else 0

	inv.job_order = jo.name
	inv.loading_delivery_note = ldn.name
	inv.customer = jo.customer
	inv.customer_name = jo.customer_name

	inv.invoice_date = today()
	inv.delivery_note_ref = ldn.name
	inv.delivery_note_date = ldn.get("loading_date") or today()
	inv.supplier_ref = jo.pi_number
	inv.supplier_ref_date = jo.get("date")
	inv.buyers_order_no = jo.job_order_number
	inv.mode_of_payment = payment_terms_label
	inv.terms_of_delivery = jo.terms_of_delivery or ""

	inv.port_of_loading = port_of_loading
	inv.port_of_discharge = port_of_discharge

	inv.consignee_name = jo.customer_name
	inv.consignee_address = addr["address_line"]
	inv.consignee_phone = addr["phone"]
	inv.consignee_fax = addr["fax"]

	inv.buyer_name = jo.customer_name
	inv.buyer_address = addr["address_line"]
	inv.buyer_phone = addr["phone"]
	inv.buyer_fax = addr["fax"]
	inv.buyer_emirate = addr["emirate"]
	inv.buyer_country = addr["country"]
	inv.place_of_supply = f"UAE, {addr['emirate']}" if addr["emirate"] else "UAE"

	inv.currency = jo.currency or "AED"
	inv.vat_percentage = 5 if is_mainland else 0

	for row in jo.items:
		description = row.item_name or row.item
		if row.get("packaging_type"):
			description = f"{description}\n{row.packaging_type}"

		inv.append("items", {
			"item": row.item,
			"description": description,
			"quantity": flt(row.quantity),
			"uom": row.uom,
			"rate": flt(row.get("custom_rate_per_unit")),
			"vat_percentage": 5 if is_mainland else 0,
		})

	inv.insert(ignore_permissions=True)

	frappe.db.set_value("Loading Delivery Note", ldn.name, "invoice_reference", inv.name, update_modified=False)

	return inv.name
