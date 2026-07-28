# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Product packing matrix lookups and gross-weight / package-count calculations."""

from __future__ import annotations

import math
from typing import Any

import frappe
from frappe.utils import flt

from apc_operations.shipping.services.uom_service import quantity_to_kg

PACKING_UNIT_TYPES = frozenset({"Drum", "IBC", "Bag", "Carton", "Flexi", "ISO", "Bulk"})

_MATERIAL_ALIASES = {
	"STEEL": "Steel",
	"STEEL DRUM": "Steel",
	"DRUM": "Steel",
	"DRUMS": "Steel",
	"HDPE": "HDPE",
	"HDPE DRUM": "HDPE",
	"CARTON": "Cartons",
	"CARTONS": "Cartons",
	"BAG": "Bags",
	"BAGS": "Bags",
	"FLEXI": "Flexi",
	"ISO": "ISO",
}


def normalize_packing_material(value: str | None) -> str | None:
	text = (value or "").strip()
	if not text:
		return None
	upper = text.upper()
	if upper in _MATERIAL_ALIASES:
		return _MATERIAL_ALIASES[upper]
	for key, canonical in _MATERIAL_ALIASES.items():
		if key in upper:
			return canonical
	return text.title()


def infer_packing_unit_type(
	packing_unit_type: str | None = None,
	packaging_type: str | None = None,
	packing_material: str | None = None,
) -> str | None:
	if packing_unit_type and packing_unit_type in PACKING_UNIT_TYPES:
		return packing_unit_type
	text = " ".join(
		(v or "").lower()
		for v in (packaging_type, packing_material)
		if v
	)
	if not text:
		return None
	if "flexi" in text:
		return "Flexi"
	if "iso" in text and "tank" in text:
		return "ISO"
	if "ibc" in text:
		return "IBC"
	if "bag" in text:
		return "Bag"
	if "carton" in text or "slab" in text:
		return "Carton"
	if "bulk" in text or "tanker" in text:
		return "Bulk"
	if "drum" in text or "steel" in text or "hdpe" in text or "barrel" in text:
		return "Drum"
	return "Drum"


def resolve_empty_packaging_kg(packing_material: str | None) -> float:
	material = normalize_packing_material(packing_material)
	if not material:
		return 0.0
	if not frappe.db.exists("DocType", "APC Packaging Tare"):
		return _default_tare_kg(material)
	tare = frappe.db.get_value(
		"APC Packaging Tare",
		{"packing_material": material, "active": 1},
		"empty_weight_kg",
	)
	if tare is not None:
		return flt(tare)
	return _default_tare_kg(material)


def _default_tare_kg(material: str) -> float:
	defaults = {
		"Steel": 18.5,
		"HDPE": 8.0,
		"IBC": 50.0,
		"Flexi": 120.0,
		"Bags": 0.0,
		"Cartons": 0.0,
	}
	return flt(defaults.get(material, 0))


def product_fill_kg_for_profile(profile: dict[str, Any] | None) -> float:
	if not profile:
		return 0.0
	unit = (profile.get("packing_unit_type") or "").strip()
	if unit == "IBC":
		return flt(profile.get("ibc_fill_kg"))
	if unit in ("Flexi", "ISO"):
		return flt(profile.get("flexi_fill_mt")) * 1000.0
	return flt(profile.get("product_fill_kg"))


def compute_unit_gross_kg(
	*,
	packing_unit_type: str | None,
	product_fill_kg: float = 0,
	ibc_fill_kg: float = 0,
	flexi_fill_mt: float = 0,
	empty_packaging_kg: float = 0,
) -> float:
	profile = {
		"packing_unit_type": packing_unit_type,
		"product_fill_kg": product_fill_kg,
		"ibc_fill_kg": ibc_fill_kg,
		"flexi_fill_mt": flexi_fill_mt,
	}
	fill = product_fill_kg_for_profile(profile)
	if fill <= 0:
		return 0.0
	if packing_unit_type in ("Flexi", "ISO", "Bulk"):
		return fill
	return fill + flt(empty_packaging_kg)


