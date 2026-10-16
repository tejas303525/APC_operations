# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Automated "issued" emails with the document attached as PDF.

GRN -> payables, Delivery Order / Delivery Note -> receivables.
Document events do not fire for these (statuses are set with db_set), so the
issuing code calls ``queue_issue_email`` directly. Sending is deferred to the
background queue and never blocks or fails the issuing action.
"""

import frappe
from frappe.utils import formatdate, nowdate

PAYABLES = "payables@asia-petrochem.com"
RECEIVABLES = "receivables@asia-petrochem.com"

# doctype -> (default recipient, print format, label, settings field prefix)
_CONFIG = {
	"Import GRN": (PAYABLES, "Standard Import GRN", "GRN", "grn"),
	"Delivery Order": (RECEIVABLES, "Standard Delivery Order", "Delivery Order", "delivery"),
	"Loading Delivery Note": (
		RECEIVABLES,
		"Standard Loading Delivery Note",
		"Delivery Note",
		"delivery",
	),
}


def _recipients(default: str, prefix: str) -> list[str]:
	"""Recipients from Issue Email Settings; empty list when switched off."""
	try:
		settings = frappe.get_cached_doc("Issue Email Settings")
	except Exception:
		return [default]
	if not settings.get(f"enable_{prefix}_email"):
		return []
	raw = settings.get(f"{prefix}_recipients") or default
	return [e.strip() for e in raw.replace(";", ",").replace(chr(10), ",").split(",") if e.strip()]


def queue_issue_email(doctype: str, name: str):
	"""Queue the email after the current transaction commits."""
	try:
		frappe.enqueue(
			"apc_operations.shipping.services.issue_email_service.send_issue_email",
			doctype=doctype,
			name=name,
			queue="short",
			enqueue_after_commit=True,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"Issue email enqueue failed: {doctype} {name}")


def send_issue_email(doctype: str, name: str):
	default, print_format, label, prefix = _CONFIG[doctype]
	recipients = _recipients(default, prefix)
	if not recipients or not frappe.db.exists(doctype, name):
		return
	today = formatdate(nowdate())
	message = f"<p>Computer generated {label} {name} on {today}.</p><p>Please find it attached.</p>"
	try:
		pdf = frappe.get_print(doctype, name, print_format=print_format, as_pdf=True)
		frappe.sendmail(
			recipients=recipients,
			subject=f"{label} {name} issued",
			message=message,
			attachments=[{"fname": f"{name}.pdf", "fcontent": pdf}],
			reference_doctype=doctype,
			reference_name=name,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"Issue email failed: {doctype} {name}")
