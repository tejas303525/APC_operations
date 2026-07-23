# Copyright (c) 2026, APC and Contributors
# See license.txt

import frappe
from frappe.utils import today
from frappe.tests.utils import FrappeTestCase


class TestJobOrder(FrappeTestCase):
    def test_confirmed_exw_road_job_order_creates_local_delivery_transport(self):
        job_order = make_job_order(status="Confirmed", terms_of_delivery="EXW", mode_of_transport="Road")

        job_order.reload()
        self.assertEqual(job_order.booking_requirement, "Transport Booking")
        self.assertEqual(job_order.transport_status, "Scheduled")
        self.assertTrue(job_order.transport_schedule)

        transport = frappe.get_doc("Transport Schedule", job_order.transport_schedule)
        self.assertEqual(transport.job_order, job_order.name)
        self.assertEqual(transport.transport_type, "Outward")
        self.assertEqual(transport.outward_type, "Local Delivery")

    def test_confirmed_exw_job_order_transport_creation_is_idempotent(self):
        job_order = make_job_order(status="Confirmed", terms_of_delivery="EXW", mode_of_transport="Road")

        job_order.create_or_link_operational_booking()
        job_order.create_or_link_operational_booking()

        schedules = frappe.get_all("Transport Schedule", filters={"job_order": job_order.name}, pluck="name")
        self.assertEqual(len(schedules), 1)
        self.assertEqual(job_order.get_existing_transport_schedule(), schedules[0])

    def test_confirmed_job_order_without_status_change_still_creates_transport(self):
        job_order = make_job_order(status="Draft", terms_of_delivery="DDP", mode_of_transport="Road")

        # Simulate data that was set to Confirmed outside normal lifecycle.
        frappe.db.set_value("Job Order", job_order.name, "status", "Confirmed", update_modified=False)
        job_order.reload()
        self.assertFalse(job_order.transport_schedule)

        # Save with a non-status change; on_update should still backfill transport.
        job_order.loading_remarks = "Trigger operational link check"
        job_order.save(ignore_permissions=True)
        job_order.reload()

        self.assertEqual(job_order.status, "Confirmed")
        self.assertTrue(job_order.transport_schedule)
        self.assertEqual(job_order.transport_status, "Scheduled")

    def test_job_order_number_must_be_unique(self):
        make_job_order(job_order_number="APC-UNIQUE-001")

        with self.assertRaises(frappe.ValidationError):
            make_job_order(job_order_number="APC-UNIQUE-001")

    # ------------------------------------------------------------------
    # Incoterm responsibility derivation tests
    # ------------------------------------------------------------------

    def test_exw_responsibility_buyer_pays_everything(self):
        jo = make_job_order(terms_of_delivery="EXW", mode_of_transport="Road")
        self.assertEqual(jo.freight_borne_by, "Customer")
        self.assertEqual(jo.insurance_borne_by, "Customer")
        self.assertEqual(jo.transport_arranged_by, "Customer")
        self.assertEqual(jo.shipping_arranged_by, "Not Applicable")
        self.assertEqual(jo.insurance_required, 0)
        self.assertEqual(jo.transport_required, 1)
        self.assertEqual(jo.shipping_required, 0)

    def test_fob_seller_arranges_inland_buyer_pays_freight(self):
        jo = make_job_order(terms_of_delivery="FOB", mode_of_transport="Sea")
        self.assertEqual(jo.freight_borne_by, "Customer")
        self.assertEqual(jo.transport_arranged_by, "APC")
        self.assertEqual(jo.shipping_arranged_by, "Customer")
        self.assertEqual(jo.transport_required, 1)
        self.assertEqual(jo.shipping_required, 1)
        self.assertEqual(jo.insurance_required, 0)

    def test_cif_seller_pays_freight_and_insurance(self):
        jo = make_job_order(terms_of_delivery="CIF", mode_of_transport="Sea")
        self.assertEqual(jo.freight_borne_by, "APC")
        self.assertEqual(jo.insurance_borne_by, "APC")
        self.assertEqual(jo.shipping_arranged_by, "APC")
        self.assertEqual(jo.insurance_required, 1)

    def test_cfr_seller_pays_freight_buyer_insures(self):
        jo = make_job_order(terms_of_delivery="CFR", mode_of_transport="Sea")
        self.assertEqual(jo.freight_borne_by, "APC")
        self.assertEqual(jo.insurance_borne_by, "Customer")
        self.assertEqual(jo.insurance_required, 0)

    def test_cip_requires_all_risk_insurance(self):
        jo = make_job_order(terms_of_delivery="CIP", mode_of_transport="Sea")
        self.assertEqual(jo.insurance_required, 1)
        self.assertEqual(jo.insurance_borne_by, "APC")

    def test_ddp_seller_bears_full_responsibility(self):
        jo = make_job_order(terms_of_delivery="DDP", mode_of_transport="Sea")
        self.assertEqual(jo.freight_borne_by, "APC")
        self.assertEqual(jo.transport_arranged_by, "APC")
        self.assertEqual(jo.shipping_arranged_by, "APC")
        self.assertEqual(jo.transport_required, 1)
        self.assertEqual(jo.shipping_required, 1)

    def test_dpu_added_to_supported_incoterms(self):
        jo = make_job_order(terms_of_delivery="DPU", mode_of_transport="Sea")
        self.assertEqual(jo.freight_borne_by, "APC")
        self.assertIn("AFTER unloading", jo.risk_transfer_point)

    def test_road_mode_skips_shipping_booking_even_for_seller_paid_incoterm(self):
        jo = make_job_order(terms_of_delivery="DAP", mode_of_transport="Road")
        self.assertEqual(jo.shipping_required, 0)
        self.assertEqual(jo.shipping_arranged_by, "Not Applicable")
        self.assertEqual(jo.freight_borne_by, "APC")

    def test_cif_confirmed_without_policy_throws(self):
        jo = make_job_order(terms_of_delivery="CIF", mode_of_transport="Sea")
        jo.status = "Confirmed"
        with self.assertRaises(frappe.ValidationError):
            jo.save()

    def test_create_inward_transport_schedule_creates_inward_ts(self):
        jo = make_job_order(terms_of_delivery="FOB", mode_of_transport="Sea")
        r1 = jo.create_inward_transport_schedule()
        self.assertTrue(r1.get("created"))
        self.assertTrue(r1.get("transport_schedule"))
        ts = frappe.get_doc("Transport Schedule", r1["transport_schedule"])
        self.assertEqual(ts.transport_type, "Inward")
        self.assertEqual(ts.job_order, jo.name)

        r2 = jo.create_inward_transport_schedule()
        self.assertFalse(r2.get("created"))
        self.assertEqual(r1["transport_schedule"], r2["transport_schedule"])

    def test_create_inward_transport_schedule_non_sea_throws(self):
        jo = make_job_order(terms_of_delivery="EXW", mode_of_transport="Road")
        with self.assertRaises(frappe.ValidationError):
            jo.create_inward_transport_schedule()

    def test_default_commercial_movement_is_export(self):
        jo = make_job_order()
        self.assertEqual(jo.commercial_movement, "Export")

    def test_export_requires_customer(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Job Order",
                    "commercial_movement": "Export",
                    "date": today(),
                    "status": "Draft",
                    "terms_of_delivery": "EXW",
                    "mode_of_transport": "Road",
                    "port_of_loading": _ensure_port("APC Test POL-X"),
                    "port_of_discharge": _ensure_port("APC Test POD-X"),
                }
            ).insert(ignore_permissions=True)

    def test_import_requires_supplier(self):
        with self.assertRaises(frappe.ValidationError):
            make_job_order(
                commercial_movement="Import",
                supplier=None,
                customer=None,
                terms_of_delivery="EXW",
                mode_of_transport="Sea",
            )

    def test_import_allowed_without_customer(self):
        jo = make_job_order(
            commercial_movement="Import",
            customer=None,
            supplier=_ensure_supplier(),
            terms_of_delivery="EXW",
            mode_of_transport="Sea",
        )
        self.assertFalse(jo.customer)
        self.assertTrue(jo.supplier)

    def test_import_fob_uses_import_matrix(self):
        jo = make_job_order(
            commercial_movement="Import",
            customer=None,
            supplier=_ensure_supplier(),
            terms_of_delivery="FOB",
            mode_of_transport="Sea",
        )
        self.assertEqual(jo.shipping_arranged_by, "APC")
        self.assertEqual(jo.transport_arranged_by, "Customer")

    def test_import_cif_insurance_not_required_for_apc_policy(self):
        jo = make_job_order(
            commercial_movement="Import",
            customer=None,
            supplier=_ensure_supplier(),
            terms_of_delivery="CIF",
            mode_of_transport="Sea",
        )
        self.assertEqual(jo.insurance_required, 0)

    def test_import_confirm_sea_exw_creates_inward_transport(self):
        jo = make_job_order(
            status="Confirmed",
            commercial_movement="Import",
            customer=None,
            supplier=_ensure_supplier(),
            terms_of_delivery="EXW",
            mode_of_transport="Sea",
        )
        jo.reload()
        self.assertTrue(jo.transport_schedule)
        ts = frappe.get_doc("Transport Schedule", jo.transport_schedule)
        self.assertEqual(ts.transport_type, "Inward")
        self.assertNotEqual(ts.transport_type, "Outward")

    def test_import_sea_job_order_requires_ports(self):
        with self.assertRaises(frappe.ValidationError):
            make_job_order(
                commercial_movement="Import",
                customer=None,
                supplier=_ensure_supplier(),
                mode_of_transport="Sea",
                port_of_loading=None,
                port_of_discharge=None,
            )

    def test_import_placeholder_shipping_booking_uses_tracking_status(self):
        jo = make_job_order(
            status="Confirmed",
            commercial_movement="Import",
            customer=None,
            supplier=_ensure_supplier(),
            terms_of_delivery="FOB",
            mode_of_transport="Sea",
        )
        jo.reload()
        self.assertTrue(jo.shipping_booking)
        sb = frappe.get_doc("Shipping Booking", jo.shipping_booking)
        self.assertEqual(sb.booking_status, "Tracking")
        self.assertEqual(sb.vessel_status, "In Transit")


