# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import re

import frappe
from frappe.model.document import Document

_DO_COMMENT_PATTERN = re.compile(r"Delivery Order generated:\s*([A-Za-z0-9.-]+)", re.I)


def find_delivery_order_for_job_order(job_order: str | None) -> str | None:
	"""Resolve a Delivery Order name for a Job Order.

	Uses ``Delivery Order.job_order`` when present; otherwise Comment /
	remarks heuristics from legacy generation.
	"""
	if not job_order:
		return None
	if frappe.db.has_column("Delivery Order", "job_order"):
		name = frappe.db.get_value(
			"Delivery Order",
			{"job_order": job_order, "docstatus": ["!=", 2]},
			"name",
			order_by="modified desc",
		)
		if name:
			return name
	rows = frappe.get_all(
		"Comment",
		filters={
			"reference_doctype": "Job Order",
			"reference_name": job_order,
			"comment_type": "Comment",
		},
		fields=["content"],
		order_by="creation desc",
		limit=40,
	)
	for row in rows:
		content = (row.get("content") or "").strip()
		m = _DO_COMMENT_PATTERN.search(content)
		if m:
			name = m.group(1).strip()
			if frappe.db.exists("Delivery Order", name):
				return name
	return frappe.db.get_value(
		"Delivery Order",
		{"remarks": ["like", f"%{job_order}%"]},
		"name",
		order_by="creation desc",
	)


def resolve_delivery_order_for_gate_pass_display(gate_pass) -> str | None:
	"""Return Delivery Order to show on a Gate Pass (link field or inferred)."""
	if isinstance(gate_pass, str):
		linked = frappe.db.get_value("Gate Pass", gate_pass, "delivery_order")
		if linked:
			return linked
		gate_pass = frappe.get_doc("Gate Pass", gate_pass)
	if getattr(gate_pass, "delivery_order", None):
		return gate_pass.delivery_order
	ts_rows = frappe.get_all(
		"Transport Schedule",
		filters={"gate_pass": gate_pass.name},
		fields=["job_order"],
		limit=1,
	)
	if ts_rows and ts_rows[0].get("job_order"):
		return find_delivery_order_for_job_order(ts_rows[0]["job_order"])
	return None


class GatePass(Document):
	pass
