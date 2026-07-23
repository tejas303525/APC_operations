# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe

from apc_operations.services.delivery_order_service import (
	backfill_delivery_order_links_from_comments,
)


def execute():
	if not frappe.db.exists("DocType", "Delivery Order"):
		return
	if not frappe.db.has_column("Delivery Order", "job_order"):
		return
	backfill_delivery_order_links_from_comments()
