"""
Clean up the magic-string "TBD" sentinel that an earlier version of
JobOrder.create_or_link_shipping_booking() wrote to Shipping Booking.vessel_name
for placeholder bookings.

The Shipping Dashboard "To Book Vessel" KPI counts records with
vessel_name in ('', NULL), so the placeholders were silently excluded.
We blank them out so they show up in the pending-bookings count.

Only touches rows where vessel_name is exactly "TBD" AND no real cutoff/
vessel/CRO data has been added yet, to avoid clobbering anything Logistics
has typed in.
"""

import frappe


def execute():
    if not frappe.db.table_exists("Shipping Booking"):
        return

    columns = set(frappe.db.get_table_columns("Shipping Booking"))
    needed = {"vessel_name", "cro_number", "cutoff_date"}
    if not needed.issubset(columns):
        return

    affected = frappe.db.sql(
        """
        UPDATE `tabShipping Booking`
        SET vessel_name = NULL
        WHERE vessel_name = 'TBD'
          AND IFNULL(cro_number, '') = ''
          AND cutoff_date IS NULL
        """
    )

    if affected:
        frappe.db.commit()
