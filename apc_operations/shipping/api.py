# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import today, add_days, getdate
from frappe import _


# ──────────────────────────────────────────────────────────────────────────────
# Shipping Dashboard API  (works against Shipping Booking doctype)
# ──────────────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_job_order_delete_preview(job_order: str):
	"""List operational documents that would be deleted with this Job Order."""
	from apc_operations.shipping.services.job_order_delete_service import (
		get_job_order_delete_preview as _preview,
	)

	return _preview(job_order)


@frappe.whitelist()
def sync_job_order_number_to_linked_docs(job_order: str):
	"""Push the current Job Order number into linked operational documents."""
	from apc_operations.shipping.services.job_order_sync_service import (
		sync_job_order_number_to_linked,
	)

	if not job_order or not frappe.db.exists("Job Order", job_order):
		frappe.throw(_("Job Order {0} does not exist.").format(job_order))

	updated = sync_job_order_number_to_linked(job_order)
	return {
		"job_order": job_order,
		"job_order_number": frappe.db.get_value("Job Order", job_order, "job_order_number"),
		"updated": updated,
	}


@frappe.whitelist()
def delete_job_order_with_linked(job_order: str):
	"""Delete Job Order and cascade-delete linked operational documents."""
	from apc_operations.shipping.services.job_order_delete_service import (
		delete_job_order_with_linked as _delete,
	)

	return _delete(job_order)


@frappe.whitelist()
def get_job_dashboard_data():
    """Return KPIs, job order list, and recent activity for the Job Order Dashboard."""
    kpis = {
        "total": frappe.db.count("Job Order"),
        "open": frappe.db.count("Job Order", {"status": "Confirmed"}),
        "in_progress": frappe.db.count("Job Order", {"status": "In Progress"}),
        "pending_security": frappe.db.count("Job Order", {
            "transport_requirement_status": ["in", [
                "Pending Review", "Pending Shipping Booking", "Pending Transport Request",
            ]],
        }),
        "completed": frappe.db.count("Job Order", {"status": "Completed"}),
        "pending_approvals": frappe.db.count("Job Order", {"status": "Draft"}),
    }

    job_orders = frappe.get_all(
        "Job Order",
        fields=[
            "name", "job_order_number", "customer", "customer_name", "mode_of_transport",
            "date", "status", "transport_requirement_status", "pi_number", "owner",
            "terms_of_delivery", "booking_requirement", "transport_status", "shipping_status",
            "transport_schedule", "shipping_booking", "commercial_movement",
        ],
        order_by="date desc, modified desc",
        limit=50,
    )

    # Attach the first linked Transport Schedule per Job Order
    if job_orders:
        jo_names = [r.name for r in job_orders]
        transport_schedules = frappe.get_all(
            "Transport Schedule",
            filters={"job_order": ["in", jo_names]},
            fields=["job_order", "name", "outward_type"],
        )
        ts_map = {}
        for ts in transport_schedules:
            if ts.job_order not in ts_map:
                ts_map[ts.job_order] = ts

        for jo in job_orders:
            ts = ts_map.get(jo.name)
            jo["transport_schedule"] = ts.name if ts else None
            jo["outward_type"]       = ts.outward_type if ts else None

    recent_activity = frappe.get_all(
        "Job Order",
        fields=["name", "status", "modified", "modified_by", "customer_name",
                "transport_requirement_status"],
        order_by="modified desc",
        limit=8,
    )

    return {
        "kpis":            kpis,
        "job_orders":      job_orders,
        "recent_activity": recent_activity,
    }


@frappe.whitelist()
def get_shipping_dashboard_data():
    """Return all data needed by the Shipping Dashboard page."""
    today_str   = today()
    tomorrow    = add_days(today_str, 1)
    in_3_days   = add_days(today_str, 3)
    in_7_days   = add_days(today_str, 7)

    # ── KPIs ────────────────────────────────────────────────────────────
    # NOTE: ["in", ["", None]] is broken in MariaDB because `field IN (NULL)`
    # never matches NULL. Use ["is", "not set"] which Frappe expands to
    # `IFNULL(field, '') = ''` and catches both NULL and empty string.
    kpi = {
        "to_book_vessel": frappe.db.count("Shipping Booking", {
            "vessel_name": ["is", "not set"],
        }),
        "dg_to_confirm": frappe.db.count("Shipping Booking", {
            "is_dangerous_goods": 1,
            "dg_class": ["is", "not set"],
        }),
        "si_to_create": frappe.db.count("Shipping Booking", {
            "cro_status": ["in", ["Generated", "Issued"]],
            "booking_status": ["!=", "Confirmed"],
        }),
        "ed_due": frappe.db.count("Shipping Booking", {
            "cutoff_date": today_str,
            "export_declaration": ["is", "not set"],
        }),
        "pull_out_today": frappe.db.count("Shipping Booking", {
            "pull_out_date": today_str,
        }),
    }

    # ── Pipeline stages ─────────────────────────────────────────────────
    pipeline = {
        "freight_containers": frappe.db.count("Shipping Booking"),
        "dg_ndg": frappe.db.count("Shipping Booking", {
            "is_dangerous_goods": 1,
            "dg_class": ["is", "not set"],
        }),
        "thc_tluc_ed": frappe.db.count("Shipping Booking", {
            "thc": ["is", "not set"],
            "booking_status": ["not in", ["Confirmed", "Completed"]],
        }),
        "si": frappe.db.count("Shipping Booking", {
            "cro_status": ["in", ["Generated", "Issued"]],
            "booking_status": ["!=", "Confirmed"],
        }),
        "cro_generated": frappe.db.count("Shipping Booking", {
            "cro_status": ["in", ["Generated", "Issued"]],
        }),
    }

    # ── Upcoming milestones ──────────────────────────────────────────────
    upcoming_milestones = {
        "ed_tomorrow": frappe.db.count("Shipping Booking", {
            "cutoff_date": tomorrow,
        }),
        "pull_out_3days": frappe.db.count("Shipping Booking", {
            "pull_out_date": ["<=", in_3_days],
            "pull_out_date": [">=", today_str],
        }),
        "etd_7days": frappe.db.count("Shipping Booking", {
            "vessel_date": ["<=", in_7_days],
            "vessel_date": [">=", today_str],
        }),
    }

    # ── Recent CROs (bookings with a CRO number) ─────────────────────────
    recent_cros = frappe.db.get_all(
        "Shipping Booking",
        filters=[["cro_number", "!=", ""]],
        fields=[
            "name", "cro_number", "vessel_name", "vessel_date",
            "total_freight_charges", "cro_status",
        ],
        order_by="cro_date desc",
        limit=10,
    )

    # ── Recent Freight Containers (with linked Job Order) ────────────────
    recent_job_orders = frappe.db.get_all(
        "Shipping Booking",
        fields=[
            "name", "job_order", "job_order_number", "shipping_line", "port_of_loading",
            "port_of_discharge", "vessel_name", "booking_status",
            "cro_status", "pull_out_date",
        ],
        order_by="modified desc",
        limit=10,
    )
    _attach_job_order_numbers(recent_job_orders)

    return {
        "kpi": kpi,
        "pipeline": pipeline,
        "upcoming_milestones": upcoming_milestones,
        "recent_cros": recent_cros,
        "recent_job_orders": recent_job_orders,
        "focus_items": [],   # built client-side from kpi counts
    }


