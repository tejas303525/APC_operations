# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, today, getdate
from frappe import _

from apc_operations.shipping.doctype.job_order.job_order import get_incoterm_rule
from apc_operations.services.email_recipients import role_user_emails


# Export booking fields required when confirming/submitting a full booking.
_EXPORT_BOOKING_MANDATORY = (
    ("shipping_line", "Shipping Line"),
    ("port_of_loading", "Port of Loading (POL)"),
    ("port_of_discharge", "Port of Discharge (POD)"),
    ("container_type", "Container Type"),
    ("cargo_description", "Cargo Description"),
    ("vessel_date", "Vessel Date (ETD)"),
    ("cutoff_date", "Cutoff Date"),
    ("pull_out_date", "Pull Out Date"),
    ("freight_rate", "Freight Rate"),
    ("currency", "Currency"),
)


class ShippingBooking(Document):
    def validate(self):
        from apc_operations.services.customer_link_service import normalize_customer_field

        normalize_customer_field(self, "customer")
        self.validate_counterparty()
        self.validate_dates()
        self.calculate_total_charges()
        self.validate_booking_completeness()

    def validate_counterparty(self):
        if self.job_order:
            movement = frappe.db.get_value("Job Order", self.job_order, "commercial_movement") or "Outward"
            if movement == "Import":
                if not self.supplier and not self.customer:
                    frappe.throw(
                        _("Set Supplier (or Customer) on the Shipping Booking for an Import Job Order.")
                    )
            elif not self.customer:
                frappe.throw(_("Customer is required for Outward shipping bookings linked to a Job Order."))
        elif not self.customer and not self.supplier:
            frappe.throw(_("Set Customer or Supplier on the Shipping Booking."))

    def validate_dates(self):
        if self.vessel_date and self.cutoff_date:
            if getdate(self.cutoff_date) > getdate(self.vessel_date):
                frappe.throw(_("Cutoff Date cannot be after Vessel Date (ETD)"))

        if self.pull_out_date and self.cutoff_date:
            if getdate(self.pull_out_date) > getdate(self.cutoff_date):
                frappe.throw(_("Pull Out Date cannot be after Cutoff Date"))

    def _get_commercial_movement(self) -> str:
        movement = (self.commercial_movement or "").strip()
        if not movement and self.job_order:
            movement = frappe.db.get_value(
                "Job Order", self.job_order, "commercial_movement"
            ) or ""
        return movement or "Outward"

    def _is_import_tracking_booking(self) -> bool:
        status = (self.booking_status or "Draft").strip()
        return self._get_commercial_movement() == "Import" and status in (
            "",
            "Draft",
            "Tracking",
        )

    def validate_booking_completeness(self):
        """Import placeholders in Tracking skip export booking fields; Export requires them on submit."""
        if self._is_import_tracking_booking():
            return
        if self.docstatus == 0 and (self.booking_status or "Draft").strip() == "Draft":
            return
        self._validate_export_booking_fields()

    def _validate_export_booking_fields(self):
        missing = [
            label
            for fieldname, label in _EXPORT_BOOKING_MANDATORY
            if not self.get(fieldname)
        ]
        if (self.container_count or 0) < 1:
            missing.append("Container Count")
        if missing:
            frappe.throw(
                _("Please set the following before confirming this Shipping Booking: {0}").format(
                    ", ".join(missing)
                )
            )

    def before_submit(self):
        if self._is_import_tracking_booking():
            frappe.throw(
                _(
                    "Complete vessel and booking details on this Import Shipping Booking "
                    "before submit, or update tracking from the Transportation Console."
                )
            )
        self._validate_export_booking_fields()

    def calculate_total_charges(self):
        self.total_freight_charges = (self.freight_rate or 0) * (self.container_count or 0)

    def on_submit(self):
        self.db_set("booking_status", "Confirmed")

    def on_update(self):
        self.sync_status_to_job_order()
        self._handle_cro_received()

    def on_update_after_submit(self):
        self.sync_status_to_job_order()
        # _handle_cro_received runs on first submit via on_update, no need to repeat here

    def _handle_cro_received(self):
        if self.has_value_changed("cro_number") and self.cro_number:
            self.db_set("cro_status", "Generated", update_modified=False)
            self.generate_transportation()
            self.notify_payables_team()

    def calculate_pickup_date(self):
        if self.cutoff_date:
            return add_days(getdate(self.cutoff_date), -3)
        elif self.pull_out_date:
            return add_days(getdate(self.pull_out_date), -3)
        return today()

    def generate_transportation(self):
        if frappe.db.exists("Transport Schedule", {"shipping_booking": self.name}):
            return
        if not self.requires_transport_schedule_from_booking():
            frappe.msgprint(
                _(
                    "Transport not auto-created for Shipping Booking {0}; "
                    "Job Order incoterm indicates counterparty-arranged inland transport."
                ).format(self.name),
                indicator="orange",
            )
            return
        try:
            pickup_date = self.calculate_pickup_date()
            transport = frappe.new_doc("Transport Schedule")
            transport.source_document_type = "Shipping Booking"
            transport.job_order = self.job_order
            transport.shipping_booking = self.name
            transport.shipping_line = self.shipping_line
            transport.vessel_name = self.vessel_name
            transport.vessel_date = self.vessel_date
            transport.cutoff_date = self.cutoff_date
            transport.gate_cutoff = self.gate_cutoff
            transport.pull_out_date = self.pull_out_date
            transport.gate_in_date = self.gate_in_date
            transport.container_count = self.container_count
            transport.container_type = self.container_type
            transport.cargo_weight = self.cargo_weight
            transport.material_description = self.cargo_description
            transport.port_of_loading = self.port_of_loading
            transport.port_of_discharge = self.port_of_discharge
            transport.cro_number = self.cro_number
            transport.cro_date = self.cro_date
            transport.scheduled_pickup_date = pickup_date
            transport.transport_status = "Pending Assignment"
            movement = None
            if self.job_order:
                movement = frappe.db.get_value("Job Order", self.job_order, "commercial_movement")
            if (movement or "").strip() == "Import":
                transport.transport_type = "Inward"
            else:
                transport.transport_type = "Outward"
                transport.outward_type = "Export Container"

            from apc_operations.services.customer_link_service import (
                resolve_customer_from_job_order,
                resolve_customer_docname,
            )

            transport.customer = (
                resolve_customer_docname(self.customer)
                or resolve_customer_from_job_order(self.job_order)
            )
            if self.supplier:
                transport.supplier = frappe.db.get_value("Supplier", self.supplier, "supplier_name") or self.supplier
            elif self.job_order:
                sup = frappe.db.get_value("Job Order", self.job_order, "supplier")
                if sup:
                    transport.supplier = frappe.db.get_value("Supplier", sup, "supplier_name") or sup

            transport.insert()

            self.db_set("linked_transport", transport.name, update_modified=False)
            self.db_set("transport_status", "Scheduled", update_modified=False)
            self.sync_status_to_job_order()

            frappe.msgprint(
                _("Transport Schedule {0} created for pickup on {1}").format(
                    transport.name, pickup_date
                ),
                indicator="green"
            )
        except Exception as e:
            frappe.log_error(f"Transport Generation Error: {str(e)}", "Shipping Booking")
            frappe.msgprint(
                _("Failed to generate Transport Schedule: {0}").format(str(e)),
                indicator="red"
            )

    def requires_transport_schedule_from_booking(self):
        """
        Whether this Shipping Booking should auto-create a Transport Schedule
        for APC-managed inland / site-coordinated transport.

        Driven by the incoterm rule (`transport_arranged_by == "APC"`) for the
        Job Order's commercial movement (Export vs Import).
        """
        if not self.job_order:
            # Standalone SB without a JO — assume APC handles transport.
            return True

        incoterm, movement = frappe.db.get_value(
            "Job Order", self.job_order, ["terms_of_delivery", "commercial_movement"]
        )
        rule = get_incoterm_rule(incoterm, movement)
        if rule is None:
            # Unknown / unset incoterm — be conservative and DON'T auto-create.
            # The user can trigger create_transport_from_booking manually.
            return False

        return rule["transport_arranged_by"] == "APC"

    def sync_status_to_job_order(self):
        if not self.job_order:
            return

        # Prevent recursive updates
        if frappe.flags.in_sync_booking_to_job_order:
            return

        values = {
            "shipping_booking": self.name,
            "shipping_status": self.get_job_order_shipping_status(),
        }

        if self.booking_status in ["Confirmed", "In Progress"] and frappe.db.get_value("Job Order", self.job_order, "status") == "Confirmed":
            values["status"] = "In Progress"
        elif self.booking_status == "Completed":
            values["status"] = "Completed"

        frappe.flags.in_sync_booking_to_job_order = True
        try:
            frappe.db.set_value("Job Order", self.job_order, values, update_modified=False)
        finally:
            frappe.flags.in_sync_booking_to_job_order = False

    def get_job_order_shipping_status(self):
        if self.booking_status == "Completed":
            return "Completed"
        if self.booking_status in ["Confirmed", "In Progress"]:
            return "In Progress"

        incoterm, movement = frappe.db.get_value(
            "Job Order", self.job_order, ["terms_of_delivery", "commercial_movement"]
        )
        rule = get_incoterm_rule(incoterm, movement)
        if rule and rule["shipping_arranged_by"] == "Customer":
            # Buyer books the vessel (e.g. FOB). APC is awaiting buyer-supplied
            # vessel/CRO information before the booking is meaningful.
            return "Pending Shipping Review"
        return "Pending Shipping Booking"

    def create_security_dispatch(self):
        if frappe.db.exists("Security Dispatch", {"shipping_booking": self.name}):
            return
        try:
            dispatch = frappe.new_doc("Security Dispatch")
            dispatch.shipping_booking = self.name
            dispatch.dispatch_date = self.calculate_pickup_date()
            dispatch.container_count = self.container_count
            dispatch.dispatch_type = "Container Pickup"
            dispatch.status = "Pending"
            dispatch.insert()

            self.db_set("linked_dispatch", dispatch.name, update_modified=False)
        except Exception as e:
            frappe.log_error(f"Security Dispatch Error: {str(e)}", "Shipping Booking")

    def notify_payables_team(self):
        try:
            payables_users = role_user_emails(["Accounts Manager", "Accounts User"])

            subject = f"Shipment Charges Tracking - CRO {self.cro_number}"
            message = f"""
            <h3>New CRO Received — Charges to Track</h3>
            <b>CRO Number:</b> {self.cro_number}<br>
            <b>Shipping Booking:</b> {self.name}<br>
            <b>Vessel:</b> {self.vessel_name}<br>
            <b>Shipping Line:</b> {self.shipping_line}<br>
            <br>
            <b>Freight Charges:</b> {self.total_freight_charges}<br>
            <b>THC:</b> {self.thc or 0}<br>
            <b>TLUC:</b> {self.tluc or 0}<br>
            <b>Export Declaration:</b> {self.export_declaration or 0}<br>
            <br>
            <a href="{frappe.utils.get_url()}/app/shipping-booking/{self.name}">Open Shipping Booking</a>
            """

            for user in payables_users:
                frappe.sendmail(
                    recipients=user,
                    subject=subject,
                    message=message,
                    reference_doctype="Shipping Booking",
                    reference_name=self.name
                )
        except Exception as e:
            frappe.log_error(f"Payables Notification Error: {str(e)}", "Shipping Booking")


@frappe.whitelist()
def get_upcoming_bookings(days=7):
    cutoff_date = add_days(today(), int(days))
    return frappe.db.sql("""
        SELECT
            name,
            vessel_name,
            vessel_date,
            cutoff_date,
            container_count,
            shipping_line,
            port_of_loading,
            port_of_discharge
        FROM `tabShipping Booking`
        WHERE docstatus = 1
        AND cutoff_date BETWEEN CURDATE() AND %s
        ORDER BY cutoff_date ASC
    """, (cutoff_date,), as_dict=True)


@frappe.whitelist()
def create_transport_from_booking(booking_name):
    doc = frappe.get_doc("Shipping Booking", booking_name)
    doc.generate_transportation()
    return {"success": True, "message": "Transport Schedule created"}
