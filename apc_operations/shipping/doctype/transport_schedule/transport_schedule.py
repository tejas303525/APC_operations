# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import today, getdate, add_days
from frappe import _


class TransportSchedule(Document):
    def validate(self):
        self.validate_dates()
        self.calculate_total_cost()

    def validate_dates(self):
        if self.scheduled_pickup_date and self.actual_pickup_date:
            if getdate(self.actual_pickup_date) < getdate(self.scheduled_pickup_date):
                frappe.msgprint(
                    _("Warning: Actual pickup is before scheduled date"),
                    indicator="orange"
                )

        if self.cutoff_date and self.scheduled_pickup_date:
            if getdate(self.scheduled_pickup_date) >= getdate(self.cutoff_date):
                frappe.throw(_("Scheduled pickup must be before cutoff date"))

    def calculate_total_cost(self):
        self.total_cost = (self.transport_charges or 0) + (self.fuel_cost or 0) + (self.additional_charges or 0)

    def before_save(self):
        self.populate_source_details()
        self.update_status_from_assignment()

    def update_status_from_assignment(self):
        if self.transport_status in ["Draft", "Pending Assignment", "Scheduled"]:
            if self.assigned_vehicle and self.assigned_driver:
                self.transport_status = "Driver Assigned"
            elif self.assigned_vehicle:
                self.transport_status = "Vehicle Assigned"
            elif self.transporter:
                self.transport_status = "Scheduled"

        if self.assigned_driver and not self.driver_phone:
            driver = frappe.get_doc("Driver", self.assigned_driver)
            self.driver_phone = driver.phone

    def before_submit(self):
        # if self.transport_status not in ["Delivered", "Completed"]:
        #     frappe.throw(_("Transport must be Delivered or Completed before submission"))
        pass

    def on_submit(self):
        self.create_gate_passes()
        self.notify_payables_team()

    def on_update(self):
        # Sync to Shipping Booking (parent document relationship)
        self.sync_status_to_booking()

        # Note: sync to Job Order is handled via hooks.py transport_events to avoid recursion

        if self.has_value_changed("transport_status"):
            self.add_status_comment()
            self.send_status_notifications()

        self.ensure_outward_follow_up_records()

    def populate_source_details(self):
        if self.shipping_booking:
            try:
                booking = frappe.get_cached_doc("Shipping Booking", self.shipping_booking)
                self.source_document_type = "Shipping Booking"
                self.job_order = self.job_order or booking.job_order
                if not self.customer and booking.customer and frappe.db.exists("Customer", booking.customer):
                    self.customer = booking.customer
                self.shipping_line = self.shipping_line or booking.shipping_line
                self.vessel_name = self.vessel_name or booking.vessel_name
                self.vessel_date = self.vessel_date or booking.vessel_date
                self.cro_number = self.cro_number or booking.cro_number
                self.cro_date = self.cro_date or booking.cro_date
                self.cutoff_date = self.cutoff_date or booking.cutoff_date
                self.gate_cutoff = self.gate_cutoff or booking.gate_cutoff
                self.pull_out_date = self.pull_out_date or booking.pull_out_date
                self.gate_in_date = self.gate_in_date or booking.gate_in_date
                self.container_type = self.container_type or booking.container_type
                self.container_count = self.container_count or booking.container_count
                self.cargo_weight = self.cargo_weight or booking.cargo_weight
                self.material_description = self.material_description or booking.cargo_description
                self.port_of_loading = self.port_of_loading or booking.port_of_loading
                self.port_of_discharge = self.port_of_discharge or booking.port_of_discharge
            except frappe.DoesNotExistError:
                frappe.msgprint(
                    _("Warning: Linked Shipping Booking {0} not found").format(self.shipping_booking),
                    indicator="orange"
                )
        elif self.job_order:
            self.source_document_type = "Job Order"
        else:
            self.source_document_type = self.source_document_type or "Manual"

        if self.job_order:
            try:
                job_order = frappe.get_cached_doc("Job Order", self.job_order)
                if not self.customer and job_order.customer and frappe.db.exists("Customer", job_order.customer):
                    self.customer = job_order.customer
                self.incoterm = job_order.terms_of_delivery
                self.port_of_loading = self.port_of_loading or job_order.port_of_loading
                self.port_of_discharge = self.port_of_discharge or job_order.port_of_discharge
                if self.transport_type == "Outward" and not self.outward_type:
                    self.outward_type = job_order.get_transport_outward_type()
                if not self.material_description and job_order.get("items"):
                    self.material_description = ", ".join(
                        filter(None, [row.get("item_name") or row.get("item_code") for row in job_order.get("items")])
                    )
            except frappe.DoesNotExistError:
                frappe.msgprint(
                    _("Warning: Linked Job Order {0} not found").format(self.job_order),
                    indicator="orange"
                )

    def sync_status_to_booking(self):
        if self.shipping_booking:
            frappe.db.set_value(
                "Shipping Booking",
                self.shipping_booking,
                {
                    "transport_status": self.get_booking_transport_status(),
                    "linked_transport": self.name,
                },
                update_modified=False,
            )

    def sync_status_to_job_order(self):
        if not self.job_order:
            return

        values = {
            "transport_schedule": self.name,
            "transport_status": self.get_job_order_transport_status(),
        }

        job_status = frappe.db.get_value("Job Order", self.job_order, "status")
        if self.transport_status in ["Dispatched", "Picked Up", "Gate In", "In Transit"]:
            if job_status not in ["Completed", "Cancelled"]:
                values["status"] = "In Progress"
        elif self.transport_status in ["Delivered", "Completed"]:
            if job_status != "Cancelled":
                values["status"] = "Completed"

        frappe.db.set_value("Job Order", self.job_order, values, update_modified=False)

    def get_job_order_transport_status(self):
        status_map = {
            "Draft": "Pending Booking",
            "Pending Assignment": "Pending Booking",
            "Scheduled": "Scheduled",
            "Vehicle Assigned": "Scheduled",
            "Driver Assigned": "Scheduled",
            "Dispatched": "In Progress",
            "Picked Up": "In Progress",
            "Gate In": "In Progress",
            "In Transit": "In Progress",
            "Delivered": "Completed",
            "Completed": "Completed",
            "Cancelled": "Cancelled",
        }
        return status_map.get(self.transport_status, "Pending Booking")

    def get_booking_transport_status(self):
        status_map = {
            "Draft": "Pending",
            "Pending Assignment": "Pending",
            "Scheduled": "Scheduled",
            "Vehicle Assigned": "Scheduled",
            "Driver Assigned": "Scheduled",
            "Dispatched": "In Progress",
            "Picked Up": "In Progress",
            "Gate In": "In Progress",
            "In Transit": "In Progress",
            "Delivered": "Completed",
            "Completed": "Completed",
            "Cancelled": "Pending"
        }
        return status_map.get(self.transport_status, "Pending")

    def add_status_comment(self):
        self.add_comment(
            "Comment",
            text=f"Transport status changed to: {self.transport_status}"
        )

    def send_status_notifications(self):
        if self.transport_status == "Driver Assigned":
            self.notify_driver_assigned()
        elif self.transport_status == "Dispatched":
            self.notify_security_team()
        elif self.transport_status == "Delivered":
            self.notify_delivery_completed()

    def notify_driver_assigned(self):
        if not self.assigned_driver:
            return
        try:
            driver = frappe.get_doc("Driver", self.assigned_driver)
            if driver.email:
                subject = f"Transport Assignment: {self.name}"
                message = f"""
                <h3>New Transport Assignment</h3>
                <p><b>Transport ID:</b> {self.name}</p>
                <p><b>Pickup Date:</b> {self.scheduled_pickup_date}</p>
                <p><b>Pickup Location:</b> {self.pickup_location or 'N/A'}</p>
                <p><b>Delivery Location:</b> {self.delivery_location or 'N/A'}</p>
                <p><b>Container Count:</b> {self.container_count or 0}</p>
                <br>
                <a href="{frappe.utils.get_url()}/app/transport-schedule/{self.name}">View Transport Schedule</a>
                """
                frappe.sendmail(
                    recipients=driver.email,
                    subject=subject,
                    message=message,
                    reference_doctype=self.doctype,
                    reference_name=self.name
                )
        except Exception as e:
            frappe.log_error(f"Driver Notification Error: {str(e)}", "Transport Schedule")

    def notify_security_team(self):
        try:
            security_users = frappe.get_all(
                "Has Role",
                filters={"role": ["in", ["Security Manager", "Security User"]]},
                fields=["parent"],
                distinct=True
            )

            subject = f"Security Dispatch Required: {self.name}"
            message = f"""
            <h3>Transport Dispatched - Security Attention Required</h3>
            <p><b>Transport ID:</b> {self.name}</p>
            <p><b>Driver:</b> {self.assigned_driver or 'Not Assigned'}</p>
            <p><b>Vehicle:</b> {self.assigned_vehicle or 'Not Assigned'}</p>
            <p><b>Pickup Date:</b> {self.scheduled_pickup_date}</p>
            <p><b>Pickup Location:</b> {self.pickup_location or 'N/A'}</p>
            <br>
            <a href="{frappe.utils.get_url()}/app/transport-schedule/{self.name}">View Transport Schedule</a>
            """

            for user in security_users:
                frappe.sendmail(
                    recipients=user.parent,
                    subject=subject,
                    message=message,
                    reference_doctype=self.doctype,
                    reference_name=self.name
                )
        except Exception as e:
            frappe.log_error(f"Security Notification Error: {str(e)}", "Transport Schedule")

    def notify_delivery_completed(self):
        if not self.customer:
            return
        try:
            subject = f"Delivery Completed - Transport {self.name}"
            message = f"""
            <h3>Delivery Completed</h3>
            <p><b>Transport ID:</b> {self.name}</p>
            <p><b>Shipping Booking:</b> {self.shipping_booking}</p>
            <p><b>Actual Delivery Date:</b> {self.actual_delivery_date}</p>
            <br>
            <a href="{frappe.utils.get_url()}/app/transport-schedule/{self.name}">View Details</a>
            """
            frappe.sendmail(
                recipients=frappe.get_value("Customer", self.customer, "email_id"),
                subject=subject,
                message=message,
                reference_doctype=self.doctype,
                reference_name=self.name
            )
        except Exception as e:
            frappe.log_error(f"Customer Notification Error: {str(e)}", "Transport Schedule")

    def notify_payables_team(self):
        try:
            if not self.total_cost or self.total_cost <= 0:
                return

            accounts_users = frappe.get_all(
                "Has Role",
                filters={"role": ["in", ["Accounts Manager", "Accounts User"]]},
                fields=["parent"],
                distinct=True
            )

            subject = f"Transport Cost Tracking - {self.name}"
            message = f"""
            <h3>Transport Cost to Track</h3>
            <p><b>Transport ID:</b> {self.name}</p>
            <p><b>Shipping Booking:</b> {self.shipping_booking}</p>
            <p><b>Transporter:</b> {self.transporter or 'N/A'}</p>
            <p><b>Driver:</b> {self.assigned_driver or 'N/A'}</p>
            <br>
            <p><b>Transport Charges:</b> {self.transport_charges or 0} {self.currency}</p>
            <p><b>Fuel Cost:</b> {self.fuel_cost or 0} {self.currency}</p>
            <p><b>Additional Charges:</b> {self.additional_charges or 0} {self.currency}</p>
            <p><b>Total Cost:</b> {self.total_cost or 0} {self.currency}</p>
            <br>
            <a href="{frappe.utils.get_url()}/app/transport-schedule/{self.name}">View Transport Schedule</a>
            """

            for user in accounts_users:
                frappe.sendmail(
                    recipients=user.parent,
                    subject=subject,
                    message=message,
                    reference_doctype=self.doctype,
                    reference_name=self.name
                )
        except Exception as e:
            frappe.log_error(f"Payables Notification Error: {str(e)}", "Transport Schedule")

    def ensure_outward_follow_up_records(self):
        if self.transport_type != "Outward":
            return
        if self.transport_status not in ["Scheduled", "Vehicle Assigned", "Driver Assigned"]:
            return

        self.create_transport_po_request()
        self.create_security_draft_delivery_note()

    def create_transport_po_request(self):
        existing = self.transport_po_request or frappe.db.exists(
            "Transport PO Request", {"transport_schedule": self.name}
        )
        if existing:
            if not self.transport_po_request:
                self.db_set("transport_po_request", existing, update_modified=False)
            if self.payables_status in [None, "", "Not Required"]:
                self.db_set("payables_status", "Pending Payables", update_modified=False)
            return existing

        po_request = frappe.new_doc("Transport PO Request")
        po_request.transport_schedule = self.name
        po_request.job_order = self.job_order
        po_request.shipping_booking = self.shipping_booking
        po_request.transport_type = self.transport_type
        po_request.outward_type = self.outward_type
        po_request.transporter = self.transporter
        po_request.vehicle = self.assigned_vehicle
        po_request.driver = self.assigned_driver
        po_request.scheduled_date = self.scheduled_pickup_date
        po_request.pickup_location = self.pickup_location
        po_request.delivery_location = self.delivery_location
        po_request.transport_charges = self.transport_charges
        po_request.currency = self.currency
        po_request.payables_status = "Pending Payables"
        po_request.insert(ignore_permissions=True)

        self.db_set("transport_po_request", po_request.name, update_modified=False)
        self.db_set("payables_status", "Pending Payables", update_modified=False)
        self.notify_payables_team()
        return po_request.name

    def create_security_draft_delivery_note(self):
        existing = self.security_draft_delivery_note or frappe.db.exists(
            "Security Draft Delivery Note", {"transport_schedule": self.name}
        )
        if existing:
            if not self.security_draft_delivery_note:
                self.db_set("security_draft_delivery_note", existing, update_modified=False)
            if self.security_status in [None, "", "Not Required"]:
                self.db_set("security_status", "Pending Review", update_modified=False)
            return existing

        draft_dn = frappe.new_doc("Security Draft Delivery Note")
        if self.customer and not frappe.db.exists("Customer", self.customer):
            self.customer = None
        draft_dn.transport_schedule = self.name
        draft_dn.job_order = self.job_order
        draft_dn.shipping_booking = self.shipping_booking
        if self.customer and frappe.db.exists("Customer", self.customer):
            draft_dn.customer = self.customer
        draft_dn.transport_type = "Outward"
        draft_dn.outward_type = self.outward_type
        draft_dn.material_description = self.material_description
        draft_dn.container_type = self.container_type
        draft_dn.container_count = self.container_count
        draft_dn.vehicle = self.assigned_vehicle
        draft_dn.driver = self.assigned_driver
        draft_dn.transporter = self.transporter
        draft_dn.pickup_date = self.scheduled_pickup_date
        draft_dn.pickup_time = self.pickup_time
        draft_dn.gate_out_status = "Pending Security Review"
        draft_dn.security_status = "Pending Review"
        draft_dn.insert(ignore_permissions=True, ignore_links=True)

        self.db_set("security_draft_delivery_note", draft_dn.name, update_modified=False)
        self.db_set("security_status", "Pending Review", update_modified=False)
        self.notify_security_review_required(draft_dn.name)
        return draft_dn.name

    def notify_security_review_required(self, draft_dn):
        try:
            security_users = frappe.get_all(
                "Has Role",
                filters={"role": ["in", ["Security Manager", "Security User"]]},
                fields=["parent"],
                distinct=True,
            )

            subject = f"Security Draft Delivery Note Pending Review: {draft_dn}"
            message = f"""
            <h3>Security Draft Delivery Note Pending Review</h3>
            <p><b>Draft DN:</b> {draft_dn}</p>
            <p><b>Transport ID:</b> {self.name}</p>
            <p><b>Pickup Date:</b> {self.scheduled_pickup_date}</p>
            <p><b>Vehicle:</b> {self.assigned_vehicle or 'Not Assigned'}</p>
            <p><b>Driver:</b> {self.assigned_driver or 'Not Assigned'}</p>
            <br>
            <a href="{frappe.utils.get_url()}/app/security-draft-delivery-note/{draft_dn}">Review Draft Delivery Note</a>
            """

            for user in security_users:
                frappe.sendmail(
                    recipients=user.parent,
                    subject=subject,
                    message=message,
                    reference_doctype="Security Draft Delivery Note",
                    reference_name=draft_dn,
                )
        except Exception as e:
            frappe.log_error(f"Security Draft DN Notification Error: {str(e)}", "Transport Schedule")

    def create_gate_passes(self):
        if self.gate_pass:
            return

        # Validate required fields before creating Gate Pass
        if not self.assigned_vehicle:
            frappe.msgprint(
                _("Cannot create Gate Pass: Vehicle not assigned"),
                indicator="orange"
            )
            return
        if not self.assigned_driver:
            frappe.msgprint(
                _("Cannot create Gate Pass: Driver not assigned"),
                indicator="orange"
            )
            return
        if self.docstatus != 1:
            frappe.msgprint(
                _("Cannot create Gate Pass: Transport Schedule must be submitted first"),
                indicator="orange"
            )
            return

        try:
            gate_pass = frappe.new_doc("Gate Pass")
            gate_pass.gate_pass_type = "Out"
            gate_pass.posting_date = today()
            gate_pass.status = "Draft"
            gate_pass.company = (
                frappe.defaults.get_user_default("Company")
                or frappe.db.get_default("company")
                or ""
            )

            if self.customer:
                gate_pass.customer = self.customer

            vehicle_plate = frappe.get_value("Vehicle", self.assigned_vehicle, "plate_number") if self.assigned_vehicle else ""
            driver_name = frappe.get_value("Driver", self.assigned_driver, "driver_name") if self.assigned_driver else ""

            gate_pass.vehicle_no = vehicle_plate
            gate_pass.driver_name = driver_name
            gate_pass.driver_phone = self.driver_phone

            # Populate items from Security Inspection if available
            items = self._get_items_for_gate_pass()
            if items:
                for item in items:
                    gate_pass.append("items", item)

            gate_pass.insert()

            self.gate_pass = gate_pass.name
            self.gate_pass_status = gate_pass.status

            frappe.msgprint(
                _("Gate Pass {0} created").format(gate_pass.name),
                indicator="green"
            )
        except Exception as e:
            frappe.log_error(f"Gate Pass Creation Error: {str(e)}", "Transport Schedule")
            frappe.msgprint(
                _("Failed to create Gate Pass: {0}").format(str(e)),
                indicator="red"
            )

    def _get_items_for_gate_pass(self):
        """Get items to populate Gate Pass from Security Inspection or Job Order"""
        items = []

        # Try to get from Security Inspection first
        if self.security_draft_delivery_note:
            try:
                inspection = frappe.get_doc("Security Inspection", {
                    "transportation_request": self.name
                }, "*", order_by="creation desc")
                if inspection and inspection.material_description:
                    items.append({
                        "item_name": inspection.material_description,
                        "description": inspection.material_description,
                        "qty": inspection.quantity or 1,
                        "uom": inspection.uom or "Nos",
                    })
                    return items
            except Exception:
                pass

        # Fallback to Job Order items
        if self.job_order:
            try:
                job_order = frappe.get_doc("Job Order", self.job_order)
                for row in job_order.get("items") or []:
                    items.append({
                        "item_name": row.get("item_name") or row.get("item_code"),
                        "description": row.get("description"),
                        "qty": row.get("qty") or 1,
                        "uom": row.get("uom") or "Nos",
                    })
            except Exception:
                pass

        return items


