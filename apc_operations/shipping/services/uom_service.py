# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Commercial quantity / UOM resolution and weighbridge (kg) conversion."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt

# Normalized tokens for mass UOM comparison (uppercase, stripped).
_METRIC_TON_ALIASES = frozenset(
	{
		"METRIC TON",
		"METRIC TONNE",
		"MT",
		"TONNE",
		"TON",
		"T",
		"MTR",
	}
)
_KG_ALIASES = frozenset({"KG", "KILOGRAM", "KILOGRAMS", "KGS"})


def normalize_uom(uom: str | None) -> str:
	if not uom:
		return ""
	return (uom or "").strip().upper()


def is_metric_ton_uom(uom: str | None) -> bool:
	return normalize_uom(uom) in _METRIC_TON_ALIASES


def is_kg_uom(uom: str | None) -> bool:
	return normalize_uom(uom) in _KG_ALIASES


def quantity_to_kg(quantity: float, uom: str | None) -> float:
	"""Convert a commercial quantity to kilograms for weighbridge comparison."""
	qty = flt(quantity)
	if qty <= 0:
		return 0.0
	norm = normalize_uom(uom)
	if norm in _METRIC_TON_ALIASES:
		return qty * 1000.0
	if norm in _KG_ALIASES:
		return qty
	if norm in ("G", "GRAM", "GRAMS"):
		return qty / 1000.0
	# Unknown mass UOM — treat numeric value as kg (legacy weighbridge rows).
	return qty


def kg_to_commercial_quantity(kg: float, uom: str | None) -> float:
	"""Convert weighbridge kilograms into the batch/LDN commercial UOM."""
	weight_kg = flt(kg)
	if weight_kg <= 0:
		return 0.0
	norm = normalize_uom(uom)
	if norm in _METRIC_TON_ALIASES:
		return weight_kg / 1000.0
	if norm in _KG_ALIASES:
		return weight_kg
	if norm in ("G", "GRAM", "GRAMS"):
		return weight_kg * 1000.0
	# Unknown mass UOM — treat kg as the stored unit (legacy rows).
	return weight_kg


def _job_order_commercial(job_order: str | None) -> dict[str, Any]:
	if not job_order or not frappe.db.exists("Job Order", job_order):
		return {"quantity": 0.0, "uom": None}
	rows = frappe.get_all(
		"Job Order Item",
		filters={"parent": job_order},
		fields=["quantity", "uom"],
		order_by="idx asc",
	)
	if not rows:
		return {"quantity": 0.0, "uom": None}
	total = 0.0
	uoms: set[str] = set()
	for row in rows:
		total += flt(row.get("quantity"))
		if row.get("uom"):
			uoms.add(row.get("uom"))
	uom = next(iter(uoms)) if len(uoms) == 1 else None
	return {"quantity": total, "uom": uom}


def resolve_commercial_quantity(
	*,
	job_order: str | None = None,
	do_name: str | None = None,
	sddn_name: str | None = None,
	ldn_name: str | None = None,
) -> dict[str, Any]:
	"""Resolve commercial qty/UOM from Job Order → SDDN → DO → LDN (first hit with qty)."""
	if not job_order and do_name:
		job_order = frappe.db.get_value("Delivery Order", do_name, "job_order")
	if not job_order and ldn_name:
		job_order = frappe.db.get_value("Loading Delivery Note", ldn_name, "job_order")
	if not job_order and sddn_name:
		job_order = frappe.db.get_value(
			"Security Draft Delivery Note", sddn_name, "job_order"
		)

	ctx = _job_order_commercial(job_order)
	if ctx.get("quantity"):
		return ctx

	if sddn_name and frappe.db.exists("Security Draft Delivery Note", sddn_name):
		row = frappe.db.get_value(
			"Security Draft Delivery Note",
			sddn_name,
			["quantity", "uom"],
			as_dict=True,
		)
		if row and flt(row.quantity) > 0:
			return {"quantity": flt(row.quantity), "uom": row.uom}

	if do_name and frappe.db.exists("Delivery Order", do_name):
		row = frappe.db.get_value(
			"Delivery Order",
			do_name,
			["planned_quantity", "total_qty", "job_order"],
			as_dict=True,
		)
		if row:
			qty = flt(row.planned_quantity) or flt(row.total_qty)
			if qty > 0:
				jo_ctx = _job_order_commercial(row.job_order or job_order)
				return {"quantity": qty, "uom": jo_ctx.get("uom")}

	if ldn_name and frappe.db.exists("Loading Delivery Note", ldn_name):
		row = frappe.db.get_value(
			"Loading Delivery Note",
			ldn_name,
			["planned_quantity", "quantity", "uom"],
			as_dict=True,
		)
		if row:
			qty = flt(row.planned_quantity) or flt(row.quantity)
			if qty > 0:
				return {"quantity": qty, "uom": row.uom}

	return {"quantity": 0.0, "uom": None}


