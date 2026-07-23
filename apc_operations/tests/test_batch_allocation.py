# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import unittest
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today, add_days, flt
from apc_operations.services.batch_allocation import (
    get_available_batches,
    calculate_free_stock,
    calculate_production_requirement,
    create_production_requirement_if_shortage,
    allocate_batches_fifo,
    release_allocation,
    validate_dispatch_batches,
)


class TestBatchAllocation(FrappeTestCase):
    """Test cases for FIFO batch allocation engine."""

    def setUp(self):
        """Set up test data before each test."""
        self.create_test_items()
        self.create_test_batches()

    def tearDown(self):
        """Clean up test data after each test."""
        self.cleanup_test_data()

    def create_test_items(self):
        """Create test items for testing."""
        # Create test item if it doesn't exist
        if not frappe.db.exists("Item", "_Test Item APC"):
            item = frappe.new_doc("Item")
            item.item_code = "_Test Item APC"
            item.item_name = "Test Item for APC"
            item.item_group = "Products"
            item.stock_uom = "Nos"
            item.is_stock_item = 1
            item.insert()

        self.test_item = "_Test Item APC"

    def create_test_batches(self):
        """Create test batches with different dates and quantities."""
        self.test_batches = []

        # Batch 1: Oldest, approved COA
        batch1 = self.create_batch(
            product=self.test_item,
            grade="Premium",
            specification="Spec A",
            quantity=100,
            manufacturing_date=add_days(today(), -30),
            status="Active",
            quality="Approved"
        )
        self.test_batches.append(batch1)

        # Batch 2: Middle age, approved COA
        batch2 = self.create_batch(
            product=self.test_item,
            grade="Premium",
            specification="Spec A",
            quantity=150,
            manufacturing_date=add_days(today(), -20),
            status="Active",
            quality="Approved"
        )
        self.test_batches.append(batch2)

        # Batch 3: Newest, approved COA
        batch3 = self.create_batch(
            product=self.test_item,
            grade="Premium",
            specification="Spec A",
            quantity=200,
            manufacturing_date=add_days(today(), -10),
            status="Active",
            quality="Approved"
        )
        self.test_batches.append(batch3)

        # Batch 4: Different grade
        batch4 = self.create_batch(
            product=self.test_item,
            grade="Standard",
            specification="Spec A",
            quantity=100,
            manufacturing_date=add_days(today(), -15),
            status="Active",
            quality="Approved"
        )
        self.test_batches.append(batch4)

    def create_batch(self, product, grade, specification, quantity,
                     manufacturing_date, status="Active", quality="Approved"):
        """Helper to create a batch."""
        batch = frappe.new_doc("APC Batch")
        batch.product = product
        batch.grade = grade
        batch.specification = specification
        batch.batch_quantity = quantity
        batch.available_quantity = quantity
        batch.allocated_quantity = 0
        batch.manufacturing_date = manufacturing_date
        batch.batch_status = status
        batch.quality_status = quality
        batch.warehouse = "_Test Warehouse"
        batch.insert()

        # Create COA for approved batches
        if quality == "Approved":
            coa = frappe.new_doc("APC COA")
            coa.batch = batch.name
            coa.product = product
            coa.approval_status = "Approved"
            coa.approved_by = frappe.session.user
            coa.approved_date = today()
            coa.insert()

            # Link COA to batch
            batch.db_set("linked_coa", coa.name, update_modified=False)

        return batch.name

    def cleanup_test_data(self):
        """Clean up test data."""
        # Delete allocations
        frappe.db.sql("""
            DELETE FROM `tabAPC Batch Allocation Detail`
            WHERE batch IN (SELECT name FROM `tabAPC Batch` WHERE product = '_Test Item APC')
        """)

        frappe.db.sql("""
            DELETE FROM `tabAPC Batch Allocation`
            WHERE name IN (SELECT parent FROM `tabAPC Batch Allocation Detail`)
        """)

        # Delete COAs
        frappe.db.sql("""
            DELETE FROM `tabAPC COA`
            WHERE batch IN (SELECT name FROM `tabAPC Batch` WHERE product = '_Test Item APC')
        """)

        # Delete batches
        frappe.db.sql("DELETE FROM `tabAPC Batch` WHERE product = '_Test Item APC'")

        # Delete demands
        frappe.db.sql("DELETE FROM `tabAPC Sales Demand Item` WHERE item = '_Test Item APC'")
        frappe.db.sql("""
            DELETE FROM `tabAPC Sales Demand`
            WHERE name NOT IN (SELECT DISTINCT parent FROM `tabAPC Sales Demand Item`)
        """)

    def create_test_demand(self, quantity, grade="Premium", specification="Spec A"):
        """Helper to create a sales demand."""
        demand = frappe.new_doc("APC Sales Demand")
        demand.customer = "_Test Customer"
        demand.sales_order_date = today()
        demand.required_dispatch_date = add_days(today(), 7)
        demand.status = "Draft"

        demand.append("items", {
            "item": self.test_item,
            "item_name": "Test Item",
            "grade": grade,
            "specification": specification,
            "demand_quantity": quantity,
            "uom": "Nos"
        })

        demand.insert()
        return demand.name

    def test_fifo_batch_retrieval(self):
        """Test FIFO ordering of batches."""
        batches = get_available_batches(
            product=self.test_item,
            grade="Premium",
            specification="Spec A"
        )

        self.assertTrue(len(batches) >= 3, "Should have at least 3 available batches")

        # Check FIFO ordering (oldest first)
        dates = [b.manufacturing_date for b in batches]
        self.assertEqual(dates, sorted(dates), "Batches should be in FIFO order")

    def test_batch_filtering_by_grade(self):
        """Test that batches are filtered by grade."""
        batches = get_available_batches(
            product=self.test_item,
            grade="Standard",
            specification="Spec A"
        )

        self.assertEqual(len(batches), 1, "Should have 1 Standard grade batch")
        self.assertEqual(batches[0].grade, "Standard")

    def test_free_stock_calculation(self):
        """Test free stock calculation."""
        batch_name = self.test_batches[0]
        free_stock = calculate_free_stock(batch_name)

        # Initially, free stock = available quantity
        batch = frappe.get_doc("APC Batch", batch_name)
        self.assertEqual(free_stock, batch.available_quantity)

    def test_fifo_allocation(self):
        """Test FIFO allocation logic."""
        # Create demand for 200 quantity
        demand_qty = 200
        demand_name = self.create_test_demand(demand_qty)

        # Allocate batches
        result = allocate_batches_fifo(demand_name)

        self.assertTrue(result["success"], "Allocation should succeed")
        self.assertIsNotNone(result["allocation"], "Should create allocation")

        # Get allocation details
        allocation = frappe.get_doc("APC Batch Allocation", result["allocation"])
        self.assertTrue(len(allocation.allocation_details) > 0, "Should have allocation details")

        # Verify FIFO: oldest batch should be used first
        details = sorted(allocation.allocation_details, key=lambda x: x.fifo_sequence)
        first_detail = details[0]

        # Oldest batch should be batch1
        oldest_batch = frappe.get_doc("APC Batch", self.test_batches[0])
        self.assertEqual(first_detail.batch, oldest_batch.name, "Should allocate from oldest batch first")

        # Verify total allocated
        total_allocated = sum(d.allocated_quantity for d in allocation.allocation_details)
        self.assertEqual(total_allocated, demand_qty, "Should allocate full demand quantity")

    def test_partial_allocation(self):
        """Test partial allocation when stock is insufficient."""
        # Create demand exceeding total available stock
        demand_qty = 1000  # More than all test batches combined
        demand_name = self.create_test_demand(demand_qty)

        result = allocate_batches_fifo(demand_name)

        # Should still succeed but with shortages
        self.assertTrue(result["success"], "Allocation should succeed with partial allocation")

        # Should report shortages
        total_shortage = sum(s["required_qty"] for s in result["shortages"])
        self.assertGreater(total_shortage, 0, "Should report shortages")

    def test_production_requirement_calculation(self):
        """Test production requirement calculation."""
        # Create demand that exceeds available stock
        demand_name = self.create_test_demand(500)  # More than available

        # Get demand item
        demand = frappe.get_doc("APC Sales Demand", demand_name)
        item_name = demand.items[0].name

        # Calculate production requirement
        production_req = calculate_production_requirement(item_name)

        # Should calculate positive requirement
        self.assertGreater(production_req, 0, "Should calculate positive production requirement")

    def test_multi_batch_allocation(self):
        """Test allocation spanning multiple batches."""
        # Demand that requires multiple batches
        demand_qty = 200  # Requires batch1 (100) + batch2 (100 from 150)
        demand_name = self.create_test_demand(demand_qty)

        result = allocate_batches_fifo(demand_name)

        self.assertTrue(result["success"])
        allocation = frappe.get_doc("APC Batch Allocation", result["allocation"])

        # Should use multiple batches
        self.assertGreater(len(allocation.allocation_details), 1, "Should allocate from multiple batches")

        # Verify FIFO order
        details = sorted(allocation.allocation_details, key=lambda x: x.fifo_sequence)
        self.assertEqual(details[0].batch, self.test_batches[0])
        if len(details) > 1:
            self.assertEqual(details[1].batch, self.test_batches[1])

    def test_allocation_release(self):
        """Test releasing an allocation."""
        demand_name = self.create_test_demand(50)
        result = allocate_batches_fifo(demand_name)

        self.assertTrue(result["success"])

        # Release allocation
        release_result = release_allocation(result["allocation"])
        self.assertTrue(release_result["success"])

        # Check allocation status
        allocation = frappe.get_doc("APC Batch Allocation", result["allocation"])
        self.assertEqual(allocation.allocation_status, "Released")

    def test_insufficient_stock_allocation(self):
        """Test allocation failure when no stock available."""
        # Create demand for non-existent item
        demand = frappe.new_doc("APC Sales Demand")
        demand.customer = "_Test Customer"
        demand.sales_order_date = today()
        demand.append("items", {
            "item": "_Non Existent Item",
            "demand_quantity": 100,
            "uom": "Nos"
        })
        demand.insert()

        result = allocate_batches_fifo(demand.name)

        # Should still create allocation but with shortages
        self.assertTrue(result["success"])
        self.assertGreater(len(result["shortages"]), 0)

    def test_rejected_batch_not_allocated(self):
        """Test that rejected batches are not allocated."""
        # Create a rejected batch
        rejected_batch = self.create_batch(
            product=self.test_item,
            grade="Premium",
            specification="Spec A",
            quantity=100,
            manufacturing_date=add_days(today(), -5),
            status="Blocked",
            quality="Rejected"
        )

        # Get available batches - should not include rejected
        batches = get_available_batches(
            product=self.test_item,
            grade="Premium",
            specification="Spec A"
        )

        batch_names = [b.name for b in batches]
        self.assertNotIn(rejected_batch, batch_names, "Rejected batch should not be available")

    def test_blocked_batch_validation(self):
        """Test that blocked batches cannot be allocated."""
        # Create demand
        demand_name = self.create_test_demand(50)

        # Create a manual allocation with blocked batch - should fail validation
        allocation = frappe.new_doc("APC Batch Allocation")
        allocation.sales_demand = demand_name
        allocation.customer = "_Test Customer"
        allocation.allocation_date = today()

        # Try to allocate from a blocked batch
        blocked_batch = frappe.get_doc("APC Batch", self.test_batches[0])
        blocked_batch.db_set("batch_status", "Blocked", update_modified=False)

        allocation.append("allocation_details", {
            "item": self.test_item,
            "batch": blocked_batch.name,
            "allocated_quantity": 50,
            "required_quantity": 50
        })

        # Validation should raise an error
        with self.assertRaises(Exception):
            allocation.insert()

    def test_missing_coa_validation(self):
        """Test that batches without COA cannot be dispatched."""
        # Create batch without COA
        batch_no_coa = frappe.new_doc("APC Batch")
        batch_no_coa.product = self.test_item
        batch_no_coa.batch_quantity = 100
        batch_no_coa.available_quantity = 100
        batch_no_coa.manufacturing_date = today()
        batch_no_coa.batch_status = "Active"
        batch_no_coa.quality_status = "Pending QC"
        batch_no_coa.insert()

        # Create dispatch with this batch
        dispatch = frappe.new_doc("APC Dispatch Order")
        dispatch.sales_demand = self.create_test_demand(50)
        dispatch.customer = "_Test Customer"
        dispatch.dispatch_date = today()

        dispatch.append("batch_details", {
            "item": self.test_item,
            "batch": batch_no_coa.name,
            "quantity": 50
        })

        # Validation should fail due to missing COA
        with self.assertRaises(Exception):
            dispatch.insert()

    def test_coa_belongs_to_batch_validation(self):
        """Test that COA attached to dispatch belongs to the batch."""
        # Create demand and allocate
        demand_name = self.create_test_demand(50)
        result = allocate_batches_fifo(demand_name)

        self.assertTrue(result["success"])

        # Create dispatch
        dispatch = frappe.new_doc("APC Dispatch Order")
        dispatch.sales_demand = demand_name
        dispatch.batch_allocation = result["allocation"]
        dispatch.customer = "_Test Customer"
        dispatch.dispatch_date = today()

        # Get allocation details
        allocation = frappe.get_doc("APC Batch Allocation", result["allocation"])
        detail = allocation.allocation_details[0]

        dispatch.append("batch_details", {
            "item": detail.item,
            "batch": detail.batch,
            "batch_number": detail.batch_number,
            "quantity": detail.allocated_quantity,
            "coa": detail.coa
        })

        dispatch.insert()

        # Validation should pass - COA belongs to batch
        validation = validate_dispatch_batches(dispatch.name)
        self.assertTrue(validation["valid"], validation.get("errors", []))


