"""Backfill Shipping Booking.vessel_status to 'In Transit' where blank.

Introduced for the page-on-page console redesign (v0.2). The new
``vessel_status`` Select field has options "In Transit / Berthed /
Cleared" with default "In Transit". This patch ensures existing rows
have a sensible value so the new Transportation Console badges render
correctly.
"""

import frappe


def execute():
	frappe.reload_doctype("Shipping Booking")

	frappe.db.sql(
		"""
		UPDATE `tabShipping Booking`
		SET vessel_status = 'In Transit'
		WHERE IFNULL(vessel_status, '') = ''
		"""
	)
	frappe.db.commit()
