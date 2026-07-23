# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""
NAS Storage Service

Saves COA and Security Inspection checklist PDFs to a configured NAS share.
NAS path configuration lives in the APC NAS Settings single DocType.

NAS folder structure:
    {nas_base_path}/
    ├── QC/
    │   ├── COA/
    │   │   └── {YYYY}/{Customer}/{JobOrder}/{COA-Number}_{BatchNumber}.pdf
    │   └── Checklists/
    │       └── {YYYY}/{SEC-INS-Number}_QC-Checklist.pdf
"""

import os
import frappe
from frappe import _
from frappe.utils import now


# ── NAS Settings helpers ─────────────────────────────────────────────────────

def _get_nas_settings():
    """Return APC NAS Settings as a dict. Returns empty dict if not configured."""
    try:
        settings = frappe.get_single("APC NAS Settings")
        return settings
    except Exception:
        return None


def _nas_is_enabled():
    """Return True if NAS is configured and enabled."""
    s = _get_nas_settings()
    if not s:
        return False
    return bool(s.enabled and s.nas_base_path)


def get_nas_path(subfolder_parts, filename):
    """
    Build a NAS file path from the configured base path, subfolder parts list, and filename.

    Example:
        get_nas_path(["QC", "COA", "2026", "CustomerA", "JO-2026-00001"], "COA-001_BATCH-001.pdf")
        → "/mnt/nas/APC Operations/QC/COA/2026/CustomerA/JO-2026-00001/COA-001_BATCH-001.pdf"
    """
    s = _get_nas_settings()
    if not s or not s.nas_base_path:
        return None

    base = s.nas_base_path.rstrip("/").rstrip("\\")
    parts = [base] + [str(p) for p in subfolder_parts] + [filename]
    return os.path.join(*parts)


def _ensure_nas_dir(path):
    """Create directory tree for path if it does not exist."""
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)


def _generate_pdf_bytes(doctype, docname, print_format=None):
    """Generate PDF bytes for a document using frappe's print engine."""
    from frappe.utils.pdf import get_pdf
    html = frappe.get_print(doctype, docname, print_format=print_format, as_pdf=False)
    return get_pdf(html)


# ── COA NAS Save ─────────────────────────────────────────────────────────────

@frappe.whitelist()
def save_coa_to_nas(coa_name):
    """
    Generate COA PDF and save to NAS.

    Path: {nas_base}/QC/COA/{YYYY}/{Customer}/{JobOrder}/{COA}_{Batch}.pdf

    If NAS is unavailable or not configured, logs a warning and returns without raising.
    Sets APC COA.nas_path on success.
    """
    if not _nas_is_enabled():
        frappe.logger().debug(f"NAS not configured — skipping NAS save for COA {coa_name}")
        return {"skipped": True, "reason": "NAS not configured"}

    coa = frappe.get_doc("APC COA", coa_name)

    from frappe.utils import getdate
    year = str(getdate(coa.coa_date or now()).year)
    customer_slug = _safe_path_segment(coa.customer or "NoCustomer")
    job_order_slug = _safe_path_segment(coa.job_order or "NoJobOrder")
    filename = f"{_safe_path_segment(coa.coa_number or coa.name)}_{_safe_path_segment(coa.batch_number or coa.batch or 'NoBatch')}.pdf"

    subfolder_parts = ["QC", "COA", year, customer_slug, job_order_slug]
    full_path = get_nas_path(subfolder_parts, filename)

    if not full_path:
        return {"skipped": True, "reason": "NAS path could not be determined"}

    try:
        _ensure_nas_dir(full_path)
        pdf_bytes = _generate_pdf_bytes("APC COA", coa_name)
        with open(full_path, "wb") as f:
            f.write(pdf_bytes)

        frappe.db.set_value("APC COA", coa_name, "nas_path", full_path, update_modified=False)

        # Also update the linked batch's nas_path
        if coa.batch:
            frappe.db.set_value("APC Batch", coa.batch, "nas_path", full_path, update_modified=False)

        frappe.logger().info(f"COA {coa_name} saved to NAS: {full_path}")
        return {"success": True, "path": full_path}

    except OSError as e:
        msg = f"NAS save failed for COA {coa_name}: {e}"
        frappe.logger().warning(msg)
        frappe.log_error(msg, "NAS COA Save")
        return {"success": False, "error": str(e)}


# ── Checklist NAS Save ───────────────────────────────────────────────────────

@frappe.whitelist()
def save_checklist_to_nas(security_inspection_name):
    """
    Generate Security Inspection checklist PDF and save to NAS.

    Path: {nas_base}/QC/Checklists/{YYYY}/{SEC-INS-Number}_QC-Checklist.pdf

    If NAS is unavailable or not configured, logs a warning and returns without raising.
    """
    if not _nas_is_enabled():
        frappe.logger().debug(f"NAS not configured — skipping NAS save for {security_inspection_name}")
        return {"skipped": True, "reason": "NAS not configured"}

    doc = frappe.get_doc("Security Inspection", security_inspection_name)

    from frappe.utils import getdate
    year = str(getdate(doc.inspection_date or now()).year)
    filename = f"{_safe_path_segment(security_inspection_name)}_QC-Checklist.pdf"

    subfolder_parts = ["QC", "Checklists", year]
    full_path = get_nas_path(subfolder_parts, filename)

    if not full_path:
        return {"skipped": True, "reason": "NAS path could not be determined"}

    try:
        _ensure_nas_dir(full_path)
        pdf_bytes = _generate_pdf_bytes("Security Inspection", security_inspection_name)
        with open(full_path, "wb") as f:
            f.write(pdf_bytes)

        if hasattr(doc, "checklist_nas_path"):
            frappe.db.set_value(
                "Security Inspection",
                security_inspection_name,
                "checklist_nas_path",
                full_path,
                update_modified=False,
            )

        frappe.logger().info(f"Checklist {security_inspection_name} saved to NAS: {full_path}")
        return {"success": True, "path": full_path}

    except OSError as e:
        msg = f"NAS save failed for Security Inspection {security_inspection_name}: {e}"
        frappe.logger().warning(msg)
        frappe.log_error(msg, "NAS Checklist Save")
        return {"success": False, "error": str(e)}


# ── Nightly retry job ────────────────────────────────────────────────────────

def retry_failed_nas_saves():
    """
    Scheduled job: retry NAS saves for any approved COAs that have no nas_path.
    Registered in hooks.py scheduler_events.
    """
    if not _nas_is_enabled():
        return

    pending_coas = frappe.get_all(
        "APC COA",
        filters={
            "approval_status": "Approved",
            "nas_path": ["in", ["", None]],
        },
        fields=["name"],
        limit=100,
    )

    for row in pending_coas:
        try:
            save_coa_to_nas(row.name)
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"NAS Retry COA {row.name}")

    # Retry checklists
    pending_inspections = frappe.get_all(
        "Security Inspection",
        filters={
            "security_status": ["in", ["Completed", "Loading DN Created", "Reported to Receivables"]],
        },
        fields=["name"],
        limit=100,
    )

    for row in pending_inspections:
        try:
            checklist_path = frappe.db.get_value("Security Inspection", row.name, "checklist_nas_path")
            if not checklist_path:
                save_checklist_to_nas(row.name)
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"NAS Retry Checklist {row.name}")


# ── Utilities ────────────────────────────────────────────────────────────────

def _safe_path_segment(value):
    """Sanitize a string for use as a file path segment."""
    if not value:
        return "Unknown"
    return "".join(c if (c.isalnum() or c in "-_ ") else "_" for c in str(value)).strip()
