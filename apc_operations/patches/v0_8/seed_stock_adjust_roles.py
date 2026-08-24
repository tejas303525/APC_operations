"""Seeds APC Operations Settings.stock_adjust_roles with the roles that were
previously hardcoded in inventory/api.py's _ADJUST_ROLES set, so making this
GUI-editable doesn't silently narrow who can already adjust/add stock.
"""

import frappe

ROLES = [
	"Shipping Manager",
	"System Manager",
	"Production Manager",
	"Transportation Manager",
	"Transportation User",
]


def execute():
	settings = frappe.get_single("APC Operations Settings")
	if settings.get("stock_adjust_roles"):
		return

	for role in ROLES:
		settings.append("stock_adjust_roles", {"role": role})
	settings.save(ignore_permissions=True)
