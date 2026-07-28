# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Parse Asia Petrochemicals packing matrix CSV into normalized profile import rows."""

from __future__ import annotations

import csv
import re
from typing import Any

from frappe.utils import cint, flt

ITEM_CODE_OVERRIDES = {
	"ETHYL ACETATE": "101",
}

_SKIP_PRODUCT_HINTS = (
	"AS PER CATALOGUE",
	"ENGINE OILS/LUBRICANT",
)


def _is_na(value: Any) -> bool:
	if value is None:
		return True
	text = str(value).strip().upper()
	return text in ("", "NA", "N/A", "-")


def _first_number(value: Any) -> float:
	if _is_na(value):
		return 0.0
	text = str(value).strip().upper()
	text = re.sub(r"\b(KGS?|MT|M\.T\.|BAGS?|CARTONS?)\b", "", text, flags=re.I)
	text = text.strip()
	if "/" in text:
		for part in text.split("/"):
			num = flt(part.strip())
			if num > 0:
				return num
		return 0.0
	match = re.search(r"[\d.]+", text)
	return flt(match.group()) if match else 0.0


def _parse_units(value: Any) -> int:
	if _is_na(value):
		return 0
	text = str(value).strip().upper()
	if "BAG" in text:
		match = re.search(r"([\d.]+)\s*BAG", text)
		if match:
			return cint(match.group(1))
	match = re.search(r"^([\d.]+)", text)
	return cint(flt(match.group(1))) if match else 0


def _map_packing_material(packing_raw: str) -> tuple[str, str] | None:
	"""Return (packing_material, primary_unit_type) or None to skip row."""
	text = (packing_raw or "").strip().upper()
	if not text:
		return "Other", "Drum"
	if any(h in text for h in _SKIP_PRODUCT_HINTS):
		return None
	if "FLEXI" in text or "ISO TANK" in text:
		return "Flexi", "Flexi"
	if "BAG" in text:
		return "Bags", "Bag"
	if "CARTON" in text or "CRTN" in text or "SLAB" in text:
		return "Cartons", "Carton"
	if "HDPE" in text and "STEEL" in text:
		return "HDPE", "Drum"
	if "HDPE" in text:
		return "HDPE", "Drum"
	if "STEEL" in text:
		return "Steel", "Drum"
	if "TRUCK" in text:
		return "Other", "Bulk"
	return "Other", "Drum"


def _normalized_row(
	*,
	product: str,
	hs_code: str,
	origin: str,
	packing_material: str,
	packing_unit_type: str,
	product_fill_kg: float = 0,
	ibc_fill_kg: float = 0,
	flexi_fill_mt: float = 0,
	cap_20ft_mode: str = "",
	cap_20ft_units: int = 0,
	cap_20ft_mt: float = 0,
	cap_40ft_mode: str = "",
	cap_40ft_units: int = 0,
	cap_40ft_mt: float = 0,
	notes: str = "",
) -> dict[str, str]:
	item_code = ITEM_CODE_OVERRIDES.get(product.strip().upper(), "")
	return {
		"product_name_alias": product.strip(),
		"item_code": item_code,
		"hs_code": (hs_code or "").strip(),
		"origin": (origin or "").strip(),
		"packing_material": packing_material,
		"packing_unit_type": packing_unit_type,
		"product_fill_kg": str(product_fill_kg) if product_fill_kg > 0 else "",
		"ibc_fill_kg": str(ibc_fill_kg) if ibc_fill_kg > 0 else "",
		"flexi_fill_mt": str(flexi_fill_mt) if flexi_fill_mt > 0 else "",
		"cap_20ft_load_mode": cap_20ft_mode,
		"cap_20ft_max_units": str(cap_20ft_units) if cap_20ft_units > 0 else "",
		"cap_20ft_max_mt": str(cap_20ft_mt) if cap_20ft_mt > 0 else "",
		"cap_40ft_load_mode": cap_40ft_mode,
		"cap_40ft_max_units": str(cap_40ft_units) if cap_40ft_units > 0 else "",
		"cap_40ft_max_mt": str(cap_40ft_mt) if cap_40ft_mt > 0 else "",
		"notes": notes,
	}