@frappe.whitelist()
def get_transportation_dashboard_data():
    """Return data for the custom Transportation workspace dashboard."""
    today_str = today()

    statuses_in_transit = ["Dispatched", "Picked Up", "Gate In", "In Transit"]
    scheduled_statuses = ["Scheduled", "Vehicle Assigned", "Driver Assigned"]
    tankers_count = frappe.db.sql(
        """
        SELECT COUNT(name)
        FROM `tabTransport Schedule`
        WHERE transport_type = 'Outward'
          AND IFNULL(transport_status, '') != 'Cancelled'
          AND (
                outward_type = 'Tanker Delivery'
                OR vehicle_type = 'Tanker'
              )
        """
    )[0][0]
    trailers_count = frappe.db.sql(
        """
        SELECT COUNT(name)
        FROM `tabTransport Schedule`
        WHERE transport_type = 'Outward'
          AND IFNULL(transport_status, '') != 'Cancelled'
          AND (
                outward_type = 'Trailer Delivery'
                OR vehicle_type IN ('Trailer', 'Container Trailer')
              )
        """
    )[0][0]

    kpis = {
        "inward_pending": frappe.db.count("Transport Schedule", {
            "transport_type": "Inward",
            "transport_status": ["in", ["Draft", "Pending Assignment", "Scheduled"]],
        }),
        "export_containers": frappe.db.count("Transport Schedule", {
            "transport_type": "Outward",
            "outward_type": "Export Container",
            "transport_status": ["!=", "Cancelled"],
        }),
        "tankers": tankers_count,
        "trailers": trailers_count,
        "dispatch_today": frappe.db.count("Transport Schedule", {
            "scheduled_pickup_date": today_str,
            "transport_status": ["in", scheduled_statuses],
        }),
        "completed_today": frappe.db.count("Transport Schedule", {
            "actual_delivery_date": today_str,
            "transport_status": ["in", ["Delivered", "Completed"]],
        }),
        "driver_pending": frappe.db.count("Transport Schedule", {"transport_status": "Vehicle Assigned"}),
        "vehicle_pending": frappe.db.count("Transport Schedule", {"transport_status": "Pending Assignment"}),
        "in_transit": frappe.db.count("Transport Schedule", {"transport_status": ["in", statuses_in_transit]}),
        "payables_pending": frappe.db.count("Transport PO Request", {"payables_status": "Pending Payables"}),
        "security_pending": frappe.db.count("Security Draft Delivery Note", {"security_status": "Pending Review"}),
        "gate_out_pending": frappe.db.count("Security Draft Delivery Note", {"gate_out_status": "Pending Security Review"}),
    }

    today_actions = [
        {
            "title": f"{kpis['inward_pending']} inward pickups need vehicle booking",
            "priority": "High" if kpis["inward_pending"] else "Normal",
            "action": "Book Vehicle",
            "route": ["List", "Transport Schedule", {"transport_type": "Inward", "transport_status": "Pending Assignment"}],
            "icon": "truck",
            "tone": "orange",
        },
        {
            "title": f"{kpis['export_containers']} export containers pending dispatch",
            "priority": "High" if kpis["export_containers"] else "Normal",
            "action": "View & Dispatch",
            "route": ["List", "Transport Schedule", {"outward_type": "Export Container"}],
            "icon": "ship",
            "tone": "blue",
        },
        {
            "title": f"{kpis['tankers']} tanker deliveries scheduled today",
            "priority": "Medium",
            "action": "View Schedule",
            "route": ["List", "Transport Schedule", {"outward_type": "Tanker Delivery", "scheduled_pickup_date": today_str}],
            "icon": "droplet",
            "tone": "green",
        },
        {
            "title": f"{kpis['driver_pending']} driver assignments pending",
            "priority": "Medium" if kpis["driver_pending"] else "Normal",
            "action": "Assign Driver",
            "route": ["List", "Transport Schedule", {"transport_status": "Vehicle Assigned"}],
            "icon": "users",
            "tone": "purple",
        },
        {
            "title": f"{frappe.db.count('Transport Schedule', {'gate_cutoff': today_str})} gate cutoffs today",
            "priority": "High",
            "action": "View Deadlines",
            "route": ["List", "Transport Schedule", {"gate_cutoff": today_str}],
            "icon": "clock",
            "tone": "red",
        },
    ]

    inward = frappe.get_all(
        "Transport Schedule",
        filters={"transport_type": "Inward", "transport_status": ["!=", "Cancelled"]},
        fields=[
            "name", "supplier", "material_description", "vehicle_type", "assigned_driver",
            "scheduled_delivery_date", "transport_status",
        ],
        order_by="scheduled_pickup_date asc",
        limit=500,
    )

    export = frappe.get_all(
        "Transport Schedule",
        filters={"transport_type": "Outward", "outward_type": "Export Container", "transport_status": ["!=", "Cancelled"]},
        fields=[
            "name", "job_order", "shipping_booking", "cro_number", "container_type", "port_of_loading",
            "port_of_discharge", "material_description", "container_count", "scheduled_pickup_date",
            "gate_cutoff", "pull_out_date", "gate_in_date", "assigned_vehicle", "assigned_driver",
            "transport_status",
        ],
        order_by="gate_cutoff asc",
        limit=500,
    )

    local = frappe.db.sql(
        """
        SELECT
            name,
            job_order,
            customer,
            delivery_location,
            outward_type,
            material_description,
            assigned_vehicle,
            assigned_driver,
            scheduled_pickup_date,
            pickup_time,
            transport_status
        FROM `tabTransport Schedule`
        WHERE transport_type = 'Outward'
          AND outward_type IN ('Local Delivery', 'Tanker Delivery', 'Trailer Delivery')
        ORDER BY
            CASE WHEN transport_status = 'Completed' THEN 1 ELSE 0 END ASC,
            scheduled_pickup_date ASC
        LIMIT 500
        """,
        as_dict=True,
    )

    _attach_job_order_numbers(export)
    _attach_job_order_numbers(local)
    _attach_driver_names(inward)
    _attach_driver_names(export)
    _attach_driver_names(local)
    _attach_shipping_booking_fields(export)

    schedule_deadlines = frappe.get_all(
        "Transport Schedule",
        filters={"gate_cutoff": [">=", today_str], "transport_status": ["not in", ["Completed", "Cancelled"]]},
        fields=["name", "job_order", "shipping_booking", "gate_cutoff", "port_of_discharge"],
        order_by="gate_cutoff asc",
        limit=5,
    )
    _attach_job_order_numbers(schedule_deadlines)
    booking_deadlines = _get_pending_transport_booking_deadlines(limit=5)

    deadlines = schedule_deadlines + booking_deadlines
    deadlines.sort(
        key=lambda row: getdate(row.get("gate_cutoff")) if row.get("gate_cutoff") else getdate("9999-12-31")
    )
    deadlines = deadlines[:5]

    alerts = []
    transport_booking_not_booked = _count_pending_transport_bookings("all")
    transport_booking_due_today = _count_pending_transport_bookings(today_str, "today")
    transport_booking_overdue = _count_pending_transport_bookings(today_str, "overdue")
    if transport_booking_not_booked:
        refs = _get_pending_transport_booking_refs(bucket="all", limit=3)
        alerts.append(
            {
                "message": f"{transport_booking_not_booked} job orders are not booked for transport yet",
                "job_order_numbers": refs,
                "age": "open",
            }
        )
    if transport_booking_overdue:
        refs = _get_pending_transport_booking_refs(today_str=today_str, bucket="overdue", limit=3)
        alerts.append(
            {
                "message": f"{transport_booking_overdue} job orders have overdue transport booking",
                "job_order_numbers": refs,
                "age": "urgent",
            }
        )
    if transport_booking_due_today:
        refs = _get_pending_transport_booking_refs(today_str=today_str, bucket="today", limit=3)
        alerts.append(
            {
                "message": f"{transport_booking_due_today} job orders need transport booking today",
                "job_order_numbers": refs,
                "age": "today",
            }
        )
    if kpis["vehicle_pending"]:
        alerts.append({"message": f"{kpis['vehicle_pending']} transport requests without vehicle booking", "age": "now"})
    if kpis["driver_pending"]:
        alerts.append({"message": f"{kpis['driver_pending']} vehicles pending driver assignment", "age": "now"})
    if kpis["payables_pending"]:
        alerts.append({"message": f"{kpis['payables_pending']} transport PO requests pending Payables", "age": "today"})
    if kpis["security_pending"]:
        alerts.append({"message": f"{kpis['security_pending']} draft delivery notes pending Security review", "age": "today"})

    status_summary = [
        {"label": "Pending Assignment", "count": frappe.db.count("Transport Schedule", {"transport_status": "Pending Assignment"})},
        {"label": "Scheduled", "count": frappe.db.count("Transport Schedule", {"transport_status": "Scheduled"})},
        {"label": "Dispatched", "count": frappe.db.count("Transport Schedule", {"transport_status": "Dispatched"})},
        {"label": "In Transit", "count": kpis["in_transit"]},
        {"label": "Delivered", "count": frappe.db.count("Transport Schedule", {"transport_status": "Delivered"})},
    ]

    return {
        "date": frappe.utils.formatdate(today_str),
        "today_actions": today_actions,
        "kpis": kpis,
        "inward": inward,
        "export": export,
        "local": local,
        "deadlines": deadlines,
        "alerts": alerts,
        "status_summary": status_summary,
    }


