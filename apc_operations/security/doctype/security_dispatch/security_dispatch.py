# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import today, now, add_days, getdate
from frappe import _


class SecurityDispatch(Document):
    def before_save(self):
        self.populate_from_transport()

    def populate_from_transport(self):
        """Auto-fill Customer, Job Order, Vehicle, Driver from Transport Schedule."""
        if not self.transport_schedule:
            return

        transport = frappe.get_cached_doc("Transport Schedule", self.transport_schedule)
        if not self.shipping_booking:
            self.shipping_booking = transport.shipping_booking
        if not self.job_order:
            self.job_order = transport.job_order
        if not self.customer:
            self.customer = transport.customer
        if not self.vehicle:
            self.vehicle = transport.assigned_vehicle
        if not self.driver:
            self.driver = transport.assigned_driver
        if not self.container_count:
            self.container_count = transport.container_count
        if not self.material_description:
            self.material_description = transport.material_description

    def validate(self):
        if self.dispatch_date and getdate(self.dispatch_date) < getdate(today()):
            frappe.msgprint(
                _("Dispatch date is in the past"),
                indicator="orange"
            )

    def on_update(self):
        if self.status == "Dispatched" and not self.actual_dispatch_time:
            self.actual_dispatch_time = now()
            self.db_set("actual_dispatch_time", self.actual_dispatch_time, update_modified=False)

        self.sync_security_status_to_transport()

        # Auto-create Security Inspection when dispatch is confirmed
        if self.status in ["Dispatched", "Confirmed"]:
            self.ensure_security_inspection()

    def ensure_security_inspection(self):
        """Create Security Inspection from this dispatch if not exists."""
        # Check if already linked
        if self.security_inspection:
            return

        # Check if already exists via transport_schedule
        if self.transport_schedule:
            existing = frappe.db.exists(
                "Security Inspection",
                {"transportation_request": self.transport_schedule}
            )
            if existing:
                self.db_set("security_inspection", existing, update_modified=False)
                return existing

        # Create new Security Inspection
        try:
            inspection = frappe.new_doc("Security Inspection")
            inspection.job_order = self.job_order
            inspection.shipping_booking = self.shipping_booking
            inspection.transportation_request = self.transport_schedule
            inspection.customer = self.customer
            inspection.vehicle = self.vehicle
            inspection.driver = self.driver
            inspection.inspection_type = self.get_inspection_type()
            inspection.material_description = self.material_description
            inspection.inspection_date = today()
            inspection.security_status = "Draft"
            inspection.qc_status = "Not Sent"
            inspection.receivables_status = "Not Applicable"
            inspection.insert(ignore_permissions=True)

            # Link back
            self.db_set("security_inspection", inspection.name, update_modified=False)

            # Create default checklist items
            self._create_checklist_for_inspection(inspection)

            frappe.msgprint(
                _("Security Inspection {0} created from Dispatch").format(inspection.name),
                indicator="green"
            )
            return inspection.name
        except Exception as e:
            frappe.log_error(
                f"Security Inspection Creation Error: {str(e)}",
                "Security Dispatch"
            )
            frappe.msgprint(
                _("Failed to auto-create Security Inspection: {0}").format(str(e)),
                indicator="red"
            )

    def get_inspection_type(self):
        """Map dispatch type to inspection type."""
        type_map = {
            "Container Pickup": "Export Container",
            "Export Container": "Export Container",
            "Local Delivery": "Local Delivery",
            "Tanker Pickup": "Tanker",
            "Tanker Delivery": "Tanker",
            "Trailer Pickup": "Trailer",
            "Trailer Delivery": "Trailer",
        }
        return type_map.get(self.dispatch_type, "Container")

    def _create_checklist_for_inspection(self, inspection):
        """Create default checklist items for the new inspection."""
        default_items = [
            {"checklist_item": "Container condition verified", "required": 1},
            {"checklist_item": "Seal number checked and recorded", "required": 1},
            {"checklist_item": "Vehicle registration verified", "required": 1},
            {"checklist_item": "Driver license verified", "required": 1},
            {"checklist_item": "Weightment slip attached", "required": 0},
            {"checklist_item": "Material description matches documents", "required": 1},
            {"checklist_item": "Dangerous goods check completed", "required": 0},
        ]

        for item in default_items:
            inspection.append("checklist_items", {
                "checklist_item": item["checklist_item"],
                "required": item["required"],
                "completed": 0,
            })

        inspection.save(ignore_permissions=True)

    def sync_security_status_to_transport(self):
        """Push security_status back to the linked Transport Schedule."""
        if not self.transport_schedule or not self.security_status:
            return

        frappe.db.set_value(
            "Transport Schedule",
            self.transport_schedule,
            "security_status",
            self.security_status,
            update_modified=False,
        )


@frappe.whitelist()
def get_pending_dispatches():
    return frappe.db.sql("""
        SELECT
            name,
            transport_schedule,
            shipping_booking,
            job_order,
            dispatch_date,
            dispatch_type,
            container_count,
            status,
            security_status
        FROM `tabSecurity Dispatch`
        WHERE status IN ('Pending', 'Scheduled')
        ORDER BY dispatch_date ASC
    """, as_dict=True)


@frappe.whitelist()
def mark_dispatched(dispatch_name):
    doc = frappe.get_doc("Security Dispatch", dispatch_name)
    doc.status = "Dispatched"
    doc.actual_dispatch_time = now()
    doc.save()
    return {"success": True}
