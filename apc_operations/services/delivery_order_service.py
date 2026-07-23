# Copyright (c) 2026, APC and contributors
"""Delivery Order operational status and console card helpers (Path B)."""

from __future__ import annotations

from typing import Any

import frappe
from apc_operations.services import console_status
from apc_operations.shipping.doctype.gate_pass.gate_pass import (
	_DO_COMMENT_PATTERN,
	find_delivery_order_for_job_order,
)

# SDDN status groupings (raw DB values)
SDDN_PENDING = frozenset(
	{"Draft", "Pending Review", "Pending Verification", "Sent to Security"}
)
SDDN_VERIFIED = frozenset(
	{"Verified", "Approved", "LDN Created", "Sent to QC", "Completed"}
)

OPERATIONAL_STATUSES = (
	"Pending Security",
	"Security In Progress",
	"Ready for Loading",
	"Loading In Progress",
	"Sent to QC",
	"QC In Progress",
	"QC Cleared",
	"Completed",
	"Cancelled",
)

_DO_FIELDS = [
	"name",
	"customer",
	"customer_name",
	"job_order",
	"job_order_number",
	"status",
	"docstatus",
	"posting_date",
	"modified",
]


def find_delivery_order_for_job_order_primary(job_order: str | None) -> str | None:
	"""Prefer direct ``job_order`` link; fall back to comment/remarks heuristics."""
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
	return find_delivery_order_for_job_order(job_order)


def link_delivery_order_to_job_order(
	do_name: str,
	job_order: str | None,
	transport_schedule: str | None = None,
	*,
	update_modified: bool = False,
) -> None:
	"""Set Job Order on an existing Delivery Order."""
	if not do_name or not frappe.db.exists("Delivery Order", do_name):
		return
	if not frappe.db.has_column("Delivery Order", "job_order"):
		return
	if job_order:
		frappe.db.set_value(
			"Delivery Order", do_name, "job_order", job_order, update_modified=update_modified
		)


def link_child_documents_on_do(
	do_name: str,
	*,
	sddn: str | None = None,
	ldn: str | None = None,
	update_modified: bool = False,
) -> None:
	"""No-op: SDDN/LDN are resolved via Job Order, not stored on Delivery Order."""
	return


def resolve_do_for_sddn(sddn_name: str) -> str | None:
	row = frappe.db.get_value(
		"Security Draft Delivery Note",
		sddn_name,
		["job_order", "transport_schedule"],
		as_dict=True,
	)
	if not row:
		return None
	if row.get("job_order"):
		do = find_delivery_order_for_job_order_primary(row["job_order"])
		if do:
			link_delivery_order_to_job_order(do, row["job_order"], update_modified=False)
			return do
	return None


def resolve_do_for_ldn(ldn_name: str) -> str | None:
	ldn = frappe.db.get_value(
		"Loading Delivery Note",
		ldn_name,
		["job_order", "security_draft_delivery_note"],
		as_dict=True,
	)
	if not ldn:
		return None
	if ldn.get("security_draft_delivery_note"):
		do = resolve_do_for_sddn(ldn["security_draft_delivery_note"])
		if do:
			return do
	if ldn.get("job_order"):
		return find_delivery_order_for_job_order_primary(ldn["job_order"])
	return None


def compute_operational_status(
	do_name: str,
	*,
	sddn_status: str | None = None,
	ldn_status: str | None = None,
	ldn_qc_status: str | None = None,
	shipping_status: str | None = None,
	docstatus: int | None = None,
) -> str:
	"""Derive console operational_status from linked documents."""
	if docstatus == 2 or shipping_status == "Cancelled":
		return "Cancelled"
	if shipping_status == "Delivered":
		return "Completed"

	if do_name and not (sddn_status or ldn_status):
		jo = frappe.db.get_value("Delivery Order", do_name, "job_order")
		if jo:
			sddn, ldn = _linked_docs_for_job_order(jo)
			if sddn and not sddn_status:
				sddn_status = frappe.db.get_value(
					"Security Draft Delivery Note", sddn, "security_status"
				)
			if ldn and not ldn_status:
				ldn_row = frappe.db.get_value(
					"Loading Delivery Note",
					ldn,
					["delivery_note_status", "qc_status"],
					as_dict=True,
				)
				if ldn_row:
					ldn_status = ldn_row.get("delivery_note_status")
					ldn_qc_status = ldn_qc_status or ldn_row.get("qc_status")

	if ldn_qc_status == "QC Rejected":
		return "QC In Progress"
	if ldn_qc_status == "QC Cleared" or ldn_status in {
		"QC Cleared",
		"COA Attached",
		"Ready for Receivables",
		"Reported to Receivables",
		"Loading Completed",
		"Completed",
	}:
		return "QC Cleared"
	if ldn_status in {"Pending QC", "Sent to QC"} or sddn_status == "Sent to QC":
		return "Sent to QC" if not ldn_qc_status or ldn_qc_status == "Pending QC" else "QC In Progress"
	if ldn_status and ldn_status not in {"Draft", "Cancelled"}:
		return "Loading In Progress"
	if sddn_status in SDDN_VERIFIED:
		return "Ready for Loading"
	if sddn_status in SDDN_PENDING or sddn_status:
		return "Security In Progress"
	return "Pending Security"


