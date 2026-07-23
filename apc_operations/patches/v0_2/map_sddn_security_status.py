"""Map legacy SDDN.security_status values to the new console vocabulary.

The Security Console (v0.2) uses the extended status list:

	Draft / Pending Review / Approved / Rejected /
	Sent to Security / Pending Verification / Verified /
	On Hold / LDN Created / Sent to QC / Completed

Legacy data uses only the first four values. To unify the queue
filters, this patch promotes the legacy values to their canonical
console equivalents:

	Approved        -> Verified
	Pending Review  -> Pending Verification

Run idempotently: repeat invocations are safe because the WHERE clauses
target only the legacy values.
"""

import frappe


def execute():
	frappe.reload_doctype("Security Draft Delivery Note")

	frappe.db.sql(
		"""
		UPDATE `tabSecurity Draft Delivery Note`
		SET security_status = 'Verified'
		WHERE security_status = 'Approved'
		"""
	)

	frappe.db.sql(
		"""
		UPDATE `tabSecurity Draft Delivery Note`
		SET security_status = 'Pending Verification'
		WHERE security_status = 'Pending Review'
		"""
	)

	frappe.db.commit()