def get_packing_profile(
	item: str | None,
	*,
	packaging_type: str | None = None,
	packing_unit_type: str | None = None,
	origin: str | None = None,
) -> dict[str, Any] | None:
	if not item or not frappe.db.exists("DocType", "APC Product Packing Profile"):
		return None

	unit = infer_packing_unit_type(packing_unit_type, packaging_type)
	material = normalize_packing_material(packaging_type)

	filters: dict[str, Any] = {"item": item, "active": 1}
	if unit:
		filters["packing_unit_type"] = unit
	if material:
		filters["packing_material"] = material
	if origin:
		filters["origin"] = origin

	rows = frappe.get_all(
		"APC Product Packing Profile",
		filters=filters,
		fields=[
			"name",
			"item",
			"packing_material",
			"packing_unit_type",
			"product_fill_kg",
			"ibc_fill_kg",
			"flexi_fill_mt",
			"empty_packaging_kg",
			"unit_gross_kg",
		],
		order_by="modified desc",
		limit=1,
	)
	if rows:
		return rows[0]

	# Relax material filter
	if material:
		relaxed = {k: v for k, v in filters.items() if k != "packing_material"}
		rows = frappe.get_all(
			"APC Product Packing Profile",
			filters=relaxed,
			fields=[
				"name",
				"item",
				"packing_material",
				"packing_unit_type",
				"product_fill_kg",
				"ibc_fill_kg",
				"flexi_fill_mt",
				"empty_packaging_kg",
				"unit_gross_kg",
			],
			order_by="modified desc",
			limit=1,
		)
		if rows:
			return rows[0]

	# Item + unit only
	if unit:
		rows = frappe.get_all(
			"APC Product Packing Profile",
			filters={"item": item, "active": 1, "packing_unit_type": unit},
			fields=[
				"name",
				"item",
				"packing_material",
				"packing_unit_type",
				"product_fill_kg",
				"ibc_fill_kg",
				"flexi_fill_mt",
				"empty_packaging_kg",
				"unit_gross_kg",
			],
			order_by="modified desc",
			limit=1,
		)
		if rows:
			return rows[0]

	return None


def expected_packaging_qty(
	*,
	quantity: float,
	uom: str | None,
	profile: dict[str, Any] | None,
	packing_unit_type: str | None = None,
) -> int:
	product_kg = quantity_to_kg(quantity, uom)
	if product_kg <= 0:
		return 0

	unit = packing_unit_type or (profile or {}).get("packing_unit_type")
	if unit in ("Flexi", "ISO", "Bulk"):
		return 1 if product_kg > 0 else 0

	fill = product_fill_kg_for_profile(profile)
	if fill <= 0:
		return 0
	return int(math.ceil(product_kg / fill))


