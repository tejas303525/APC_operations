# Copyright (c) 2026, APC and contributors

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from apc_operations.shipping.doctype.job_order.test_job_order import (
	_ensure_customer,
	_ensure_port,
	_ensure_supplier,
	make_job_order,
)
from apc_operations.shipping.services.delivery_order_generation_service import (
	APC_IMPORT_CUSTOMER_LABEL,
	_ensure_apc_customer,
	generate_delivery_order_for_job_order,
	try_auto_issue_import_delivery_order,
)
from apc_operations.shipping.services.import_handoff_service import (
	create_export_job_order_from_import,
	link_import_to_export_job_order,
)


class TestImportDeliveryOrderPath(FrappeTestCase):
	def setUp(self):
		_ensure_apc_customer_for_tests()
		frappe.db.set_single_value("APC Operations Settings", "zoho_dispatch_sync_enabled", 1)
		frappe.db.set_single_value("APC Operations Settings", "zoho_dispatch_stub_only", 1)

	def test_generate_import_delivery_order(self):
		jo = make_job_order(
			status="Confirmed",
			commercial_movement="Import",
			customer=None,
			supplier=_ensure_supplier(),
			terms_of_delivery="FOB",
			mode_of_transport="Sea",
		)
		jo.reload()
		ts = frappe.get_doc("Transport Schedule", jo.transport_schedule)
		ts.assigned_vehicle = _ensure_vehicle()
		ts.assigned_driver = _ensure_driver()
		ts.transport_status = "Driver Assigned"
		ts.save(ignore_permissions=True)

		if jo.shipping_booking:
			frappe.db.set_value(
				"Shipping Booking", jo.shipping_booking, "vessel_status", "Cleared"
			)

		result = generate_delivery_order_for_job_order(
			jo.name, movement="Import", auto_issue_to_security=True
		)
		self.assertTrue(result.get("delivery_order"))
		do = frappe.get_doc("Delivery Order", result["delivery_order"])
		self.assertEqual((do.commercial_movement or "").strip(), "Import")
		apc_customer, _ = _ensure_apc_customer()
		self.assertEqual(do.customer, apc_customer)
		self.assertEqual(do.job_order, jo.name)
		self.assertTrue(do.pre_check_clearance or frappe.db.exists(
			"Pre-Check Clearance", {"delivery_order": do.name}
		))

	def test_auto_issue_creates_do_and_sddn(self):
		jo = make_job_order(
			status="Confirmed",
			commercial_movement="Import",
			customer=None,
			supplier=_ensure_supplier(),
			terms_of_delivery="EXW",
			mode_of_transport="Sea",
		)
		jo.reload()
		ts = frappe.get_doc("Transport Schedule", jo.transport_schedule)
		ts.assigned_vehicle = _ensure_vehicle()
		ts.assigned_driver = _ensure_driver()
		ts.save(ignore_permissions=True)
		if jo.shipping_booking:
			frappe.db.set_value(
				"Shipping Booking", jo.shipping_booking, "vessel_status", "Cleared"
			)

		ts.ensure_inward_follow_up_records()
		do_name = frappe.db.get_value(
			"Delivery Order", {"job_order": jo.name}, "name"
		)
		self.assertTrue(do_name)
		sddn = frappe.db.get_value(
			"Security Draft Delivery Note",
			{"transport_schedule": ts.name},
			"name",
		)
		self.assertTrue(sddn)

	def test_export_handoff_from_import(self):
		jo = make_job_order(
			status="Confirmed",
			commercial_movement="Import",
			customer=None,
			supplier=_ensure_supplier(),
			mode_of_transport="Sea",
		)
		jo.reload()
		ts = frappe.get_doc("Transport Schedule", jo.transport_schedule)
		ts.assigned_vehicle = _ensure_vehicle()
		ts.assigned_driver = _ensure_driver()
		ts.save(ignore_permissions=True)
		if jo.shipping_booking:
			frappe.db.set_value(
				"Shipping Booking", jo.shipping_booking, "vessel_status", "Cleared"
			)
		try_auto_issue_import_delivery_order(jo.name, transport_schedule=ts.name)
		ts.ensure_inward_follow_up_records()

		do_name = frappe.db.get_value("Delivery Order", {"job_order": jo.name}, "name")
		frappe.db.set_value(
			"Delivery Order", do_name, "operational_status", "QC Pre-check Passed"
		)
		pcc = frappe.db.get_value("Delivery Order", do_name, "pre_check_clearance")
		if pcc:
			frappe.db.set_value("Pre-Check Clearance", pcc, "qc_status", "Passed")

		export_customer = _ensure_customer()
		created = create_export_job_order_from_import(jo.name, customer=export_customer)
		self.assertTrue(created.get("export_job_order"))
		self.assertEqual(
			frappe.db.get_value("Job Order", jo.name, "linked_export_job_order"),
			created["export_job_order"],
		)

		export_jo = make_job_order(status="Draft", commercial_movement="Outward")
		jo2 = make_job_order(
			status="Confirmed",
			commercial_movement="Import",
			customer=None,
			supplier=_ensure_supplier(),
			mode_of_transport="Sea",
		)
		jo2.reload()
		ts2 = frappe.get_doc("Transport Schedule", jo2.transport_schedule)
		ts2.assigned_vehicle = _ensure_vehicle()
		ts2.assigned_driver = _ensure_driver()
		ts2.save(ignore_permissions=True)
		if jo2.shipping_booking:
			frappe.db.set_value(
				"Shipping Booking", jo2.shipping_booking, "vessel_status", "Cleared"
			)
		generate_delivery_order_for_job_order(jo2.name, movement="Import")
		do2 = frappe.db.get_value("Delivery Order", {"job_order": jo2.name}, "name")
		frappe.db.set_value(
			"Delivery Order", do2, "operational_status", "QC Pre-check Passed"
		)
		link_import_to_export_job_order(jo2.name, export_jo.name)
		self.assertEqual(
			frappe.db.get_value("Job Order", jo2.name, "linked_export_job_order"),
			export_jo.name,
		)


def _ensure_vehicle():
	name = frappe.db.get_value("Vehicle", {}, "name")
	if name:
		return name
	doc = frappe.get_doc(
		{
			"doctype": "Vehicle",
			"license_plate": "IMP-TEST-01",
			"make": "Test",
			"model": "Truck",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_apc_customer_for_tests():
	name = frappe.db.get_value(
		"Customer", {"customer_name": APC_IMPORT_CUSTOMER_LABEL}, "name"
	)
	if name:
		return name
	group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	payload = {
		"doctype": "Customer",
		"customer_name": APC_IMPORT_CUSTOMER_LABEL,
		"customer_type": "Company",
	}
	if group:
		payload["customer_group"] = group
	doc = frappe.get_doc(payload)
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	return doc.name


def _ensure_driver():
	name = frappe.db.get_value("Driver", {}, "name")
	if name:
		return name
	doc = frappe.get_doc({"doctype": "Driver", "full_name": "Import Test Driver"})
	doc.insert(ignore_permissions=True)
	return doc.name
