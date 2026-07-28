# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Import APC Product Packing Profile rows from bundled CSV."""

from __future__ import annotations

import csv
import os
import re
from typing import Any

import frappe
from frappe.utils import cint, flt

from apc_operations.shipping.services.packing_calculation_service import (
	compute_unit_gross_kg,
	normalize_packing_material,
	resolve_empty_packaging_kg,
)

CSV_PATH = os.path.join(
	os.path.dirname(__file__),
	"..",
	"fixtures",
	"asia_petrochemicals.csv",
)

DEFAULT_TARE = [
	("Steel", 18.5),
	("HDPE", 8.0),
	("IBC", 50.0),
	("Flexi", 120.0),
	("Cartons", 0.0),
	("Bags", 0.0),
]


def _packing_doctype_installed(doctype: str) -> bool:
	return bool(frappe.db.exists("DocType", doctype))


def ensure_packaging_tare_seeded() -> int:
	"""Insert default tare rows if missing. Returns count created."""
	if not _packing_doctype_installed("APC Packaging Tare"):
		return 0
	created = 0
	for material, kg in DEFAULT_TARE:
		if frappe.db.exists("APC Packaging Tare", material):
			continue
		frappe.get_doc(
			{
				"doctype": "APC Packaging Tare",
				"packing_material": material,
				"empty_weight_kg": kg,
				"active": 1,
			}
		).insert(ignore_permissions=True)
		created += 1
	return created


def _slug_item_code(alias: str) -> str:
	text = re.sub(r"[^A-Za-z0-9]+", "-", (alias or "").upper()).strip("-")
	return (text[:140] if text else "PACK-ITEM")


def resolve_item_for_matrix(
	*,
	product_name_alias: str,
	item_code: str | None = None,
) -> str:
	alias = (product_name_alias or "").strip()
	if not alias:
		frappe.throw("product_name_alias is required")

	code = (item_code or "").strip()
	if code and frappe.db.exists("Item", code):
		return code

	if code:
		item = frappe.db.get_value("Item", {"item_code": code}, "name")
		if item:
			return item

	# Match by item_name (case-insensitive)
	match = frappe.db.sql(
		"""
		select name from `tabItem`
		where upper(item_name) = upper(%s) or upper(name) = upper(%s)
		limit 1
		""",
		(alias, code or alias),
	)
	if match:
		return match[0][0]

	# Partial name match
	match = frappe.db.sql(
		"""
		select name from `tabItem`
		where item_name like %s
		order by modified desc
		limit 1
		""",
		(f"%{alias[:40]}%",),
	)
	if match:
		return match[0][0]

	# ETAC shorthand
	if "ETHYL ACETATE" in alias.upper() and frappe.db.exists("Item", "101"):
		return "101"

	new_code = _slug_item_code(alias)
	if frappe.db.exists("Item", new_code):
		return new_code

	item_group = (
		frappe.db.get_value("Item Group", {"name": "APC Products"}, "name")
		or frappe.db.get_value("Item Group", {"name": "Products"}, "name")
		or frappe.db.get_value("Item Group", {"is_group": 0}, "name")
	)
	if not item_group:
		frappe.throw(f"No Item Group found to create Item for {alias}")

	stock_uom = "Nos"
	if frappe.db.exists("UOM", "KG"):
		stock_uom = "KG"
	elif frappe.db.exists("UOM", "Kg"):
		stock_uom = "Kg"

	doc = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": new_code,
			"item_name": alias,
			"item_group": item_group,
			"stock_uom": stock_uom,
			"is_stock_item": 1,
		}
	)
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	if not frappe.db.exists("Item", doc.name):
		frappe.throw(f"Failed to create Item for {alias}")
	return doc.name


def _profile_exists(item: str, packing_unit_type: str, packing_material: str) -> str | None:
	return frappe.db.get_value(
		"APC Product Packing Profile",
		{
			"item": item,
			"packing_unit_type": packing_unit_type,
			"packing_material": packing_material,
		},
		"name",
	)


def _append_capacity_rows(doc, row: dict[str, Any]) -> None:
	pairs = (
		("20FT", "cap_20ft_load_mode", "cap_20ft_max_units", "cap_20ft_max_mt"),
		("40FT", "cap_40ft_load_mode", "cap_40ft_max_units", "cap_40ft_max_mt"),
	)
	for size, mode_key, units_key, mt_key in pairs:
		load_mode = (row.get(mode_key) or "").strip()
		if not load_mode:
			continue
		max_units = cint(row.get(units_key))
		max_mt = flt(row.get(mt_key))
		if max_units <= 0 and max_mt <= 0:
			continue
		doc.append(
			"container_capacities",
			{
				"container_size": size,
				"load_mode": load_mode,
				"max_units": max_units or None,
				"max_product_net_mt": max_mt or None,
			},
		)


