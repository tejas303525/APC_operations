# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Shared console queue sorting by Job Order delivery date."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import add_days, getdate, today

URGENCY_OVERDUE = "overdue"
URGENCY_TODAY = "today"
URGENCY_UPCOMING = "upcoming"
URGENCY_UNKNOWN = "unknown"

_URGENCY_ORDER = {
	URGENCY_OVERDUE: 0,
	URGENCY_TODAY: 1,
	URGENCY_UPCOMING: 2,
	URGENCY_UNKNOWN: 3,
}


def delivery_urgency(due_date) -> str:
	"""Classify a due date relative to today."""
	if not due_date:
		return URGENCY_UNKNOWN
	due = getdate(due_date)
	now = getdate(today())
	if due < now:
		return URGENCY_OVERDUE
	if due == now:
		return URGENCY_TODAY
	return URGENCY_UPCOMING


def resolve_delivery_due_date(
	job_order: str | None = None,
	transport_schedule: str | None = None,
	posting_date=None,
	scheduled_delivery_date=None,
) -> str | None:
	"""Resolve the canonical delivery due date for console sorting."""
	if job_order and frappe.db.exists("Job Order", job_order):
		jo_date = frappe.db.get_value("Job Order", job_order, "date")
		if jo_date:
			return jo_date
	if scheduled_delivery_date:
		return scheduled_delivery_date
	if transport_schedule and frappe.db.exists("Transport Schedule", transport_schedule):
		ts_date = frappe.db.get_value(
			"Transport Schedule",
			transport_schedule,
			"scheduled_delivery_date",
		)
		if ts_date:
			return ts_date
	return posting_date


def attach_delivery_due_fields(
	item: dict[str, Any],
	*,
	job_order_key: str = "job_order",
	transport_schedule_key: str = "transport_schedule",
	posting_date_key: str = "posting_date",
) -> dict[str, Any]:
	"""Attach delivery_due_date, delivery_urgency, and is_delivery_overdue."""
	due = resolve_delivery_due_date(
		item.get(job_order_key),
		item.get(transport_schedule_key),
		item.get(posting_date_key),
		item.get("scheduled_delivery_date"),
	)
	item["delivery_due_date"] = due
	item["delivery_urgency"] = delivery_urgency(due)
	item["is_delivery_overdue"] = item["delivery_urgency"] == URGENCY_OVERDUE
	return item


def sort_console_queue(
	items: list[dict[str, Any]],
	*,
	date_key: str = "delivery_due_date",
	creation_key: str = "creation",
) -> list[dict[str, Any]]:
	"""Sort console cards: overdue first, then today, then upcoming; earliest date first."""

	def _sort_key(item: dict[str, Any]) -> tuple:
		if not item.get(date_key):
			attach_delivery_due_fields(item)
		urgency = item.get("delivery_urgency") or delivery_urgency(item.get(date_key))
		due = getdate(item[date_key]) if item.get(date_key) else getdate("9999-12-31")
		secondary = (
			item.get(creation_key)
			or item.get("modified")
			or item.get("name")
			or ""
		)
		return (_URGENCY_ORDER.get(urgency, 3), due, str(secondary))

	return sorted(items, key=_sort_key)


def enrich_and_sort_console_queue(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
	"""Attach delivery metadata and sort a console queue."""
	for item in items:
		attach_delivery_due_fields(item)
	return sort_console_queue(items)


def summarize_urgency_counts(items: list[dict[str, Any]]) -> dict[str, int]:
	"""Count queue items by delivery urgency bucket."""
	counts = {
		"overdue": 0,
		"today": 0,
		"this_week": 0,
		"upcoming": 0,
		"unknown": 0,
		"total": len(items),
	}
	week_end = getdate(add_days(today(), 7))
	for item in items:
		if not item.get("delivery_urgency"):
			attach_delivery_due_fields(item)
		urgency = item.get("delivery_urgency") or URGENCY_UNKNOWN
		if urgency == URGENCY_OVERDUE:
			counts["overdue"] += 1
		elif urgency == URGENCY_TODAY:
			counts["today"] += 1
		elif urgency == URGENCY_UPCOMING:
			due = item.get("delivery_due_date")
			if due and getdate(due) <= week_end:
				counts["this_week"] += 1
			else:
				counts["upcoming"] += 1
		else:
			counts["unknown"] += 1
	return counts


def filter_by_urgency(
	items: list[dict[str, Any]],
	filter_id: str | None,
) -> list[dict[str, Any]]:
	"""Filter a console queue by urgency chip selection."""
	if not filter_id or filter_id == "all":
		return list(items)

	week_end = getdate(add_days(today(), 7))
	out: list[dict[str, Any]] = []
	for item in items:
		if not item.get("delivery_urgency"):
			attach_delivery_due_fields(item)
		urgency = item.get("delivery_urgency") or URGENCY_UNKNOWN
		due = getdate(item["delivery_due_date"]) if item.get("delivery_due_date") else None

		if filter_id == "overdue" and urgency == URGENCY_OVERDUE:
			out.append(item)
		elif filter_id == "today" and urgency == URGENCY_TODAY:
			out.append(item)
		elif filter_id == "week" and (
			urgency in (URGENCY_OVERDUE, URGENCY_TODAY)
			or (due and due <= week_end)
		):
			out.append(item)
	return out
