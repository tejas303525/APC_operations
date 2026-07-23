# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

from apc_operations.services.delivery_order_service import (
	sync_delivery_order_operational_status,
	sync_from_ldn,
	sync_from_qcr,
	sync_from_sddn,
)


def on_delivery_order_update(doc, method):
	sync_delivery_order_operational_status(doc.name, update_modified=False)


def on_security_draft_dn_update(doc, method):
	sync_from_sddn(doc.name)


def on_loading_delivery_note_update_hook(doc, method):
	sync_from_ldn(doc.name)


def on_qc_report_request_update_hook(doc, method):
	sync_from_qcr(doc.name)
