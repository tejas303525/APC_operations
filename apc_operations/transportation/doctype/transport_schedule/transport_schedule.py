# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import today, getdate, add_days, flt
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
    if not roles:
        return []

    has_roles = frappe.get_all(
        "Has Role",
        filters={"parenttype": "User", "role": ["in", roles]},
        fields=["parent"],
        distinct=True,
    )

    emails = []
    for row in has_roles:
        email = _resolve_user_email(row.parent)
        if email:
            emails.append(email)

    if not emails:
        fallback = _first_valid_email(FALLBACK_NOTIFICATION_EMAIL)
        if fallback:
            emails.append(fallback)

    return list(dict.fromkeys(emails))


def _get_driver_display_name(driver_id):
    """Resolve driver display name across standard/custom Driver schemas."""
    if not driver_id:
        return None

    full_name, driver_name = frappe.db.get_value(
        "Driver",
        driver_id,
        ["full_name", "driver_name"],
    ) or (None, None)

    return full_name or driver_name or driver_id


class TransportSchedule(Document):
    def get_job_order_quantity_and_uom(self):
        """Return total quantity and a representative UOM from Job Order items."""
        if not self.job_order:
            return 0, None

        try:
            job_order = frappe.get_cached_doc("Job Order", self.job_order)
        except frappe.DoesNotExistError:
            return 0, None

        total_qty = 0
        uom_values = set()
        for row in job_order.get("items") or []:
            total_qty += flt(row.get("quantity"))
            if row.get("uom"):
                uom_values.add(row.get("uom"))

        if not uom_values:
            resolved_uom = None
        elif len(uom_values) == 1:
            resolved_uom = next(iter(uom_values))
        else:
            # Avoid stamping an incorrect UOM when Job Order has mixed UOM rows.
            resolved_uom = None

        return total_qty, resolved_uom

    def validate(self):
        from apc_operations.services.customer_link_service import normalize_customer_field

        normalize_customer_field(self, "customer")
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
            if (self.transport_type or "").strip() != "Inward":
                if getdate(self.scheduled_pickup_date) >= getdate(self.cutoff_date):
                    frappe.throw(_("Scheduled pickup must be before cutoff date"))

    def calculate_total_cost(self):
        self.total_cost = (
            flt(self.transport_charges)
            + flt(self.fuel_cost)
            + flt(self.additional_charges)
        )

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
            self.driver_phone = (
                getattr(driver, "cell_number", None)
                or getattr(driver, "phone", None)
                or ""
            )

    def before_submit(self):
        # if self.transport_status not in ["Delivered", "Completed"]:
        #     frappe.throw(_("Transport must be Delivered or Completed before submission"))
        pass

    def on_submit(self):
        self.create_gate_passes(allow_without_submit=False, ignore_permissions=False)
        self.notify_payables_team()

    def on_update(self):
        # Sync to Shipping Booking (parent document relationship)
        self.sync_status_to_booking()

        # Note: sync to Job Order is handled via hooks.py transport_events to avoid recursion

        if self.has_value_changed("transport_status"):
            self.add_status_comment()
            self.send_status_notifications()

        self.ensure_outward_follow_up_records()
        self.ensure_inward_follow_up_records()
        self.sync_transport_po_request_charges()
        if self.job_order and (
            self.has_value_changed("transport_charges")
            or self.has_value_changed("fuel_cost")
            or self.has_value_changed("additional_charges")
            or self.has_value_changed("transport_status")
        ):
            from apc_operations.shipping.services.logistics_cost_service import (
                refresh_job_order_logistics_display,
            )

            refresh_job_order_logistics_display(self.job_order)
        self.sync_assignment_to_security_draft_dn()
        if self.has_value_changed("customer"):
            from apc_operations.services.customer_link_service import sync_sddn_customer_from_transport

            sync_sddn_customer_from_transport(self.name, self.customer)

    def sync_assignment_to_security_draft_dn(self):
        """Keep linked Security Draft DN in sync when vehicle/driver/transporter are assigned later."""
        if not self.security_draft_delivery_note:
            return
        if not frappe.db.exists("Security Draft Delivery Note", self.security_draft_delivery_note):
            return
        from apc_operations.services.customer_link_service import (
            resolve_customer_docname,
            sync_sddn_customer_from_transport,
        )

        updates = {
            "vehicle": self.assigned_vehicle,
            "driver": self.assigned_driver,
            "transporter": self.transporter,
        }
        customer = resolve_customer_docname(self.customer)
        if customer:
            updates["customer"] = customer
            current_buyer = frappe.db.get_value(
                "Security Draft Delivery Note",
                self.security_draft_delivery_note,
                "buyer",
            )
            if not resolve_customer_docname(current_buyer):
                updates["buyer"] = customer
        frappe.db.set_value(
            "Security Draft Delivery Note",
            self.security_draft_delivery_note,
            updates,
            update_modified=False,
        )
        if customer:
            sync_sddn_customer_from_transport(self.name, customer)

    def populate_source_details(self):
        if self.shipping_booking:
            try:
                booking = frappe.get_cached_doc("Shipping Booking", self.shipping_booking)
                self.source_document_type = "Shipping Booking"
                self.job_order = self.job_order or booking.job_order
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
                if getattr(job_order, "supplier", None) and not self.supplier:
                    self.supplier = (
                        frappe.db.get_value("Supplier", job_order.supplier, "supplier_name")
                        or job_order.supplier
                    )
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

        from apc_operations.services.customer_link_service import apply_customer_from_sources

        apply_customer_from_sources(self)

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

        # Prevent recursive updates
        if frappe.flags.in_sync_status_to_job_order:
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

        frappe.flags.in_sync_status_to_job_order = True
        try:
            frappe.db.set_value("Job Order", self.job_order, values, update_modified=False)
        finally:
            frappe.flags.in_sync_status_to_job_order = False

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
            security_emails = _role_user_emails(["Security Manager", "Security User"])

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

            for email in security_emails:
                frappe.sendmail(
                    recipients=email,
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

            account_emails = _role_user_emails(["Accounts Manager", "Accounts User"])

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

            for email in account_emails:
                frappe.sendmail(
                    recipients=email,
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
        self.sync_transport_po_request_charges()
        self.create_security_draft_delivery_note()

    def ensure_inward_follow_up_records(self):
        """Import inward leg: after vessel is cleared and transport is booked, open security review."""
        if (self.transport_type or "").strip() != "Inward":
            return
        if self.transport_status not in ["Scheduled", "Vehicle Assigned", "Driver Assigned"]:
            return

        self.create_transport_po_request()
        self.sync_transport_po_request_charges()
        if not self.assigned_vehicle or not self.assigned_driver:
            return
        if not self._inward_vessel_cleared_for_security():
            return

        if self.job_order:
            from apc_operations.shipping.services.delivery_order_generation_service import (
                try_auto_issue_import_delivery_order,
            )

            try_auto_issue_import_delivery_order(
                self.job_order, transport_schedule=self.name
            )

        self.create_security_draft_delivery_note()

    def _inward_vessel_cleared_for_security(self):
        """Sea import bookings wait for Shipping Booking vessel_status = Cleared."""
        if not self.job_order:
            return True
        movement, mode = frappe.db.get_value(
            "Job Order",
            self.job_order,
            ["commercial_movement", "mode_of_transport"],
        ) or (None, None)
        if (movement or "").strip() != "Import" or (mode or "").strip() != "Sea":
            return True
        if not self.shipping_booking:
            return True
        vessel_status = frappe.db.get_value(
            "Shipping Booking", self.shipping_booking, "vessel_status"
        )
        return (vessel_status or "").strip() == "Cleared"

    def create_transport_po_request(self):
        existing = self.transport_po_request or frappe.db.exists(
            "Transport PO Request", {"transport_schedule": self.name}
        )
        if existing:
            if not self.transport_po_request:
                self.db_set("transport_po_request", existing, update_modified=False)
            if self.payables_status in [None, "", "Not Required"]:
                self.db_set("payables_status", "Pending Payables", update_modified=False)
            self.sync_transport_po_request_charges(existing)
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
        po_request.fuel_cost = self.fuel_cost
        po_request.additional_charges = self.additional_charges
        po_request.currency = self.currency
        po_request.payables_status = "Pending Payables"
        po_request.insert(ignore_permissions=True)

        self.db_set("transport_po_request", po_request.name, update_modified=False)
        self.db_set("payables_status", "Pending Payables", update_modified=False)
        self.sync_transport_po_request_charges(po_request.name)
        self.notify_payables_team()
        return po_request.name

    def sync_transport_po_request_charges(self, po_name=None):
        po_name = po_name or self.transport_po_request
        if not po_name:
            return
        total = (self.transport_charges or 0) + (self.fuel_cost or 0) + (self.additional_charges or 0)
        frappe.db.set_value(
            "Transport PO Request",
            po_name,
            {
                "transport_charges": self.transport_charges,
                "fuel_cost": self.fuel_cost,
                "additional_charges": self.additional_charges,
                "total_transport_cost": total,
                "currency": self.currency,
            },
            update_modified=False,
        )

    def create_security_draft_delivery_note(self):
        existing = self.security_draft_delivery_note or frappe.db.exists(
            "Security Draft Delivery Note", {"transport_schedule": self.name}
        )
        if existing:
            if not self.security_draft_delivery_note:
                self.db_set("security_draft_delivery_note", existing, update_modified=False)
            if self.security_status in [None, "", "Not Required"]:
                self.db_set("security_status", "Pending Review", update_modified=False)
            from apc_operations.services.customer_link_service import (
                apply_customer_from_sources,
                sync_sddn_customer_from_transport,
            )

            apply_customer_from_sources(self)
            stored_customer = frappe.db.get_value("Transport Schedule", self.name, "customer")
            if self.customer and self.customer != stored_customer:
                self.db_set("customer", self.customer, update_modified=False)
            if self.customer:
                sync_sddn_customer_from_transport(self.name, self.customer)
            return existing

        from apc_operations.services.customer_link_service import apply_customer_from_sources

        apply_customer_from_sources(self)

        draft_dn = frappe.new_doc("Security Draft Delivery Note")
        draft_dn.transport_schedule = self.name
        draft_dn.job_order = self.job_order
        draft_dn.job_order_number = frappe.db.get_value("Job Order", self.job_order, "job_order_number") if self.job_order else None
        draft_dn.terms_of_delivery = self.incoterm
        if self.customer and frappe.db.exists("Customer", self.customer):
            draft_dn.customer = self.customer
            draft_dn.buyer = self.customer
        movement_type = (self.transport_type or "Outward").strip()
        draft_dn.transport_type = movement_type
        if movement_type == "Outward":
            draft_dn.outward_type = self.outward_type
        draft_dn.material_description = self.material_description
        draft_dn.quantity, draft_dn.uom = self.get_job_order_quantity_and_uom()
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

        try:
            from apc_operations.services.delivery_order_service import sync_from_sddn

            sync_from_sddn(draft_dn.name)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "SDDN Delivery Order link sync")

        self.db_set("security_draft_delivery_note", draft_dn.name, update_modified=False)
        self.db_set("security_status", "Pending Review", update_modified=False)
        self.notify_security_review_required(draft_dn.name)
        return draft_dn.name

    def notify_security_review_required(self, draft_dn):
        try:
            security_emails = _role_user_emails(["Security Manager", "Security User"])

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

            for email in security_emails:
                frappe.sendmail(
                    recipients=email,
                    subject=subject,
                    message=message,
                    reference_doctype="Security Draft Delivery Note",
                    reference_name=draft_dn,
                )
        except Exception as e:
            frappe.log_error(f"Security Draft DN Notification Error: {str(e)}", "Transport Schedule")

    def create_gate_passes(self, allow_without_submit=False, ignore_permissions=False):
        """Create an outbound Gate Pass and link it to this Transport Schedule.

        By default requires submitted Transport Schedule (on_submit path).
        When ``allow_without_submit`` is True (e.g. Security after checklist),
        vehicle and driver must still be set on the schedule (or synced from
        Security Inspection before calling).

        Returns the new Gate Pass name, an existing linked name, or None if
        creation was skipped or failed.
        """
        if self.gate_pass and frappe.db.exists("Gate Pass", self.gate_pass):
            return self.gate_pass

        # Validate required fields before creating Gate Pass
        if not self.assigned_vehicle:
            frappe.msgprint(
                _("Cannot create Gate Pass: Vehicle not assigned"),
                indicator="orange"
            )
            return None
        if not self.assigned_driver:
            frappe.msgprint(
                _("Cannot create Gate Pass: Driver not assigned"),
                indicator="orange"
            )
            return None
        if not allow_without_submit and self.docstatus != 1:
            frappe.msgprint(
                _("Cannot create Gate Pass: Transport Schedule must be submitted first"),
                indicator="orange"
            )
            return None

        try:
            gate_pass = frappe.new_doc("Gate Pass")
            gate_pass.gate_pass_type = (
                "In" if (self.transport_type or "").strip() == "Inward" else "Out"
            )
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
            driver_name = _get_driver_display_name(self.assigned_driver) if self.assigned_driver else ""

            gate_pass.vehicle_no = vehicle_plate
            gate_pass.driver_name = driver_name
            gate_pass.driver_phone = self.driver_phone

            # Populate items from Security Inspection if available
            items = self._get_items_for_gate_pass()
            if items:
                for item in items:
                    gate_pass.append("items", item)

            gate_pass.insert(ignore_permissions=ignore_permissions)

            try:
                from apc_operations.shipping.doctype.gate_pass.gate_pass import (
                    find_delivery_order_for_job_order,
                )

                if self.job_order:
                    do_name = find_delivery_order_for_job_order(self.job_order)
                    if do_name:
                        frappe.db.set_value(
                            "Gate Pass",
                            gate_pass.name,
                            "delivery_order",
                            do_name,
                            update_modified=False,
                        )
            except Exception:
                frappe.log_error(frappe.get_traceback(), "Gate Pass Delivery Order link")

            frappe.db.set_value(
                "Transport Schedule",
                self.name,
                {
                    "gate_pass": gate_pass.name,
                    "gate_pass_status": gate_pass.status,
                },
                update_modified=False,
            )
            self.gate_pass = gate_pass.name
            self.gate_pass_status = gate_pass.status

            frappe.msgprint(
                _("Gate Pass {0} created").format(gate_pass.name),
                indicator="green"
            )
            return gate_pass.name
        except Exception as e:
            frappe.log_error(f"Gate Pass Creation Error: {str(e)}", "Transport Schedule")
            frappe.msgprint(
                _("Failed to create Gate Pass: {0}").format(str(e)),
                indicator="red"
            )
            return None

    def _get_items_for_gate_pass(self):
        """Get items to populate Gate Pass from Security Inspection or Job Order"""
        items = []
        job_order_items = []

        if self.job_order:
            try:
                job_order = frappe.get_doc("Job Order", self.job_order)
                job_order_items = job_order.get("items") or []
            except Exception:
                job_order_items = []

        # Try to get from Security Inspection first
        if self.name:
            try:
                # Use get_all to find the most recent inspection for this transport
                inspections = frappe.get_all(
                    "Security Inspection",
                    filters={"transportation_request": self.name},
                    fields=["name", "material_description", "quantity", "uom"],
                    order_by="creation desc",
                    limit=1
                )
                if inspections and inspections[0].get("material_description"):
                    inspection = inspections[0]
                    material_description = inspection.get("material_description") or ""
                    matched_row = None

                    for row in job_order_items:
                        row_item_code = row.get("item_code")
                        row_item_name = row.get("item_name") or ""
                        row_description = row.get("description") or ""
                        if not row_item_code:
                            continue
                        if (
                            material_description == row_item_name
                            or material_description == row_item_code
                            or material_description in row_description
                        ):
                            matched_row = row
                            break

                    if matched_row and frappe.db.exists("Item", matched_row.get("item_code")):
                        items.append({
                            "item_code": matched_row.get("item_code"),
                            "item_name": matched_row.get("item_name") or matched_row.get("item_code"),
                            "description": inspection.get("material_description") or matched_row.get("description"),
                            "qty": inspection.get("quantity") or matched_row.get("qty") or 1,
                            "uom": inspection.get("uom") or matched_row.get("uom") or "Nos",
                        })
                        return items
            except Exception:
                pass

        # Fallback to Job Order items
        for row in job_order_items:
            item_code = row.get("item_code")
            if not item_code or not frappe.db.exists("Item", item_code):
                continue
            items.append({
                "item_code": item_code,
                "item_name": row.get("item_name") or item_code,
                "description": row.get("description"),
                "qty": row.get("qty") or 1,
                "uom": row.get("uom") or "Nos",
            })

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