def _linked_docs_for_job_order(job_order: str | None) -> tuple[str | None, str | None]:
	if not job_order:
		return None, None
	sddn = frappe.db.get_value(
		"Security Draft Delivery Note",
		{"job_order": job_order},
		"name",
		order_by="modified desc",
	)
	ldn = None
	if sddn:
		ldn = frappe.db.get_value(
			"Loading Delivery Note",
			{"security_draft_delivery_note": sddn},
			"name",
		)
	return sddn, ldn


def sync_delivery_order_operational_status(
	do_name: str,
	*,
	update_modified: bool = False,
) -> str | None:
	"""Return computed console status (not persisted on Delivery Order)."""
	if not do_name or not frappe.db.exists("Delivery Order", do_name):
		return None
	row = frappe.db.get_value(
		"Delivery Order",
		do_name,
		["job_order", "status", "docstatus"],
		as_dict=True,
	)
	if not row:
		return None
	return compute_operational_status(
		do_name,
		shipping_status=row.get("status"),
		docstatus=row.get("docstatus"),
	)


def sync_from_sddn(sddn_name: str) -> None:
	do = resolve_do_for_sddn(sddn_name)
	if do:
		sync_delivery_order_operational_status(do, update_modified=False)


def sync_from_ldn(ldn_name: str) -> None:
	do = resolve_do_for_ldn(ldn_name)
	if do:
		sync_delivery_order_operational_status(do, update_modified=False)


def sync_from_qcr(qcr_name: str) -> None:
	ldn = frappe.db.get_value("QC Report Request", qcr_name, "loading_delivery_note")
	if ldn:
		sync_from_ldn(ldn)


def _enrich_do_row(do_row: dict[str, Any]) -> dict[str, Any]:
	"""Build a console card payload from a Delivery Order row."""
	do_name = do_row.get("name")
	jo = do_row.get("job_order")
	sddn, ldn = _linked_docs_for_job_order(jo)

	sddn_status_raw = None
	if sddn:
		sddn_status_raw = frappe.db.get_value(
			"Security Draft Delivery Note", sddn, "security_status"
		)

	ldn_status_raw = None
	ldn_qc_status = None
	if ldn:
		ldn_row = frappe.db.get_value(
			"Loading Delivery Note",
			ldn,
			["delivery_note_status", "qc_status", "qc_report_request"],
			as_dict=True,
		)
		if ldn_row:
			ldn_status_raw = ldn_row.get("delivery_note_status")
			ldn_qc_status = ldn_row.get("qc_status")

	operational = compute_operational_status(
		do_name,
		sddn_status=sddn_status_raw,
		ldn_status=ldn_status_raw,
		ldn_qc_status=ldn_qc_status,
		shipping_status=do_row.get("status"),
		docstatus=do_row.get("docstatus"),
	)

	return {
		"name": do_name,
		"delivery_order": do_name,
		"job_order": jo,
		"job_order_number": do_row.get("job_order_number")
		or (frappe.db.get_value("Job Order", jo, "job_order_number") if jo else None),
		"customer": do_row.get("customer"),
		"customer_name": do_row.get("customer_name"),
		"operational_status": operational,
		"operational_status_tone": operational_status_tone(operational),
		"do_shipping_status": do_row.get("status"),
		"do_shipping_status_label": console_status.do_display_label(do_row),
		"do_shipping_status_tone": console_status.do_status_tone(
			console_status.do_display_label(do_row)
		),
		"sddn": sddn,
		"sddn_status": console_status.sddn_display_label(sddn_status_raw),
		"sddn_status_tone": console_status.sddn_status_tone(sddn_status_raw),
		"raw_sddn_status": sddn_status_raw,
		"loading_delivery_note": ldn,
		"ldn": ldn,
		"ldn_status": console_status.ldn_display_label(ldn_status_raw),
		"ldn_status_tone": console_status.ldn_status_tone(ldn_status_raw),
		"qc_status": ldn_qc_status,
		"qc_status_tone": console_status.qc_status_tone(ldn_qc_status),
		"posting_date": do_row.get("posting_date"),
		"modified": do_row.get("modified"),
	}


