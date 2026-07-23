import frappe


def execute():
    if not frappe.db.table_exists("Transport Schedule"):
        return

    columns = set(frappe.db.get_table_columns("Transport Schedule"))
    if "joborder" not in columns or "job_order" not in columns:
        return

    frappe.db.sql(
        """
        UPDATE `tabTransport Schedule` ts
        SET ts.job_order = ts.joborder
        WHERE IFNULL(ts.job_order, '') = ''
          AND IFNULL(ts.joborder, '') != ''
          AND EXISTS (
              SELECT 1
              FROM `tabJob Order` jo
              WHERE jo.name = ts.joborder
          )
        """
    )

    if "transport_type" in columns:
        frappe.db.sql(
            """
            UPDATE `tabTransport Schedule`
            SET transport_type = CASE
                WHEN transport_type = 'Import' THEN 'Inward'
                ELSE 'Outward'
            END
            WHERE transport_type IN ('Export', 'Import', 'Internal')
            """
        )

    if "payables_status" in columns:
        frappe.db.sql(
            """
            UPDATE `tabTransport Schedule`
            SET payables_status = CASE
                WHEN payables_status IN ('Paid') THEN 'Paid'
                WHEN payables_status IN ('Invoice Received', 'Approved') THEN 'Sent to Zoho Books'
                WHEN IFNULL(payables_status, '') = '' THEN 'Not Required'
                ELSE 'Pending Payables'
            END
            WHERE payables_status IN ('Pending', 'Invoice Received', 'Approved', 'Disputed', '')
            """
        )
