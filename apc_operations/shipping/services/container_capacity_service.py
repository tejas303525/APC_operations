# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Remaining capacity tracking for planned containers on a Job Order.

Multiple Job Order Item rows can share the same planned_container_no when a
container carries more than one product. Capacity is tracked against the
container type's Max Gross Weight (KG) rather than a product-specific packing
profile, since a shared container has no single product capacity to compare
against.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import escape_html, flt


def get_container_capacity_summary(job_order: str) -> dict[str, Any]:
	if not job_order or not frappe.db.exists("Job Order", job_order):
		return {}

	jo = frappe.db.get_value(
		"Job Order", job_order, ["container_type", "container_quantity"], as_dict=True
	)
	if not jo:
		return {}

	capacity_kg = 0.0
	if jo.container_type:
		capacity_kg = flt(frappe.db.get_value("APC Container Type", jo.container_type, "max_gross_kg"))

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
		],
		order_by="idx asc",
	)

	containers: dict[str, dict[str, Any]] = {}
	unassigned_count = 0
	for row in rows:
		if not row.item:
			continue
		used_kg = flt(row.planned_cargo_gross_kg) or flt(row.planned_gross_kg) or flt(row.planned_product_kg)
		container_no = (row.planned_container_no or "").strip()
		if not container_no:
			unassigned_count += 1
			continue
		bucket = containers.setdefault(
			container_no,
			{"container_no": container_no, "used_kg": 0.0, "packaging_qty": 0, "products": []},
		)
		bucket["used_kg"] += used_kg
		bucket["packaging_qty"] += int(flt(row.packaging_qty))
		bucket["products"].append(row.item_name or row.item)

	def _sort_key(no: str):
		return (0, int(no)) if no.isdigit() else (1, no)

	container_rows = []
	for no in sorted(containers, key=_sort_key):
		c = containers[no]
		remaining_kg = (capacity_kg - c["used_kg"]) if capacity_kg else None
		container_rows.append(
			{
				"container_no": no,
				"product_count": len(c["products"]),
				"products": c["products"],
				"packaging_qty": c["packaging_qty"],
				"used_kg": c["used_kg"],
				"capacity_kg": capacity_kg,
				"remaining_kg": remaining_kg,
				"over_capacity": bool(capacity_kg and c["used_kg"] > capacity_kg),
			}
		)

	return {
		"job_order": job_order,
		"container_type": jo.container_type,
		"capacity_kg": capacity_kg,
		"total_planned_containers": int(flt(jo.container_quantity)) if jo.container_quantity else 0,
		"containers": container_rows,
		"unassigned_count": unassigned_count,
	}


def _fmt_kg(value) -> str:
	return frappe.format_value(flt(value), {"fieldtype": "Float", "precision": 2})


def build_container_capacity_html(summary: dict[str, Any]) -> str:
	if not summary or not summary.get("job_order"):
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
			"<th>Container No</th><th>Products</th><th>Units</th>"
			"<th>Used (KG)</th><th>Capacity (KG)</th><th>Remaining (KG)</th></tr></thead><tbody>"
		)
		for c in container_rows:
			remaining = c.get("remaining_kg")
			if remaining is None:
				remaining_cell = "-"
			elif c.get("over_capacity"):
				remaining_cell = f"<b class='text-danger'>{_fmt_kg(remaining)} (over capacity)</b>"
			else:
				remaining_cell = _fmt_kg(remaining)
			products = escape_html(", ".join(c.get("products") or []))
			lines.append(
				f"<tr><td>{escape_html(c.get('container_no') or '')}</td>"
				f"<td>{products}</td>"
				f"<td>{c.get('packaging_qty') or 0}</td>"
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
	return build_container_capacity_html(get_container_capacity_summary(job_order))