def make_job_order(**overrides):
    port_of_loading = _ensure_port("APC Test POL")
    port_of_discharge = _ensure_port("APC Test POD")

    values = {
        "doctype": "Job Order",
        "date": today(),
        "status": "Draft",
        "terms_of_delivery": "EXW",
        "mode_of_transport": "Road",
        "commercial_movement": "Export",
        "port_of_loading": port_of_loading,
        "port_of_discharge": port_of_discharge,
    }
    values.update(overrides)
    if values.get("commercial_movement") == "Export" and not values.get("customer"):
        values["customer"] = _ensure_customer()
    if values.get("commercial_movement") == "Import" and "supplier" not in overrides:
        values["supplier"] = _ensure_supplier()

    doc = frappe.get_doc(values)
    doc.insert(ignore_permissions=True)
    return doc


def _ensure_customer():
    name = "APC Test Customer"
    customer_name = frappe.db.get_value("Customer", {"customer_name": name}, "name")
    if customer_name:
        return customer_name

    existing_customer = frappe.db.get_value("Customer", {}, "name")
    if existing_customer:
        return existing_customer

    customer = frappe.get_doc(
        {
            "doctype": "Customer",
            "customer_name": name,
            "customer_type": "Company",
        }
    ).insert(ignore_permissions=True, ignore_mandatory=True)
    return customer.name


def _ensure_port(name):
    if not frappe.db.exists("Port", name):
        frappe.get_doc(
            {
                "doctype": "Port",
                "port_name": name,
                "port_type": "Seaport",
            }
        ).insert(ignore_permissions=True)
    return name


def _ensure_supplier():
    name = "APC Test Import Supplier"
    existing = frappe.db.get_value("Supplier", {"supplier_name": name}, "name")
    if existing:
        return existing
    sup = frappe.get_doc(
        {
            "doctype": "Supplier",
            "supplier_name": name,
            "supplier_type": "Company",
        }
    ).insert(ignore_permissions=True, ignore_mandatory=True)
    return sup.name
