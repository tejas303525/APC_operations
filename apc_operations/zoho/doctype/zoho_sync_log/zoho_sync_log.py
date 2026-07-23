# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now


class ZohoSyncLog(Document):
    pass


@frappe.whitelist()
def log_sync_attempt(sync_type, zoho_id=None, apc_document_type=None, apc_document=None,
                      request_data=None, sync_status="Pending"):
    """Log a sync attempt."""
    log = frappe.new_doc("Zoho Sync Log")
    log.sync_type = sync_type
    log.sync_status = sync_status
    log.sync_date = now()
    log.zoho_id = zoho_id
    log.apc_document_type = apc_document_type
    log.apc_document = apc_document
    log.request_data = request_data
    log.insert()
    return log.name


@frappe.whitelist()
def update_sync_status(log_name, sync_status, response_data=None, error_message=None, error_details=None):
    """Update sync log status."""
    log = frappe.get_doc("Zoho Sync Log", log_name)
    log.sync_status = sync_status

    if response_data:
        log.response_data = response_data
    if error_message:
        log.error_message = error_message
    if error_details:
        log.error_details = error_details

    if sync_status == "Failed":
        log.retry_count = log.retry_count + 1

    log.save()


@frappe.whitelist()
def get_failed_syncs(sync_type=None, limit=50):
    """Get list of failed syncs for retry."""
    filters = {"sync_status": "Failed", "retry_count": ["<", 3]}
    if sync_type:
        filters["sync_type"] = sync_type

    return frappe.get_all(
        "Zoho Sync Log",
        filters=filters,
        fields=["name", "sync_type", "zoho_id", "apc_document", "retry_count", "error_message"],
        order_by="sync_date DESC",
        limit=limit
    )