def _attach_job_order_numbers(rows):
    job_orders = [row.get("job_order") for row in rows if row.get("job_order")]
    if not job_orders:
        return

    job_order_numbers = frappe._dict(
        frappe.get_all(
            "Job Order",
            filters={"name": ["in", job_orders]},
            fields=["name", "job_order_number"],
            as_list=True,
        )
    )

    for row in rows:
        job_order = row.get("job_order")
        row["job_order_number"] = job_order_numbers.get(job_order) or job_order


def _attach_driver_names(rows):
    """Resolve linked Driver IDs to display names for dashboard rows."""
    driver_ids = [row.get("assigned_driver") for row in rows if row.get("assigned_driver")]
    if not driver_ids:
        return

    driver_rows = frappe.get_all(
        "Driver",
        filters={"name": ["in", list(set(driver_ids))]},
        fields=["name", "driver_name", "full_name"],
    )
    driver_map = {}
    for row in driver_rows:
        driver_map[row.name] = row.get("full_name") or row.get("driver_name") or row.name

    for row in rows:
        driver_id = row.get("assigned_driver")
        if not driver_id:
            continue
        row["assigned_driver_name"] = driver_map.get(driver_id) or driver_id


def _attach_shipping_booking_fields(rows):
    """Attach Shipping Booking deadlines for export dashboard rows."""
    booking_ids = [row.get("shipping_booking") for row in rows if row.get("shipping_booking")]
    if not booking_ids:
        return

    booking_map = {
        row["name"]: row
        for row in frappe.get_all(
            "Shipping Booking",
            filters={"name": ["in", list(set(booking_ids))]},
            fields=["name", "si_cutoff"],
        )
    }

    for row in rows:
        booking = booking_map.get(row.get("shipping_booking"))
        if not booking:
            continue
        row["si_cutoff"] = booking.get("si_cutoff")


