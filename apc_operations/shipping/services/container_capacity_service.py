# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Remaining capacity tracking for planned containers on a Job Order.

Multiple Job Order Item rows can share the same planned_container_no when a
container carries more than one product. Capacity is tracked two ways:

- Weight (KG) against the container type's Max Gross Weight - always
  available once Container Type is set.
- Units (drums/IBCs/etc) against the first product's own container-capacity
  matrix entry for that container size/load mode - a best-effort reference,
  since a shared container has no single authoritative product capacity to
  compare against once multiple products are mixed in.

This is informational only (a soft warning), not a hard block - per user,
over-capacity should be visible but not prevent adding more items.

The summary is built from whatever row data is handed to it, not from a DB
query keyed on the Job Order name - an unsaved/new Job Order has no rows in
`tabJob Order Item` yet, so a DB-driven lookup would always show nothing
until after the first save. Building from the client's current in-memory
`frm.doc.items` instead makes the widget live.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import escape_html, flt


def _val(row: Any, field: str, default=None):
	if isinstance(row, dict):
		return row.get(field, default)
	return getattr(row, field, default)


def get_container_capacity_summary(
	*,
	container_type: str | None,
	container_quantity: float | int | None,
	rows: list,
) -> dict[str, Any]:
	"""Build the capacity summary from already-loaded row data - works
	identically for saved and unsaved Job Orders, since neither path
	requires a DB query for the child rows."""
	capacity_kg = 0.0
	container_size = None
	if container_type:
		info = frappe.db.get_value(
			"APC Container Type", container_type, ["max_gross_kg", "container_size"], as_dict=True
		)
		if info:
			capacity_kg = flt(info.max_gross_kg)
			container_size = info.container_size

	containers: dict[str, dict[str, Any]] = {}
	unassigned_count = 0
	for row in rows or []:
		item = _val(row, "item")
		if not item:
			continue
		used_kg = (
			flt(_val(row, "planned_cargo_gross_kg"))
			or flt(_val(row, "planned_gross_kg"))
			or flt(_val(row, "planned_product_kg"))
		)
		container_no = (_val(row, "planned_container_no") or "").strip()
		if not container_no:
			unassigned_count += 1
			continue
		bucket = containers.setdefault(
			container_no,
			{"container_no": container_no, "used_kg": 0.0, "packaging_qty": 0, "products": [], "rows": []},
		)
		bucket["used_kg"] += used_kg
		bucket["packaging_qty"] += int(flt(_val(row, "packaging_qty")))
		bucket["products"].append(_val(row, "item_name") or item)
		bucket["rows"].append(row)

	def _sort_key(no: str):
		return (0, int(no)) if no.isdigit() else (1, no)

	container_rows = []
	for no in sorted(containers, key=_sort_key):
		c = containers[no]
		remaining_kg = (capacity_kg - c["used_kg"]) if capacity_kg else None

		max_units = _reference_max_units(c["rows"], container_size)
		remaining_units = (max_units - c["packaging_qty"]) if max_units else None

		container_rows.append(
			{
				"container_no": no,
				"product_count": len(c["products"]),
				"products": c["products"],
				"packaging_qty": c["packaging_qty"],
				"max_units": max_units,
				"remaining_units": remaining_units,
				"used_kg": c["used_kg"],
				"capacity_kg": capacity_kg,
				"remaining_kg": remaining_kg,
				"over_capacity": bool(
					(capacity_kg and c["used_kg"] > capacity_kg) or (max_units and c["packaging_qty"] > max_units)
				),
			}
		)

	return {
		"has_data": True,
		"container_type": container_type,
		"capacity_kg": capacity_kg,
		"total_planned_containers": int(flt(container_quantity)) if container_quantity else 0,
		"containers": container_rows,
		"unassigned_count": unassigned_count,
	}


def get_container_capacity_summary_for_job_order(job_order: str) -> dict[str, Any]:
	"""DB-driven fallback: build the summary from the saved Job Order and its
	saved Job Order Item rows. Only reflects what's actually saved."""
	if not job_order or not frappe.db.exists("Job Order", job_order):
		return {}

	jo = frappe.db.get_value("Job Order", job_order, ["container_type", "container_quantity"], as_dict=True)
	if not jo:
		return {}

	rows = frappe.get_all(
		"Job Order Item",
		filters={"parent": job_order},
		fields=[
			"item",
			"item_name",
			"planned_container_no",
			"packaging_qty",
			"planned_product_kg",
			"planned_gross_kg",
			"planned_cargo_gross_kg",
			"capacity_load_mode",
			"packaging_type",
			"packing_unit_type",
		],
		order_by="idx asc",
	)

	return get_container_capacity_summary(
		container_type=jo.container_type, container_quantity=jo.container_quantity, rows=rows
	)