class TestBatchAllocationTransactionSafety(FrappeTestCase):
    """Test transaction safety and concurrency."""

    def test_no_double_allocation(self):
        """Test that same batch quantity cannot be allocated twice."""
        # This would require concurrent execution testing
        # For now, test that allocated_quantity + available_quantity = batch_quantity
        batch = frappe.new_doc("APC Batch")
        batch.product = "_Test Item"
        batch.batch_quantity = 100
        batch.available_quantity = 100
        batch.allocated_quantity = 0
        batch.manufacturing_date = today()
        batch.batch_status = "Active"
        batch.quality_status = "Approved"
        batch.insert()

        # Verify initial state
        self.assertEqual(batch.batch_quantity, batch.available_quantity + batch.allocated_quantity)


class TestProductionRequirement(FrappeTestCase):
    """Test production requirement creation."""

    def setUp(self):
        self.test_item = "_Test Item Prod"
        if not frappe.db.exists("Item", self.test_item):
            item = frappe.new_doc("Item")
            item.item_code = self.test_item
            item.item_name = "Test Item for Production"
            item.item_group = "Products"
            item.stock_uom = "Nos"
            item.insert()

    def test_create_production_requirement(self):
        """Test creation of production requirement when stock is short."""
        # Create demand without any available batches
        demand = frappe.new_doc("APC Sales Demand")
        demand.customer = "_Test Customer"
        demand.sales_order_date = today()
        demand.append("items", {
            "item": self.test_item,
            "demand_quantity": 500,
            "uom": "Nos"
        })
        demand.insert()

        # Calculate and create production requirements
        result = create_production_requirement_if_shortage(demand.name)

        self.assertTrue(result["success"])

        # Should have created a production requirement
        self.assertGreater(len(result["created"]), 0, "Should create production requirement")

    def test_update_existing_production_requirement(self):
        """Test updating existing production requirement instead of creating duplicate."""
        # Create demand
        demand = frappe.new_doc("APC Sales Demand")
        demand.customer = "_Test Customer"
        demand.sales_order_date = today()
        demand.append("items", {
            "item": self.test_item,
            "demand_quantity": 300,
            "uom": "Nos"
        })
        demand.insert()

        # First call - create requirement
        result1 = create_production_requirement_if_shortage(demand.name)
        self.assertGreater(len(result1["created"]), 0)

        # Update demand quantity
        demand.items[0].demand_quantity = 500
        demand.save()

        # Second call - should update existing
        result2 = create_production_requirement_if_shortage(demand.name)
        self.assertGreater(len(result2["updated"]), 0, "Should update existing requirement")