def apply_packing_fields(row: Any, *, origin: str | None = None) -> bool:
	"""Populate packing fields on a Job Order Item row (dict or Document). Returns True if updated."""
	item = getattr(row, "item", None) or (row.get("item") if isinstance(row, dict) else None)
	if not item:
		return False

	packaging_type = getattr(row, "packaging_type", None) or (
		row.get("packaging_type") if isinstance(row, dict) else None
	)
	unit = infer_packing_unit_type(
		getattr(row, "packing_unit_type", None) or (row.get("packing_unit_type") if isinstance(row, dict) else None),
		packaging_type,
	)

	profile = get_packing_profile(
		item,
		packaging_type=packaging_type,
		packing_unit_type=unit,
		origin=origin,
	)

	def _set(field: str, value) -> None:
		if isinstance(row, dict):
			row[field] = value
		else:
			setattr(row, field, value)

	if unit:
		_set("packing_unit_type", unit)

	if profile:
		_set("packing_profile", profile.get("name"))
		if profile.get("packing_material") and not packaging_type:
			_set("packaging_type", profile.get("packing_material"))
		_set("product_fill_kg", flt(profile.get("product_fill_kg")))
		_set("ibc_fill_kg", flt(profile.get("ibc_fill_kg")))
		_set("flexi_fill_mt", flt(profile.get("flexi_fill_mt")))
		empty = flt(profile.get("empty_packaging_kg"))
		if empty <= 0:
			empty = resolve_empty_packaging_kg(
				profile.get("packing_material") or packaging_type
			)
		_set("empty_packaging_kg", empty)
		unit_gross = flt(profile.get("unit_gross_kg"))
		if unit_gross <= 0:
			unit_gross = compute_unit_gross_kg(
				packing_unit_type=unit or profile.get("packing_unit_type"),
				product_fill_kg=profile.get("product_fill_kg"),
				ibc_fill_kg=profile.get("ibc_fill_kg"),
				flexi_fill_mt=profile.get("flexi_fill_mt"),
				empty_packaging_kg=empty,
			)
		_set("unit_gross_kg", unit_gross)
	else:
		_set("packing_profile", None)
		_set("product_fill_kg", 0)
		_set("unit_gross_kg", 0)

	qty = flt(getattr(row, "quantity", None) or (row.get("quantity") if isinstance(row, dict) else 0))
	uom = getattr(row, "uom", None) or (row.get("uom") if isinstance(row, dict) else None)
	product_kg = quantity_to_kg(qty, uom)
	_set("planned_product_kg", product_kg)
	_set("net_weight", product_kg)

	override = flt(
		getattr(row, "packaging_qty_override", None)
		or (row.get("packaging_qty_override") if isinstance(row, dict) else 0)
	)
	manual_qty = int(
		flt(getattr(row, "packaging_qty", None) or (row.get("packaging_qty") if isinstance(row, dict) else 0))
	)
	if override and manual_qty > 0:
		pkg_qty = manual_qty
	else:
		pkg_qty = expected_packaging_qty(
			quantity=qty,
			uom=uom,
			profile=profile,
			packing_unit_type=unit,
		)
	_set("packaging_qty", pkg_qty)

	unit_gross = flt(
		getattr(row, "unit_gross_kg", None)
		or (row.get("unit_gross_kg") if isinstance(row, dict) else 0)
	)
	if unit in ("Flexi", "ISO", "Bulk") and profile:
		flexi_kg = flt(profile.get("flexi_fill_mt")) * 1000.0
		_set("planned_gross_kg", flexi_kg if flexi_kg > 0 else product_kg)
	elif pkg_qty > 0 and unit_gross > 0:
		_set("planned_gross_kg", pkg_qty * unit_gross)
	else:
		_set("planned_gross_kg", product_kg)

	return True


def apply_packing_to_job_order(doc) -> None:
	for row in doc.get("items") or []:
		apply_packing_fields(row)




def _loading_entry_schema_flags() -> tuple[bool, bool]:
	"""Whether tabLoading Entry has packing-matrix columns (post v0_8 patch)."""
	return (
		frappe.db.has_column("Loading Entry", "units_loaded"),
		frappe.db.has_column("Loading Entry", "unit_gross_kg"),
	)


def _packaging_units_from_loading_row(row, has_units_loaded: bool) -> int:
	bags = flt(getattr(row, "bags_count", None) or 0)
	if has_units_loaded:
		return int(flt(getattr(row, "units_loaded", None)) or bags)
	return int(bags)


def _loading_entry_fields_for_packaging_qty() -> list[str]:
	has_units, _ = _loading_entry_schema_flags()
	fields = ["bags_count"]
	if has_units:
		fields.insert(0, "units_loaded")
	return fields


def _loading_entry_fields_for_gross_kg() -> list[str]:
	has_units, has_unit_gross = _loading_entry_schema_flags()
	fields = ["bags_count", "actual_weight_kg"]
	if has_units:
		fields.insert(0, "units_loaded")
	if has_unit_gross:
		fields.append("unit_gross_kg")
	return fields

def sum_job_order_packing_totals(job_order: str) -> dict[str, float]:
	rows = frappe.get_all(
		"Job Order Item",
		filters={"parent": job_order},
		fields=[
			"packaging_qty",
			"planned_product_kg",
			"planned_gross_kg",
		],
	)
	return {
		"packaging_qty": sum(flt(r.packaging_qty) for r in rows),
		"planned_product_kg": sum(flt(r.planned_product_kg) for r in rows),
		"planned_gross_kg": sum(flt(r.planned_gross_kg) for r in rows),
	}


