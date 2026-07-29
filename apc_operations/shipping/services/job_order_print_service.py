# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Print context for Standard Job Order."""

from __future__ import annotations

import frappe

from apc_operations.shipping.services.logistics_cost_service import get_logistics_cost_summary


@frappe.whitelist()
def get_print_context(job_order_name: str) -> dict:
	summary = get_logistics_cost_summary(job_order_name)
	jo = summary.get("job_order") or {}
	counterparty_name = jo.get("customer_name") or jo.get("supplier_name")
	counterparty_label = "Customer" if (jo.get("commercial_movement") or "Outward") == "Outward" else "Supplier"

	payment_terms_label = jo.get("payment_terms")
	if jo.get("payment_terms"):
		payment_terms_label = frappe.db.get_value("Payment Term", jo["payment_terms"], "payment_term_name") or jo["payment_terms"]

	bank_label = ""
	if jo.get("bank_account"):
		bank_label = frappe.db.get_value("Bank Account", jo["bank_account"], "bank_account_no") or jo["bank_account"]

	return {
		**summary,
		"counterparty_label": counterparty_label,
		"counterparty_name": counterparty_name,
		"payment_terms_label": payment_terms_label,
		"bank_account_label": bank_label,
	}
