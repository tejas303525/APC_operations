# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Smoke tests for the Transportation Console API.

These tests exercise:
- The pure helpers in ``apc_operations.services.console_status`` that
  back the Transportation Console badges.
- The whitelisted endpoint surface (each list/detail/pending-counts
  endpoint is callable and returns the expected shape) on whatever
  data the site currently has.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from apc_operations.services import console_status
from apc_operations.shipping.doctype.job_order.test_job_order import (
	_ensure_supplier,
	make_job_order,
)
from apc_operations.transportation import api as transportation_api


class TestTransportationConsoleStatus(FrappeTestCase):
	"""Pure-Python status mapping for the Transportation Console."""

	def test_docs_status_label(self):
		self.assertEqual(console_status.docs_status_label("Delivered"), "Cleared")
		self.assertEqual(console_status.docs_status_label("Completed"), "Cleared")
		self.assertEqual(console_status.docs_status_label("Scheduled"), "Uncleared")
		self.assertEqual(console_status.docs_status_label(None), "Uncleared")
		self.assertEqual(console_status.docs_status_label("Cancelled"), "Hidden")

	def test_vessel_status_label_defaults_in_transit(self):
		self.assertEqual(console_status.vessel_status_label(None), "In Transit")
		self.assertEqual(console_status.vessel_status_label("Berthed"), "Berthed")

	def test_transport_booking_label(self):
		self.assertEqual(console_status.transport_booking_label("Draft"), "Pending")
		self.assertEqual(
			console_status.transport_booking_label("Pending Assignment"), "Pending"
		)
		self.assertEqual(console_status.transport_booking_label("Scheduled"), "Booked")
		self.assertEqual(
			console_status.transport_booking_label("Vehicle Assigned"), "Booked"
		)

	def test_can_generate_delivery_order_allowlist(self):
		for status in ("Vehicle Assigned", "Driver Assigned", "Scheduled", "Dispatched"):
			self.assertTrue(console_status.can_generate_delivery_order(status), status)
		for status in ("Draft", "Pending Assignment", "Delivered", "Completed", None):
			self.assertFalse(console_status.can_generate_delivery_order(status), status)

	def test_filter_visible_transport_statuses(self):
		rows = [
			{"transport_status": "Scheduled"},
			{"transport_status": "Cancelled"},
			{"transport_status": "Delivered"},
		]
		visible = console_status.filter_visible_transport_statuses(rows)
		self.assertEqual(len(visible), 2)
		self.assertTrue(all(r["transport_status"] != "Cancelled" for r in visible))