def calculated_gross_kg_from_loading_entries(security_inspection: str | None) -> float:
	if not security_inspection:
		return 0.0
	has_units, has_unit_gross = _loading_entry_schema_flags()
	rows = frappe.get_all(
		"Loading Entry",
		filters={"parent": security_inspection, "parenttype": "Security Inspection"},
		fields=_loading_entry_fields_for_gross_kg(),
	)
	total = 0.0
	for row in rows:
		actual = flt(row.actual_weight_kg)
		if actual > 0:
			total += actual
			continue
		units = _packaging_units_from_loading_row(row, has_units)
		unit_gross = flt(getattr(row, "unit_gross_kg", None)) if has_unit_gross else 0.0
		if units > 0 and unit_gross > 0:
			total += units * unit_gross
	return total


def loaded_packaging_qty_from_loading_entries(security_inspection: str | None) -> int:
	if not security_inspection:
		return 0
	has_units, _ = _loading_entry_schema_flags()
	rows = frappe.get_all(
		"Loading Entry",
		filters={"parent": security_inspection, "parenttype": "Security Inspection"},
		fields=_loading_entry_fields_for_packaging_qty(),
	)
	return int(
		sum(
			_packaging_units_from_loading_row(r, has_units)
			for r in rows
			if _packaging_units_from_loading_row(r, has_units) > 0
		)
	)


def _doc_val(doc, field: str, default=None):
	if doc is None:
		return default
	if isinstance(doc, dict):
		return doc.get(field, default)
	return getattr(doc, field, default)


def apply_packing_variance_to_ldn(ldn, do: dict[str, Any] | None = None) -> None:
	"""Set gross planned, calculated gross, and package variance on LDN."""
	from apc_operations.shipping.services.uom_service import planned_gross_quantity_kg

	planned_gross = planned_gross_quantity_kg(do=do, ldn=ldn)
	if planned_gross > 0 and not flt(_doc_val(ldn, "planned_quantity")):
		ldn.planned_quantity = planned_gross

	si = _doc_val(ldn, "security_inspection")
	calculated = calculated_gross_kg_from_loading_entries(si)
	if calculated > 0:
		ldn.calculated_gross_kg = calculated

	expected_units = 0
	if do and flt(do.get("expected_packaging_qty")):
		expected_units = int(flt(do.get("expected_packaging_qty")))
	elif _doc_val(ldn, "job_order"):
		totals = sum_job_order_packing_totals(_doc_val(ldn, "job_order"))
		expected_units = int(totals.get("packaging_qty") or 0)

	if expected_units > 0:
		ldn.expected_packaging_qty = expected_units

	loaded_units = loaded_packaging_qty_from_loading_entries(si)
	if loaded_units > 0:
		ldn.loaded_packaging_qty = loaded_units

	if expected_units > 0 and loaded_units > 0:
		ldn.package_variance_qty = loaded_units - expected_units
		if loaded_units == expected_units:
			ldn.package_variance_status = "OK"
		else:
			ldn.package_variance_status = "Mismatch"


# A Capacity Load Mode implies a packing unit type even before the user has
# picked a packaging type — this is the primary signal used to resolve which
# packing profile a container-capacity lookup should use.
_LOAD_MODE_UNIT_TYPES = {
	"Palletised Drums": "Drum",
	"Non-Pallet Drums": "Drum",
	"IBC": "IBC",
	"Flexi": "Flexi",
	"Bags": "Bag",
}


def container_size_bucket(container_type: str | None) -> str | None:
	"""Map a Job Order's APC Container Type link to the 20FT/40FT/Truck bucket
	used by APC Container Load Capacity."""
	if not container_type:
		return None
	return frappe.db.get_value("APC Container Type", container_type, "container_size")