def import_row(row: dict[str, str]) -> dict[str, str]:
	alias = (row.get("product_name_alias") or "").strip()
	if not alias:
		return {"status": "skipped", "reason": "empty alias"}

	packing_material = normalize_packing_material(row.get("packing_material")) or "Other"
	packing_unit_type = (row.get("packing_unit_type") or "Drum").strip()

	item = resolve_item_for_matrix(
		product_name_alias=alias,
		item_code=(row.get("item_code") or "").strip() or None,
	)

	existing = _profile_exists(item, packing_unit_type, packing_material)
	if existing:
		return {"status": "skipped", "name": existing, "reason": "exists"}

	product_fill = flt(row.get("product_fill_kg"))
	ibc_fill = flt(row.get("ibc_fill_kg"))
	flexi_mt = flt(row.get("flexi_fill_mt"))
	empty_kg = resolve_empty_packaging_kg(packing_material)

	doc = frappe.new_doc("APC Product Packing Profile")
	doc.item = item
	doc.product_name_alias = alias
	doc.hs_code = (row.get("hs_code") or "").strip() or None
	doc.origin = (row.get("origin") or "").strip() or None
	doc.packing_material = packing_material
	doc.packing_unit_type = packing_unit_type
	doc.product_fill_kg = product_fill or None
	doc.ibc_fill_kg = ibc_fill or None
	doc.flexi_fill_mt = flexi_mt or None
	doc.empty_packaging_kg = empty_kg
	doc.unit_gross_kg = compute_unit_gross_kg(
		packing_unit_type=packing_unit_type,
		product_fill_kg=product_fill,
		ibc_fill_kg=ibc_fill,
		flexi_fill_mt=flexi_mt,
		empty_packaging_kg=empty_kg,
	)
	doc.active = 1
	doc.notes = (row.get("notes") or "").strip() or None
	_append_capacity_rows(doc, row)
	doc.insert(ignore_permissions=True)
	return {"status": "created", "name": doc.name}


def clear_all_packing_profiles() -> int:
	"""Remove all packing profiles and container capacity child rows."""
	if not _packing_doctype_installed("APC Product Packing Profile"):
		return 0
	if frappe.db.table_exists("tabAPC Container Load Capacity"):
		frappe.db.sql("DELETE FROM `tabAPC Container Load Capacity`")
	count = frappe.db.count("APC Product Packing Profile")
	if count:
		frappe.db.sql("DELETE FROM `tabAPC Product Packing Profile`")
	frappe.db.commit()
	return count


def _iter_import_rows(path: str):
	"""Asia Petrochemicals source CSV or legacy normalized CSV."""
	name = os.path.basename(path).lower()
	if "asia_petrochemical" in name:
		from apc_operations.shipping.services.asia_petrochemicals_csv import (
			iter_asia_petrochemicals_rows,
		)

		yield from iter_asia_petrochemicals_rows(path)
		return

	with open(path, newline="", encoding="utf-8-sig") as handle:
		reader = csv.DictReader(handle)
		yield from reader


def import_packing_matrix_from_csv(
	csv_path: str | None = None,
	*,
	replace_existing: bool = False,
) -> dict[str, Any]:
	"""Load CSV and create profiles. Idempotent on item+unit+material unless replace_existing."""
	path = csv_path or CSV_PATH
	path = os.path.abspath(path)
	if not os.path.isfile(path):
		frappe.throw(f"Packing matrix CSV not found: {path}")

	if not _packing_doctype_installed("APC Product Packing Profile"):
		frappe.throw("APC Product Packing Profile DocType is not installed. Run bench migrate.")

	tare_created = ensure_packaging_tare_seeded()
	removed = clear_all_packing_profiles() if replace_existing else 0

	stats = {
		"created": 0,
		"skipped": 0,
		"errors": [],
		"tare_created": tare_created,
		"removed": removed,
		"source": path,
	}
	for row in _iter_import_rows(path):
		try:
			result = import_row(row)
			if result.get("status") == "created":
				stats["created"] += 1
			else:
				stats["skipped"] += 1
		except Exception as exc:
			stats["errors"].append(
				{"product": row.get("product_name_alias"), "error": str(exc)}
			)
			frappe.log_error(
				frappe.get_traceback(),
				f"Packing matrix import: {row.get('product_name_alias')}",
			)

	frappe.db.commit()
	return stats


def replace_packing_matrix_from_csv(csv_path: str | None = None) -> dict[str, Any]:
	"""Delete all profiles and import from CSV (Asia Petrochemicals format)."""
	return import_packing_matrix_from_csv(csv_path, replace_existing=True)


@frappe.whitelist()
def import_packing_matrix_api(csv_path: str | None = None, replace_existing: int = 0) -> dict[str, Any]:
	frappe.only_for(("System Manager", "Operations Manager"))
	return import_packing_matrix_from_csv(csv_path, replace_existing=bool(replace_existing))


@frappe.whitelist()
def replace_packing_matrix_api(csv_path: str | None = None) -> dict[str, Any]:
	frappe.only_for(("System Manager", "Operations Manager"))
	return replace_packing_matrix_from_csv(csv_path)
