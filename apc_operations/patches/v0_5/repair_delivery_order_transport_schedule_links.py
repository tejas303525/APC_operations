# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Repair Delivery Orders wrongly linked to a newer transport leg (LDN provenance wins)."""

import frappe


def execute():
	if not frappe.db.has_column("Delivery Order", "transport_schedule"):
		return

	# Authoritative: LDN → SDDN → Transport Schedule
	frappe.db.sql(
		"""
		UPDATE `tabDelivery Order` do
		INNER JOIN `tabLoading Delivery Note` ldn ON ldn.transport_delivery_order = do.name
		INNER JOIN `tabSecurity Draft Delivery Note` sddn ON sddn.name = ldn.security_draft_delivery_note
		   SET do.transport_schedule = sddn.transport_schedule
		 WHERE sddn.transport_schedule IS NOT NULL
		   AND sddn.transport_schedule != ''
		   AND do.docstatus != 2
		"""
	)

	for do in frappe.get_all(
		"Delivery Order",
		filters={"docstatus": ["!=", 2]},
		fields=["name", "remarks", "transport_schedule"],
	):
		remarks = do.get("remarks") or ""
		marker = "Transport: "
		if marker not in remarks:
			continue
		ts_name = remarks.split(marker, 1)[1].split(")", 1)[0].strip()
		if ts_name:
			frappe.db.set_value(
				"Delivery Order",
				do.name,
				"transport_schedule",
				ts_name,
				update_modified=False,
			)
