# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import today, now, getdate, flt
from frappe import _
from apc_operations.services.email_recipients import role_user_emails


# Default Security Checklist applied to every Security Inspection (and surfaced
# in the new Security Console via the SDDN modal).  Exported so the Security
# Console API can return the same template when an SDDN has no linked
# Security Inspection yet.
DEFAULT_CHECKLIST_ITEMS = [
    {"checklist_item": "A-1 Vehicle parked in designated area", "required": 1},
    {"checklist_item": "A-2 Vehicle type and purpose verified (Pick Up / Tanker / Container)", "required": 1},
    {"checklist_item": "A-3 Quantity to load/offload confirmed", "required": 1},
    {"checklist_item": "A-4 Vehicle number recorded", "required": 1},
    {"checklist_item": "A-5 Driver name and details verified", "required": 1},
    {"checklist_item": "A-6 Driver EID collected and log book maintained", "required": 1},
    {"checklist_item": "A-7 Sending and receiving parties verified", "required": 1},
    {"checklist_item": "A-8 Material name matched with documents", "required": 1},
    {"checklist_item": "A-9 Gross/Tare/Net weight captured", "required": 0},
    {"checklist_item": "B-1 Vehicle exterior visually in good condition", "required": 1},
    {"checklist_item": "B-2 Vehicle interior in good condition", "required": 1},
    {"checklist_item": "B-3 Fire extinguishers available", "required": 1},
    {"checklist_item": "B-4 Spark arrestor available at exhaust", "required": 1},
    {"checklist_item": "B-5 Vehicle covered properly", "required": 1},
    {"checklist_item": "B-6 Hand brake applied and wheel chock used", "required": 1},
    {"checklist_item": "B-7 Vehicle engine switched off", "required": 1},
    {"checklist_item": "B-8 Driver wearing mandatory PPE", "required": 1},
    {"checklist_item": "L-1 Manholes opened", "required": 0},
    {"checklist_item": "L-2 Earthing done", "required": 0},
    {"checklist_item": "L-3 Hoses connected with camlock tie", "required": 0},
    {"checklist_item": "L-4 Pump rotation and flow checked", "required": 0},
    {"checklist_item": "L-5 Valves lined up", "required": 0},
    {"checklist_item": "L-6 Suitable PPE and harness available", "required": 0},
    {"checklist_item": "L-7 Watcher available for tanker overflow while loading", "required": 0},
    {"checklist_item": "L-8 ST level confirmed to prevent overflow", "required": 0},
    {"checklist_item": "L-9 Tank number for load/offload verified", "required": 0},
    {"checklist_item": "C-1 Completion: Hose and earthing disconnected", "required": 0},
    {"checklist_item": "C-2 Completion: Manholes closed", "required": 0},
    {"checklist_item": "C-3 Completion: Vehicle safety lock points checked (all sides)", "required": 0},
    {"checklist_item": "C-4 Completion: Final visual inspection completed", "required": 0},
]