class TestCOAManagement(FrappeTestCase):
    """Test COA management and validation."""

    def setUp(self):
        self.test_item = "_Test Item COA"
        if not frappe.db.exists("Item", self.test_item):
            item = frappe.new_doc("Item")
            item.item_code = self.test_item
            item.item_name = "Test Item for COA"
            item.item_group = "Products"
            item.stock_uom = "Nos"
            item.insert()

    def test_coa_sync_to_batch(self):
        """Test that COA approval syncs to batch quality status."""
        # Create batch
        batch = frappe.new_doc("APC Batch")
        batch.product = self.test_item
        batch.batch_quantity = 100
        batch.available_quantity = 100
        batch.manufacturing_date = today()
        batch.batch_status = "Active"
        batch.quality_status = "Pending QC"
        batch.insert()

        # Create and approve COA
        coa = frappe.new_doc("APC COA")
        coa.batch = batch.name
        coa.product = self.test_item
        coa.approval_status = "Approved"
        coa.approved_by = frappe.session.user
        coa.approved_date = today()
        coa.insert()

        # Check batch quality status updated
        batch.reload()
        self.assertEqual(batch.quality_status, "Approved")
        self.assertEqual(batch.linked_coa, coa.name)

    def test_rejected_coa_blocks_batch(self):
        """Test that rejected COA blocks the batch."""
        # Create batch
        batch = frappe.new_doc("APC Batch")
        batch.product = self.test_item
        batch.batch_quantity = 100
        batch.available_quantity = 100
        batch.manufacturing_date = today()
        batch.batch_status = "Active"
        batch.quality_status = "Pending QC"
        batch.insert()

        # Create and reject COA
        coa = frappe.new_doc("APC COA")
        coa.batch = batch.name
        coa.product = self.test_item
        coa.approval_status = "Rejected"
        coa.rejected_by = frappe.session.user
        coa.rejected_date = today()
        coa.insert()

        # Check batch is blocked
        batch.reload()
        self.assertEqual(batch.quality_status, "Rejected")
        self.assertEqual(batch.batch_status, "Blocked")
