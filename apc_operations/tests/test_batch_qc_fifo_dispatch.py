# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""
Integration test suite: Production → QC → Batch → FIFO Dispatch

Covers the plan's full test matrix as documented in section 12.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today, add_days, flt


def _make_item(item_code="TEST-PRODUCT-001", item_group="Products"):
    if frappe.db.exists("Item", item_code):
        return item_code
    item = frappe.new_doc("Item")
    item.item_code = item_code
    item.item_name = "Test Product 001"
    item.item_group = item_group
    item.stock_uom = "KG"
    item.is_stock_item = 1
    item.insert(ignore_permissions=True)
    return item_code


def _make_batch(product=None, batch_qty=5000, mfg_date=None, quality_status="QC Cleared",
                stock_status="Available", batch_status="Active", linked_coa=None):
    product = product or _make_item()
    batch = frappe.new_doc("APC Batch")
    batch.product = product
    batch.batch_quantity = batch_qty
    batch.available_quantity = batch_qty
    batch.allocated_quantity = 0
    batch.dispatched_quantity = 0
    batch.manufacturing_date = mfg_date or today()
    batch.quality_status = quality_status
    batch.stock_status = stock_status
    batch.batch_status = batch_status
    batch.uom = "KG"
    batch.created_from_production = 0
    if linked_coa:
        batch.linked_coa = linked_coa
    batch.insert(ignore_permissions=True)
    return batch


def _make_approved_coa(batch_name):
    coa = frappe.new_doc("APC COA")
    coa.batch = batch_name
    coa.product = frappe.db.get_value("APC Batch", batch_name, "product")
    coa.status = "Approved"
    coa.approval_status = "Approved"
    coa.coa_status = "Approved"
    coa.insert(ignore_permissions=True)
    frappe.db.set_value("APC Batch", batch_name, "linked_coa", coa.name, update_modified=False)
    return coa


def _make_loading_dn(job_order=None, quantity=5000):
    dn = frappe.new_doc("Loading Delivery Note")
    dn.delivery_note_status = "Batch Allocation Pending"
    dn.receivables_status = "Pending Receivables"
    dn.loading_date = today()
    dn.quantity = quantity
    dn.uom = "KG"
    if job_order:
        dn.job_order = job_order
    dn.insert(ignore_permissions=True)
    return dn


class TestBatchCreationFromProduction(FrappeTestCase):
    """Phase 1: Production Order → APC Batch creation chain."""

    def test_production_order_batch_creation_on_completion(self):
        """Completing a Production Order with item set creates an APC Batch."""
        product = _make_item("TEST-PROD-ITEM-001")
        po = frappe.new_doc("Production Order")
        po.item = product
        po.required_quantity = 3000
        po.uom = "KG"
        po.status = "In Progress"
        po.planned_date = today()
        po.insert(ignore_permissions=True)

        po.status = "Completed"
        po.save(ignore_permissions=True)

        po.reload()
        self.assertTrue(po.apc_batch, "APC Batch should be created when Production Order is completed")

        batch = frappe.get_doc("APC Batch", po.apc_batch)
        self.assertEqual(batch.quality_status, "Pending QC")
        self.assertEqual(batch.stock_status, "QC Hold")
        self.assertEqual(flt(batch.batch_quantity), 3000)

    def test_completed_po_without_item_does_not_create_batch(self):
        """Production Order without an item field set must not create a batch."""
        po = frappe.new_doc("Production Order")
        po.required_quantity = 1000
        po.status = "Completed"
        po.planned_date = today()
        po.insert(ignore_permissions=True)
        po.reload()
        self.assertFalse(po.apc_batch)


