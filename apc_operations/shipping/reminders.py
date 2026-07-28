# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import today, add_days, date_diff
from frappe import _

FALLBACK_NOTIFICATION_EMAIL = "tejas303525@gmail.com"


def _first_valid_email(candidate):
    if not candidate:
        return None
    valid = frappe.utils.validate_email_address(candidate, throw=False)
    if isinstance(valid, (list, tuple)):
        return valid[0] if valid else None
    return valid if isinstance(valid, str) and valid else None


def _resolve_user_email(user_id):
    if not user_id:
        return None
    email = frappe.db.get_value("User", user_id, "email")
    return _first_valid_email(email) or _first_valid_email(user_id)


def _role_user_emails(roles):
    if isinstance(roles, str):
        roles = [roles]

    has_roles = frappe.get_all(
        "Has Role",
        filters={"parenttype": "User", "role": ["in", roles]},
        fields=["parent"],
        distinct=True,
    )

    recipients = []
    for row in has_roles:
        email = _resolve_user_email(row.parent)
        if email:
            recipients.append(email)

    if not recipients:
        fallback = _first_valid_email(FALLBACK_NOTIFICATION_EMAIL)
        if fallback:
            recipients.append(fallback)

    return list(dict.fromkeys(recipients))


def check_upcoming_cutoffs():
    """Check for shipping booking cutoffs in next 3 days and notify users"""
    cutoff_date = add_days(today(), 3)

    bookings = frappe.db.sql("""
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

    if bookings:
        notify_users_about_cutoffs(bookings)


def check_pending_pull_outs():
    """Check for pull outs due within 2 days"""
    pullout_date = add_days(today(), 2)

    bookings = frappe.db.sql("""
        SELECT
            name,
            vessel_name,
            pull_out_date,
            cutoff_date,
            shipping_line,
            container_count,
            modified_by
        FROM `tabShipping Booking`
        WHERE docstatus = 1
        AND pull_out_date BETWEEN CURDATE() AND %s
        AND transport_status IN ('Pending', 'Scheduled')
    """, (pullout_date,), as_dict=True)

    if bookings:
        notify_users_about_pullouts(bookings)


def check_pending_cros():
    """Check for bookings where CRO has not yet been received"""
    bookings = frappe.db.sql("""
        SELECT
            name,
            vessel_name,
            cutoff_date,
            cro_status,
            modified_by
        FROM `tabShipping Booking`
        WHERE docstatus = 1
        AND cro_status = 'Pending'
        AND creation <= DATE_SUB(NOW(), INTERVAL 1 DAY)
    """, as_dict=True)

    if bookings:
        notify_users_about_pending_cros(bookings)


def check_pending_transport():
    """Check for transport schedules pending pickup"""
    pickup_date = add_days(today(), 1)

    transports = frappe.db.sql("""
        SELECT
            name,
            shipping_booking,
            vessel_name,
            scheduled_pickup_date,
            transport_status,
            assigned_vehicle,
            modified_by
        FROM `tabTransport Schedule`
        WHERE transport_status IN ('Pending Assignment', 'Scheduled', 'Vehicle Assigned', 'Driver Assigned')
        AND scheduled_pickup_date <= %s
    """, (pickup_date,), as_dict=True)

    if transports:
        notify_users_about_pending_transport(transports)


def send_daily_dashboard_summary():
    """Send daily summary to shipping managers"""
    summary_data = get_daily_summary()
    unbooked_job_orders = get_unbooked_transport_job_orders(limit=20)

    users = _role_user_emails(["Shipping Manager", "Transportation Manager"])

    unbooked_count = len(unbooked_job_orders)
    unbooked_lines = ""
    for row in unbooked_job_orders:
        ref = row.get("job_order_number") or row.get("name")
        unbooked_lines += (
            f"<li><b>{ref}</b> | Date: {row.get('date') or 'N/A'} | "
            f"Customer: {row.get('customer_name') or row.get('customer') or 'N/A'} | "
            f"Incoterm: {row.get('terms_of_delivery') or 'N/A'}</li>"
        )

    unbooked_section = (
        f"""
        <h3>Job Orders Not Booked Yet:</h3>
        <p><b>{unbooked_count}</b> job orders still need transport booking.</p>
        <ul>{unbooked_lines}</ul>
        """
        if unbooked_count
        else "<h3>Job Orders Not Booked Yet:</h3><p>None pending today.</p>"
    )

    subject = f"Daily Shipping Dashboard Summary - {today()}"
    message = f"""
    <h2>Shipping Operations Daily Summary - {today()}</h2>

    <h3>Action Items:</h3>
    <ul>
        <li><b>{summary_data['pending_cros']}</b> Bookings Awaiting CRO</li>
        <li><b>{summary_data['upcoming_cutoffs']}</b> Upcoming Cutoffs (7 days)</li>
        <li><b>{summary_data['pending_pullouts']}</b> Pending Pull Outs (3 days)</li>
        <li><b>{summary_data['pending_transport']}</b> Transport Schedules Pending</li>
        <li><b>{summary_data['open_gate_passes']}</b> Open Gate Passes</li>
        <li><b>{summary_data['dg_pending']}</b> DG Shipments Pending Approval</li>
    </ul>
    {unbooked_section}
    {_console_delivery_urgency_section()}

    <p><a href="{frappe.utils.get_url()}/app/shipping">Open Shipping Dashboard</a></p>
    """

    for user in users:
        frappe.sendmail(
            recipients=user,
            subject=subject,
            message=message,
            reference_doctype="Shipping Booking",
            reference_name="",
        )


def send_morning_reminders():
    """Send morning reminders at 8 AM"""
    todays_actions = get_todays_actions_data()

    if not todays_actions['total_actions']:
        return

    users = _role_user_emails("Shipping User")

    subject = f"Morning Reminders: {todays_actions['total_actions']} Actions Today"
    message = f"""
    <h2>Good Morning! Today's Shipping Actions</h2>

    <h3>You have {todays_actions['total_actions']} items requiring attention today:</h3>
    <ul>
        <li>{todays_actions['cros_today']} Bookings awaiting CRO</li>
        <li>{todays_actions['pullouts_today']} Pull outs scheduled</li>
        <li>{todays_actions['cutoffs_tomorrow']} Vessel cutoffs tomorrow</li>
        <li>{todays_actions['transport_pending']} Transport schedules pending</li>
    </ul>

    <p><a href="{frappe.utils.get_url()}/app/shipping">View Dashboard</a></p>
    """

    for user in users:
        frappe.sendmail(recipients=user, subject=subject, message=message)


def send_evening_reminders():
    """Send evening reminders at 4 PM"""
    overdue = get_overdue_items()

    if not overdue:
        return

    users = _role_user_emails("Shipping Manager")

    subject = f"End of Day: {overdue['total']} Overdue Items"
    message = f"""
    <h2>End of Day Summary - Overdue Items</h2>

    <h3>{overdue['total']} items are overdue or due tomorrow:</h3>
    <ul>
        <li>{overdue['overdue_cros']} Bookings with overdue CRO</li>
        <li>{overdue['overdue_transport']} Overdue Transport</li>
        <li>{overdue['tomorrow_cutoffs']} Cutoffs Tomorrow</li>
    </ul>
    """

    for user in users:
        frappe.sendmail(recipients=user, subject=subject, message=message)


def notify_users_about_cutoffs(bookings):
    for booking in bookings:
        days_until = date_diff(booking.cutoff_date, today())
        subject = f"URGENT: Vessel Cutoff in {days_until} days - {booking.vessel_name}"
        message = f"""
        <b>Vessel:</b> {booking.vessel_name}<br>
        <b>Cutoff Date:</b> {booking.cutoff_date}<br>
        <b>Days Remaining:</b> {days_until}<br>
        <b>Containers:</b> {booking.container_count}<br>
        <b>Port:</b> {booking.port_of_loading}<br>
        <br>
        <a href="{frappe.utils.get_url()}/app/shipping-booking/{booking.name}">View Shipping Booking</a>
        """
        frappe.sendmail(
            recipients=_resolve_user_email(booking.modified_by) or FALLBACK_NOTIFICATION_EMAIL,
            subject=subject,
            message=message,
            reference_doctype="Shipping Booking",
            reference_name=booking.name,
        )
        frappe.get_doc({
            "doctype": "Notification Log",
            "subject": subject,
            "type": "Alert",
            "document_type": "Shipping Booking",
            "document_name": booking.name,
            "for_user": booking.modified_by if frappe.db.exists("User", booking.modified_by) else "Administrator",
        }).insert(ignore_permissions=True)


def notify_users_about_pullouts(bookings):
    for booking in bookings:
        days_until = date_diff(booking.pull_out_date, today())
        subject = f"Pull Out Scheduled in {days_until} days - {booking.vessel_name}"
        message = f"""
        <b>Vessel:</b> {booking.vessel_name}<br>
        <b>Pull Out Date:</b> {booking.pull_out_date}<br>
        <b>Cutoff Date:</b> {booking.cutoff_date}<br>
        <b>Containers:</b> {booking.container_count}<br>
        <br>
        Transport must be arranged immediately.
        """
        frappe.sendmail(
            recipients=_resolve_user_email(booking.modified_by) or FALLBACK_NOTIFICATION_EMAIL,
            subject=subject,
            message=message,
            reference_doctype="Shipping Booking",
            reference_name=booking.name,
        )


def notify_users_about_pending_cros(bookings):
    for booking in bookings:
        subject = f"CRO Not Yet Received: {booking.name}"
        message = f"""
        <b>Shipping Booking:</b> {booking.name}<br>
        <b>Vessel:</b> {booking.vessel_name}<br>
        <b>CRO Status:</b> {booking.cro_status}<br>
        <b>Cutoff:</b> {booking.cutoff_date}<br>
        <br>
        Please enter the CRO number on the Shipping Booking.
        <br>
        <a href="{frappe.utils.get_url()}/app/shipping-booking/{booking.name}">Open Booking</a>
        """
        frappe.sendmail(
            recipients=_resolve_user_email(booking.modified_by) or FALLBACK_NOTIFICATION_EMAIL,
            subject=subject,
            message=message,
            reference_doctype="Shipping Booking",
            reference_name=booking.name,
        )


def notify_users_about_pending_transport(transports):
    for transport in transports:
        subject = f"Transport Pickup Due: {transport.name}"
        message = f"""
        <b>Transport Schedule:</b> {transport.name}<br>
        <b>Shipping Booking:</b> {transport.shipping_booking}<br>
        <b>Vessel:</b> {transport.vessel_name}<br>
        <b>Pickup Date:</b> {transport.scheduled_pickup_date}<br>
        <b>Status:</b> {transport.transport_status}<br>
        <br>
        Ensure vehicle is assigned and driver notified.
        """
        frappe.sendmail(
            recipients=_resolve_user_email(transport.modified_by) or FALLBACK_NOTIFICATION_EMAIL,
            subject=subject,
            message=message,
            reference_doctype="Transport Schedule",
            reference_name=transport.name,
        )


def _console_delivery_urgency_section() -> str:
    """HTML snippet summarising overdue / due-today console work across hubs."""
    from apc_operations.services.daily_work_summary_service import build_daily_work_summary

    all_summary = build_daily_work_summary()
    lines = []
    for hub, label in (
        ("shipping", "Shipping"),
        ("transportation", "Transportation"),
        ("security", "Security"),
        ("qc", "QC"),
    ):
        totals = (all_summary.get(hub) or {}).get("totals") or {}
        if not totals.get("total"):
            continue
        lines.append(
            f"<li><b>{label}</b>: {totals.get('overdue', 0)} overdue, "
            f"{totals.get('today', 0)} due today, {totals.get('this_week', 0)} this week</li>"
        )
    if not lines:
        return ""
    return f"<h3>Console Delivery Deadlines:</h3><ul>{''.join(lines)}</ul>"


def get_daily_summary():
    return {
        "pending_cros": frappe.db.count("Shipping Booking", {
            "cro_status": "Pending",
            "docstatus": 1
        }),
        "upcoming_cutoffs": frappe.db.count("Shipping Booking", {
            "cutoff_date": ["<=", add_days(today(), 7)],
            "docstatus": 1
        }),
        "pending_pullouts": frappe.db.count("Shipping Booking", {
            "pull_out_date": ["<=", add_days(today(), 3)],
            "transport_status": ["in", ["Pending", "Scheduled"]],
            "docstatus": 1
        }),
        "pending_transport": frappe.db.count("Transport Schedule", {
            "transport_status": ["in", ["Pending Assignment", "Scheduled", "Vehicle Assigned", "Driver Assigned", "Dispatched", "Picked Up", "Gate In", "In Transit"]]
        }),
        "open_gate_passes": frappe.db.count("Gate Pass", {
            "status": ["in", ["Draft", "Submitted"]]
        }),
        "dg_pending": frappe.db.count("Shipping Booking", {
            "is_dangerous_goods": 1,
            "booking_status": ["!=", "Confirmed"],
            "docstatus": 1
        }),
    }


def get_todays_actions_data():
    today_str = today()
    tomorrow = add_days(today_str, 1)
    return {
        "total_actions": (
            frappe.db.count("Shipping Booking", {"cro_status": "Pending", "docstatus": 1}) +
            frappe.db.count("Shipping Booking", {"pull_out_date": today_str, "docstatus": 1}) +
            frappe.db.count("Shipping Booking", {"cutoff_date": tomorrow, "docstatus": 1}) +
            frappe.db.count("Transport Schedule", {"transport_status": "Scheduled", "scheduled_pickup_date": today_str})
        ),
        "cros_today": frappe.db.count("Shipping Booking", {"cro_status": "Pending", "docstatus": 1}),
        "pullouts_today": frappe.db.count("Shipping Booking", {"pull_out_date": today_str, "docstatus": 1}),
        "cutoffs_tomorrow": frappe.db.count("Shipping Booking", {"cutoff_date": tomorrow, "docstatus": 1}),
        "transport_pending": frappe.db.count("Transport Schedule", {"transport_status": "Scheduled", "scheduled_pickup_date": today_str}),
    }


def get_overdue_items():
    return {
        "total": (
            frappe.db.count("Shipping Booking", {"cro_status": "Pending", "creation": ["<=", add_days(today(), -1)], "docstatus": 1}) +
            frappe.db.count("Transport Schedule", {"transport_status": ["in", ["Pending Assignment", "Scheduled", "Vehicle Assigned", "Driver Assigned"]], "scheduled_pickup_date": ["<", today()]}) +
            frappe.db.count("Shipping Booking", {"cutoff_date": add_days(today(), 1), "docstatus": 1})
        ),
        "overdue_cros": frappe.db.count("Shipping Booking", {"cro_status": "Pending", "creation": ["<=", add_days(today(), -1)], "docstatus": 1}),
        "overdue_transport": frappe.db.count("Transport Schedule", {"transport_status": ["in", ["Pending Assignment", "Scheduled", "Vehicle Assigned", "Driver Assigned"]], "scheduled_pickup_date": ["<", today()]}),
        "tomorrow_cutoffs": frappe.db.count("Shipping Booking", {"cutoff_date": add_days(today(), 1), "docstatus": 1}),
    }


def get_unbooked_transport_job_orders(limit=20, unbooked_for_hours=None):
    """Job Orders where APC transport is required but no Transport Schedule exists yet."""
    filters = {
        "transport_required": 1,
        "transport_status": ["in", ["Pending Booking", "Pending Review"]],
        "transport_schedule": ["is", "not set"],
        "booking_requirement": ["in", ["Transport Booking", "Transport and Ship Booking"]],
        "status": ["not in", ["Completed", "Cancelled"]],
    }
    if unbooked_for_hours:
        from frappe.utils import add_to_date, now

        filters["modified"] = ["<=", add_to_date(now(), hours=-int(unbooked_for_hours))]

    return frappe.get_all(
        "Job Order",
        filters=filters,
        fields=[
            "name",
            "job_order_number",
            "date",
            "customer",
            "customer_name",
            "terms_of_delivery",
            "modified",
            "creation",
        ],
        order_by="date asc, modified asc",
        limit=limit,
    )


def check_unbooked_transport_over_24h():
    """Notify transportation team when required transport is still unbooked after 24 hours."""
    job_orders = get_unbooked_transport_job_orders(limit=50, unbooked_for_hours=24)
    if job_orders:
        notify_transportation_team_about_unbooked(job_orders)


def notify_transportation_team_about_unbooked(job_orders):
    """Email Transportation User/Manager about Job Orders awaiting transport booking."""
    transportation_users = _role_user_emails(["Transportation Manager", "Transportation User"])

    lines = ""
    for row in job_orders:
        ref = row.get("job_order_number") or row.get("name")
        lines += f"""
        <li>
            <b>{ref}</b> |
            Delivery: {row.get('date') or 'N/A'} |
            Customer: {row.get('customer_name') or row.get('customer') or 'N/A'} |
            Incoterm: {row.get('terms_of_delivery') or 'N/A'} |
            Waiting since: {frappe.utils.format_datetime(row.get('modified') or row.get('creation'))}
        </li>"""

    subject = f"URGENT: {len(job_orders)} Job Order(s) Unbooked for 24+ Hours"
    message = f"""
    <h3>Transport Booking Overdue</h3>
    <p>The following job orders require APC transport but have <b>no Transport Schedule</b>
    for more than <b>24 hours</b>:</p>
    <ul>{lines}</ul>
    <p>Please create transport schedules in the Transportation Console.</p>
    <br>
    <a href="{frappe.utils.get_url()}/app/transportation-console">Open Transportation Console</a>
    """

    for user in transportation_users:
        frappe.sendmail(
            recipients=user,
            subject=subject,
            message=message,
            reference_doctype="Job Order",
            reference_name=job_orders[0].name if job_orders else "",
        )


def check_unassigned_transport_reminder():
    """Check for transport schedules unassigned for more than 48 hours"""
    from frappe.utils import add_to_date

    cutoff_datetime = add_to_date(frappe.utils.now(), hours=-48)

    unassigned_transports = frappe.db.sql("""
        SELECT
            name,
            shipping_booking,
            vessel_name,
            scheduled_pickup_date,
            creation,
            modified_by
        FROM `tabTransport Schedule`
        WHERE transport_status IN ('Draft', 'Pending Assignment')
        AND creation <= %s
    """, (cutoff_datetime,), as_dict=True)

    if unassigned_transports:
        notify_transportation_team_about_unassigned(unassigned_transports)


def notify_transportation_team_about_unassigned(transports):
    """Notify transportation team about unassigned transport requests"""
    transportation_users = _role_user_emails(["Transportation Manager", "Transportation User"])

    transport_list = ""
    for transport in transports:
        transport_list += f"""
        <li>
            <b>{transport.name}</b> -
            Vessel: {transport.vessel_name or 'N/A'},
            Pickup: {transport.scheduled_pickup_date or 'Not Scheduled'},
            Created: {frappe.utils.format_datetime(transport.creation)}
        </li>"""

    subject = f"URGENT: {len(transports)} Transport Request(s) Unassigned for 48+ Hours"
    message = f"""
    <h3>Transport Assignment Overdue</h3>
    <p>The following transport requests have been pending assignment for more than 48 hours:</p>
    <ul>{transport_list}</ul>
    <p>Please assign vehicles and drivers immediately to avoid delays.</p>
    <br>
    <a href="{frappe.utils.get_url()}/app/transport-schedule?transport_status=Draft+Pending+Assignment">View Unassigned Transports</a>
    """

    for user in transportation_users:
        frappe.sendmail(
            recipients=user,
            subject=subject,
            message=message,
            reference_doctype="Transport Schedule",
            reference_name=transports[0].name if transports else ""
        )


def check_transportation_daily_summary():
    """Send daily summary to transportation managers"""
    summary = {
        "pending_assignments": frappe.db.count("Transport Schedule", {"transport_status": ["in", ["Draft", "Pending Assignment"]]}),
        "scheduled_today": frappe.db.count("Transport Schedule", {
            "scheduled_pickup_date": today(),
            "transport_status": ["not in", ["Completed", "Cancelled"]]
        }),
        "in_transit": frappe.db.count("Transport Schedule", {"transport_status": ["in", ["Dispatched", "Picked Up", "Gate In", "In Transit"]]}),
        "driver_pending": frappe.db.count("Transport Schedule", {"transport_status": "Vehicle Assigned"}),
        "payables_pending": frappe.db.count("Transport Schedule", {"payables_status": "Pending Payables"}),
    }

    transportation_managers = _role_user_emails("Transportation Manager")

    subject = f"Daily Transportation Summary - {today()}"
    message = f"""
    <h2>Transportation Operations Daily Summary - {today()}</h2>

    <h3>Key Metrics:</h3>
    <ul>
        <li><b>{summary['pending_assignments']}</b> Pending Assignments</li>
        <li><b>{summary['scheduled_today']}</b> Pickups Scheduled Today</li>
        <li><b>{summary['in_transit']}</b> Shipments In Transit</li>
        <li><b>{summary['driver_pending']}</b> Driver Assignment Pending</li>
        <li><b>{summary['payables_pending']}</b> Payables Pending</li>
    </ul>
    {_console_delivery_urgency_section()}

    <p><a href="{frappe.utils.get_url()}/app/transportation">Open Transportation Workspace</a></p>
    """

    for user in transportation_managers:
        frappe.sendmail(
            recipients=user,
            subject=subject,
            message=message
        )