def operational_status_tone(status: str | None) -> str:
	return {
		"Pending Security": "neutral",
		"Security In Progress": "warn",
		"Ready for Loading": "info",
		"Loading In Progress": "info",
		"Sent to QC": "info",
		"QC In Progress": "warn",
		"QC Cleared": "success",
		"Completed": "success",
		"Cancelled": "danger",
	}.get(status or "", "neutral")


def _list_delivery_orders(
	filters: dict[str, Any] | list | None = None,
	*,
	limit: int = 400,
) -> list[dict[str, Any]]:
	if not frappe.db.has_column("Delivery Order", "job_order"):
		return []
	rows = frappe.get_all(
		"Delivery Order",
		filters=filters or {"docstatus": ["!=", 2]},
		fields=_DO_FIELDS,
		order_by="modified desc",
		limit=limit,
	)
	return [_enrich_do_row(r) for r in rows]


def get_security_new_dos() -> list[dict[str, Any]]:
	"""DO submitted/draft with no SDDN or SDDN still at gate (pending security)."""
	out = []
	for card in _list_delivery_orders():
		op = card.get("operational_status")
		raw_sddn = card.get("raw_sddn_status")
		if op in ("Pending Security",) or (not card.get("sddn")):
			out.append(card)
		elif raw_sddn in SDDN_PENDING and op == "Security In Progress":
			out.append(card)
	return out


def get_security_pending_dos() -> list[dict[str, Any]]:
	"""DO with SDDN awaiting verification (replaces standalone Pending SDDN hub)."""
	return [
		c
		for c in _list_delivery_orders()
		if c.get("raw_sddn_status") in SDDN_PENDING
		and c.get("operational_status") in ("Security In Progress", "Pending Security")
	]


def get_security_in_progress_dos() -> list[dict[str, Any]]:
	"""Verified SDDN; loading/QC handoff not completed."""
	return [
		c
		for c in _list_delivery_orders()
		if c.get("operational_status")
		in ("Ready for Loading", "Loading In Progress", "Sent to QC", "QC In Progress")
	]


def get_security_completed_dos() -> list[dict[str, Any]]:
	"""Security handoff complete: sent to QC or operational completed."""
	return [
		c
		for c in _list_delivery_orders()
		if c.get("operational_status") in ("QC Cleared", "Completed")
		or (
			c.get("operational_status") == "Sent to QC"
			and c.get("raw_sddn_status") in SDDN_VERIFIED
		)
	]


def get_security_console_counts() -> dict[str, int]:
	return {
		"new": len(get_security_new_dos()),
		"pending": len(get_security_pending_dos()),
		"in_progress": len(get_security_in_progress_dos()),
		"completed": len(get_security_completed_dos()),
	}


def backfill_delivery_order_links_from_comments() -> int:
	"""Link existing DOs to Job Orders via Comment trail; returns rows updated."""
	if not frappe.db.has_column("Delivery Order", "job_order"):
		return 0
	updated = 0
	rows = frappe.get_all(
		"Comment",
		filters={
			"reference_doctype": "Job Order",
			"comment_type": "Comment",
		},
		fields=["reference_name", "content"],
		order_by="creation desc",
		limit=5000,
	)
	seen_jo: set[str] = set()
	for row in rows:
		jo = row.get("reference_name")
		if not jo or jo in seen_jo:
			continue
		content = (row.get("content") or "").strip()
		m = _DO_COMMENT_PATTERN.search(content)
		if not m:
			continue
		do_name = m.group(1).strip()
		if not frappe.db.exists("Delivery Order", do_name):
			continue
		current = frappe.db.get_value("Delivery Order", do_name, "job_order")
		if current:
			seen_jo.add(jo)
			continue
		ts = frappe.db.get_value(
			"Transport Schedule",
			{"job_order": jo, "transport_status": ["!=", "Cancelled"]},
			"name",
			order_by="modified desc",
		)
		link_delivery_order_to_job_order(do_name, jo, ts, update_modified=False)
		sync_delivery_order_operational_status(do_name, update_modified=False)
		seen_jo.add(jo)
		updated += 1
	return updated