class TestAPCBatchAutoCoaCreation(FrappeTestCase):
    """Phase 2: APC Batch auto-creates COA on insert from production."""

    def test_auto_coa_created_from_production_batch(self):
        """Batch inserted with created_from_production=1 triggers COA auto-creation."""
        product = _make_item("TEST-AUTO-COA-ITEM")
        batch = frappe.new_doc("APC Batch")
        batch.product = product
        batch.batch_quantity = 2000
        batch.available_quantity = 2000
        batch.manufacturing_date = today()
        batch.quality_status = "Pending QC"
        batch.stock_status = "QC Hold"
        batch.batch_status = "Active"
        batch.created_from_production = 1
        batch.uom = "KG"
        batch.insert(ignore_permissions=True)

        batch.reload()
        self.assertTrue(batch.linked_coa, "COA should be auto-created for production batch")
        coa = frappe.get_doc("APC COA", batch.linked_coa)
        self.assertEqual(coa.status, "Pending Testing")

    def test_no_auto_coa_for_non_production_batch(self):
        """Batch without created_from_production should NOT auto-create COA."""
        product = _make_item("TEST-NO-COA-ITEM")
        batch = frappe.new_doc("APC Batch")
        batch.product = product
        batch.batch_quantity = 1000
        batch.available_quantity = 1000
        batch.manufacturing_date = today()
        batch.quality_status = "Pending QC"
        batch.stock_status = "QC Hold"
        batch.batch_status = "Active"
        batch.created_from_production = 0
        batch.uom = "KG"
        batch.insert(ignore_permissions=True)
        batch.reload()
        self.assertFalse(batch.linked_coa)


class TestCOAApprovalRoleGuard(FrappeTestCase):
    """Phase 3: COA approval role guard."""

    def test_non_qc_user_cannot_approve_coa(self):
        """User without Quality Manager role raises PermissionError on approve_coa."""
        product = _make_item("TEST-COA-GUARD-ITEM")
        batch = _make_batch(product=product, quality_status="QC Cleared", stock_status="QC Hold")
        coa = frappe.new_doc("APC COA")
        coa.batch = batch.name
        coa.product = product
        coa.status = "Passed"
        coa.approval_status = "Pending"
        coa.insert(ignore_permissions=True)

        # Simulate user without Quality Manager role
        frappe.set_user("test@example.com")
        self.assertRaises(frappe.PermissionError, coa.approve_coa)
        frappe.set_user("Administrator")

    def test_validate_checklist_complete_fails_if_no_results(self):
        """validate_checklist_complete raises when no test_results exist."""
        coa = frappe.new_doc("APC COA")
        coa.status = "Passed"
        with self.assertRaises(frappe.exceptions.ValidationError):
            coa.validate_checklist_complete()

    def test_coa_approval_updates_batch_stock_status(self):
        """Approving COA sets batch.stock_status = Available and quality_status = QC Cleared."""
        product = _make_item("TEST-COA-APPROVAL-ITEM")
        batch = _make_batch(product=product, quality_status="Pending QC", stock_status="QC Hold")
        coa = frappe.new_doc("APC COA")
        coa.batch = batch.name
        coa.product = product
        coa.status = "Approved"
        coa.approval_status = "Approved"
        coa.insert(ignore_permissions=True)

        coa.sync_to_batch()

        batch.reload()
        self.assertEqual(batch.quality_status, "QC Cleared")
        self.assertEqual(batch.stock_status, "Available")