def _ctx_val(ctx, field: str, default=None):
	if ctx is None:
		return default
	if isinstance(ctx, dict):
		return ctx.get(field, default)
	return getattr(ctx, field, default)


def planned_gross_quantity_kg(
	*,
	do: dict[str, Any] | None = None,
	ldn: dict[str, Any] | None = None,
) -> float:
	"""Planned loaded weight in kg (product + packaging) for weighbridge variance."""
	if do and flt(_ctx_val(do, "planned_gross_kg")) > 0:
		return flt(_ctx_val(do, "planned_gross_kg"))
	job_order = _ctx_val(ldn, "job_order")
	if job_order:
		from apc_operations.shipping.services.packing_calculation_service import (
			sum_job_order_packing_totals,
		)

		totals = sum_job_order_packing_totals(job_order)
		gross = flt(totals.get("planned_gross_kg"))
		if gross > 0:
			return gross
	if ldn and flt(_ctx_val(ldn, "planned_quantity")) > 0:
		return flt(_ctx_val(ldn, "planned_quantity"))
	return 0.0


def planned_quantity_kg(
	*,
	do: dict[str, Any] | None = None,
	ldn: dict[str, Any] | None = None,
) -> float:
	"""Planned dispatch quantity in kg for weighbridge variance.

	Uses planned gross kg (product + packaging) when available; otherwise
	falls back to commercial product quantity converted to kg.
	"""
	gross = planned_gross_quantity_kg(do=do, ldn=ldn)
	if gross > 0:
		return gross
	job_order = None
	do_name = None
	if do:
		job_order = do.get("job_order")
		do_name = do.get("name")
	if ldn and not job_order:
		job_order = ldn.get("job_order")
	if ldn and not do_name:
		do_name = ldn.get("transport_delivery_order")

	commercial = resolve_commercial_quantity(
		job_order=job_order,
		do_name=do_name,
		ldn_name=ldn.get("name") if ldn else None,
	)
	uom = commercial.get("uom")

	qty = 0.0
	if do and flt(do.get("planned_quantity")) > 0:
		qty = flt(do.get("planned_quantity"))
	elif ldn and flt(ldn.get("planned_quantity")) > 0:
		qty = flt(ldn.get("planned_quantity"))
	elif commercial.get("quantity"):
		qty = flt(commercial["quantity"])
	elif do:
		qty = flt(frappe.db.get_value("Delivery Order", do.get("name"), "total_qty"))

	if qty <= 0:
		return 0.0
	return quantity_to_kg(qty, uom)


def apply_commercial_fields(
	doc,
	*,
	job_order: str | None = None,
	do_name: str | None = None,
	sddn_name: str | None = None,
	force_uom: bool = False,
) -> bool:
	"""Set quantity, planned_quantity, and uom from commercial source (JO/SDDN/DO).

	Returns True when any field was updated.
	"""
	if not doc:
		return False
	if not job_order:
		job_order = getattr(doc, "job_order", None)
	if not do_name:
		do_name = getattr(doc, "transport_delivery_order", None)
	if not sddn_name:
		sddn_name = getattr(doc, "security_draft_delivery_note", None)

	ctx = resolve_commercial_quantity(
		job_order=job_order,
		do_name=do_name,
		sddn_name=sddn_name,
		ldn_name=getattr(doc, "name", None) if getattr(doc, "doctype", None) == "Loading Delivery Note" else None,
	)
	qty = flt(ctx.get("quantity"))
	uom = ctx.get("uom")
	if qty <= 0:
		return False

	changed = False
	current_uom = getattr(doc, "uom", None)
	uom_is_weighbridge_default = not current_uom or is_kg_uom(current_uom)
	net = flt(getattr(doc, "net_weight", 0))

	commercial_fields = ["quantity"]
	if getattr(doc, "doctype", None) != "Loading Delivery Note":
		commercial_fields.append("planned_quantity")

	for field in commercial_fields:
		current = flt(getattr(doc, field, 0))
		# Replace weighbridge net mistakenly stored as commercial quantity.
		if field == "quantity" and net > 0 and current > 0 and abs(current - net) < 0.01:
			setattr(doc, field, qty)
			changed = True
			continue
		if field == "quantity" and current > 0 and not is_metric_ton_uom(uom):
			if current > qty * 50 and net > 0:
				setattr(doc, field, qty)
				changed = True
			continue
		if current != qty:
			setattr(doc, field, qty)
			changed = True

	if uom and (force_uom or uom_is_weighbridge_default):
		if current_uom != uom:
			doc.uom = uom
			changed = True

	return changed


def sync_commercial_fields_to_ldn(
	ldn,
	*,
	do_name: str | None = None,
	force_uom: bool = False,
) -> bool:
	"""Apply commercial qty/UOM to a Loading Delivery Note (in-memory or saved)."""
	return apply_commercial_fields(
		ldn,
		job_order=getattr(ldn, "job_order", None),
		do_name=do_name or getattr(ldn, "transport_delivery_order", None),
		sddn_name=getattr(ldn, "security_draft_delivery_note", None),
		force_uom=force_uom,
	)