def _expand_main_row(row: dict[str, str]) -> list[dict[str, str]]:
	product = (row.get("PRODUCT") or "").strip()
	if not product or product.upper() in ("BASE OILS", "PRODUCT"):
		return []

	packing_raw = row.get("PACKING") or ""
	mapped = _map_packing_material(packing_raw)
	if not mapped:
		return []
	packing_material, default_unit = mapped

	drum_fill = _first_number(row.get("DRUM/CRTN FILLING-KGS"))
	ibc_fill = _first_number(row.get("IBC FILLING KGS"))
	flexi_mt = _first_number(row.get("FLEXI/ISO FILLING-M.T"))

	hs_code = row.get("HS CODE") or ""
	origin = row.get("ORIGIN") or ""
	sr = (row.get("SR.NO") or "").strip()
	notes = f"SR{sr}" if sr else ""

	cap_20_pal = _parse_units(row.get("20FT TOTAL DRUMS PALLETISED"))
	cap_20_np = _parse_units(row.get("20FT TOTAL DRUMS NON PALET"))
	cap_20_ibc = _parse_units(row.get("20FT IBC'S"))
	cap_20_mt = flt(row.get("20FT TOTAL NW (IN M.T.)"))
	cap_40_pal = _parse_units(row.get("40FT TOTAL DRUMS PALLETISED"))
	cap_40_np = _parse_units(row.get("40FT TOTAL DRUMS NON PALET"))
	cap_40_ibc = _parse_units(row.get("40FT IBC'S"))
	cap_40_mt = flt(row.get("40FT TOTAL NW (M.T)"))

	out: list[dict[str, str]] = []

	# Drum / bag / carton unit profile
	if drum_fill > 0 and default_unit in ("Drum", "Bag", "Carton"):
		unit = default_unit
		cap_20_units = cap_20_pal or cap_20_np
		cap_40_units = cap_40_pal or cap_40_np
		cap_20_mode = "Palletised Drums" if cap_20_pal else ("Non-Pallet Drums" if cap_20_np else "Bags")
		if unit == "Bag":
			cap_20_mode = "Bags"
			# Some rows store bag count in odd columns
			if not cap_20_units:
				cap_20_units = _parse_units(row.get("IBC FILLING KGS")) or cap_20_units
		elif unit == "Carton":
			cap_20_mode = "Bags"
		cap_40_mode = cap_20_mode if cap_40_units else ""
		out.append(
			_normalized_row(
				product=product,
				hs_code=hs_code,
				origin=origin,
				packing_material=packing_material,
				packing_unit_type=unit,
				product_fill_kg=drum_fill,
				cap_20ft_mode=cap_20_mode,
				cap_20ft_units=cap_20_units,
				cap_20ft_mt=cap_20_mt,
				cap_40ft_mode=cap_40_mode,
				cap_40ft_units=cap_40_units,
				cap_40ft_mt=cap_40_mt,
				notes=notes,
			)
		)

	# IBC profile
	if ibc_fill > 0:
		out.append(
			_normalized_row(
				product=product,
				hs_code=hs_code,
				origin=origin,
				packing_material=packing_material if packing_material != "Flexi" else "Steel",
				packing_unit_type="IBC",
				ibc_fill_kg=ibc_fill,
				cap_20ft_mode="IBC",
				cap_20ft_units=cap_20_ibc,
				cap_20ft_mt=cap_20_mt,
				cap_40ft_mode="IBC",
				cap_40ft_units=cap_40_ibc,
				cap_40ft_mt=cap_40_mt,
				notes=f"{notes} IBC".strip(),
			)
		)

	# Flexi profile
	if flexi_mt > 0:
		out.append(
			_normalized_row(
				product=product,
				hs_code=hs_code,
				origin=origin,
				packing_material="Flexi",
				packing_unit_type="Flexi",
				flexi_fill_mt=flexi_mt,
				cap_20ft_mode="Flexi",
				cap_20ft_units=1 if cap_20_mt > 0 else 0,
				cap_20ft_mt=cap_20_mt,
				cap_40ft_mode="Flexi",
				cap_40ft_units=1 if cap_40_mt > 0 else 0,
				cap_40ft_mt=cap_40_mt,
				notes=f"{notes} Flexi".strip(),
			)
		)

	# Flexi-only rows (no drum fill)
	if not out and default_unit == "Flexi" and flexi_mt <= 0 and packing_material == "Flexi":
		# e.g. LINEAR ALKALINE BENZENE with no fills — skip
		pass

	return out