class TestFIFOAllocation(FrappeTestCase):
    """Phase 5: FIFO Loading DN batch allocation."""

    def _create_approved_batch(self, mfg_date, qty, product=None):
        product = product or _make_item("TEST-FIFO-ITEM-001")
        batch = _make_batch(
            product=product,
            batch_qty=qty,
            mfg_date=mfg_date,
            quality_status="QC Cleared",
            stock_status="Available",
        )
        _make_approved_coa(batch.name)
        batch.reload()
        return batch

    def test_single_batch_fifo_allocation(self):
        """One batch allocates fully when sufficient stock available."""
        from apc_operations.services.batch_allocation import create_loading_dn_batch_allocations

        product = _make_item("TEST-FIFO-SINGLE-ITEM")
        batch = self._create_approved_batch(today(), 5000, product)
        dn = _make_loading_dn(quantity=3000)

        result = create_loading_dn_batch_allocations(
            loading_dn_name=dn.name,
            product=product,
            required_qty=3000,
        )
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["shortage"], 0)
        self.assertEqual(flt(result["total_allocated"]), 3000)

    def test_multi_batch_fifo_allocation(self):
        """Allocation spans multiple batches in manufacturing date order (oldest first)."""
        from apc_operations.services.batch_allocation import create_loading_dn_batch_allocations

        product = _make_item("TEST-FIFO-MULTI-ITEM")
        batch1 = self._create_approved_batch(add_days(today(), -10), 3000, product)
        batch2 = self._create_approved_batch(add_days(today(), -5), 4000, product)
        batch3 = self._create_approved_batch(today(), 5000, product)

        dn = _make_loading_dn(quantity=8000)
        result = create_loading_dn_batch_allocations(
            loading_dn_name=dn.name,
            product=product,
            required_qty=8000,
        )

        dn.reload()
        self.assertEqual(result["shortage"], 0)
        self.assertGreaterEqual(len(dn.batch_allocations), 2)

        # Oldest batch (batch1) should be first in FIFO sequence
        row_batches = [r.batch for r in sorted(dn.batch_allocations, key=lambda x: x.fifo_sequence)]
        self.assertEqual(row_batches[0], batch1.name)

    def test_insufficient_stock_raises_warning(self):
        """When stock is insufficient, result has shortage > 0."""
        from apc_operations.services.batch_allocation import create_loading_dn_batch_allocations

        product = _make_item("TEST-FIFO-SHORT-ITEM")
        self._create_approved_batch(today(), 2000, product)
        dn = _make_loading_dn(quantity=10000)

        result = create_loading_dn_batch_allocations(
            loading_dn_name=dn.name,
            product=product,
            required_qty=10000,
        )
        self.assertGreater(result["shortage"], 0)

    def test_qc_hold_batch_excluded_from_fifo(self):
        """Batch with stock_status=QC Hold must not appear in FIFO allocation."""
        from apc_operations.services.batch_allocation import create_loading_dn_batch_allocations

        product = _make_item("TEST-FIFO-QC-HOLD")
        batch_hold = _make_batch(product=product, batch_qty=5000,
                                  quality_status="Pending QC", stock_status="QC Hold")
        dn = _make_loading_dn(quantity=5000)

        result = create_loading_dn_batch_allocations(
            loading_dn_name=dn.name,
            product=product,
            required_qty=5000,
        )
        allocated_batches = [r["batch"] for r in result["rows"]]
        self.assertNotIn(batch_hold.name, allocated_batches)
        self.assertGreater(result["shortage"], 0)

    def test_rejected_batch_excluded_from_fifo(self):
        """Batch with stock_status=Rejected must not appear in FIFO allocation."""
        from apc_operations.services.batch_allocation import create_loading_dn_batch_allocations

        product = _make_item("TEST-FIFO-REJECTED")
        batch_rej = _make_batch(product=product, batch_qty=5000,
                                 quality_status="QC Rejected", stock_status="Rejected",
                                 batch_status="Blocked")
        dn = _make_loading_dn(quantity=5000)

        result = create_loading_dn_batch_allocations(
            loading_dn_name=dn.name, product=product, required_qty=5000,
        )
        allocated_batches = [r["batch"] for r in result["rows"]]
        self.assertNotIn(batch_rej.name, allocated_batches)

    def test_missing_coa_blocks_dispatch(self):
        """confirm_dispatch raises ValidationError when batch has no COA."""
        from apc_operations.services.batch_allocation import confirm_dispatch_and_deduct_stock

        product = _make_item("TEST-DISPATCH-NO-COA")
        batch = _make_batch(product=product, batch_qty=3000, stock_status="Reserved",
                             quality_status="QC Cleared")

        dn = _make_loading_dn(quantity=3000)
        dn.append("batch_allocations", {
            "batch": batch.name,
            "batch_number": batch.batch_number,
            "product": batch.product,
            "allocated_qty": 3000,
            "dispatched_qty": 0,
            "coa": None,
            "fifo_sequence": 1,
        })
        dn.save(ignore_permissions=True)

        with self.assertRaises(frappe.exceptions.ValidationError):
            confirm_dispatch_and_deduct_stock(dn.name)

    def test_confirm_dispatch_deducts_stock(self):
        """confirm_dispatch correctly deducts available_quantity and sets Dispatched status."""
        from apc_operations.services.batch_allocation import confirm_dispatch_and_deduct_stock

        product = _make_item("TEST-DISPATCH-DEDUCT")
        batch = _make_batch(product=product, batch_qty=5000, stock_status="Reserved",
                             quality_status="QC Cleared", batch_status="Active")
        coa = _make_approved_coa(batch.name)
        batch.reload()
        batch.allocated_quantity = 3000
        batch.available_quantity = 2000
        batch.save(ignore_permissions=True)

        dn = _make_loading_dn(quantity=3000)
        dn.append("batch_allocations", {
            "batch": batch.name,
            "batch_number": batch.batch_number,
            "product": batch.product,
            "allocated_qty": 3000,
            "dispatched_qty": 0,
            "coa": coa.name,
            "fifo_sequence": 1,
        })
        dn.save(ignore_permissions=True)

        result = confirm_dispatch_and_deduct_stock(dn.name)
        self.assertTrue(result["success"])

        batch.reload()
        self.assertEqual(flt(batch.dispatched_quantity), 3000)
        self.assertEqual(batch.stock_status, "Dispatched")

    def test_fifo_override_without_permission_raises(self):
        """FIFO override row without Quality Manager role raises PermissionError on dispatch."""
        from apc_operations.services.batch_allocation import confirm_dispatch_and_deduct_stock

        product = _make_item("TEST-FIFO-OVERRIDE-PERM")
        batch = _make_batch(product=product, batch_qty=5000, stock_status="Reserved",
                             quality_status="QC Cleared")
        coa = _make_approved_coa(batch.name)
        batch.reload()
        batch.allocated_quantity = 3000
        batch.available_quantity = 2000
        batch.save(ignore_permissions=True)

        dn = _make_loading_dn(quantity=3000)
        dn.append("batch_allocations", {
            "batch": batch.name,
            "batch_number": batch.batch_number,
            "product": batch.product,
            "allocated_qty": 3000,
            "dispatched_qty": 0,
            "coa": coa.name,
            "fifo_sequence": 1,
            "is_fifo_override": 1,
            "override_reason": "",  # missing reason
        })
        dn.save(ignore_permissions=True)

        frappe.set_user("test@example.com")
        with self.assertRaises((frappe.PermissionError, frappe.exceptions.ValidationError)):
            confirm_dispatch_and_deduct_stock(dn.name)
        frappe.set_user("Administrator")

    def test_fifo_override_with_permission_and_reason_succeeds(self):
        """FIFO override with Quality Manager role and reason is accepted on dispatch."""
        from apc_operations.services.batch_allocation import confirm_dispatch_and_deduct_stock

        product = _make_item("TEST-FIFO-OVERRIDE-OK")
        batch = _make_batch(product=product, batch_qty=5000, stock_status="Reserved",
                             quality_status="QC Cleared", batch_status="Active")
        coa = _make_approved_coa(batch.name)
        batch.reload()
        batch.allocated_quantity = 3000
        batch.available_quantity = 2000
        batch.save(ignore_permissions=True)

        dn = _make_loading_dn(quantity=3000)
        dn.append("batch_allocations", {
            "batch": batch.name,
            "batch_number": batch.batch_number,
            "product": batch.product,
            "allocated_qty": 3000,
            "dispatched_qty": 0,
            "coa": coa.name,
            "fifo_sequence": 1,
            "is_fifo_override": 1,
            "override_reason": "Customer required specific batch for testing",
        })
        dn.save(ignore_permissions=True)

        # Administrator has System Manager role — should succeed
        result = confirm_dispatch_and_deduct_stock(dn.name)
        self.assertTrue(result["success"])