@frappe.whitelist()
def get_pending_transports(days=7):
    pickup_date = add_days(today(), int(days))
    return frappe.db.sql("""
        SELECT
            name,
            shipping_booking,
            vessel_name,
            scheduled_pickup_date,
            transport_status,
            container_count
        FROM `tabTransport Schedule`
        WHERE transport_status IN ('Pending Assignment', 'Scheduled', 'Vehicle Assigned', 'Driver Assigned')
        AND scheduled_pickup_date <= %s
        ORDER BY scheduled_pickup_date ASC
    """, (pickup_date,), as_dict=True)


@frappe.whitelist()
def update_transport_status(transport_name, status, actual_date=None):
    doc = frappe.get_doc("Transport Schedule", transport_name)
    doc.transport_status = status

    if status == "Picked Up" and not doc.actual_pickup_date:
        doc.actual_pickup_date = actual_date or today()

    if status == "Delivered" and not doc.actual_delivery_date:
        doc.actual_delivery_date = actual_date or today()

    if status == "Gate In" and not doc.gate_in_date:
        doc.gate_in_date = actual_date or today()

    doc.save()
    return {"success": True}


@frappe.whitelist()
def assign_vehicle_and_driver(transport_name, vehicle=None, driver=None, transporter=None):
    doc = frappe.get_doc("Transport Schedule", transport_name)

    if vehicle:
        doc.assigned_vehicle = vehicle
    if driver:
        doc.assigned_driver = driver
    if transporter:
        doc.transporter = transporter

    doc.save()
    return {"success": True, "message": "Assignment updated"}


@frappe.whitelist()
def get_overdue_assignments(hours=48):
    cutoff = add_days(today(), -2)
    return frappe.get_all(
        "Transport Schedule",
        filters={
            "transport_status": ["in", ["Draft", "Pending Assignment"]],
            "creation": ["<", cutoff]
        },
        fields=["name", "shipping_booking", "scheduled_pickup_date", "transport_status"],
        order_by="scheduled_pickup_date ASC"
    )
