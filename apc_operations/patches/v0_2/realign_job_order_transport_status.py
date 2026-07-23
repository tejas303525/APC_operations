"""Realign Job Order.transport_status with the linked Transport Schedule.

Before this patch, Job Order.create_or_link_transport_schedule and
Job Order.sync_booking_flags both force-set ``transport_status = "Scheduled"``
whenever a Transport Schedule was linked to a Job Order — regardless of the
TS's actual state. That meant TSs auto-created from the Shipping Booking
CRO-received flow (which correctly start at "Pending Assignment") were
hidden from the Transportation Console "Pending Transport Bookings" queue
because their parent JO was reported as already "Scheduled".

This patch realigns Job Order.transport_status with the linked
Transport Schedule.transport_status, using the same mapping
``transport_events.TRANSPORT_TO_JOB_ORDER_STATUS`` the runtime sync uses.

Terminal JO states (``Completed`` / ``Cancelled``) are left untouched so we
don't accidentally resurrect finished work.
"""

import frappe

from apc_operations.shipping.transport_events import TRANSPORT_TO_JOB_ORDER_STATUS

# JO states that should never be rewritten from a TS mapping.
TERMINAL_JO_STATUSES = {"Completed", "Cancelled"}


def execute():
	frappe.reload_doctype("Job Order")
	frappe.reload_doctype("Transport Schedule")

	rows = frappe.db.sql(
		"""
		SELECT
			jo.name AS job_order,
			jo.transport_status AS jo_status,
			ts.name AS transport_schedule,
			ts.transport_status AS ts_status
		FROM `tabJob Order` jo
		INNER JOIN `tabTransport Schedule` ts
			ON ts.name = jo.transport_schedule
		WHERE COALESCE(jo.transport_schedule, '') <> ''
		""",
		as_dict=True,
	)

	updated = 0
	for r in rows:
		if r.jo_status in TERMINAL_JO_STATUSES:
			continue
		desired = TRANSPORT_TO_JOB_ORDER_STATUS.get(r.ts_status, "Pending Booking")
		if desired == r.jo_status:
			continue
		frappe.db.set_value(
			"Job Order",
			r.job_order,
			"transport_status",
			desired,
			update_modified=False,
		)
		updated += 1

	frappe.db.commit()

	if updated:
		frappe.logger().info(
			"realign_job_order_transport_status: updated %s Job Orders", updated
		)