def _pending_transport_booking_filters():
    return {
        "transport_required": 1,
        "transport_status": ["in", ["Pending Booking", "Pending Review"]],
        "transport_schedule": ["is", "not set"],
        "booking_requirement": ["in", ["Transport Booking", "Transport and Ship Booking"]],
        "status": ["not in", ["Completed", "Cancelled"]],
    }


def _get_pending_transport_booking_deadlines(limit=5):
    filters = _pending_transport_booking_filters()

    rows = frappe.get_all(
        "Job Order",
        filters=filters,
        fields=["name", "job_order_number", "date", "port_of_discharge", "terms_of_delivery"],
        order_by="date asc",
        limit=limit,
    )

    deadlines = []
    for row in rows:
        ref = row.get("job_order_number") or row.get("name")
        incoterm = row.get("terms_of_delivery") or "N/A"
        deadlines.append(
            {
                "name": row.get("name"),
                "job_order_number": ref,
                "shipping_booking": f"JO {ref} ({incoterm})",
                "gate_cutoff": row.get("date"),
                "port_of_discharge": row.get("port_of_discharge") or "Transport Booking Due",
            }
        )

    return deadlines


def _count_pending_transport_bookings(today_str=None, bucket="all"):
    filters = _pending_transport_booking_filters()
    if bucket == "all":
        return frappe.db.count("Job Order", filters)
    if bucket == "today":
        filters["date"] = today_str
    elif bucket == "overdue":
        filters["date"] = ["<", today_str]
    else:
        return 0
    return frappe.db.count("Job Order", filters)


def _get_pending_transport_booking_refs(today_str=None, bucket="all", limit=3):
    filters = _pending_transport_booking_filters()
    if bucket == "today":
        filters["date"] = today_str
    elif bucket == "overdue":
        filters["date"] = ["<", today_str]

    rows = frappe.get_all(
        "Job Order",
        filters=filters,
        fields=["name", "job_order_number"],
        order_by="date asc",
        limit=limit,
    )
    return [row.get("job_order_number") or row.get("name") for row in rows]


@frappe.whitelist()
def get_todays_actions():
    """Get action items for today - used by dashboard"""
    today_str = today()
    tomorrow = add_days(today_str, 1)
    three_days = add_days(today_str, 3)

    return {
        "cros_pending": frappe.db.count("Shipping Booking", {
            "cro_status": "Pending"
        }),
        "gate_passes_open": frappe.db.count("Gate Pass", {
            "status": ["in", ["Draft", "Open"]]
        }),
        "vessel_cutoffs_tomorrow": frappe.db.count("Shipping Booking", {
            "cutoff_date": tomorrow,
            "docstatus": 1
        }),
        "pull_outs_pending": frappe.db.count("Shipping Booking", {
            "pull_out_date": ["<=", three_days],
            "transport_status": ["in", ["Pending", "Scheduled"]],
            "docstatus": 1
        }),
        "transport_schedules_pending": frappe.db.count("Transport Schedule", {
            "transport_status": ["in", ["Pending Assignment", "Scheduled", "Vehicle Assigned", "Driver Assigned"]]
        }),
        "dg_approval_pending": frappe.db.count("Shipping Booking", {
            "is_dangerous_goods": 1,
            "booking_status": ["!=", "Confirmed"],
            "docstatus": 1
        }),
    }


@frappe.whitelist()
def get_dashboard_data():
    """Get comprehensive dashboard data"""
    return {
        "counts": get_todays_actions(),
        "upcoming_vessels": get_upcoming_vessels(),
        "pending_cros": get_pending_cros_list(),
        "pending_transport": get_pending_transport_list(),
    }


