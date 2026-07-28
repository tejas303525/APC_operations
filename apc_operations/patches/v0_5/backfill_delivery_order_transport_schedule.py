# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Link Delivery Orders to Transport Schedule (1:1 SDDN ↔ DO per leg)."""

import frappe


def execute():
	if not frappe.db.has_column("Delivery Order", "transport_schedule"):
		return

	# LDN → SDDN → Transport Schedule
	frappe.db.sql(
		"""
		UPDATE `tabDelivery Order` do
		INNER JOIN `tabLoading Delivery Note` ldn ON ldn.transport_delivery_order = do.name
		INNER JOIN `tabSecurity Draft Delivery Note` sddn ON sddn.name = ldn.security_draft_delivery_note
		   SET do.transport_schedule = sddn.transport_schedule
		 WHERE (do.transport_schedule IS NULL OR do.transport_schedule = '')
		   AND sddn.transport_schedule IS NOT NULL
		   AND sddn.transport_schedule != ''
		   AND do.docstatus != 2
		"""
	)

	# Follow-up DO remarks: Transport: TRN-...
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
		if ts_name and ts_name != do.get("transport_schedule"):
			frappe.db.set_value(
				"Delivery Order",
				do.name,
				"transport_schedule",
				ts_name,
				update_modified=False,
			)