def _reference_max_units(rows: list, container_size: str | None) -> int:
	"""Best-effort unit capacity for a shared container: the first row that
	resolves a real container-capacity match wins. Different products sharing
	a container may have different max_units for the same load mode in
	principle, but in this data set it consistently reflects physical
	drum/unit count for the container size regardless of product, so the
	first match is a reasonable reference."""
	if not container_size:
		return 0

	from apc_operations.shipping.services.packing_calculation_service import (
		get_container_load_capacity,
	)

	for row in rows:
		load_mode = _val(row, "capacity_load_mode")
		item = _val(row, "item")
		if not load_mode or not item:
			continue
		capacity = get_container_load_capacity(
			item,
			packing_unit_type=_val(row, "packing_unit_type"),
			container_size=container_size,
			load_mode=load_mode,
		)
		if capacity and flt(capacity.get("max_units")):
			return int(flt(capacity["max_units"]))
	return 0


def _fmt_kg(value) -> str:
	return frappe.format_value(flt(value), {"fieldtype": "Float", "precision": 2})


def build_container_capacity_html(summary: dict[str, Any]) -> str:
	if not summary or not summary.get("has_data"):
		return "<p class='text-muted'>No container capacity data.</p>"

	if not summary.get("container_type"):
		return "<p class='text-muted'>Set Container Type to track remaining container capacity.</p>"

	lines = ["<div class='apc-container-capacity-summary'>"]

	if not summary.get("capacity_kg"):
		lines.append(
			"<p class='text-muted'>Set Max Gross Weight (KG) on APC Container Type "
			f"'{escape_html(summary.get('container_type') or '')}' to track remaining capacity.</p>"
		)

	container_rows = summary.get("containers") or []
	if not container_rows:
		lines.append("<p class='text-muted'>No items assigned to a Planned Container No yet.</p>")
	else:
		lines.append(
			"<table class='table table-bordered table-sm'><thead><tr>"
			"<th>Container No</th><th>Products</th><th>Units (used/max)</th>"
			"<th>Used (KG)</th><th>Capacity (KG)</th><th>Remaining (KG)</th></tr></thead><tbody>"
		)
		for c in container_rows:
			remaining = c.get("remaining_kg")
			over_units = bool(c.get("max_units") and c.get("packaging_qty", 0) > c["max_units"])
			if remaining is None:
				remaining_cell = "-"
			elif c.get("over_capacity"):
				remaining_cell = f"<b class='text-danger'>{_fmt_kg(remaining)} (over capacity)</b>"
			else:
				remaining_cell = _fmt_kg(remaining)

			if c.get("max_units"):
				units_text = f"{c.get('packaging_qty') or 0} / {c['max_units']}"
				units_cell = f"<b class='text-danger'>{units_text} (over)</b>" if over_units else units_text
			else:
				units_cell = str(c.get("packaging_qty") or 0)

			products = escape_html(", ".join(c.get("products") or []))
			lines.append(
				f"<tr><td>{escape_html(c.get('container_no') or '')}</td>"
				f"<td>{products}</td>"
				f"<td>{units_cell}</td>"
				f"<td>{_fmt_kg(c.get('used_kg'))}</td>"
				f"<td>{_fmt_kg(c.get('capacity_kg')) if c.get('capacity_kg') else '-'}</td>"
				f"<td>{remaining_cell}</td></tr>"
			)
		lines.append("</tbody></table>")

	if summary.get("unassigned_count"):
		lines.append(
			f"<p class='text-muted'>{summary['unassigned_count']} item(s) have no Planned Container No set.</p>"
		)

	total_planned = summary.get("total_planned_containers") or 0
	used_containers = len(container_rows)
	if total_planned:
		lines.append(f"<p class='text-muted'>{used_containers} of {total_planned} planned container(s) in use.</p>")

	lines.append("</div>")
	return "".join(lines)


def get_container_capacity_html_for_job_order(job_order: str) -> str:
	"""Return HTML for the Job Order form (HTML field is not stored in DB)."""
	if not job_order or not frappe.db.exists("Job Order", job_order):
		return "<p class='text-muted'>No container capacity data.</p>"
	return build_container_capacity_html(get_container_capacity_summary_for_job_order(job_order))


@frappe.whitelist()
def get_live_container_capacity_html(
	container_type: str | None = None,
	container_quantity: float | int | None = None,
	items: list | str | None = None,
) -> dict:
	"""Client-facing endpoint: build the widget HTML from the form's current
	in-memory state (unsaved edits included), not a DB query."""
	rows = frappe.parse_json(items) if items else []
	summary = get_container_capacity_summary(
		container_type=container_type, container_quantity=container_quantity, rows=rows
	)
	return {"html": build_container_capacity_html(summary)}