class SecurityInspection(Document):
    def before_insert(self):
        self.ensure_default_checklist_items()

    def validate(self):
        self.calculate_net_weight()
        self.sync_packing_counts()
        self.validate_checklist_completion()
        self.validate_qc_transition_integrity()

    def sync_packing_counts(self):
        from apc_operations.shipping.services.packing_calculation_service import (
            loaded_packaging_qty_from_loading_entries,
        )

        loaded = loaded_packaging_qty_from_loading_entries(self.name)
        if loaded > 0:
            self.loaded_packaging_qty = loaded
        if not flt(self.expected_packaging_qty) and self.job_order:
            from apc_operations.shipping.services.packing_calculation_service import (
                sum_job_order_packing_totals,
            )

            totals = sum_job_order_packing_totals(self.job_order)
            expected = int(totals.get("packaging_qty") or 0)
            if expected > 0:
                self.expected_packaging_qty = expected

    def calculate_net_weight(self):
        if self.gross_weight and self.tare_weight:
            self.net_weight = self.gross_weight - self.tare_weight

    def validate_checklist_completion(self):
        """Advance status to Checklist Completed only when ALL required items are done.
        Never regress status — only move forward."""
        if not self.checklist_items:
            return

        required_items = [item for item in self.checklist_items if item.required]
        if not required_items:
            return

        all_done = all(item.completed for item in required_items)

        if all_done and self.security_status in ["Draft", "Pending Checklist"]:
            self.security_status = "Checklist Completed"
        elif not all_done and self.security_status == "Draft":
            self.security_status = "Pending Checklist"

    def validate_qc_transition_integrity(self):
        """Prevent inconsistent manual status changes that bypass action methods."""
        if self.security_status == "Reported to QC" and not self.qc_report_request:
            frappe.throw(
                _(
                    "QC Report Request is missing. Use the 'Report to QC' action to create and link it automatically."
                )
            )

    def _resolve_loading_delivery_note_for_report(self) -> str | None:
        """Link SI ↔ LDN from the Job Order / Delivery Order when reporting to QC."""
        if self.loading_delivery_note:
            frappe.db.set_value(
                "Loading Delivery Note",
                self.loading_delivery_note,
                "security_inspection",
                self.name,
                update_modified=False,
            )
            return self.loading_delivery_note

        ldn_name = None
        if self.job_order:
            from apc_operations.services.delivery_order_service import (
                find_delivery_order_for_job_order_primary,
            )

            do_name = find_delivery_order_for_job_order_primary(self.job_order)
            if do_name:
                ldn_name = frappe.db.get_value("Delivery Order", do_name, "loading_delivery_note")
            if not ldn_name:
                ldn_name = frappe.db.get_value(
                    "Loading Delivery Note",
                    {"job_order": self.job_order, "dispatch_confirmed": 0},
                    "name",
                    order_by="modified desc",
                )

        if ldn_name:
            self.loading_delivery_note = ldn_name
            frappe.db.set_value(
                "Loading Delivery Note",
                ldn_name,
                "security_inspection",
                self.name,
                update_modified=False,
            )
        return ldn_name

    def _resolve_sddn_for_report(self) -> str | None:
        if self.transportation_request:
            draft_dn = frappe.db.get_value(
                "Security Draft Delivery Note",
                {"transport_schedule": self.transportation_request},
                "name",
            )
            if draft_dn:
                return draft_dn
        if self.job_order:
            return frappe.db.get_value(
                "Security Draft Delivery Note",
                {"job_order": self.job_order},
                "name",
                order_by="modified desc",
            )
        return None

    def before_save(self):
        self.populate_from_source()

    def ensure_default_checklist_items(self):
        """Ensure every inspection always has baseline checklist rows."""
        if self.checklist_items:
            return

        for item in DEFAULT_CHECKLIST_ITEMS:
            self.append("checklist_items", {
                "checklist_item": item["checklist_item"],
                "required": item["required"],
                "completed": 0,
            })

    def populate_from_source(self):
        if self.job_order and not self.customer:
            self.customer = frappe.db.get_value("Job Order", self.job_order, "customer")

        from apc_operations.shipping.services.uom_service import apply_commercial_fields

        sddn = None
        if self.transportation_request:
            sddn = frappe.db.get_value(
                "Security Draft Delivery Note",
                {"transport_schedule": self.transportation_request},
                "name",
            )
        apply_commercial_fields(
            self,
            job_order=self.job_order,
            sddn_name=sddn,
            force_uom=not (self.uom or "").strip(),
        )

        if self.transportation_request:
            transport = frappe.get_cached_doc("Transport Schedule", self.transportation_request)
            if not self.vehicle:
                self.vehicle = transport.assigned_vehicle
            if not self.driver:
                self.driver = transport.assigned_driver
            if not self.transporter:
                self.transporter = transport.transporter
            if not self.container_type:
                self.container_type = transport.container_type

    def on_update(self):
        self.sync_to_qc_report()
        self.sync_to_loading_dn()
        self._maybe_save_checklist_to_nas()

    def sync_to_qc_report(self):
        if self.qc_report_request:
            qc_doc = frappe.get_doc("QC Report Request", self.qc_report_request)
            qc_doc.qc_status = self.qc_status
            qc_doc.save()

    def sync_to_loading_dn(self):
        if frappe.flags.get("apc_syncing_ldn_transport"):
            return
        if not self.loading_delivery_note:
            return
        from apc_operations.security.dispatch_workflow import _sync_ldn_from_si

        ld_doc = frappe.get_doc("Loading Delivery Note", self.loading_delivery_note)
        _sync_ldn_from_si(ld_doc, self)
        if self.driver and not ld_doc.driver:
            ld_doc.driver = self.driver
        if self.vehicle and not ld_doc.vehicle:
            ld_doc.vehicle = self.vehicle
        new_status = self.get_loading_dn_status()
        if new_status:
            ld_doc.delivery_note_status = new_status
        ld_doc.save(ignore_permissions=True)

    def _maybe_save_checklist_to_nas(self):
        """Save checklist PDF to NAS when inspection is completed or Loading DN created."""
        if self.security_status not in ("Completed", "Loading DN Created", "Reported to Receivables"):
            return
        try:
            from apc_operations.services.nas_service import save_checklist_to_nas
            save_checklist_to_nas(self.name)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Security Inspection NAS Save")

    def get_loading_dn_status(self):
        """Map Security Inspection security_status to Loading Delivery Note delivery_note_status."""
        status_map = {
            "QC Cleared": "QC Cleared",
            "Loading DN Created": "Draft",
            "Reported to Receivables": "Reported to Receivables",
            "Completed": "Completed",
        }
        return status_map.get(self.security_status)

    def _is_import_inspection(self):
        if not self.job_order:
            return False
        return (
            frappe.db.get_value("Job Order", self.job_order, "commercial_movement") or ""
        ).strip() == "Import"

    @frappe.whitelist()
    def report_to_qc(self):
        if self.qc_report_request:
            frappe.throw(_("QC Report Request already exists for this inspection"))

        is_import = self._is_import_inspection()
        if is_import:
            if self.security_status not in ("Checklist Completed", "Loading DN Created"):
                frappe.throw(
                    _(
                        "Complete the security checklist before reporting to QC. Current status: {0}"
                    ).format(self.security_status)
                )
        else:
            allowed_statuses = ("Checklist Completed", "Loading DN Created", "Reported to QC")
            if self.security_status not in allowed_statuses:
                frappe.throw(
                    _(
                        "Complete the security checklist before reporting to QC. Current status: {0}"
                    ).format(self.security_status)
                )

        # Resolve optional LDN link from DO / job order (Report to QC does not require LDN).
        ldn_name = self._resolve_loading_delivery_note_for_report()

        # Resolve the batch and COA linked to this Job Order's allocation
        batch_name, coa_name = self._get_batch_and_coa_for_job_order()

        qc_request = frappe.new_doc("QC Report Request")
        qc_request.security_inspection = self.name
        qc_request.job_order = self.job_order
        qc_request.loading_delivery_note = ldn_name
        qc_request.requested_by = frappe.session.user
        qc_request.requested_on = now()
        qc_request.qc_status = "Pending QC"
        if batch_name:
            qc_request.batch = batch_name
        if coa_name:
            qc_request.coa = coa_name

        sddn_name = self._resolve_sddn_for_report()
        if sddn_name:
            qc_request.security_draft_delivery_note = sddn_name

        # Copy material/vehicle context for QC reference
        qc_request.material_description = self.material_description
        qc_request.container_number = self.container_number
        qc_request.vehicle_number = self.vehicle_number
        qc_request.driver_name = self.driver_name
        qc_request.inspection_type = self.inspection_type

        qc_request.insert()

        if ldn_name:
            frappe.db.set_value(
                "Loading Delivery Note",
                ldn_name,
                {
                    "qc_report_request": qc_request.name,
                    "delivery_note_status": "Pending QC",
                    "qc_status": "Pending QC",
                },
                update_modified=False,
            )

        from apc_operations.services.delivery_order_service import resolve_do_for_ldn

        do_name = None
        if ldn_name:
            do_name = resolve_do_for_ldn(ldn_name)
        elif self.job_order:
            from apc_operations.services.delivery_order_service import (
                find_delivery_order_for_job_order_primary,
            )

            do_name = find_delivery_order_for_job_order_primary(self.job_order)
        if do_name:
            from apc_operations.shipping.services.dispatch_lifecycle_service import (
                sync_dispatch_lifecycle_status,
            )

            sync_dispatch_lifecycle_status(do_name, update_modified=False)

        self.qc_report_request = qc_request.name
        self.security_status = "Reported to QC"
        self.qc_status = "Pending QC"
        self.save()

        self.notify_qc_team()

        return {"success": True, "qc_report_request": qc_request.name}

    def _get_batch_and_coa_for_job_order(self):
        """Look up the primary batch and COA allocated to this Job Order's Sales Demand."""
        if not self.job_order:
            return None, None

        # Try from batch_allocation field on Security Inspection itself
        if self.batch_allocation:
            detail = frappe.get_all(
                "APC Batch Allocation Detail",
                filters={"parent": self.batch_allocation, "status": ["in", ["Allocated", "Partially Dispatched"]]},
                fields=["batch", "coa"],
                limit=1,
            )
            if detail:
                return detail[0].batch, detail[0].coa

        # Try from Sales Demand linked to Job Order.
        # Support both standard and Customize Form auto-prefixed fieldnames.
        sales_demand_job_order_field = None
        if frappe.db.has_column("APC Sales Demand", "job_order"):
            sales_demand_job_order_field = "job_order"
        elif frappe.db.has_column("APC Sales Demand", "custom_job_order"):
            sales_demand_job_order_field = "custom_job_order"

        if not sales_demand_job_order_field:
            return None, None

        sales_demand = frappe.db.get_value(
            "APC Sales Demand",
            {sales_demand_job_order_field: self.job_order},
            "name",
        )
        if not sales_demand:
            return None, None

        allocation = frappe.db.get_value(
            "APC Batch Allocation",
            {"sales_demand": sales_demand, "allocation_status": ["in", ["Allocated", "Partially Dispatched"]]},
            "name",
        )
        if not allocation:
            return None, None

        detail = frappe.get_all(
            "APC Batch Allocation Detail",
            filters={"parent": allocation, "status": ["in", ["Allocated", "Partially Dispatched"]]},
            fields=["batch", "coa"],
            limit=1,
        )
        if detail:
            return detail[0].batch, detail[0].coa

        return None, None

    def notify_qc_team(self):
        try:
            qc_users = role_user_emails(["Quality Manager", "Quality User"])

            if not qc_users:
                return

            subject = f"QC Inspection Required: {self.name}"
            message = f"""
            <h3>New QC Inspection Request</h3>
            <p><b>Security Inspection:</b> {self.name}</p>
            <p><b>Job Order:</b> {self.job_order or 'N/A'}</p>
            <p><b>Customer:</b> {self.customer_name or 'N/A'}</p>
            <p><b>Inspection Type:</b> {self.inspection_type}</p>
            <p><b>Container Number:</b> {self.container_number or 'N/A'}</p>
            <p><b>Vehicle Number:</b> {self.vehicle_number or 'N/A'}</p>
            <br>
            <a href="{frappe.utils.get_url()}/app/qc-report-request/{self.qc_report_request}">View QC Report Request</a>
            """

            for user in qc_users:
                frappe.sendmail(
                    recipients=user,
                    subject=subject,
                    message=message,
                    reference_doctype="QC Report Request",
                    reference_name=self.qc_report_request
                )
        except Exception as e:
            frappe.log_error(f"QC Notification Error: {str(e)}", "Security Inspection")

    @frappe.whitelist()
    def create_loading_delivery_note(self):
        """
        Security creates the Loading Delivery Note after completing the security checklist.
        The Loading DN is created in 'Pending QC' status — QC clearance happens separately.

        Normally a QC Report Request is raised AFTER this via report_to_qc(). But
        report_to_qc() doesn't require an LDN to exist first (it resolves one if
        available, see _resolve_loading_delivery_note_for_report), so a QC Report
        Request can legitimately already exist here too (e.g. Security reported
        to QC for pre-check before creating the LDN). In that case, create the
        LDN as normal and link it back onto the existing QC Report Request
        instead of blocking - the "already exists" guard below only protects
        against creating a second LDN for the same inspection, which is the
        actual duplicate this method needs to prevent.
        """
        if self.loading_delivery_note:
            frappe.throw(_("Loading Delivery Note already exists for this inspection"))

        already_reported_to_qc = self.security_status == "Reported to QC" and self.qc_report_request

        loading_dn = frappe.new_doc("Loading Delivery Note")
        loading_dn.security_inspection = self.name
        loading_dn.job_order = self.job_order
        loading_dn.transportation_request = self.transportation_request
        loading_dn.customer = self.customer
        loading_dn.buyer = self.customer
        loading_dn.vehicle = self.vehicle
        loading_dn.driver = self.driver
        loading_dn.container_number = self.container_number
        loading_dn.seal_number = self.seal_number
        loading_dn.material_description = self.material_description
        loading_dn.loading_date = today()
        from apc_operations.shipping.services.uom_service import apply_commercial_fields

        apply_commercial_fields(
            loading_dn,
            job_order=self.job_order,
            sddn_name=loading_dn.security_draft_delivery_note,
            force_uom=True,
        )
        if not flt(loading_dn.quantity):
            loading_dn.quantity = self.quantity
        if not loading_dn.uom:
            loading_dn.uom = self.uom
        # Propagate Security Draft DN reference if available
        if self.transportation_request:
            draft_dn = frappe.db.get_value(
                "Security Draft Delivery Note",
                {"transport_schedule": self.transportation_request},
                "name",
            )
            if draft_dn:
                loading_dn.security_draft_delivery_note = draft_dn
                loading_dn.buyer = frappe.db.get_value(
                    "Security Draft Delivery Note", draft_dn, "buyer"
                ) or loading_dn.buyer
        # Created in Pending QC — awaiting QC clearance before receivables
        loading_dn.delivery_note_status = "Pending QC"
        loading_dn.qc_status = "Pending QC"
        if self._is_import_inspection():
            loading_dn.receivables_status = "Not Applicable"
            loading_dn.delivery_note_status = "Pending QC"
        else:
            loading_dn.receivables_status = "Pending Receivables"
        loading_dn.insert()

        from apc_operations.shipping.services.dispatch_flow_service import ensure_ldn_do_link

        ensure_ldn_do_link(ldn_name=loading_dn.name, update_modified=False)

        self.loading_delivery_note = loading_dn.name
        if not already_reported_to_qc:
            self.security_status = "Loading DN Created"
        self.save()

        if already_reported_to_qc:
            frappe.db.set_value(
                "QC Report Request",
                self.qc_report_request,
                "loading_delivery_note",
                loading_dn.name,
                update_modified=False,
            )

        # Copy Job Order reservations first; fall back to fresh FIFO when none exist.
        try:
            from apc_operations.services.batch_allocation import (
                create_loading_dn_batch_allocations,
                sync_loading_dn_from_job_order_allocations,
            )

            sync_result = sync_loading_dn_from_job_order_allocations(loading_dn.name)
            if not sync_result.get("rows"):
                create_loading_dn_batch_allocations(
                    loading_dn_name=loading_dn.name,
                    required_qty=self.quantity,
                )
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Loading DN Batch Allocation")

        if already_reported_to_qc:
            msg = _(
                "Loading Delivery Note {0} created and linked to the existing "
                "QC Report Request {1}."
            ).format(loading_dn.name, self.qc_report_request)
        else:
            msg = _(
                "Loading Delivery Note {0} created in Pending QC status. "
                "Use 'Report to QC' to send for QC clearance."
            ).format(loading_dn.name)
        frappe.msgprint(
            msg,
            indicator="blue",
        )

        return {"success": True, "loading_delivery_note": loading_dn.name}

    @frappe.whitelist()
    def create_gate_pass(self):
        """Create Gate Pass for the linked Transport Schedule after checklist completion.

        Security can use this when the Transport Schedule is not yet submitted
        (so ``on_submit`` gate pass creation did not run) or when no gate pass exists.

        Vehicle and driver are taken from the Transport Schedule, or synced from
        this inspection if the schedule is missing them.
        """
        allowed_after_checklist = (
            "Checklist Completed",
            "Loading DN Created",
            "Reported to QC",
            "QC Cleared",
            "QC Rejected",
            "Reported to Receivables",
            "Completed",
        )
        if self.security_status not in allowed_after_checklist:
            frappe.throw(
                _("Create Gate Pass is only available after the security checklist is completed.")
            )
        if not self.transportation_request:
            frappe.throw(_("Transport Schedule is required to create a Gate Pass."))

        ts = frappe.get_doc("Transport Schedule", self.transportation_request, ignore_permissions=True)

        existing_gp = ts.get("gate_pass")
        if existing_gp and frappe.db.exists("Gate Pass", existing_gp):
            frappe.throw(_("Gate Pass {0} already exists for this transport.").format(existing_gp))

        updates = {}
        if not ts.assigned_vehicle and self.vehicle:
            updates["assigned_vehicle"] = self.vehicle
        if not ts.assigned_driver and self.driver:
            updates["assigned_driver"] = self.driver
        if not ts.get("driver_phone") and self.driver_phone:
            updates["driver_phone"] = self.driver_phone
        if updates:
            frappe.db.set_value("Transport Schedule", ts.name, updates, update_modified=False)
            ts.reload()

        if not ts.assigned_vehicle:
            frappe.throw(
                _("Assign a vehicle on this inspection or the Transport Schedule before creating a Gate Pass.")
            )
        if not ts.assigned_driver:
            frappe.throw(
                _("Assign a driver on this inspection or the Transport Schedule before creating a Gate Pass.")
            )

        gp_name = ts.create_gate_passes(allow_without_submit=True, ignore_permissions=True)
        if not gp_name:
            frappe.throw(
                _("Could not create Gate Pass. Ensure vehicle and driver are set, then try again.")
            )

        return {"success": True, "gate_pass": gp_name}

    @frappe.whitelist()
    def create_dispatch_order(self):
        """Create Dispatch Order from Security Inspection after QC clearance."""
        if self.dispatch_order:
            frappe.throw(_("Dispatch Order already exists for this inspection"))

        if self.qc_status != "QC Cleared":
            frappe.throw(_("QC clearance is required before creating Dispatch Order"))

        # Find the batch allocation for this job order
        if not self.job_order:
            frappe.throw(_("Job Order is required to create Dispatch Order"))

        # Phase 1 (Option B): Job Order.sales_demand is the single source
        # of truth for the originating Sales Demand. Falls back to NULL
        # for legacy JOs (feature flag off) so downstream code must
        # tolerate a None.
        sales_demand = frappe.db.get_value("Job Order", self.job_order, "sales_demand")

        allocation = None
        if sales_demand:
            allocation = frappe.db.get_value(
                "APC Batch Allocation",
                {
                    "sales_demand": sales_demand,
                    "allocation_status": ["in", ["Allocated", "Partially Dispatched"]],
                },
                "name",
            )

        # Create dispatch order
        dispatch = frappe.new_doc("APC Dispatch Order")
        dispatch.sales_demand = sales_demand
        dispatch.batch_allocation = allocation
        dispatch.customer = self.customer
        dispatch.dispatch_date = today()
        dispatch.status = "Ready"

        # Add delivery details from inspection
        dispatch.vehicle_number = self.vehicle_number
        dispatch.driver_name = self.driver_name
        dispatch.delivery_address = ""

        # Add batch details from allocation if exists
        if allocation:
            alloc_doc = frappe.get_doc("APC Batch Allocation", allocation)
            for detail in alloc_doc.allocation_details:
                if detail.status in ["Allocated", "Partially Dispatched"]:
                    remaining = flt(detail.allocated_quantity) - flt(detail.dispatched_quantity)
                    if remaining > 0:
                        dispatch.append("batch_details", {
                            "sales_demand_item": detail.sales_demand_item,
                            "item": detail.item,
                            "item_name": detail.item_name,
                            "batch": detail.batch,
                            "batch_number": detail.batch_number,
                            "quantity": remaining,
                            "coa": detail.coa,
                            "manufacturing_date": detail.manufacturing_date,
                            "warehouse": detail.warehouse,
                            "quality_status": "Approved"
                        })
        else:
            # No allocation - add items from job order
            job_order = frappe.get_doc("Job Order", self.job_order)
            for item in job_order.items:
                dispatch.append("batch_details", {
                    "item": item.item,
                    "item_name": item.item_name,
                    "quantity": item.quantity,
                    "uom": item.uom
                })

        dispatch.insert()

        # Link dispatch to inspection
        self.dispatch_order = dispatch.name
        self.batch_allocation = allocation
        self.save()

        frappe.msgprint(_("Dispatch Order {0} created successfully").format(dispatch.name))

        return {"success": True, "dispatch_order": dispatch.name}


