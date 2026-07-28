# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""Tests for Job Order batch allocation dashboard APIs."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, today

from apc_operations.services.job_order_allocation_dashboard import (
    auto_fifo_lines_for_job_order_line,
    get_batches_for_job_order_line,
    get_job_order_allocation_lines,
    get_job_orders_for_allocation_dashboard,
    get_job_orders_for_product_line,
    get_product_lines_for_allocation_dashboard,
    save_job_order_line_allocation,
)
from apc_operations.shipping.doctype.job_order.test_job_order import make_job_order


def _ensure_item(name):
    if frappe.db.exists("Item", name):
        return name
    if not frappe.db.exists("Item Group", "Products"):
        ig = frappe.new_doc("Item Group")
        ig.item_group_name = "Products"
        ig.insert(ignore_permissions=True, ignore_mandatory=True)
    item = frappe.new_doc("Item")
    item.item_code = name
    item.item_name = name
    item.item_group = "Products"
    item.stock_uom = "Nos"
    item.is_stock_item = 1
    item.insert(ignore_permissions=True, ignore_mandatory=True)
    return name


def _make_sales_demand(customer, item, qty=100, grade="A1"):
    sd = frappe.new_doc("APC Sales Demand")
    sd.customer = customer
    sd.sales_order_date = today()
    sd.required_dispatch_date = add_days(today(), 7)
    sd.status = "Confirmed"
    sd.append(
        "items",
        {
            "item": item,
            "item_name": item,
            "grade": grade,
            "specification": "SPEC",
            "packaging_type": "25KG",
            "demand_quantity": qty,
            "allocated_quantity": 0,
        },
    )
    sd.insert(ignore_permissions=True)
    return sd


def _make_batch(product, qty, mfg_offset=-10, grade="A1"):
    batch = frappe.new_doc("APC Batch")
    batch.product = product
    batch.grade = grade
    batch.specification = "SPEC"
    batch.packaging_type = "25KG"
    batch.batch_quantity = qty
    batch.available_quantity = qty
    batch.allocated_quantity = 0
    batch.manufacturing_date = add_days(today(), mfg_offset)
    batch.batch_status = "Active"
    batch.quality_status = "Approved"
    batch.stock_status = "Available"
    batch.insert(ignore_permissions=True)

    coa = frappe.new_doc("APC COA")
    coa.batch = batch.name
    coa.product = product
    coa.approval_status = "Approved"
    coa.approved_by = frappe.session.user
    coa.insert(ignore_permissions=True)
    batch.db_set("linked_coa", coa.name, update_modified=False)
    return batch


