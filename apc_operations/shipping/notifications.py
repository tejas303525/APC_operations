# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from apc_operations.services.email_recipients import role_user_emails, resolve_user_email


def get_notification_config():
    """Return notification configuration"""
    return {
        "for_doctype": {}
    }


@frappe.whitelist()
def send_payables_notification(booking_name):
    """Send notification to payables team for a Shipping Booking with CRO details."""
    booking = frappe.get_doc("Shipping Booking", booking_name)

    users = role_user_emails(["Accounts Manager", "Accounts User"])

    subject = f"Shipment Charges Tracking - CRO {booking.cro_number}"

    message = f"""
    <h2>Shipment Charges Tracking</h2>

    <b>CRO Number:</b> {booking.cro_number}<br>
    <b>Vessel:</b> {booking.vessel_name}<br>
    <b>Shipping Line:</b> {booking.shipping_line}<br>
    <b>Cutoff Date:</b> {booking.cutoff_date}<br>

    <h3>Charges Breakdown:</h3>
    <ul>
        <li><b>Freight Charges:</b> {booking.currency} {booking.total_freight_charges or 0}</li>
        <li><b>THC:</b> {booking.currency} {booking.thc or 0}</li>
        <li><b>TLUC:</b> {booking.currency} {booking.tluc or 0}</li>
        <li><b>Export Declaration:</b> {booking.currency} {booking.export_declaration or 0}</li>
    </ul>

    <p><a href="{frappe.utils.get_url()}/app/shipping-booking/{booking.name}">View Shipping Booking</a></p>
    """

    for user in users:
        frappe.sendmail(
            recipients=user,
            subject=subject,
            message=message,
            reference_doctype="Shipping Booking",
            reference_name=booking.name
        )

    return {"success": True}


@frappe.whitelist()
def notify_payables_bulk():
    """Send notifications to payables team for all pending shipment charges"""
    bookings = frappe.get_all(
        "Shipping Booking",
        filters={
            "cro_status": "Generated",
            "total_freight_charges": [">", 0]
        },
        fields=["name", "cro_number", "vessel_name", "total_freight_charges", "currency"]
    )

    for booking in bookings:
        send_payables_notification(booking.name)

    return {"success": True, "count": len(bookings)}


@frappe.whitelist()
def notify_driver(transport_name):
    """Send notification to assigned driver"""
    transport = frappe.get_doc("Transport Schedule", transport_name)

    if not transport.assigned_driver:
        frappe.throw(_("No driver assigned to this transport"))

    # Get driver details
    driver = frappe.get_doc("Driver", transport.assigned_driver)

    driver_phone = getattr(driver, "cell_number", None) or getattr(driver, "phone", None)
    if not driver_phone:
        frappe.throw(_("Driver has no mobile number"))

    message = f"""
    Transport Assignment

    Transport: {transport.name}
    Vehicle: {transport.assigned_vehicle}
    Pickup Date: {transport.scheduled_pickup_date}
    Vessel: {transport.vessel_name}
    Container Count: {transport.container_count}
    Port of Loading: {transport.port_of_loading}

    Please report on time.
    """

    # Send SMS if SMS settings configured
    if frappe.db.get_single_value("SMS Settings", "sms_sender_name"):
        frappe.send_sms(driver_phone, message)

    # Also send email if available
    driver_email = getattr(driver, "email", None)
    if driver_email:
        frappe.sendmail(
            recipients=driver_email,
            subject=f"Transport Assignment: {transport.name}",
            message=message.replace('\n', '<br>')
        )

    return {"success": True}


@frappe.whitelist()
def send_cutoff_reminders():
    """Send cutoff reminders to shipping team"""
    from frappe.utils import today, add_days

    cutoff_date = add_days(today(), 3)

    vessels = frappe.db.sql("""
        SELECT
            name,
            vessel_name,
            cutoff_date,
            pull_out_date,
            shipping_line,
            container_count,
            port_of_loading,
            modified_by
        FROM `tabShipping Booking`
        WHERE docstatus = 1
        AND cutoff_date BETWEEN CURDATE() AND %s
        AND transport_status != 'Completed'
    """, (cutoff_date,), as_dict=True)

    for vessel in vessels:
        days_until = frappe.utils.date_diff(vessel.cutoff_date, today())

        subject = f"URGENT: Vessel Cutoff in {days_until} days - {vessel.vessel_name}"

        message = f"""
        <b>Vessel:</b> {vessel.vessel_name}<br>
        <b>Cutoff Date:</b> {vessel.cutoff_date}<br>
        <b>Days Remaining:</b> {days_until}<br>
        <b>Containers:</b> {vessel.container_count}<br>
        <b>Port:</b> {vessel.port_of_loading}<br>
        """

        # Send to vessel owner
        frappe.sendmail(
            recipients=resolve_user_email(vessel.modified_by) or "tejas303525@gmail.com",
            subject=subject,
            message=message,
            reference_doctype="Shipping Booking",
            reference_name=vessel.name
        )

    return {"success": True, "count": len(vessels)}