def get_upcoming_vessels():
    """Get upcoming vessels for dashboard"""
    return frappe.db.sql("""
        SELECT
            name,
            vessel_name,
            vessel_date,
            cutoff_date,
            shipping_line,
            container_count,
            port_of_loading,
            DATEDIFF(cutoff_date, CURDATE()) as days_until_cutoff
        FROM `tabShipping Booking`
        WHERE docstatus = 1
        AND cutoff_date >= CURDATE()
        ORDER BY cutoff_date ASC
        LIMIT 10
    """, as_dict=True)


def get_pending_cros_list():
    """Get pending CROs list from Shipping Booking."""
    return frappe.db.sql("""
        SELECT
            name,
            cro_number,
            vessel_name,
            cutoff_date,
            cro_status,
            DATEDIFF(cutoff_date, CURDATE()) as days_remaining
        FROM `tabShipping Booking`
        WHERE cro_status IN ('Pending', 'Generated')
        ORDER BY cutoff_date ASC
        LIMIT 10
    """, as_dict=True)


def get_pending_transport_list():
    """Get pending transport list"""
    return frappe.db.sql("""
        SELECT
            name,
            shipping_booking,
            vessel_name,
            scheduled_pickup_date,
            transport_status,
            assigned_vehicle,
            assigned_driver,
            DATEDIFF(scheduled_pickup_date, CURDATE()) as days_until_pickup
        FROM `tabTransport Schedule`
        WHERE transport_status IN ('Pending Assignment', 'Scheduled', 'Vehicle Assigned', 'Driver Assigned', 'Dispatched', 'Picked Up', 'Gate In', 'In Transit')
        ORDER BY scheduled_pickup_date ASC
        LIMIT 10
    """, as_dict=True)


@frappe.whitelist()
def get_shipment_timeline(shipment_name):
    """Get complete timeline for a shipment"""
    timeline = []

    # Get shipping booking
    vessel = frappe.get_doc("Shipping Booking", shipment_name)

    timeline.append({
        "date": vessel.creation,
        "event": "Shipping Booking Created",
        "status": "Completed",
        "doctype": "Shipping Booking",
        "docname": vessel.name
    })

    if vessel.cro_number:
        timeline.append({
            "date": vessel.cro_date or vessel.modified,
            "event": f"CRO Generated: {vessel.cro_number}",
            "status": vessel.cro_status,
            "doctype": "Shipping Booking",
            "docname": vessel.name
        })

    # Get Transport
    transport = frappe.db.get_value(
        "Transport Schedule",
        {"shipping_booking": shipment_name},
        ["name", "creation", "scheduled_pickup_date", "actual_pickup_date", "transport_status"],
        as_dict=True
    )

    if transport:
        timeline.append({
            "date": transport.scheduled_pickup_date,
            "event": "Transport Scheduled",
            "status": "Scheduled",
            "doctype": "Transport Schedule",
            "docname": transport.name
        })

        if transport.actual_pickup_date:
            timeline.append({
                "date": transport.actual_pickup_date,
                "event": "Pickup Completed",
                "status": "Completed",
                "doctype": "Transport Schedule",
                "docname": transport.name
            })

    # Sort by date
    timeline.sort(key=lambda x: x["date"], reverse=True)

    return timeline


@frappe.whitelist()
def quick_create_vessel_booking(data):
    """Quick create shipping booking from dashboard."""
    doc = frappe.new_doc("Shipping Booking")
    doc.shipping_line = data.get("shipping_line")
    doc.container_type = data.get("container_type")
    doc.container_number = data.get("container_number")
    doc.container_count = data.get("container_count", 1)
    doc.port_of_loading = data.get("port_of_loading")
    doc.port_of_discharge = data.get("port_of_discharge")
    doc.cargo_description = data.get("cargo_description")
    doc.cargo_weight = data.get("cargo_weight")
    doc.is_dangerous_goods = data.get("is_dangerous_goods", 0)
    doc.vessel_name = data.get("vessel_name")
    doc.vessel_date = data.get("vessel_date")
    doc.cutoff_date = data.get("cutoff_date")
    doc.pull_out_date = data.get("pull_out_date")
    doc.freight_rate = data.get("freight_rate", 0)
    doc.currency = data.get("currency", "USD")
    doc.insert()

    return {"success": True, "name": doc.name}


