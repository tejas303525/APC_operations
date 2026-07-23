# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""
Migration patch: add qc_status and security_draft_delivery_note fields to
Loading Delivery Note and QC Report Request, to support the corrected
Security → QC → Receivables workflow.

Backfill rules:
- Loading DNs with delivery_note_status = 'QC Cleared' or 'Reported to Receivables'
  get qc_status = 'QC Cleared'.
- All other Loading DNs get qc_status = 'Pending QC'.
"""

import frappe


def execute():
    frappe.db.sql("""
        ALTER TABLE `tabLoading Delivery Note`
        ADD COLUMN IF NOT EXISTS `qc_status` varchar(140) DEFAULT 'Pending QC',
        ADD COLUMN IF NOT EXISTS `security_draft_delivery_note` varchar(140) DEFAULT NULL
    """)

    frappe.db.sql("""
        ALTER TABLE `tabQC Report Request`
        ADD COLUMN IF NOT EXISTS `security_draft_delivery_note` varchar(140) DEFAULT NULL
    """)

    frappe.db.commit()

    # Backfill qc_status on existing Loading DNs
    frappe.db.sql("""
        UPDATE `tabLoading Delivery Note`
        SET qc_status = CASE
            WHEN delivery_note_status IN ('QC Cleared', 'Reported to Receivables', 'Completed',
                                          'COA Attached', 'Ready for Receivables', 'Dispatch Confirmed')
                THEN 'QC Cleared'
            WHEN delivery_note_status = 'QC Rejected'
                THEN 'QC Rejected'
            ELSE 'Pending QC'
        END
        WHERE qc_status IS NULL OR qc_status = ''
    """)

    frappe.db.commit()
    print("Loading Delivery Note qc_status and security_draft_delivery_note fields added and backfilled.")