@frappe.whitelist()
def create_security_inspection_from_job_order(job_order):
    """Create Security Inspection directly from a Job Order."""
    # Check if an inspection already exists for this job order
    existing = frappe.db.exists("Security Inspection", {"job_order": job_order})
    if existing:
        frappe.throw(_("Security Inspection {0} already exists for this Job Order").format(existing))

    job = frappe.get_doc("Job Order", job_order)

    inspection = frappe.new_doc("Security Inspection")
    inspection.job_order = job_order
    inspection.customer = job.customer

    # Link to transport schedule only if it exists and is not cancelled
    transport_schedule = frappe.db.get_value(
        "Transport Schedule",
        {"job_order": job_order, "docstatus": ["!=", 2]},
        "name"
    )
    if transport_schedule:
        inspection.transportation_request = transport_schedule

    inspection.inspection_type = "Container"
    inspection.inspection_date = today()
    inspection.security_status = "Draft"
    inspection.qc_status = "Not Sent"
    inspection.receivables_status = "Not Applicable"

    inspection.insert()

    return {"success": True, "inspection": inspection.name}


@frappe.whitelist()
def create_security_inspection_from_draft_dn(draft_dn_name):
    """Promote a Security Draft Delivery Note into a Security Inspection."""
    draft_dn_ts = frappe.db.get_value("Security Draft Delivery Note", draft_dn_name, "transport_schedule")
    if not draft_dn_ts:
        frappe.throw(_("Security Draft Delivery Note has no linked Transport Schedule"))

    # Check if an inspection already exists for this transport schedule
    existing_inspection = frappe.db.exists(
        "Security Inspection",
        {"transportation_request": draft_dn_ts, "docstatus": ["!=", 2]}
    )
    if existing_inspection:
        frappe.throw(_("A Security Inspection already exists for this transport schedule"))

    # Check if transport schedule is cancelled — if so, skip the link
    ts_docstatus = frappe.db.get_value("Transport Schedule", draft_dn_ts, "docstatus")
    ts_is_cancelled = ts_docstatus == 2

    draft_dn = frappe.get_doc("Security Draft Delivery Note", draft_dn_name)

    inspection = frappe.new_doc("Security Inspection")
    inspection.job_order = draft_dn.job_order
    if not ts_is_cancelled:
        inspection.transportation_request = draft_dn.transport_schedule
    inspection.shipping_booking = frappe.db.get_value(
        "Transport Schedule", draft_dn.transport_schedule, "shipping_booking"
    )
    from apc_operations.services.customer_link_service import (
        ensure_sddn_customer_links,
        get_customer_display_name,
    )

    ensure_sddn_customer_links(draft_dn)
    inspection.customer = draft_dn.customer
    if draft_dn.customer:
        inspection.customer_name = get_customer_display_name(draft_dn.customer)
    inspection.vehicle = draft_dn.vehicle
    inspection.driver = draft_dn.driver
    inspection.transporter = draft_dn.transporter
    inspection.container_type = draft_dn.container_type
    inspection.material_description = draft_dn.material_description
    inspection.quantity = draft_dn.quantity
    inspection.uom = draft_dn.uom
    inspection.inspection_date = today()

    if (draft_dn.transport_type or "").strip() == "Inward":
        inspection.inspection_type = "Import Container"
    else:
        outward_type_map = {
            "Export Container": "Export Container",
            "Local Delivery": "Local Delivery",
            "Tanker Delivery": "Tanker",
            "Trailer Delivery": "Trailer",
        }
        inspection.inspection_type = outward_type_map.get(draft_dn.outward_type, "Container")

    inspection.security_status = "Draft"
    inspection.qc_status = "Not Sent"
    inspection.receivables_status = "Not Applicable"
    inspection.insert()

    # Update draft DN status
    frappe.db.set_value(
        "Security Draft Delivery Note",
        draft_dn_name,
        {"security_status": "Approved"},
        update_modified=False,
    )

    frappe.msgprint(
        _("Security Inspection {0} created from Draft DN").format(inspection.name),
        indicator="green",
    )

    return {"success": True, "inspection": inspection.name}

@frappe.whitelist()
def get_pending_inspections():
    return frappe.get_all(
        "Security Inspection",
        filters={
            "security_status": ["in", ["Draft", "Pending Checklist", "Checklist Completed"]]
        },
        fields=["name", "job_order", "customer_name", "inspection_type", "security_status", "inspection_date"],
        order_by="inspection_date ASC"
    )


@frappe.whitelist()
def get_qc_pending_inspections():
    return frappe.get_all(
        "Security Inspection",
        filters={
            "qc_status": ["in", ["Pending QC", "Not Sent"]],
            "security_status": ["!=", "Cancelled"]
        },
        fields=["name", "job_order", "customer_name", "qc_status", "qc_report_request"],
        order_by="inspection_date ASC"
    )