@frappe.whitelist()
def bulk_generate_transport(cro_list):
    """Generate transport for multiple Shipping Bookings."""
    import json
    cros = json.loads(cro_list)

    results = []
    for booking_name in cros:
        try:
            booking = frappe.get_doc("Shipping Booking", booking_name)
            booking.generate_transportation()
            results.append({"shipping_booking": booking_name, "status": "success"})
        except Exception as e:
            results.append({"shipping_booking": booking_name, "status": "error", "message": str(e)})

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Security Dashboard API
# ──────────────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_security_dashboard_data():
    """Return all KPI counts and action lists needed by the Security workspace dashboard."""
    today_str = today()

    # ── KPI counts ───────────────────────────────────────────────────────────
    kpis = {
        "draft_dns_pending_review": frappe.db.count(
            "Security Draft Delivery Note",
            {"security_status": "Pending Review"}
        ),
        "vehicles_at_gate": frappe.db.count(
            "Security Inspection",
            [
                ["gate_in_time", "is", "set"],
                ["gate_out_time", "is", "not set"],
                ["security_status", "not in", ["Cancelled", "Completed", "Reported to Receivables"]],
            ]
        ),
        "pending_inspections": frappe.db.count(
            "Security Inspection",
            {"security_status": ["in", ["Draft", "Pending Checklist", "Checklist Completed"]], "docstatus": ["!=", 2]}
        ),
        "checklist_pending": frappe.db.count(
            "Security Inspection",
            {"security_status": "Pending Checklist", "docstatus": ["!=", 2]}
        ),
        "iso_checks_pending": frappe.db.count(
            "Security Inspection",
            [
                ["inspection_type", "in", ["ISO Tank", "Tanker"]],
                ["security_status", "not in", ["Cancelled", "Completed", "Reported to Receivables"]],
                ["docstatus", "!=", 2],
            ]
        ),
        "weightment_slips_pending": frappe.db.count(
            "Security Inspection",
            [
                ["weighment_slip", "is", "not set"],
                ["security_status", "in", ["Pending Checklist", "Checklist Completed", "Reported to QC"]],
                ["docstatus", "!=", 2],
            ]
        ),
        "qc_pending": frappe.db.count(
            "QC Report Request",
            {"qc_status": "Pending QC"}
        ),
        "qc_cleared": frappe.db.count(
            "Security Inspection",
            {"qc_status": "QC Cleared", "security_status": ["!=", "Cancelled"]}
        ),
        "qc_rejected": frappe.db.count(
            "Security Inspection",
            {"qc_status": "QC Rejected"}
        ),
        "loading_dns_created_today": frappe.db.count(
            "Loading Delivery Note",
            {"loading_date": today_str}
        ),
        "loading_dns_pending": frappe.db.count(
            "Security Inspection",
            {
                "security_status": "Checklist Completed",
                "loading_delivery_note": ["is", "not set"],
                "docstatus": ["!=", 2],
            }
        ),
        "pending_receivables": frappe.db.count(
            "Loading Delivery Note",
            {
                "receivables_status": "Pending Receivables",
                "delivery_note_status": ["in", ["QC Cleared", "Ready for Receivables"]]
            }
        ),
        "completed_today": frappe.db.count(
            "Security Inspection",
            {
                "security_status": ["in", ["Reported to Receivables", "Completed"]],
                "modified": [">=", today_str]
            }
        ),
    }

    # ── Today's actionable Draft DNs ─────────────────────────────────────────
    draft_dns = frappe.get_all(
        "Security Draft Delivery Note",
        filters={"security_status": "Pending Review"},
        fields=[
            "name", "transport_schedule", "job_order", "customer",
            "outward_type", "container_type", "container_count",
            "vehicle", "driver", "pickup_date", "security_status"
        ],
        order_by="pickup_date ASC",
        limit=10,
    )

    # ── Pending inspections (checklist not yet done) ─────────────────────────
    pending_inspections = frappe.get_all(
        "Security Inspection",
        filters={
            "security_status": ["in", ["Draft", "Pending Checklist", "Checklist Completed"]],
            "docstatus": ["!=", 2],
        },
        fields=[
            "name", "job_order", "customer_name", "inspection_type",
            "inspection_date", "security_status", "qc_status",
            "vehicle_number", "container_number"
        ],
        order_by="inspection_date ASC",
        limit=10,
    )

    # ── Pending QC requests ──────────────────────────────────────────────────
    pending_qc = frappe.get_all(
        "QC Report Request",
        filters={"qc_status": "Pending QC"},
        fields=[
            "name", "security_inspection", "job_order",
            "container_number", "vehicle_number", "requested_on"
        ],
        order_by="requested_on ASC",
        limit=10,
    )

    # ── Loading DNs ready for Receivables ────────────────────────────────────
    pending_receivables_list = frappe.get_all(
        "Loading Delivery Note",
        filters={
            "receivables_status": "Pending Receivables",
            "delivery_note_status": ["in", ["QC Cleared", "Ready for Receivables"]]
        },
        fields=[
            "name", "customer_name", "job_order", "container_number",
            "material_description", "quantity", "uom", "loading_date"
        ],
        order_by="loading_date ASC",
        limit=10,
    )

    # ── Today's completed dispatches ─────────────────────────────────────────
    completed_today = frappe.get_all(
        "Security Inspection",
        filters={
            "security_status": ["in", ["Reported to Receivables", "Completed"]],
            "modified": [">=", today_str]
        },
        fields=[
            "name", "job_order", "customer_name", "inspection_type",
            "container_number", "security_status", "loading_delivery_note"
        ],
        order_by="modified DESC",
        limit=10,
    )

    # ── Today's action items ─────────────────────────────────────────────────
    today_actions = []

    if kpis["draft_dns_pending_review"]:
        today_actions.append({
            "title": f"{kpis['draft_dns_pending_review']} Draft DNs awaiting security review",
            "priority": "High",
            "action": "Review Draft DNs",
            "route": ["List", "Security Draft Delivery Note", {"security_status": "Pending Review"}],
            "icon": "file-text",
            "tone": "red",
        })

    if kpis["checklist_pending"]:
        today_actions.append({
            "title": f"{kpis['checklist_pending']} inspections awaiting checklist completion",
            "priority": "High",
            "action": "Complete Checklist",
            "route": ["List", "Security Inspection", {"security_status": "Pending Checklist"}],
            "icon": "check-square",
            "tone": "orange",
        })

    if kpis["qc_pending"]:
        today_actions.append({
            "title": f"{kpis['qc_pending']} QC requests pending clearance",
            "priority": "Medium",
            "action": "View QC Requests",
            "route": ["List", "QC Report Request", {"qc_status": "Pending QC"}],
            "icon": "activity",
            "tone": "blue",
        })

    if kpis["pending_receivables"]:
        today_actions.append({
            "title": f"{kpis['pending_receivables']} Loading DNs ready to send to Receivables",
            "priority": "Medium",
            "action": "Send to Receivables",
            "route": ["List", "Loading Delivery Note", {"receivables_status": "Pending Receivables"}],
            "icon": "send",
            "tone": "green",
        })

    today_queue = _build_security_today_queue(
        draft_dns, pending_inspections, pending_qc, pending_receivables_list
    )

    return {
        "date": frappe.utils.formatdate(today_str),
        "kpis": kpis,
        "today_actions": today_actions,
        "draft_dns": draft_dns,
        "pending_inspections": pending_inspections,
        "pending_qc": pending_qc,
        "pending_receivables": pending_receivables_list,
        "completed_today": completed_today,
        "today_queue": today_queue,
    }