class TestJobOrderAllocationDashboard(FrappeTestCase):
    def setUp(self):
        self.item = frappe.db.get_value("Item", {"is_stock_item": 1}, "name")
        if not self.item:
            self.item = _ensure_item("_Test JO Alloc Item")
        self.customer = frappe.db.get_value("Customer", {}, "name")
        if not self.customer:
            self.customer = frappe.new_doc(
                {
                    "doctype": "Customer",
                    "customer_name": "_Test JO Alloc Customer",
                    "customer_type": "Company",
                }
            ).insert(ignore_permissions=True).name

        self.spec = f"JO-ALLOC-{frappe.generate_hash(length=8)}"
        self.sd = _make_sales_demand(self.customer, self.item, qty=100, grade="JO-ALLOC-T")
        self.sd.items[0].specification = self.spec
        self.sd.save(ignore_permissions=True)
        sd_item = self.sd.items[0].name

        self.jo = make_job_order(
            status="Confirmed",
            customer=self.customer,
            sales_demand=self.sd.name,
        )
        self.jo.set("items", [])
        self.jo.append(
            "items",
            {
                "item": self.item,
                "item_name": self.item,
                "grade": "JO-ALLOC-T",
                "specification": self.spec,
                "packaging_type": "25KG",
                "quantity": 100,
                "sales_demand_item": sd_item,
            },
        )
        self.jo.save(ignore_permissions=True)
        self.jo_item = self.jo.items[0].name

        self.batch_old = _make_batch(self.item, 40, mfg_offset=-20, grade="JO-ALLOC-T")
        self.batch_new = _make_batch(self.item, 80, mfg_offset=-5, grade="JO-ALLOC-T")
        self.batch_old.specification = self.spec
        self.batch_old.save(ignore_permissions=True)
        self.batch_new.specification = self.spec
        self.batch_new.save(ignore_permissions=True)
        for batch in (self.batch_old, self.batch_new):
            frappe.db.set_value(
                "APC Batch",
                batch.name,
                {
                    "available_quantity": batch.batch_quantity,
                    "allocated_quantity": 0,
                    "stock_status": "Available",
                    "batch_status": "Active",
                },
                update_modified=False,
            )

    def test_product_lines_and_job_orders_for_product(self):
        products = get_product_lines_for_allocation_dashboard()
        match = next(
            (
                row for row in products
                if row["product"] == self.item
                and row.get("grade") == "JO-ALLOC-T"
                and row.get("specification") == self.spec
            ),
            None,
        )
        self.assertIsNotNone(match)
        self.assertGreaterEqual(flt(match["total_pending_qty"]), 100)

        jo_lines = get_job_orders_for_product_line(
            self.item,
            grade="JO-ALLOC-T",
            specification=self.spec,
            packaging_type="25KG",
        )
        self.assertGreaterEqual(len(jo_lines["lines"]), 1)
        self.assertEqual(jo_lines["lines"][0]["job_order"], self.jo.name)

    def test_job_order_list_includes_summary(self):
        rows = get_job_orders_for_allocation_dashboard()
        match = next((row for row in rows if row["name"] == self.jo.name), None)
        self.assertIsNotNone(match)
        self.assertEqual(match["lines_total"], 1)
        self.assertGreaterEqual(flt(match["total_pending_qty"]), 100)

    def test_allocation_lines_and_fifo_batches(self):
        payload = get_job_order_allocation_lines(self.jo.name)
        self.assertEqual(payload["header"]["job_order"], self.jo.name)
        self.assertEqual(len(payload["lines"]), 1)
        self.assertEqual(flt(payload["lines"][0]["pending_qty"]), 100)

        batch_payload = get_batches_for_job_order_line(self.jo.name, self.jo_item)
        batches = batch_payload["batches"]
        self.assertGreaterEqual(len(batches), 2)
        self.assertEqual(batches[0]["name"], self.batch_old.name)

    def test_auto_fifo_and_save_allocation(self):
        suggestion = auto_fifo_lines_for_job_order_line(self.jo.name, self.jo_item)
        self.assertGreaterEqual(len(suggestion["lines"]), 2)
        self.assertEqual(flt(suggestion["remaining_shortage"]), 0)
        total = sum(flt(line["allocated_quantity"]) for line in suggestion["lines"])
        self.assertEqual(total, 100)
        self.assertEqual(suggestion["lines"][0]["batch"], self.batch_old.name)

        result = save_job_order_line_allocation(
            self.jo.name,
            self.jo_item,
            suggestion["lines"],
        )
        self.assertTrue(result["success"])
        self.assertEqual(flt(result["remaining_pending"]), 0)

        sd_item = frappe.get_doc("APC Sales Demand Item", self.sd.items[0].name)
        self.assertEqual(flt(sd_item.allocated_quantity), 100)

    def test_sync_loading_dn_from_job_order_allocations(self):
        from apc_operations.services.batch_allocation import sync_loading_dn_from_job_order_allocations

        suggestion = auto_fifo_lines_for_job_order_line(self.jo.name, self.jo_item)
        save_job_order_line_allocation(self.jo.name, self.jo_item, suggestion["lines"])

        ldn = frappe.new_doc("Loading Delivery Note")
        ldn.job_order = self.jo.name
        ldn.customer = self.customer
        ldn.loading_date = today()
        ldn.delivery_note_status = "Pending QC"
        ldn.qc_status = "Pending QC"
        ldn.insert(ignore_permissions=True)

        result = sync_loading_dn_from_job_order_allocations(ldn.name)
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(flt(result["total_allocated"]), 100)

        ldn.reload()
        self.assertEqual(len(ldn.batch_allocations), 2)
        self.assertEqual(ldn.delivery_note_status, "Pending QC")
        row_batches = sorted(ldn.batch_allocations, key=lambda row: row.fifo_sequence)
        self.assertEqual(row_batches[0].batch, self.batch_old.name)
        self.assertTrue(all(row.batch_allocation_detail for row in ldn.batch_allocations))
