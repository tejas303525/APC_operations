# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Print context for Standard Loading Delivery Note (loaded weight vs drums)."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt

from apc_operations.shipping.services.uom_service import (
	kg_to_commercial_quantity,
	quantity_to_kg,
)

_BULK_HINTS = ("bulk", "tanker", "iso tank", "flexi", "tank ", " road tank")
_DRUM_HINTS = ("drum", "barrel")


def resolve_customer_display_name(customer: str | None) -> str | None:
	if not customer:
		return None
	return frappe.db.get_value("Customer", customer, "customer_name") or customer


def resolve_customer_address(
	customer: str | None,
	*,
	shipping_address: str | None = None,
	shipping_address_name: str | None = None,
) -> str:
	if shipping_address_name and shipping_address_name.strip():
		return shipping_address_name.strip()
	if shipping_address and frappe.db.exists("Address", shipping_address):
		return frappe.get_doc("Address", shipping_address).get_display()
	if not customer:
		return ""
	addr_row = frappe.db.sql(
		"""
		select a.name from `tabAddress` a
		inner join `tabDynamic Link` dl on dl.parent=a.name and dl.parenttype='Address'
		where dl.link_doctype='Customer' and dl.link_name=%s
		order by ifnull(a.is_primary_address,0) desc, a.modified desc
		limit 1
		""",
		customer,
	)
	if addr_row and addr_row[0]:
		return frappe.get_doc("Address", addr_row[0][0]).get_display()
	return ""


def resolve_buyer_party(
	*,
	buyer: str | None,
	customer: str | None,
	customer_name: str | None = None,
	shipping_address: str | None = None,
	shipping_address_name: str | None = None,
) -> dict[str, str]:
	buyer_customer = buyer or customer
	name = (
		resolve_customer_display_name(buyer_customer)
		or customer_name
		or buyer_customer
		or "-"
	)
	address = resolve_customer_address(
		buyer_customer or customer,
		shipping_address=shipping_address,
		shipping_address_name=shipping_address_name,
	)
	return {"buyer_name": name, "buyer_address": address}


def job_order_packaging_by_item(job_order: str | None) -> dict[str, str]:
	if not job_order:
		return {}
	rows = frappe.get_all(
		"Job Order Item",
		filters={"parent": job_order},
		fields=["item", "packaging_type", "packaging"],
	)
	result: dict[str, str] = {}
	for row in rows:
		if not row.item:
			continue
		pkg = (row.packaging_type or row.packaging or "").strip()
		if pkg:
			result[row.item] = pkg
	return result


def _packaging_text(*values: str | None) -> str:
	parts = [(v or "").strip().lower() for v in values if v]
	return " ".join(parts)


def is_bulk_packaging(packaging_type: str | None, material_description: str | None = None) -> bool:
	text = _packaging_text(packaging_type, material_description)
	if not text:
		return False
	if any(h in text for h in _DRUM_HINTS):
		return False
	return any(h in text for h in _BULK_HINTS)


def is_drum_packaging(packaging_type: str | None, material_description: str | None = None) -> bool:
	text = _packaging_text(packaging_type, material_description)
	return any(h in text for h in _DRUM_HINTS)


def _sum_loading_entry_bags(security_inspection: str | None) -> int:
	from apc_operations.shipping.services.packing_calculation_service import (
		loaded_packaging_qty_from_loading_entries,
	)

	return loaded_packaging_qty_from_loading_entries(security_inspection)


def _sum_loading_entry_kg(security_inspection: str | None) -> float:
	if not security_inspection:
		return 0.0
	rows = frappe.get_all(
		"Loading Entry",
		filters={"parent": security_inspection, "parenttype": "Security Inspection"},
		fields=["actual_weight_kg"],
	)
	return sum(flt(r.actual_weight_kg) for r in rows)


def _resolve_shipping_booking_containers(job_order: str | None) -> tuple[str | None, list[dict[str, Any]]]:
	"""(container_summary, [{container_number, seal_number}, ...]) from the
	Job Order's Shipping Booking - Container Number/Seal Number used to live
	nowhere on the LDN itself, so the print silently showed "-" for both."""
	if not job_order:
		return None, []
	sb_name = frappe.db.get_value("Job Order", job_order, "shipping_booking")
	if not sb_name:
		return None, []

	rows = frappe.get_all(
		"Shipping Booking Container",
		filters={"parent": sb_name, "parenttype": "Shipping Booking"},
		fields=["container_number", "seal_number"],
		order_by="idx asc",
	)
	if not rows:
		container_number = frappe.db.get_value("Shipping Booking", sb_name, "container_number")
		if not container_number:
			return None, []
		return container_number, [{"container_number": container_number, "seal_number": None}]

	summary = ", ".join(r.container_number for r in rows if r.container_number) or None
	return summary, rows