def get_container_load_capacity(
	item: str | None,
	*,
	packing_material: str | None = None,
	packing_unit_type: str | None = None,
	container_size: str | None = None,
	load_mode: str | None = None,
) -> dict[str, Any] | None:
	"""Look up the drum/unit count and net MT a container holds for an item,
	from the item's packing profile's container capacity matrix.

	packing_unit_type falls back to what the load_mode implies (e.g.
	"Palletised Drums" -> "Drum") so this resolves correctly even before a
	packaging type has been chosen on the row.
	"""
	if not item or not container_size or not load_mode:
		return None

	unit = packing_unit_type or _LOAD_MODE_UNIT_TYPES.get(load_mode)

	profile_filters: dict[str, Any] = {"item": item, "active": 1}
	if unit:
		profile_filters["packing_unit_type"] = unit
	material = normalize_packing_material(packing_material)
	if material:
		profile_filters["packing_material"] = material

	profile_names = frappe.get_all("APC Product Packing Profile", filters=profile_filters, pluck="name")
	if not profile_names and material:
		# Relax the material filter — the unit type (from load_mode) is the
		# more reliable signal here.
		relaxed = {k: v for k, v in profile_filters.items() if k != "packing_material"}
		profile_names = frappe.get_all("APC Product Packing Profile", filters=relaxed, pluck="name")
	if not profile_names:
		return None

	rows = frappe.get_all(
		"APC Container Load Capacity",
		filters={"parent": ["in", profile_names], "container_size": container_size, "load_mode": load_mode},
		fields=["parent", "max_units", "max_product_net_mt"],
		order_by="max_units desc, max_product_net_mt desc",
		limit=1,
	)
	if not rows:
		return None

	row = rows[0]
	profile = frappe.db.get_value(
		"APC Product Packing Profile", row.parent, ["packing_material", "packing_unit_type"], as_dict=True
	)
	return {
		"packing_profile": row.parent,
		"packing_material": profile.packing_material if profile else None,
		"packing_unit_type": profile.packing_unit_type if profile else None,
		"max_units": row.max_units,
		"max_product_net_mt": row.max_product_net_mt,
	}


def resolve_packaging_type_name(packing_material: str | None, packing_unit_type: str | None = None) -> str | None:
	"""Match a packing material/unit type to a real APC Packaging Type record
	name, so autofilled values line up with the master list shown in the
	Packaging Type dropdown. Falls back to the raw material text when no
	master record matches (free text is still accepted on that field)."""
	material = normalize_packing_material(packing_material)
	if not material and not packing_unit_type:
		return None

	filters: dict[str, Any] = {"active": 1}
	if material:
		filters["packing_material"] = material
	if packing_unit_type:
		filters["packing_unit_type"] = packing_unit_type

	name = frappe.db.get_value("APC Packaging Type", filters, "name", order_by="modified desc")
	if name:
		return name
	if material:
		name = frappe.db.get_value(
			"APC Packaging Type", {"active": 1, "packing_material": material}, "name", order_by="modified desc"
		)
		if name:
			return name
	return material


@frappe.whitelist()
def calculate_job_order_item_packing(item_row: dict, container_type: str | None = None) -> dict:
	"""Client-side helper: return packing fields for a Job Order Item row.

	When the row has a Capacity Load Mode set and a container_type is passed
	(the parent Job Order's container), fill quantity/UOM from the matching
	container's full-load capacity before running the normal packing calc —
	e.g. Steel Drum + Palletised Drums + 20FT -> 80 drums / 14.8 MT.
	"""
	row = dict(item_row or {})
	load_mode = row.get("capacity_load_mode")
	if row.get("item") and load_mode:
		capacity = get_container_load_capacity(
			row.get("item"),
			packing_material=row.get("packaging_type"),
			packing_unit_type=row.get("packing_unit_type"),
			container_size=container_size_bucket(container_type),
			load_mode=load_mode,
		)
		if capacity and flt(capacity.get("max_product_net_mt")) > 0:
			row["quantity"] = flt(capacity.get("max_product_net_mt"))
			row["uom"] = "Metric Ton"
			if capacity.get("packing_unit_type"):
				row["packing_unit_type"] = capacity["packing_unit_type"]
			if capacity.get("packing_material") and not row.get("packaging_type"):
				row["packaging_type"] = resolve_packaging_type_name(
					capacity["packing_material"], capacity.get("packing_unit_type")
				)

	apply_packing_fields(row)
	return row