class TestTransportationConsoleApi(FrappeTestCase):
	"""Endpoint surface — each list endpoint returns a list."""

	def test_list_endpoints_return_lists(self):
		endpoints = [
			transportation_api.get_inward_import_list,
			transportation_api.get_inward_land_list,
			transportation_api.get_local_delivery_list,
			transportation_api.get_export_container_list,
			transportation_api.get_grn_summary_list,
		]
		for fn in endpoints:
			rows = fn()
			self.assertIsInstance(rows, list, fn.__name__)

	def test_pending_counts_shape(self):
		counts = transportation_api.get_transportation_pending_counts()
		self.assertIsInstance(counts, dict)
		self.assertEqual(
			set(counts.keys()),
			{"transport", "do", "sddn", "partial_followup", "grn_summary"},
		)
		for value in counts.values():
			self.assertIsInstance(value, int)

	def test_active_transport_for_job_order_respects_movement(self):
		imp = make_job_order(
			status="Confirmed",
			commercial_movement="Import",
			customer=None,
			supplier=_ensure_supplier(),
			terms_of_delivery="EXW",
			mode_of_transport="Sea",
		)
		row = transportation_api._active_transport_for_job_order(imp.name)
		self.assertTrue(row)
		self.assertEqual(row.get("transport_type"), "Inward")

		exp = make_job_order(
			status="Confirmed",
			commercial_movement="Outward",
			terms_of_delivery="FOB",
			mode_of_transport="Sea",
		)
		row_o = transportation_api._active_transport_for_job_order(exp.name)
		self.assertTrue(row_o)
		self.assertEqual(row_o.get("transport_type"), "Outward")

	def test_update_inward_import_tracking_on_placeholder_shipping_booking(self):
		imp = make_job_order(
			status="Confirmed",
			commercial_movement="Import",
			customer=None,
			supplier=_ensure_supplier(),
			terms_of_delivery="FOB",
			mode_of_transport="Sea",
		)
		imp.reload()
		self.assertTrue(imp.shipping_booking)

		result = transportation_api.update_inward_import_tracking(
			imp.name,
			vessel_status="Berthed",
			cutoff_date="2026-05-20",
			remarks="Vessel berthed at POD",
		)
		self.assertEqual(result.get("vessel_status_value"), "Berthed")
		self.assertEqual(str(result.get("cutoff_date")), "2026-05-20")

		sb_status = frappe.db.get_value(
			"Shipping Booking", imp.shipping_booking, "vessel_status"
		)
		self.assertEqual(sb_status, "Berthed")
		sb_cutoff = frappe.db.get_value(
			"Shipping Booking", imp.shipping_booking, "cutoff_date"
		)
		self.assertEqual(str(sb_cutoff), "2026-05-20")
		self.assertEqual(
			frappe.db.get_value("Job Order", imp.name, "loading_remarks"),
			"Vessel berthed at POD",
		)

	def test_inward_land_detail_exposes_delivery_order_fields_for_road_import(self):
		from apc_operations.tests.test_import_delivery_order_path import (
			_ensure_driver,
			_ensure_vehicle,
		)

		jo = make_job_order(
			status="Confirmed",
			commercial_movement="Import",
			customer=None,
			supplier=_ensure_supplier(),
			terms_of_delivery="EXW",
			mode_of_transport="Road",
		)
		jo.reload()
		self.assertEqual(jo.mode_of_transport, "Road")
		ts = frappe.get_doc("Transport Schedule", jo.transport_schedule)
		self.assertEqual(ts.transport_type, "Inward")
		ts.assigned_vehicle = _ensure_vehicle()
		ts.assigned_driver = _ensure_driver()
		ts.transport_status = "Driver Assigned"
		ts.save(ignore_permissions=True)

		land_rows = transportation_api.get_inward_land_list()
		land_jobs = {r.get("job_order") for r in land_rows}
		self.assertIn(jo.name, land_jobs)

		detail = transportation_api.get_inward_land_detail(jo.name)
		self.assertEqual(detail["commercial_movement"], "Import")
		self.assertTrue(detail["can_generate_do"])
		self.assertEqual(detail["transport_schedule"], ts.name)
		self.assertTrue(detail["is_transport_booked"])

	def test_partial_followup_list_returns_list(self):
		rows = transportation_api.get_partial_delivery_followup_list()
		self.assertIsInstance(rows, list)

	def test_create_partial_followup_transport_new_leg(self):
		from apc_operations.shipping.doctype.job_order.test_job_order import (
			_ensure_customer,
			make_job_order,
		)
		from apc_operations.tests.test_confirm_dispatch_validation import (
			_make_approved_coa,
			_make_batch,
		)
		from apc_operations.tests.test_option_b_schema import _ensure_item

		customer = _ensure_customer()
		product = _ensure_item("_Test Item Option B")
		sd = frappe.new_doc("APC Sales Demand")
		sd.customer = customer
		sd.sales_order_date = today()
		sd.required_dispatch_date = today()
		sd.append("items", {"item": product, "demand_quantity": 1000, "uom": "Nos"})
		sd.insert(ignore_permissions=True)
		sd.db_set(
			{
				"total_demand_quantity": 1000,
				"total_dispatched_quantity": 600,
				"status": "Partially Dispatched",
			},
			update_modified=False,
		)

		jo = make_job_order(
			status="Confirmed",
			terms_of_delivery="EXW",
			mode_of_transport="Road",
			sales_demand=sd.name,
		)
		jo.append("items", {"item": product, "quantity": 1000, "uom": "Nos"})
		jo.save(ignore_permissions=True)
		jo.reload()
		first_ts = jo.transport_schedule
		self.assertTrue(first_ts)

		batch = _make_batch(product=product, batch_qty=1000, stock_status="Available")
		coa = _make_approved_coa(batch.name)
		ldn = frappe.new_doc("Loading Delivery Note")
		ldn.job_order = jo.name
		ldn.customer = jo.customer
		ldn.loading_date = today()
		ldn.dispatch_confirmed = 1
		ldn.append(
			"batch_allocations",
			{
				"batch": batch.name,
				"batch_number": batch.batch_number,
				"product": product,
				"allocated_qty": 600,
				"dispatched_qty": 600,
				"coa": coa.name,
			},
		)
		ldn.insert(ignore_permissions=True)

		frappe.db.set_value(
			"Transport Schedule", first_ts, "transport_status", "Completed", update_modified=False
		)

		rows = transportation_api.get_partial_delivery_followup_list(only_actionable=1)
		names = {r["job_order"] for r in rows}
		self.assertIn(jo.name, names)
		match = next(r for r in rows if r["job_order"] == jo.name)
		self.assertEqual(flt(match["job_order_quantity"]), 1000.0)
		self.assertEqual(flt(match["total_dispatched_quantity"]), 600.0)

		res = transportation_api.create_partial_delivery_followup_transport(jo.name)
		self.assertTrue(res.get("is_follow_up_leg"))
		self.assertNotEqual(res["transport_schedule"], first_ts)
		self.assertEqual(
			frappe.db.get_value("Job Order", jo.name, "transport_schedule"),
			res["transport_schedule"],
		)
		self.assertEqual(frappe.db.get_value("Job Order", jo.name, "status"), "In Progress")

		vehicle = _ensure_test_vehicle()
		driver = _ensure_test_driver()
		transportation_api.book_transport_schedule(
			res["transport_schedule"],
			assigned_vehicle=vehicle,
			assigned_driver=driver,
		)

		from apc_operations.shipping.api import generate_followup_delivery_order_for_export
		from apc_operations.shipping.services.delivery_order_generation_service import (
			get_followup_delivery_order_eligibility,
		)

		eligibility = get_followup_delivery_order_eligibility(jo.name)
		self.assertTrue(eligibility.get("can_issue_followup_do"))

		detail = transportation_api.get_partial_delivery_followup_detail(jo.name)
		self.assertTrue(detail.get("can_issue_followup_do"))
		self.assertEqual(detail.get("transport_schedule"), res["transport_schedule"])
		self.assertEqual(flt(detail.get("pending_dispatch_quantity")), 400.0)

		do_result = generate_followup_delivery_order_for_export(jo.name)
		self.assertTrue(do_result.get("created"))
		self.assertTrue(do_result.get("is_follow_up_do"))
		do = frappe.get_doc("Delivery Order", do_result["delivery_order"])
		do_qty = sum(flt(row.qty) for row in do.items)
		self.assertEqual(do_qty, 400.0)
		self.assertEqual(do.transport_schedule, res["transport_schedule"])

	def test_followup_do_blocked_while_open_do_exists(self):
		from apc_operations.shipping.doctype.job_order.test_job_order import (
			_ensure_customer,
			make_job_order,
		)
		from apc_operations.tests.test_confirm_dispatch_validation import (
			_make_approved_coa,
			_make_batch,
		)
		from apc_operations.tests.test_option_b_schema import _ensure_item

		customer = _ensure_customer()
		product = _ensure_item("_Test Item Option B")
		jo = make_job_order(
			status="Confirmed",
			terms_of_delivery="EXW",
			mode_of_transport="Road",
		)
		jo.append("items", {"item": product, "quantity": 1000, "uom": "Nos"})
		jo.save(ignore_permissions=True)
		jo.reload()
		first_ts = jo.transport_schedule

		batch = _make_batch(product=product, batch_qty=1000, stock_status="Available")
		coa = _make_approved_coa(batch.name)
		ldn = frappe.new_doc("Loading Delivery Note")
		ldn.job_order = jo.name
		ldn.customer = jo.customer
		ldn.loading_date = today()
		ldn.dispatch_confirmed = 1
		ldn.append(
			"batch_allocations",
			{
				"batch": batch.name,
				"batch_number": batch.batch_number,
				"product": product,
				"allocated_qty": 600,
				"dispatched_qty": 600,
				"coa": coa.name,
			},
		)
		ldn.insert(ignore_permissions=True)

		open_do = frappe.new_doc("Delivery Order")
		open_do.job_order = jo.name
		open_do.customer = jo.customer
		open_do.company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
			"Global Defaults", "default_company"
		)
		open_do.posting_date = today()
		open_do.operational_status = "Draft"
		open_do.append("items", {"item_code": product, "qty": 600, "uom": "Nos"})
		open_do.insert(ignore_permissions=True)

		frappe.db.set_value(
			"Transport Schedule", first_ts, "transport_status", "Completed", update_modified=False
		)

		res = transportation_api.create_partial_delivery_followup_transport(jo.name)
		transportation_api.book_transport_schedule(
			res["transport_schedule"],
			assigned_vehicle=_ensure_test_vehicle(),
			assigned_driver=_ensure_test_driver(),
		)
		frappe.db.set_value(
			"Delivery Order",
			open_do.name,
			"transport_schedule",
			res["transport_schedule"],
			update_modified=False,
		)

		from apc_operations.shipping.services.delivery_order_generation_service import (
			get_followup_delivery_order_eligibility,
		)

		eligibility = get_followup_delivery_order_eligibility(
			jo.name, transport_schedule=res["transport_schedule"]
		)
		self.assertFalse(eligibility.get("can_issue_followup_do"))
		self.assertEqual(eligibility.get("do_name"), open_do.name)

	def test_resolve_do_for_sddn_does_not_relink_existing_do_to_new_leg(self):
		from apc_operations.services.delivery_order_service import resolve_do_for_sddn
		from apc_operations.shipping.doctype.job_order.test_job_order import make_job_order
		from apc_operations.tests.test_option_b_schema import _ensure_item

		product = _ensure_item("_Test Item Option B")
		jo = make_job_order(status="Confirmed", terms_of_delivery="EXW", mode_of_transport="Road")
		jo.save(ignore_permissions=True)
		first_ts = jo.transport_schedule

		company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
			"Global Defaults", "default_company"
		)
		first_do = frappe.new_doc("Delivery Order")
		first_do.job_order = jo.name
		first_do.customer = jo.customer
		first_do.company = company
		first_do.posting_date = today()
		first_do.transport_schedule = first_ts
		first_do.append("items", {"item_code": product, "qty": 10, "uom": "Nos"})
		first_do.insert(ignore_permissions=True)

		new_ts = frappe.new_doc("Transport Schedule")
		new_ts.job_order = jo.name
		new_ts.customer = jo.customer
		new_ts.transport_type = "Outward"
		new_ts.outward_type = "Local Delivery"
		new_ts.transport_status = "Pending Assignment"
		new_ts.scheduled_pickup_date = today()
		new_ts.scheduled_delivery_date = today()
		new_ts.insert(ignore_permissions=True)

		new_sddn = frappe.new_doc("Security Draft Delivery Note")
		new_sddn.transport_schedule = new_ts.name
		new_sddn.job_order = jo.name
		new_sddn.customer = jo.customer
		new_sddn.transport_type = "Outward"
		new_sddn.outward_type = "Local Delivery"
		new_sddn.insert(ignore_permissions=True, ignore_links=True)
		frappe.db.set_value(
			"Transport Schedule",
			new_ts.name,
			"security_draft_delivery_note",
			new_sddn.name,
			update_modified=False,
		)

		resolved = resolve_do_for_sddn(new_sddn.name)
		self.assertIsNone(resolved)
		self.assertEqual(
			frappe.db.get_value("Delivery Order", first_do.name, "transport_schedule"),
			first_ts,
		)

	def test_partial_followup_without_sales_demand_uses_jo_and_ldn(self):
		from apc_operations.shipping.doctype.job_order.test_job_order import make_job_order
		from apc_operations.tests.test_confirm_dispatch_validation import (
			_make_approved_coa,
			_make_batch,
		)
		from apc_operations.tests.test_option_b_schema import _ensure_item

		product = _ensure_item("_Test Item Option B")
		jo = make_job_order(
			status="Confirmed",
			terms_of_delivery="EXW",
			mode_of_transport="Road",
		)
		jo.append("items", {"item": product, "quantity": 800, "uom": "Nos"})
		jo.save(ignore_permissions=True)
		jo.reload()
		first_ts = jo.transport_schedule
		self.assertTrue(first_ts)

		batch = _make_batch(product=product, batch_qty=800, stock_status="Available")
		coa = _make_approved_coa(batch.name)
		ldn = frappe.new_doc("Loading Delivery Note")
		ldn.job_order = jo.name
		ldn.customer = jo.customer
		ldn.loading_date = today()
		ldn.dispatch_confirmed = 1
		ldn.append(
			"batch_allocations",
			{
				"batch": batch.name,
				"batch_number": batch.batch_number,
				"product": product,
				"allocated_qty": 300,
				"dispatched_qty": 300,
				"coa": coa.name,
			},
		)
		ldn.insert(ignore_permissions=True)

		frappe.db.set_value(
			"Transport Schedule", first_ts, "transport_status", "Completed", update_modified=False
		)

		summary = transportation_api._partial_dispatch_summary(jo.name)
		self.assertIsNotNone(summary)
		self.assertEqual(flt(summary["job_order_quantity"]), 800.0)
		self.assertEqual(flt(summary["total_dispatched_quantity"]), 300.0)
		self.assertEqual(flt(summary["pending_dispatch_quantity"]), 500.0)

		rows = transportation_api.get_partial_delivery_followup_list(only_actionable=1)
		self.assertIn(jo.name, {r["job_order"] for r in rows})

	def test_partial_followup_with_issued_ldn_without_completed_transport(self):
		from apc_operations.shipping.doctype.job_order.test_job_order import make_job_order
		from apc_operations.tests.test_confirm_dispatch_validation import (
			_make_approved_coa,
			_make_batch,
		)
		from apc_operations.tests.test_option_b_schema import _ensure_item

		product = _ensure_item("_Test Item Option B")
		jo = make_job_order(
			status="Confirmed",
			terms_of_delivery="EXW",
			mode_of_transport="Road",
		)
		jo.append("items", {"item": product, "quantity": 10, "uom": "Nos"})
		jo.save(ignore_permissions=True)
		jo.reload()
		first_ts = jo.transport_schedule
		self.assertTrue(first_ts)

		batch = _make_batch(product=product, batch_qty=10, stock_status="Available")
		coa = _make_approved_coa(batch.name)
		ldn = frappe.new_doc("Loading Delivery Note")
		ldn.job_order = jo.name
		ldn.customer = jo.customer
		ldn.loading_date = today()
		ldn.dispatch_confirmed = 1
		ldn.append(
			"batch_allocations",
			{
				"batch": batch.name,
				"batch_number": batch.batch_number,
				"product": product,
				"allocated_qty": 8,
				"dispatched_qty": 8,
				"coa": coa.name,
			},
		)
		ldn.insert(ignore_permissions=True)

		frappe.db.set_value(
			"Transport Schedule",
			first_ts,
			"transport_status",
			"Driver Assigned",
			update_modified=False,
		)

		summary = transportation_api._partial_dispatch_summary(jo.name)
		self.assertEqual(flt(summary["pending_dispatch_quantity"]), 2.0)

		row = transportation_api._partial_followup_row(
			{
				"name": jo.name,
				"job_order_number": jo.job_order_number,
				"customer": jo.customer,
				"customer_name": jo.customer_name,
				"port_of_discharge": jo.port_of_discharge,
			}
		)
		self.assertIsNotNone(row)
		self.assertEqual(flt(row["pending_dispatch_quantity"]), 2.0)
		self.assertTrue(row["followup_needed"])

		rows = transportation_api.get_partial_delivery_followup_list(only_actionable=1)
		self.assertIn(jo.name, {r["job_order"] for r in rows})

		res = transportation_api.create_partial_delivery_followup_transport(jo.name)
		self.assertNotEqual(res["transport_schedule"], first_ts)


def _ensure_test_vehicle():
	name = frappe.db.get_value("Vehicle", {}, "name")
	if name:
		return name
	doc = frappe.get_doc(
		{
			"doctype": "Vehicle",
			"license_plate": "PFU-TEST-01",
			"make": "Test",
			"model": "Truck",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_test_driver():
	name = frappe.db.get_value("Driver", {}, "name")
	if name:
		return name
	doc = frappe.get_doc({"doctype": "Driver", "full_name": "Partial Follow-up Driver"})
	doc.insert(ignore_permissions=True)
	return doc.name
