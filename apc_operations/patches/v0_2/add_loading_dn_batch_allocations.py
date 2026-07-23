# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""
Migration patch: add new fields to Loading Delivery Note for batch allocations
and dispatch confirmation.

Existing Loading DN records are left intact. The new child table (Loading DN Batch)
and new fields are optional — old records with no batch allocations remain valid.
Also adds batch/coa fields to QC Report Request.
"""

import frappe


def execute():
    # Loading Delivery Note new columns
    frappe.db.sql("""
        ALTER TABLE `tabLoading Delivery Note`
        ADD COLUMN IF NOT EXISTS `dispatch_confirmed` int(1) DEFAULT 0,
        ADD COLUMN IF NOT EXISTS `dispatch_confirmed_on` datetime DEFAULT NULL,
        ADD COLUMN IF NOT EXISTS `dispatch_confirmed_by` varchar(140) DEFAULT NULL,
        ADD COLUMN IF NOT EXISTS `coa_verified` int(1) DEFAULT 0,
        ADD COLUMN IF NOT EXISTS `coa_verified_by` varchar(140) DEFAULT NULL,
        ADD COLUMN IF NOT EXISTS `coa_verified_on` datetime DEFAULT NULL
    """)

    # QC Report Request: batch and coa link fields
    frappe.db.sql("""
        ALTER TABLE `tabQC Report Request`
        ADD COLUMN IF NOT EXISTS `batch` varchar(140) DEFAULT NULL,
        ADD COLUMN IF NOT EXISTS `batch_number` varchar(255) DEFAULT NULL,
        ADD COLUMN IF NOT EXISTS `coa` varchar(140) DEFAULT NULL
    """)

    # APC COA: new fields
    frappe.db.sql("""
        ALTER TABLE `tabAPC COA`
        ADD COLUMN IF NOT EXISTS `nas_path` varchar(255) DEFAULT NULL,
        ADD COLUMN IF NOT EXISTS `customer` varchar(140) DEFAULT NULL,
        ADD COLUMN IF NOT EXISTS `loading_delivery_note` varchar(140) DEFAULT NULL
    """)

    frappe.db.commit()
    print("Loading Delivery Note, QC Report Request, and APC COA field migration complete.")