def _expand_base_oil_row(cells: list[str]) -> list[dict[str, str]]:
	"""Base oils subsection uses a different column layout (see row 82+)."""
	if len(cells) < 6:
		return []
	product = (cells[1] if len(cells) > 1 else "").strip()
	if not product or product.upper() in ("PRODUCT",):
		return []

	packing_raw = cells[4] if len(cells) > 4 else ""
	mapped = _map_packing_material(packing_raw)
	if not mapped:
		return []
	packing_material, default_unit = mapped

	drum_fill = _first_number(cells[5] if len(cells) > 5 else "")
	ibc_fill = _first_number(cells[6] if len(cells) > 6 else "")
	flexi_mt = _first_number(cells[7] if len(cells) > 7 else "")
	hs_code = cells[2] if len(cells) > 2 else ""
	origin = cells[3] if len(cells) > 3 else ""
	sr = (cells[0] if len(cells) > 0 else "").strip()

	cap_20_pal = _parse_units(cells[8] if len(cells) > 8 else "")
	cap_20_mt = flt(cells[11] if len(cells) > 11 else "")
	cap_40_pal = _parse_units(cells[12] if len(cells) > 12 else "")
	cap_40_mt = flt(cells[15] if len(cells) > 15 else "")

	out: list[dict[str, str]] = []
	notes = f"Base oil SR{sr}" if sr else "Base oil"

	if drum_fill > 0:
		out.append(
			_normalized_row(
				product=product,
				hs_code=hs_code,
				origin=origin,
				packing_material=packing_material,
				packing_unit_type="Drum",
				product_fill_kg=drum_fill,
				cap_20ft_mode="Palletised Drums",
				cap_20ft_units=cap_20_pal,
				cap_20ft_mt=cap_20_mt,
				cap_40ft_mode="Palletised Drums",
				cap_40ft_units=cap_40_pal,
				cap_40ft_mt=cap_40_mt,
				notes=notes,
			)
		)

	if flexi_mt > 0:
		out.append(
			_normalized_row(
				product=product,
				hs_code=hs_code,
				origin=origin,
				packing_material="Flexi",
				packing_unit_type="Flexi",
				flexi_fill_mt=flexi_mt,
				cap_20ft_mode="Flexi",
				cap_20ft_units=1 if cap_20_mt > 0 else 0,
				cap_20ft_mt=cap_20_mt,
				cap_40ft_mode="Flexi",
				cap_40ft_units=1 if cap_40_mt > 0 else 0,
				cap_40ft_mt=cap_40_mt,
				notes=f"{notes} Flexi",
			)
		)

	if not out and flexi_mt > 0:
		out.append(
			_normalized_row(
				product=product,
				hs_code=hs_code,
				origin=origin,
				packing_material="Flexi",
				packing_unit_type="Flexi",
				flexi_fill_mt=flexi_mt,
				notes=notes,
			)
		)

	return out


def iter_asia_petrochemicals_rows(csv_path: str):
	"""Yield normalized import rows from the Asia Petrochemicals CSV."""
	with open(csv_path, newline="", encoding="utf-8-sig") as handle:
		reader = csv.reader(handle)
		rows = list(reader)

	section = "main"
	header: list[str] | None = None
	for row in rows:
		if not row or not any((c or "").strip() for c in row):
			continue
		first = (row[0] or "").strip().upper()
		if first == "BASE OILS":
			section = "base_oils"
			header = None
			continue
		if section == "main":
			if first == "SR.NO" and "PRODUCT" in (row[1] or "").upper():
				header = row
				continue
			if not header:
				continue
			data = {header[i]: row[i] if i < len(row) else "" for i in range(len(header))}
			for norm in _expand_main_row(data):
				yield norm
		else:
			if first == "SR.NO":
				continue
			for norm in _expand_base_oil_row(row):
				yield norm