def _print_rows_from_batches(
	ldn, *, jo_packaging: dict[str, str], default_packaging: str, container_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
	"""One print row per dispatched batch - the real Allocated Batch -> Linked
	COA -> Dispatch COA traceability (CLAUDE.md), instead of the Delivery
	Order's static per-item quantities copied from the Job Order at DO
	generation time (which don't reflect what was actually loaded/allocated)."""
	rows = []
	for idx, batch_row in enumerate(ldn.get("batch_allocations") or []):
		qty = flt(batch_row.dispatched_qty) or flt(batch_row.allocated_qty)
		if qty <= 0:
			continue
		row_uom = batch_row.uom or ldn.uom or ""
		line: dict[str, Any] = {
			"description": batch_row.product_name or batch_row.product or ldn.material_description or "-",
			"qty": qty,
			"uom": row_uom,
			"qty_display": f"{qty:g} {row_uom}".strip(),
			"packaging": jo_packaging.get(batch_row.product) or default_packaging,
			"batch_lines": [
				{
					"batch": batch_row.batch_number or batch_row.batch,
					"coa": batch_row.coa_number or batch_row.coa,
					"qty": qty,
					"uom": row_uom,
					"qty_kg": quantity_to_kg(qty, row_uom),
				}
			],
		}
		container = container_rows[idx] if idx < len(container_rows) else (container_rows[0] if container_rows else None)
		if container:
			line["container_number"] = container.get("container_number")
			line["seal_number"] = container.get("seal_number")
		rows.append(line)
	return rows


def _batch_lines(ldn) -> list[dict[str, Any]]:
	lines = []
	for row in ldn.get("batch_allocations") or []:
		qty = flt(row.dispatched_qty) or flt(row.allocated_qty)
		if qty <= 0:
			continue
		uom = row.uom or ldn.uom or ""
		lines.append(
			{
				"batch": row.batch_number or row.batch,
				"coa": row.coa_number or row.coa,
				"qty": qty,
				"uom": uom,
				"qty_kg": quantity_to_kg(qty, uom),
			}
		)
	return lines


def resolve_loaded_commercial_qty(ldn, *, net_kg: float, loading_kg: float) -> float:
	uom = getattr(ldn, "uom", None) if not isinstance(ldn, dict) else ldn.get("uom")
	batch_rows = getattr(ldn, "batch_allocations", None) or []
	if isinstance(ldn, dict):
		batch_rows = ldn.get("batch_allocations") or batch_rows
	batch_total = sum(
		flt(row.dispatched_qty) or flt(row.allocated_qty) for row in batch_rows
	)
	if batch_total > 0:
		return batch_total
	ldn_qty = flt(getattr(ldn, "quantity", 0) if not isinstance(ldn, dict) else ldn.get("quantity"))
	if ldn_qty > 0:
		return ldn_qty
	if net_kg > 0:
		return kg_to_commercial_quantity(net_kg, uom)
	if loading_kg > 0:
		return kg_to_commercial_quantity(loading_kg, uom)
	return 0.0


@frappe.whitelist()
def get_print_context(ldn_name: str) -> dict[str, Any]:
	"""Build quantity / package / weight fields for the LDN print format."""
	ldn = frappe.get_doc("Loading Delivery Note", ldn_name)
	do_name = ldn.get("transport_delivery_order")
	do = None
	packaging_type = None
	do_items: list[dict[str, Any]] = []

	if do_name and frappe.db.exists("Delivery Order", do_name):
		do = frappe.get_doc("Delivery Order", do_name)
		packaging_type = do.get("packaging_type")
		for row in do.get("items") or []:
			qty = flt(row.qty)
			line_uom = row.uom or ""
			qty_display = "-"
			if qty > 0:
				qty_display = f"{qty:g} {line_uom}".strip()
			do_items.append(
				{
					"item_code": row.item_code,
					"description": row.description or row.item_name or row.item_code,
					"qty": qty,
					"uom": line_uom,
					"qty_display": qty_display,
					"net_weight": flt(row.net_weight),
					"no_of_packages": int(flt(row.no_of_packages)),
					"container_type": row.get("no_of_containers"),
				}
			)

	if not packaging_type and ldn.job_order:
		packaging_type = frappe.db.get_value(
			"Job Order Item",
			{"parent": ldn.job_order},
			"packaging_type",
		)

	material = ldn.material_description
	net_kg = flt(ldn.net_weight)
	loading_kg = _sum_loading_entry_kg(ldn.security_inspection)
	if net_kg <= 0 and loading_kg > 0:
		net_kg = loading_kg

	bulk = is_bulk_packaging(packaging_type, material)
	drums = is_drum_packaging(packaging_type, material) and not bulk

	loaded_qty = resolve_loaded_commercial_qty(ldn, net_kg=net_kg, loading_kg=loading_kg)
	uom = ldn.uom or (do_items[0]["uom"] if do_items else "") or ""

	packages_count = _sum_loading_entry_bags(ldn.security_inspection)
	if packages_count <= 0 and do_items:
		packages_count = max((i["no_of_packages"] for i in do_items), default=0)

	if drums and packages_count > 0:
		packages_display = str(packages_count)
		no_and_kind = f"{packages_count} Drums" if packages_count else (ldn.get("package_type") or "-")
	elif bulk:
		packages_display = ldn.container_number or (do.get("packaging_type") if do else None) or "-"
		no_and_kind = (
			ldn.get("package_type")
			or (do.packaging_type if do else None)
			or "Bulk"
		)
	else:
		packages_display = ldn.get("package_type") or ldn.container_number or "-"
		no_and_kind = packages_display

	loaded_qty_display = "-"
	if loaded_qty > 0:
		loaded_qty_display = f"{loaded_qty:g} {uom}".strip()
	elif net_kg > 0:
		loaded_qty_display = f"{net_kg:g} kg"

	batch_lines = _batch_lines(ldn)

	# When DO has no item rows, show loaded qty on the single product line.
	if not do_items and loaded_qty > 0:
		do_items.append(
			{
				"description": material or "-",
				"qty": loaded_qty,
				"uom": uom,
				"qty_display": loaded_qty_display,
				"net_weight": net_kg,
				"no_of_packages": packages_count,
				"container_type": None,
			}
		)
	elif do_items and loaded_qty > 0 and len(do_items) == 1:
		do_items[0]["qty"] = loaded_qty
		do_items[0]["qty_display"] = loaded_qty_display
		if net_kg > 0:
			do_items[0]["net_weight"] = net_kg

	jo_packaging = job_order_packaging_by_item(ldn.job_order)
	default_packaging = packaging_type or next(iter(jo_packaging.values()), None) or "-"
	for item in do_items:
		item["packaging"] = jo_packaging.get(item.get("item_code")) or default_packaging

	container_summary, container_rows = _resolve_shipping_booking_containers(ldn.job_order)
	print_rows = _print_rows_from_batches(
		ldn,
		jo_packaging=jo_packaging,
		default_packaging=default_packaging,
		container_rows=container_rows,
	)

	buyer_party = resolve_buyer_party(
		buyer=ldn.buyer,
		customer=ldn.customer,
		customer_name=ldn.customer_name,
	)

	jo_row = None
	if ldn.job_order and frappe.db.exists("Job Order", ldn.job_order):
		jo_row = frappe.db.get_value(
			"Job Order", ldn.job_order, ["date", "payment_terms"], as_dict=True
		)

	return {
		"is_bulk": bulk,
		"is_drums": drums,
		"loaded_qty": loaded_qty,
		"loaded_qty_display": loaded_qty_display,
		"loaded_uom": uom,
		"net_weight_kg": net_kg,
		"total_net_weight_kg": net_kg,
		"packages_count": packages_count,
		"packages_display": packages_display,
		"no_and_kind_of_packages": no_and_kind,
		"batch_lines": batch_lines,
		"do_items": do_items,
		# Actual dispatched-batch rows (Allocated Batch -> Linked COA ->
		# Dispatch COA) - the print template prefers this over do_items
		# whenever there's real batch_allocations data to show.
		"print_rows": print_rows,
		"container_summary": container_summary,
		"packaging_type": packaging_type,
		"buyer_name": buyer_party["buyer_name"],
		"buyer_address": buyer_party["buyer_address"],
		# Header/party fields the LDN's own doc carries directly, but a
		# non-LDN document printing through this same context (e.g. the
		# linked ERPNext stock Delivery Note - see
		# get_print_context_for_erpnext_dn) has none of - returned here so
		# one print format template works for both source doctypes.
		"delivery_note_no": ldn.name,
		"job_order": ldn.job_order,
		"security_inspection": ldn.security_inspection,
		"security_draft_delivery_note": ldn.security_draft_delivery_note,
		"terms_of_delivery": ldn.get("terms_of_delivery"),
		"material_description": material,
		"loading_date": ldn.loading_date,
		"job_order_date": jo_row.date if jo_row else None,
		"payment_terms": (jo_row.payment_terms if jo_row else None) or ldn.get("payment_terms"),
		"other_reference": ldn.get("other_reference") or ldn.security_draft_delivery_note,
		"supplier_ref": ldn.get("supplier_ref") or ldn.security_draft_delivery_note,
		"company_trn": ldn.get("company_trn"),
		"emirate": ldn.get("emirate"),
		"country": ldn.get("country"),
		"trn": ldn.get("trn"),
		"place_of_supply": ldn.get("place_of_supply"),
		"vat_text": ldn.get("vat_text"),
	}


@frappe.whitelist()
def get_print_context_for_erpnext_dn(erpnext_dn_name: str) -> dict[str, Any]:
	"""Same context as get_print_context(), resolved from the linked
	ERPNext stock Delivery Note instead of the Loading Delivery Note
	directly - lets the "Standard Delivery Note (Stock)" print format
	reuse the exact same branded template and data."""
	ldn_name = frappe.db.get_value(
		"Loading Delivery Note", {"erpnext_delivery_note": erpnext_dn_name}, "name"
	)
	if not ldn_name:
		return {}
	return get_print_context(ldn_name)
