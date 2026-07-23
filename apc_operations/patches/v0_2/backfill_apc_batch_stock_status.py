# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""
Migration patch: backfill stock_status and coa_status on existing APC Batch records.

Rules:
- quality_status in (Approved, QC Cleared) and batch_status != Blocked → stock_status = Available
- quality_status in (Rejected, QC Rejected) or batch_status = Blocked  → stock_status = Rejected
- batch_status = Cancelled                                               → stock_status = Cancelled
- batch_status = Depleted                                                → stock_status = Dispatched
- All others                                                             → stock_status = QC Hold

Also backfills coa_status from linked_coa.approval_status.
"""

import frappe


def execute():
    frappe.db.sql("""
        ALTER TABLE `tabAPC Batch`
        ADD COLUMN IF NOT EXISTS `stock_status` varchar(140) DEFAULT 'QC Hold',
        ADD COLUMN IF NOT EXISTS `coa_status` varchar(140) DEFAULT 'Not Generated',
        ADD COLUMN IF NOT EXISTS `dispatched_quantity` decimal(21,9) DEFAULT 0,
        ADD COLUMN IF NOT EXISTS `job_order` varchar(140) DEFAULT NULL,
        ADD COLUMN IF NOT EXISTS `nas_path` varchar(255) DEFAULT NULL
    """)

    frappe.db.commit()

    # Set stock_status
    frappe.db.sql("""
        UPDATE `tabAPC Batch`
        SET stock_status = CASE
            WHEN batch_status = 'Cancelled' THEN 'Cancelled'
            WHEN batch_status = 'Depleted' THEN 'Dispatched'
            WHEN batch_status = 'Blocked' THEN 'Rejected'
            WHEN quality_status IN ('Approved', 'QC Cleared') THEN 'Available'
            WHEN quality_status IN ('Rejected', 'QC Rejected') THEN 'Rejected'
            ELSE 'QC Hold'
        END
        WHERE stock_status IS NULL OR stock_status = ''
    """)

    # Set coa_status from linked COA
    frappe.db.sql("""
        UPDATE `tabAPC Batch` b
        LEFT JOIN `tabAPC COA` c ON c.name = b.linked_coa
        SET b.coa_status = CASE
            WHEN b.linked_coa IS NULL OR b.linked_coa = '' THEN 'Not Generated'
            WHEN c.approval_status = 'Approved' THEN 'Approved'
            WHEN c.approval_status = 'Rejected' THEN 'Rejected'
            WHEN c.status IN ('Passed', 'Failed') THEN 'Generated'
            ELSE 'Pending'
        END
        WHERE b.coa_status IS NULL OR b.coa_status = ''
    """)

    frappe.db.commit()
    print("APC Batch stock_status and coa_status backfill complete.")
