# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Whitelisted APIs shared by operational consoles."""

from __future__ import annotations

import frappe

from apc_operations.services.daily_work_summary_service import (
	build_daily_work_summary,
	build_my_work_today,
)


@frappe.whitelist()
def get_daily_work_summary(hub: str | None = None):
	"""Return overdue / due-today / this-week counts for console hub queues."""
	return build_daily_work_summary(hub=hub)


@frappe.whitelist()
def get_my_work_today(urgency_filter: str = "urgent"):
	"""Return cross-hub delivery-urgent work rollup for the My Work Today page."""
	return build_my_work_today(urgency_filter=urgency_filter)