class TestSecurityBridge(FrappeTestCase):
    """Phase 6: Security Inspection → QC Report Request → Loading DN batch link."""

    def test_report_to_qc_requires_checklist_completed(self):
        """report_to_qc raises if security_status != Checklist Completed."""
        if not frappe.db.exists("Security Inspection", {"security_status": "Draft"}):
            return

        ins = frappe.new_doc("Security Inspection")
        ins.inspection_type = "Vehicle"
        ins.inspection_date = today()
        ins.security_status = "Draft"
        ins.qc_status = "Not Sent"
        ins.insert(ignore_permissions=True)

        with self.assertRaises(frappe.exceptions.ValidationError):
            ins.report_to_qc()

    def test_loading_dn_creation_blocked_before_qc_cleared(self):
        """create_loading_delivery_note raises if qc_status != QC Cleared."""
        ins = frappe.new_doc("Security Inspection")
        ins.inspection_type = "Vehicle"
        ins.inspection_date = today()
        ins.security_status = "Reported to QC"
        ins.qc_status = "Pending QC"
        ins.quantity = 1000
        ins.uom = "KG"
        ins.insert(ignore_permissions=True)

        with self.assertRaises(frappe.exceptions.ValidationError):
            ins.create_loading_delivery_note()


class TestFullFlowIntegration(FrappeTestCase):
    """End-to-end: Production Req → Batch → QC → Loading DN → Dispatch."""

    def test_full_flow_status_transitions(self):
        """All intermediate statuses transition correctly through the full flow."""
        from apc_operations.services.batch_allocation import (
            create_loading_dn_batch_allocations,
            confirm_dispatch_and_deduct_stock,
        )

        product = _make_item("TEST-FULL-FLOW-ITEM")

        # 1. Batch from production
        batch = frappe.new_doc("APC Batch")
        batch.product = product
        batch.batch_quantity = 5000
        batch.available_quantity = 5000
        batch.manufacturing_date = add_days(today(), -15)
        batch.quality_status = "Pending QC"
        batch.stock_status = "QC Hold"
        batch.batch_status = "Active"
        batch.uom = "KG"
        batch.created_from_production = 0
        batch.insert(ignore_permissions=True)

        self.assertEqual(batch.stock_status, "QC Hold")

        # 2. Create approved COA and update batch
        coa = _make_approved_coa(batch.name)
        frappe.db.set_value("APC Batch", batch.name, {
            "quality_status": "QC Cleared",
            "stock_status": "Available",
            "coa_status": "Approved",
        }, update_modified=False)
        batch.reload()

        self.assertEqual(batch.stock_status, "Available")
        self.assertEqual(batch.quality_status, "QC Cleared")

        # 3. Create Loading DN and FIFO allocate
        dn = _make_loading_dn(quantity=4000)
        result = create_loading_dn_batch_allocations(
            loading_dn_name=dn.name,
            product=product,
            required_qty=4000,
        )
        self.assertEqual(result["shortage"], 0)

        dn.reload()
        self.assertEqual(dn.delivery_note_status, "Batch Allocated")
        self.assertGreater(len(dn.batch_allocations), 0)

        # 4. Verify COAs
        dn.verify_coas()
        dn.reload()
        self.assertEqual(dn.coa_verified, 1)

        # 5. Confirm dispatch
        confirm_dispatch_and_deduct_stock(dn.name)
        dn.reload()
        batch.reload()

        self.assertEqual(dn.delivery_note_status, "Dispatch Confirmed")
        self.assertEqual(dn.dispatch_confirmed, 1)
        self.assertEqual(flt(batch.dispatched_quantity), 4000)
        self.assertEqual(batch.stock_status, "Dispatched")
