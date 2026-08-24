# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class APCOperationsSettings(Document):
	pass


def require_sales_demand_on_job_order() -> bool:
	return bool(frappe.db.get_single_value("APC Operations Settings", "require_sales_demand_on_job_order"))


def zoho_dispatch_sync_enabled() -> bool:
	return bool(frappe.db.get_single_value("APC Operations Settings", "zoho_dispatch_sync_enabled"))


def zoho_dispatch_stub_only() -> bool:
	value = frappe.db.get_single_value("APC Operations Settings", "zoho_dispatch_stub_only")
	return True if value is None else bool(value)


def default_import_do_customer() -> str | None:
	return frappe.db.get_single_value("APC Operations Settings", "default_import_do_customer")


def qc_manager_role() -> str:
	return frappe.db.get_single_value("APC Operations Settings", "qc_manager_role") or "Quality Manager"


def loading_quantity_tolerance_pct() -> float:
	value = frappe.db.get_single_value("APC Operations Settings", "loading_quantity_tolerance_pct")
	return float(value) if value else 1.0
