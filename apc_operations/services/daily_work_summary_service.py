# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Daily work summaries for operational console hubs."""

from __future__ import annotations

from typing import Any, Callable

import frappe

from apc_operations.services.console_queue_service import summarize_urgency_counts


def _count_queue(label: str, loader: Callable[[], list[dict[str, Any]]]) -> dict[str, Any]:
	try:
		items = loader() or []
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"Daily work summary: {label}")
		items = []
	counts = summarize_urgency_counts(items)
	return {"label": label, **counts}


def _aggregate(counts_list: list[dict[str, Any]]) -> dict[str, int]:
	total = {
		"overdue": 0,
		"today": 0,
		"this_week": 0,
		"upcoming": 0,
		"unknown": 0,
		"total": 0,
	}
	for row in counts_list:
		for key in total:
			total[key] += int(row.get(key) or 0)
	return total


def build_daily_work_summary(hub: str | None = None) -> dict[str, Any]:
	"""Return overdue / today / this-week counts per console hub queue."""
	hub = (hub or "").strip().lower()
	builders = {
		"security": _security_summary,
		"qc": _qc_summary,
		"transportation": _transportation_summary,
		"shipping": _shipping_summary,
	}

	if hub:
		builder = builders.get(hub)
		if not builder:
			return {"hub": hub, "queues": {}, "totals": _aggregate([])}
		data = builder()
		data["hub"] = hub
		return data

	return {name: builders[name]() for name in builders}


def _security_summary() -> dict[str, Any]:
	from apc_operations.services.delivery_order_service import (
		get_security_completed_dos,
		get_security_in_progress_dos,
		get_security_new_dos,
		get_security_pending_dos,
	)

	queues = {
		"new_dos": _count_queue("New Delivery Orders", get_security_new_dos),
		"pending_dos": _count_queue("Pending Delivery Orders", get_security_pending_dos),
		"in_progress_dos": _count_queue("In Progress Delivery Orders", get_security_in_progress_dos),
		"completed_dos": _count_queue("Completed Delivery Orders", get_security_completed_dos),
	}
	return {"queues": queues, "totals": _aggregate(list(queues.values()))}


def _qc_summary() -> dict[str, Any]:
	from apc_operations.services.delivery_order_service import (
		get_qc_completed_dos,
		get_qc_new_dos,
		get_qc_pending_dos,
	)
	from apc_operations.quality.api import get_rejected_qc_items

	queues = {
		"new_dos": _count_queue("New Delivery Orders", get_qc_new_dos),
		"pending_dos": _count_queue("Pending Delivery Orders", get_qc_pending_dos),
		"completed_dos": _count_queue("Completed Delivery Orders", get_qc_completed_dos),
		"rejected_dos": _count_queue("Rejected Delivery Orders", get_rejected_qc_items),
	}
	return {"queues": queues, "totals": _aggregate(list(queues.values()))}


def _transportation_summary() -> dict[str, Any]:
	from apc_operations.transportation.api import (
		get_export_container_list,
		get_grn_summary_list,
		get_inward_import_list,
		get_inward_land_list,
		get_local_delivery_list,
		get_partial_delivery_followup_list,
	)

	queues = {
		"inward_import": _count_queue("Inward Import", get_inward_import_list),
		"inward_land": _count_queue("Inward Land", get_inward_land_list),
		"grn_summary": _count_queue("GRN Summary", lambda: get_grn_summary_list(only_actionable=1)),
		"local_delivery": _count_queue("Local Deliveries", get_local_delivery_list),
		"export_container": _count_queue("Export Containers", get_export_container_list),
		"partial_followup": _count_queue(
			"Partial Delivery Follow-up",
			lambda: get_partial_delivery_followup_list(only_actionable=1),
		),
	}
	return {"queues": queues, "totals": _aggregate(list(queues.values()))}


def _shipping_summary() -> dict[str, Any]:
	from apc_operations.shipping.api import (
		get_open_cro_schedule,
		get_pending_bookings,
		get_pending_cros,
	)

	queues = {
		"pending_bookings": _count_queue("Pending Bookings", get_pending_bookings),
		"pending_cros": _count_queue("Pending CRO", get_pending_cros),
		"open_cro_schedule": _count_queue("Open CRO Schedule", get_open_cro_schedule),
	}
	return {"queues": queues, "totals": _aggregate(list(queues.values()))}


def format_console_subtitle(counts: dict[str, Any] | None) -> str:
	"""Human-readable subtitle for hub buttons."""
	if not counts:
		return ""
	parts: list[str] = []
	if counts.get("overdue"):
		parts.append(f"{counts['overdue']} overdue")
	if counts.get("today"):
		parts.append(f"{counts['today']} due today")
	if not parts and counts.get("this_week"):
		parts.append(f"{counts['this_week']} this week")
	return " · ".join(parts)


HUB_REGISTRY: dict[str, dict[str, Any]] = {
	"shipping": {
		"label": "Shipping",
		"console_page": "shipping-console",
		"sort_order": 1,
	},
	"transportation": {
		"label": "Transportation",
		"console_page": "transportation-console",
		"sort_order": 2,
	},
	"security": {
		"label": "Security",
		"console_page": "security-console",
		"sort_order": 3,
	},
	"qc": {
		"label": "QC",
		"console_page": "qc-console",
		"sort_order": 4,
	},
}


def _queue_urgent_score(queue: dict[str, Any]) -> int:
	return int(queue.get("overdue") or 0) + int(queue.get("today") or 0)


def _queue_week_score(queue: dict[str, Any]) -> int:
	return _queue_urgent_score(queue) + int(queue.get("this_week") or 0)


def _queue_matches_filter(queue: dict[str, Any], filter_id: str) -> bool:
	if filter_id == "urgent":
		return _queue_urgent_score(queue) > 0
	if filter_id == "week":
		return _queue_week_score(queue) > 0
	return int(queue.get("total") or 0) > 0


def build_my_work_today(urgency_filter: str = "urgent") -> dict[str, Any]:
	"""Cross-hub rollup of delivery-urgent console work for the My Work Today page."""
	filter_id = (urgency_filter or "urgent").strip().lower()
	if filter_id not in ("urgent", "week", "all"):
		filter_id = "urgent"

	all_summary = build_daily_work_summary()
	hubs: list[dict[str, Any]] = []

	for hub_id, meta in HUB_REGISTRY.items():
		hub_data = all_summary.get(hub_id) or {}
		queues_raw = hub_data.get("queues") or {}
		queues: list[dict[str, Any]] = []

		for key, row in queues_raw.items():
			queue = {"key": key, **row}
			if not _queue_matches_filter(queue, filter_id):
				continue
			queue["urgent_total"] = _queue_urgent_score(queue)
			queue["console_page"] = meta["console_page"]
			queues.append(queue)

		if not queues:
			continue

		hub_totals = _aggregate(queues)
		hubs.append(
			{
				"hub": hub_id,
				"label": meta["label"],
				"console_page": meta["console_page"],
				"totals": hub_totals,
				"queues": sorted(
					queues,
					key=lambda q: (-_queue_urgent_score(q), q.get("label") or ""),
				),
			}
		)

	hubs.sort(
		key=lambda h: (
			-_queue_urgent_score(h["totals"]),
			HUB_REGISTRY[h["hub"]]["sort_order"],
		)
	)

	return {
		"date": frappe.utils.today(),
		"filter": filter_id,
		"totals": _aggregate([h["totals"] for h in hubs]),
		"hubs": hubs,
	}