def _build_security_today_queue(draft_dns, pending_inspections, pending_qc, pending_receivables):
    """Build a combined Today's Queue list from all active security items."""
    queue = []

    for item in draft_dns:
        queue.append({
            "reference": item.get("name"),
            "doctype": "Security Draft Delivery Note",
            "type": "Draft Delivery Note",
            "status": "Draft Ready",
            "status_color": "blue",
            "deadline": str(item.get("pickup_date") or ""),
            "action": "Review",
            "route": f"/app/security-draft-delivery-note/{item.get('name')}",
        })

    status_map = {
        "Draft": ("Gate Inspection", "Waiting at Gate", "orange", "Start"),
        "Pending Checklist": ("Container Checklist", "Pending", "yellow", "Complete"),
        "Checklist Completed": ("Checklist Done", "Ready for QC", "green", "Report to QC"),
    }

    for item in pending_inspections:
        s = item.get("security_status", "Draft")
        item_type, status_label, color, action = status_map.get(
            s, ("Inspection", s, "gray", "View")
        )
        queue.append({
            "reference": item.get("job_order") or item.get("name"),
            "doctype": "Security Inspection",
            "inspection_name": item.get("name"),
            "type": item_type,
            "status": status_label,
            "status_color": color,
            "deadline": str(item.get("inspection_date") or ""),
            "action": action,
            "route": f"/app/security-inspection/{item.get('name')}",
        })

    for item in pending_qc:
        queue.append({
            "reference": item.get("name"),
            "doctype": "QC Report Request",
            "type": "QC Report",
            "status": "Pending QC",
            "status_color": "blue",
            "deadline": str(item.get("requested_on") or "")[:10],
            "action": "Clear",
            "route": f"/app/qc-report-request/{item.get('name')}",
        })

    for item in pending_receivables:
        queue.append({
            "reference": item.get("name"),
            "doctype": "Loading Delivery Note",
            "type": "Loading DN",
            "status": "Ready for Receivables",
            "status_color": "green",
            "deadline": str(item.get("loading_date") or ""),
            "action": "Notify",
            "route": f"/app/loading-delivery-note/{item.get('name')}",
        })

    queue.sort(key=lambda x: x.get("deadline") or "9999")
    return queue[:10]


# ──────────────────────────────────────────────────────────────────────────────
# Shipping Console — page-on-page redesign (DESIGN_CONCEPT.md Section 7)
#
# Endpoints below back the /app/shipping-console page. Filters and modal
# field lists follow the design doc exactly; status labels go through
# apc_operations.services.console_status so the four consoles stay in
# sync.
# ──────────────────────────────────────────────────────────────────────────────

from apc_operations.services import console_status as _console_status
from apc_operations.services.console_queue_service import (
    attach_delivery_due_fields,
    enrich_and_sort_console_queue,
)


def _booking_summary_fields():
    return [
        "name",
        "customer",
        "customer_name",
        "job_order",
        "job_order_number",
        "incoterm",
        "shipping_line",
        "container_type",
        "container_number",
        "container_count",
        "port_of_loading",
        "port_of_discharge",
        "cargo_description",
        "vessel_name",
        "vessel_date",
        "vessel_status",
        "cro_number",
        "cro_date",
        "cro_status",
        "cutoff_date",
        "pull_out_date",
        "si_cutoff",
        "gate_cutoff",
        "vgm_cutoff",
        "thc",
        "tluc",
        "export_declaration",
        "booking_status",
        "transport_status",
        "modified",
    ]


def _booking_card(sb: dict) -> dict:
    from apc_operations.shipping.services.job_order_sync_service import (
        get_live_job_order_number,
    )

    jo = sb.get("job_order")
    jo_number = get_live_job_order_number(jo) if jo else None
    jo_number = jo_number or sb.get("job_order_number") or jo

    card = {
        "name": sb.get("name"),
        "shipping_booking": sb.get("name"),
        "job_order": jo,
        "job_order_number": jo_number,
        "customer": sb.get("customer"),
        "customer_name": sb.get("customer_name"),
        "shipping_line": sb.get("shipping_line"),
        "pol": sb.get("port_of_loading"),
        "pod": sb.get("port_of_discharge"),
        "vessel": sb.get("vessel_name"),
        "vessel_status": _console_status.vessel_status_label(sb.get("vessel_status")),
        "vessel_status_tone": _console_status.vessel_status_tone(sb.get("vessel_status")),
        "cro_number": sb.get("cro_number"),
        "cro_status": sb.get("cro_status") or "Pending",
        "booking_status": sb.get("booking_status") or "Draft",
        "container_count": sb.get("container_count"),
        "container_type": sb.get("container_type"),
        "etd": sb.get("vessel_date"),
        "si_cutoff": sb.get("si_cutoff"),
        "gate_cutoff": sb.get("gate_cutoff"),
        "pull_out_date": sb.get("pull_out_date"),
        "product_summary": sb.get("product_summary"),
        "packaging_summary": sb.get("packaging_summary"),
    }
    return attach_delivery_due_fields(card)


