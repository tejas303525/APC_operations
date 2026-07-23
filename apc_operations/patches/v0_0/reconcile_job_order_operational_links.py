import frappe


def execute():
    if not frappe.db.table_exists("Job Order"):
        return

    if frappe.db.table_exists("Transport Schedule"):
        _backfill_transport_schedule_links()

    if frappe.db.table_exists("Shipping Booking"):
        _backfill_shipping_booking_links()

    _create_missing_confirmed_exw_transport_schedules()


def _has_columns(doctype, required_columns):
    columns = set(frappe.db.get_table_columns(doctype))
    return set(required_columns).issubset(columns)


def _backfill_transport_schedule_links():
    if not _has_columns("Job Order", ["transport_schedule", "transport_status"]):
        return
    if not _has_columns("Transport Schedule", ["name", "job_order"]):
        return

    frappe.db.sql(
        """
        UPDATE `tabJob Order` jo
        SET
            jo.transport_schedule = (
                SELECT ts.name
                FROM `tabTransport Schedule` ts
                WHERE ts.job_order = jo.name
                ORDER BY ts.creation ASC, ts.name ASC
                LIMIT 1
            ),
            jo.transport_status = 'Scheduled'
        WHERE IFNULL(jo.transport_schedule, '') = ''
          AND EXISTS (
              SELECT 1
              FROM `tabTransport Schedule` ts
              WHERE ts.job_order = jo.name
          )
        """
    )


def _backfill_shipping_booking_links():
    if not _has_columns("Job Order", ["shipping_booking", "shipping_status"]):
        return
    if not _has_columns("Shipping Booking", ["name", "job_order"]):
        return

    frappe.db.sql(
        """
        UPDATE `tabJob Order` jo
        SET
            jo.shipping_booking = (
                SELECT sb.name
                FROM `tabShipping Booking` sb
                WHERE sb.job_order = jo.name
                ORDER BY sb.creation ASC, sb.name ASC
                LIMIT 1
            ),
            jo.shipping_status = CASE
                WHEN jo.terms_of_delivery IN ('CFR', 'CIF') THEN 'Pending Shipping Review'
                ELSE 'Pending Shipping Booking'
            END
        WHERE IFNULL(jo.shipping_booking, '') = ''
          AND EXISTS (
              SELECT 1
              FROM `tabShipping Booking` sb
              WHERE sb.job_order = jo.name
          )
        """
    )


def _create_missing_confirmed_exw_transport_schedules():
    if not _has_columns("Job Order", ["status", "terms_of_delivery", "transport_schedule"]):
        return

    job_orders = frappe.get_all(
        "Job Order",
        filters={
            "status": "Confirmed",
            "terms_of_delivery": "EXW",
            "transport_schedule": ["in", ["", None]],
        },
        pluck="name",
    )

    for job_order_name in job_orders:
        if frappe.db.exists("Transport Schedule", {"job_order": job_order_name}):
            continue

        job_order = frappe.get_doc("Job Order", job_order_name)
        job_order.create_or_link_transport_schedule()