def _sorted_booking_cards(rows: list[dict]) -> list[dict]:
    from apc_operations.shipping.services.job_order_sync_service import (
        attach_job_order_product_summary,
    )

    attach_job_order_product_summary(rows)
    return enrich_and_sort_console_queue([_booking_card(r) for r in rows])


@frappe.whitelist()
def get_pending_bookings():
    """Shipping Bookings where vessel_name is not set (Section 7.3)."""
    rows = frappe.get_all(
        "Shipping Booking",
        filters={"vessel_name": ["is", "not set"], "docstatus": ["!=", 2]},
        or_filters=None,
        fields=_booking_summary_fields(),
        order_by="modified desc",
        limit=200,
    )
    return _sorted_booking_cards(rows)


@frappe.whitelist()
def get_pending_booking_detail(name: str):
    if not name:
        frappe.throw(_("name is required"))

    # The console editor exposes every editable Shipping Booking field, so the
    # detail payload has to carry the full set — not just the list-card subset.
    detail_fields = list(
        set(_booking_summary_fields())
        | {
            "cargo_weight",
            "freight_rate",
            "currency",
            "notes",
            "is_dangerous_goods",
            "dg_class",
            "un_number",
            "gate_in_date",
        }
    )

    sb = frappe.db.get_value("Shipping Booking", name, detail_fields, as_dict=True)
    if not sb:
        frappe.throw(_("Shipping Booking {0} not found").format(name))

    base = _booking_card(sb)
    # Expose every raw field by its original fieldname so the dialog can
    # pre-populate without inverting the pol/pod/etd/vessel rename map.
    for k, v in sb.items():
        base.setdefault(k, v)

    base["containers"] = frappe.get_all(
        "Shipping Booking Container",
        filters={"parent": name, "parenttype": "Shipping Booking"},
        fields=["container_number", "seal_number"],
        order_by="idx asc",
    )
    return base


@frappe.whitelist()
def get_pending_cros():
    """Bookings with vessel set but CRO not yet issued (Section 7.4)."""
    rows = frappe.get_all(
        "Shipping Booking",
        filters={
            "vessel_name": ["is", "set"],
            "cro_status": ["not in", ["Generated", "Issued", "Completed"]],
            "docstatus": ["!=", 2],
        },
        fields=_booking_summary_fields(),
        order_by="modified desc",
        limit=200,
    )
    return _sorted_booking_cards(rows)


@frappe.whitelist()
def get_pending_cro_detail(name: str):
    return get_pending_booking_detail(name)


@frappe.whitelist()
def get_open_cro_schedule():
    """CRO Schedule items (Section 7.5) — bookings with CRO Generated/Issued."""
    rows = frappe.get_all(
        "Shipping Booking",
        filters={
            "cro_status": ["in", ["Generated", "Issued", "Completed"]],
            "docstatus": ["!=", 2],
        },
        fields=_booking_summary_fields(),
        order_by="vessel_date asc",
        limit=200,
    )
    return _sorted_booking_cards(rows)


@frappe.whitelist()
def get_open_cro_schedule_detail(name: str):
    return get_pending_booking_detail(name)


@frappe.whitelist()
def generate_delivery_order_for_export(job_order: str):
    """Create a Delivery Order for an export Job Order (Section 7.7)."""
    from apc_operations.shipping.services.delivery_order_generation_service import (
        generate_delivery_order_for_job_order,
    )

    return generate_delivery_order_for_job_order(job_order, movement="Outward")


@frappe.whitelist()
def generate_followup_delivery_order_for_export(
    job_order: str, transport_schedule: str | None = None, quantity: float | None = None
):
    """Create a follow-up Delivery Order for remaining partial-dispatch quantity."""
    from apc_operations.shipping.services.delivery_order_generation_service import (
        generate_followup_delivery_order_for_job_order,
    )

    return generate_followup_delivery_order_for_job_order(
        job_order, transport_schedule=transport_schedule, quantity=quantity
    )


@frappe.whitelist()
def generate_delivery_order_for_import(job_order: str):
    """Create a Delivery Order for an import Job Order (inward Path B)."""
    from apc_operations.shipping.services.delivery_order_generation_service import (
        generate_delivery_order_for_job_order,
    )

    return generate_delivery_order_for_job_order(
        job_order, movement="Import", auto_issue_to_security=True
    )


@frappe.whitelist()
def link_import_to_export_job_order(import_job_order: str, export_job_order: str):
    from apc_operations.shipping.services.import_handoff_service import (
        link_import_to_export_job_order as _link,
    )

    return _link(import_job_order, export_job_order)


@frappe.whitelist()
def create_export_job_order_from_import(
    import_job_order: str, customer: str | None = None, terms_of_delivery: str | None = None
):
    from apc_operations.shipping.services.import_handoff_service import (
        create_export_job_order_from_import as _create,
    )

    return _create(import_job_order, customer=customer, terms_of_delivery=terms_of_delivery)


def _resolve_port_label(value):
    if not value:
        return None
    port_name = frappe.db.get_value("Port", value, "port_name")
    return port_name or value


def _copy_job_order_items_to_delivery_order(job_order: str, no_of_containers=None):
    from apc_operations.shipping.services.delivery_order_sync_service import (
        job_order_items_for_delivery_order,
    )

    return job_order_items_for_delivery_order(job_order, no_of_containers=no_of_containers)
