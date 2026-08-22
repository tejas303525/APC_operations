# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, today


# Incoterms 2020 — responsibility matrix for OUTWARD (APC selling).
# Keys map cleanly to the dropdown options in job_order.json.
#
# Field meaning:
#   freight_borne_by         – who pays main carriage
#   insurance_borne_by       – who is contractually obligated to insure
#   transport_arranged_by    – who arranges the inland leg from APC premises
#   shipping_arranged_by     – who books the main international carriage
#   transport_required       – APC needs an internal Transport Schedule
#                              (always 1 for outward — security/gate-pass
#                              tracking applies even when buyer collects)
#   shipping_required        – APC needs a Shipping Booking record
#                              (set 1 whenever vessel info needs to be tracked,
#                              regardless of who books — APC for CFR/CIF/etc.,
#                              buyer for FOB)
#   insurance_required       – APC must procure a cargo insurance policy
#   booking_requirement      – legacy summary field
#   transport_requirement_status / notes – user-facing status & note
#   risk_transfer_point      – plain-English risk transfer description
INCOTERM_RULES = {
    "EXW": {
        "freight_borne_by": "Customer",
        "insurance_borne_by": "Customer",
        "transport_arranged_by": "Customer",
        "shipping_arranged_by": "Not Applicable",
        "transport_required": 1,
        "shipping_required": 0,
        "insurance_required": 0,
        "booking_requirement": "Transport Booking",
        "transport_requirement_status": "Customer Arranged",
        "risk_transfer_point": "Seller's premises — goods made available to buyer",
        "transport_requirement_notes": (
            "EXW: Buyer collects from APC premises and arranges all onward "
            "transport, freight and insurance. APC creates a Transport "
            "Schedule purely for security gate-pass tracking."
        ),
    },
    "FCA": {
        "freight_borne_by": "Customer",
        "insurance_borne_by": "Customer",
        "transport_arranged_by": "APC",
        "shipping_arranged_by": "Customer",
        "transport_required": 1,
        "shipping_required": 0,
        "insurance_required": 0,
        "booking_requirement": "Transport Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "On delivery to the carrier nominated by buyer at the named place",
        "transport_requirement_notes": (
            "FCA: APC delivers cleared-for-export goods to the buyer's "
            "nominated carrier or named place. Buyer arranges and pays "
            "the main carriage and insurance."
        ),
    },
    "FOB": {
        "freight_borne_by": "Customer",
        "insurance_borne_by": "Customer",
        "transport_arranged_by": "APC",
        "shipping_arranged_by": "Customer",
        "transport_required": 1,
        "shipping_required": 1,
        "insurance_required": 0,
        "booking_requirement": "Transport and Ship Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "On board the vessel at Port of Loading",
        "transport_requirement_notes": (
            "FOB: APC arranges inland transport to POL, export clearance "
            "and on-board loading. Buyer books and pays the main vessel "
            "and insurance. Shipping Booking is used to record buyer-"
            "supplied vessel/CRO information."
        ),
    },
    "CFR": {
        "freight_borne_by": "APC",
        "insurance_borne_by": "Customer",
        "transport_arranged_by": "APC",
        "shipping_arranged_by": "APC",
        "transport_required": 1,
        "shipping_required": 1,
        "insurance_required": 0,
        "booking_requirement": "Transport and Ship Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "On board the vessel at Port of Loading (cost transferred at POD)",
        "transport_requirement_notes": (
            "CFR: APC arranges and pays inland transport AND main carriage "
            "to Port of Discharge. Buyer assumes risk once goods are on "
            "board and arranges its own insurance."
        ),
    },
    "CIF": {
        "freight_borne_by": "APC",
        "insurance_borne_by": "APC",
        "transport_arranged_by": "APC",
        "shipping_arranged_by": "APC",
        "transport_required": 1,
        "shipping_required": 1,
        "insurance_required": 1,
        "booking_requirement": "Transport and Ship Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "On board the vessel at Port of Loading (cost+insurance to POD)",
        "transport_requirement_notes": (
            "CIF: APC arranges main carriage to POD AND procures minimum-"
            "cover marine cargo insurance for the buyer's benefit. Risk "
            "passes when goods are on board."
        ),
    },
    "CPT": {
        "freight_borne_by": "APC",
        "insurance_borne_by": "Customer",
        "transport_arranged_by": "APC",
        "shipping_arranged_by": "APC",
        "transport_required": 1,
        "shipping_required": 1,
        "insurance_required": 0,
        "booking_requirement": "Transport and Ship Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "On handover to the first carrier (cost paid to named destination)",
        "transport_requirement_notes": (
            "CPT: APC arranges and pays carriage to the named place of "
            "destination. Risk transfers at first carrier; buyer arranges "
            "insurance."
        ),
    },
    "CIP": {
        "freight_borne_by": "APC",
        "insurance_borne_by": "APC",
        "transport_arranged_by": "APC",
        "shipping_arranged_by": "APC",
        "transport_required": 1,
        "shipping_required": 1,
        "insurance_required": 1,
        "booking_requirement": "Transport and Ship Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "On handover to the first carrier (cost+all-risk insurance to destination)",
        "transport_requirement_notes": (
            "CIP: APC arranges carriage AND procures all-risk (Institute "
            "Cargo Clauses A) insurance to the named destination."
        ),
    },
    "DAP": {
        "freight_borne_by": "APC",
        "insurance_borne_by": "APC",
        "transport_arranged_by": "APC",
        "shipping_arranged_by": "APC",
        "transport_required": 1,
        "shipping_required": 1,
        "insurance_required": 0,
        "booking_requirement": "Transport and Ship Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "At named destination, ready for unloading",
        "transport_requirement_notes": (
            "DAP: APC delivers to the named destination ready for "
            "unloading. Buyer unloads and clears imports. APC carries "
            "risk to delivery; insurance is APC's commercial decision."
        ),
    },
    "DDU": {
        # Pre-2010 Incoterms predecessor of DAP, superseded by it but still
        # used by some counterparties. Same obligations as DAP: seller
        # delivers to the named destination ready for unloading; buyer
        # clears import and unloads.
        "freight_borne_by": "APC",
        "insurance_borne_by": "APC",
        "transport_arranged_by": "APC",
        "shipping_arranged_by": "APC",
        "transport_required": 1,
        "shipping_required": 1,
        "insurance_required": 0,
        "booking_requirement": "Transport and Ship Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "At named destination, ready for unloading",
        "transport_requirement_notes": (
            "DDU (pre-2010 equivalent of DAP): APC delivers to the named "
            "destination ready for unloading, not cleared for import. "
            "Buyer unloads and clears imports/duties. APC carries risk to "
            "delivery; insurance is APC's commercial decision."
        ),
    },
    "DPU": {
        "freight_borne_by": "APC",
        "insurance_borne_by": "APC",
        "transport_arranged_by": "APC",
        "shipping_arranged_by": "APC",
        "transport_required": 1,
        "shipping_required": 1,
        "insurance_required": 0,
        "booking_requirement": "Transport and Ship Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "At named destination, AFTER unloading",
        "transport_requirement_notes": (
            "DPU: APC delivers AND unloads at the named destination. "
            "Buyer handles import clearance and onward duties."
        ),
    },
    "DDP": {
        "freight_borne_by": "APC",
        "insurance_borne_by": "APC",
        "transport_arranged_by": "APC",
        "shipping_arranged_by": "APC",
        "transport_required": 1,
        "shipping_required": 1,
        "insurance_required": 0,
        "booking_requirement": "Transport and Ship Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "At named destination after import clearance, ready for unloading",
        "transport_requirement_notes": (
            "DDP: APC bears the maximum obligation — inland transport, "
            "main carriage, export AND import clearance, import duties, "
            "and delivery to the buyer's named place. Insurance is APC's "
            "commercial decision."
        ),
    },
}


# Incoterms 2020 — APC as **buyer** (import). "Customer" in freight/insurance/arrangement
# fields denotes the **supplier / foreign seller** (same option set as export for UI).
INCOTERM_RULES_IMPORT = {
    "EXW": {
        "freight_borne_by": "APC",
        "insurance_borne_by": "APC",
        "transport_arranged_by": "APC",
        "shipping_arranged_by": "Not Applicable",
        "transport_required": 1,
        "shipping_required": 0,
        "insurance_required": 0,
        "booking_requirement": "Transport Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "Supplier's premises — goods made available to APC (buyer)",
        "transport_requirement_notes": (
            "EXW (Import): Supplier makes goods available at their premises. APC arranges "
            "collection, onward transport and insurance. Transport Schedule coordinates "
            "pickup and site control at origin."
        ),
    },
    "FCA": {
        "freight_borne_by": "APC",
        "insurance_borne_by": "APC",
        "transport_arranged_by": "Customer",
        "shipping_arranged_by": "APC",
        "transport_required": 1,
        "shipping_required": 0,
        "insurance_required": 0,
        "booking_requirement": "Transport Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "When supplier delivers goods to the carrier nominated by APC at the named place",
        "transport_requirement_notes": (
            "FCA (Import): Supplier delivers cleared-for-export goods to APC's nominated "
            "carrier or place. APC arranges and pays main carriage and insurance thereafter."
        ),
    },
    "FOB": {
        "freight_borne_by": "APC",
        "insurance_borne_by": "APC",
        "transport_arranged_by": "Customer",
        "shipping_arranged_by": "APC",
        "transport_required": 1,
        "shipping_required": 1,
        "insurance_required": 0,
        "booking_requirement": "Transport and Ship Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "On board the vessel at Port of Loading (supplier's country)",
        "transport_requirement_notes": (
            "FOB (Import): Supplier loads on board the vessel nominated by APC. APC books "
            "the vessel and marine insurance as buyer. Shipping Booking records vessel/CRO. "
            "Supplier arranges pre-carriage to the port of loading."
        ),
    },
    "CFR": {
        "freight_borne_by": "Customer",
        "insurance_borne_by": "APC",
        "transport_arranged_by": "APC",
        "shipping_arranged_by": "Customer",
        "transport_required": 1,
        "shipping_required": 1,
        "insurance_required": 0,
        "booking_requirement": "Transport and Ship Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "On board the vessel at Port of Loading; cost to POD borne by supplier",
        "transport_requirement_notes": (
            "CFR (Import): Supplier pays freight to Port of Discharge. APC assumes risk once "
            "goods are on board and arranges marine insurance. APC may coordinate onward "
            "transport from POD via Transport Schedule."
        ),
    },
    "CIF": {
        "freight_borne_by": "Customer",
        "insurance_borne_by": "Customer",
        "transport_arranged_by": "APC",
        "shipping_arranged_by": "Customer",
        "transport_required": 1,
        "shipping_required": 1,
        "insurance_required": 0,
        "booking_requirement": "Transport and Ship Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "On board the vessel at Port of Loading; supplier arranges freight and minimum insurance to POD",
        "transport_requirement_notes": (
            "CIF (Import): Supplier arranges main carriage and minimum marine insurance to POD. "
            "Risk passes when goods are on board. APC does not procure the seller's policy; "
            "optional additional cover is APC's commercial decision."
        ),
    },
    "CPT": {
        "freight_borne_by": "Customer",
        "insurance_borne_by": "APC",
        "transport_arranged_by": "APC",
        "shipping_arranged_by": "Customer",
        "transport_required": 1,
        "shipping_required": 1,
        "insurance_required": 0,
        "booking_requirement": "Transport and Ship Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "On handover to the first carrier; supplier pays carriage to named destination",
        "transport_requirement_notes": (
            "CPT (Import): Supplier pays carriage to the named place of destination. Risk transfers "
            "to APC at first carrier; APC arranges its own cargo insurance if desired."
        ),
    },
    "CIP": {
        "freight_borne_by": "Customer",
        "insurance_borne_by": "Customer",
        "transport_arranged_by": "APC",
        "shipping_arranged_by": "Customer",
        "transport_required": 1,
        "shipping_required": 1,
        "insurance_required": 0,
        "booking_requirement": "Transport and Ship Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "On handover to the first carrier; supplier pays carriage and all-risk insurance to destination",
        "transport_requirement_notes": (
            "CIP (Import): Supplier arranges carriage and all-risk insurance to the named destination. "
            "APC does not enter the seller's policy on this Job Order."
        ),
    },
    "DAP": {
        "freight_borne_by": "Customer",
        "insurance_borne_by": "Customer",
        "transport_arranged_by": "Customer",
        "shipping_arranged_by": "Customer",
        "transport_required": 1,
        "shipping_required": 1,
        "insurance_required": 0,
        "booking_requirement": "Transport and Ship Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "At named destination ready for unloading — supplier delivers",
        "transport_requirement_notes": (
            "DAP (Import): Supplier delivers to the named place in the destination country ready for "
            "unloading. APC clears import and unloads. APC may use Transport Schedule for site coordination."
        ),
    },
    "DDU": {
        # Pre-2010 predecessor of DAP - same obligations.
        "freight_borne_by": "Customer",
        "insurance_borne_by": "Customer",
        "transport_arranged_by": "Customer",
        "shipping_arranged_by": "Customer",
        "transport_required": 1,
        "shipping_required": 1,
        "insurance_required": 0,
        "booking_requirement": "Transport and Ship Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "At named destination ready for unloading — supplier delivers",
        "transport_requirement_notes": (
            "DDU (Import, pre-2010 equivalent of DAP): Supplier delivers to the named place in the "
            "destination country ready for unloading, not cleared for import. APC clears import and "
            "unloads. APC may use Transport Schedule for site coordination."
        ),
    },
    "DPU": {
        "freight_borne_by": "Customer",
        "insurance_borne_by": "Customer",
        "transport_arranged_by": "Customer",
        "shipping_arranged_by": "Customer",
        "transport_required": 1,
        "shipping_required": 1,
        "insurance_required": 0,
        "booking_requirement": "Transport and Ship Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "At named destination after unloading — supplier delivers and unloads",
        "transport_requirement_notes": (
            "DPU (Import): Supplier delivers and unloads at the named place. APC handles import "
            "clearance and onward duties."
        ),
    },
    "DDP": {
        "freight_borne_by": "Customer",
        "insurance_borne_by": "Customer",
        "transport_arranged_by": "Customer",
        "shipping_arranged_by": "Customer",
        "transport_required": 1,
        "shipping_required": 1,
        "insurance_required": 0,
        "booking_requirement": "Transport and Ship Booking",
        "transport_requirement_status": "Transport Required",
        "risk_transfer_point": "At named destination after import clearance — supplier bears maximum obligation",
        "transport_requirement_notes": (
            "DDP (Import): Supplier delivers duty paid to APC's named place including import clearance "
            "and duties. APC receives goods; internal transport records may still be used for site coordination."
        ),
    },
}


# Modes of transport for which a Shipping Booking record is meaningful.
# For purely Road/Rail outward movements, no Shipping Booking is created
# even if the incoterm rule says shipping_required = 1.
SHIPPING_BOOKING_MODES = {"sea", "air"}


def get_incoterm_rule(incoterm, movement=None):
    """Return the rules dict for a given incoterm and commercial movement.

    ``movement``: ``Outward`` (default), ``Import``, or None to infer Outward.
    """
    if not incoterm:
        return None
    key = incoterm.strip().upper()
    if (movement or "").strip() == "Import":
        return INCOTERM_RULES_IMPORT.get(key)
    return INCOTERM_RULES.get(key)


def get_primary_transport_type_for_job_order(movement):
    """Transport type stored on Job Order.transport_schedule for this movement."""
    return "Inward" if (movement or "").strip() == "Import" else "Outward"


# Legacy Select values from Job Order.bank before Link → Bank Account migration.
_LEGACY_BANK_ACCOUNT_MAP = {
    "HABIB": "HABIB - HABIB",
}


class JobOrder(Document):
    def normalize_bank_account(self):
        """Map legacy bank codes to ERPNext Bank Account names before link validation."""
        bank_account = (self.bank_account or "").strip()
        if bank_account in _LEGACY_BANK_ACCOUNT_MAP:
            self.bank_account = _LEGACY_BANK_ACCOUNT_MAP[bank_account]
            return

        if bank_account and frappe.db.exists("Bank Account", bank_account):
            return

        legacy = (self.get("bank") or "").strip()
        if not legacy and self.name:
            legacy = (frappe.db.get_value("Job Order", self.name, "bank") or "").strip()

        if legacy in _LEGACY_BANK_ACCOUNT_MAP:
            self.bank_account = _LEGACY_BANK_ACCOUNT_MAP[legacy]
            return

        if bank_account and not frappe.db.exists("Bank Account", bank_account):
            self.bank_account = None

    def insert(self, *args, **kwargs):
        self.normalize_bank_account()
        return super().insert(*args, **kwargs)

    def save(self, *args, **kwargs):
        self.normalize_bank_account()
        return super().save(*args, **kwargs)

    def validate(self):
        self.validate_job_order_number_uniqueness()
        self.validate_commercial_counterparty()
        self.validate_import_sea_ports()
        self.validate_sales_demand_link()
        self.fetch_customer_name()
        self.apply_packing_matrix()
        self.determine_booking_requirement()
        self.sync_booking_flags()
        self.validate_insurance_on_confirm()

    def apply_packing_matrix(self):
        from apc_operations.shipping.services.packing_calculation_service import (
            apply_packing_to_job_order,
        )

        apply_packing_to_job_order(self)

    def validate_sales_demand_link(self):
        """Option B: enforce the Job Order \u2194 Sales Demand cardinality.

        When the feature flag is on, ``sales_demand`` is mandatory. When a
        Sales Demand is linked the customer must match. Job Order Items that
        carry a ``sales_demand_item`` reference must belong to the same SD.
        """
        from apc_operations.shipping.doctype.apc_operations_settings.apc_operations_settings import (
            require_sales_demand_on_job_order,
        )

        flag_on = require_sales_demand_on_job_order()

        if flag_on and not self.sales_demand:
            frappe.throw(_(
                "Sales Demand is required on Job Order (APC Operations Settings \u2192 "
                "Require Sales Demand on Job Order is on). Link a Sales Demand or "
                "disable the flag to allow standalone Job Orders."
            ))

        if not self.sales_demand:
            return

        sd_customer = frappe.db.get_value("APC Sales Demand", self.sales_demand, "customer")
        if sd_customer and self.customer and sd_customer != self.customer:
            frappe.throw(_(
                "Sales Demand {0} belongs to customer {1}, but Job Order customer is {2}."
            ).format(self.sales_demand, sd_customer, self.customer))

        # Every Job Order Item that references a Sales Demand Item must belong
        # to the same Sales Demand.
        sd_items = set(
            frappe.get_all(
                "APC Sales Demand Item",
                filters={"parent": self.sales_demand},
                pluck="name",
            )
        )
        for row in self.items or []:
            if row.sales_demand_item and row.sales_demand_item not in sd_items:
                frappe.throw(_(
                    "Row {0}: Sales Demand Item {1} does not belong to Sales Demand {2}."
                ).format(row.idx, row.sales_demand_item, self.sales_demand))

    def validate_commercial_counterparty(self):
        movement = (self.commercial_movement or "").strip() or "Outward"
        if movement == "Outward":
            if not self.customer:
                frappe.throw(_("Customer is mandatory for Outward Job Orders."))
        elif movement == "Import":
            if not self.supplier:
                frappe.throw(_("Supplier is mandatory for Import Job Orders."))
        else:
            frappe.throw(_("Commercial movement must be Outward or Import."))

    def validate_import_sea_ports(self):
        if not self._is_import_movement():
            return
        if (self.mode_of_transport or "").strip() != "Sea":
            return
        if not self.port_of_loading:
            frappe.throw(_("Port of Loading is required for Import sea Job Orders."))
        if not self.port_of_discharge:
            frappe.throw(_("Port of Discharge is required for Import sea Job Orders."))

    def validate_job_order_number_uniqueness(self):
        """Prevent duplicate external/business job order references."""
        if not self.job_order_number:
            return

        duplicate = frappe.db.exists(
            "Job Order",
            {"job_order_number": self.job_order_number, "name": ["!=", self.name]},
        )
        if duplicate:
            frappe.throw(
                _(
                    "Job Order Number {0} is already used by {1}. Please use a unique reference."
                ).format(self.job_order_number, duplicate)
            )

    def on_update(self):
        # Keep confirmed records operationally complete even if status was
        # already Confirmed before this save (e.g. data imports/manual edits).
        self.ensure_operational_booking_links()
        if self.job_order_number and (
            self.has_value_changed("job_order_number") or self._linked_job_order_number_is_stale()
        ):
            self._sync_job_order_number_to_linked_documents()

    def _linked_job_order_number_is_stale(self) -> bool:
        """True when a linked doc still stores an old copied job order number."""
        if not self.name or not self.job_order_number:
            return False

        if self.shipping_booking:
            stored = frappe.db.get_value(
                "Shipping Booking", self.shipping_booking, "job_order_number"
            )
            if stored and stored != self.job_order_number:
                return True

        if self.transport_schedule:
            stored = frappe.db.get_value(
                "Transport Schedule", self.transport_schedule, "job_order_number"
            )
            if stored and stored != self.job_order_number:
                return True

        return False

    def _sync_job_order_number_to_linked_documents(self):
        from apc_operations.shipping.services.job_order_sync_service import (
            sync_job_order_number_to_linked,
        )

        sync_job_order_number_to_linked(self.name, self.job_order_number)

    def after_insert(self):
        self.ensure_operational_booking_links()

    def on_submit(self):
        self.ensure_operational_booking_links()

    def fetch_customer_name(self):
        from apc_operations.services.customer_link_service import normalize_customer_field

        normalize_customer_field(self, "customer")
        if self.customer and not self.customer_name:
            self.customer_name = frappe.db.get_value("Customer", self.customer, "customer_name")
        if self.supplier and not self.supplier_name:
            self.supplier_name = frappe.db.get_value("Supplier", self.supplier, "supplier_name")

    def determine_booking_requirement(self):
        incoterm = (self.terms_of_delivery or "").strip().upper()

        if not incoterm:
            self._reset_responsibility_fields()
            self.transport_requirement_notes = (
                "Select Terms of Delivery to evaluate transport responsibility."
            )
            return

        rule = get_incoterm_rule(incoterm, self.commercial_movement)
        if not rule:
            self._reset_responsibility_fields()
            self.transport_requirement_notes = (
                f"No responsibility rule configured for incoterm {incoterm}."
            )
            return

        self._apply_rule(rule)

    def _reset_responsibility_fields(self):
        self.booking_requirement = ""
        self.transport_required = 0
        self.shipping_required = 0
        self.transport_status = "Pending Review"
        self.shipping_status = "Pending Review"
        self.transport_requirement_status = "Pending Review"
        self.freight_borne_by = ""
        self.insurance_borne_by = ""
        self.transport_arranged_by = ""
        self.shipping_arranged_by = ""
        self.insurance_required = 0
        self.risk_transfer_point = ""

    def _apply_rule(self, rule):
        # Mode of transport gates whether a Shipping Booking is needed.
        # If the user picks Road/Rail, force shipping_required = 0 even
        # if the incoterm rule defaults to 1.
        mode = (self.mode_of_transport or "").strip().lower()
        rule_shipping_required = int(rule["shipping_required"])
        if rule_shipping_required and mode and mode not in SHIPPING_BOOKING_MODES:
            shipping_required = 0
            shipping_arranged_by = "Not Applicable"
        else:
            shipping_required = rule_shipping_required
            shipping_arranged_by = rule["shipping_arranged_by"]

        self.booking_requirement = rule["booking_requirement"]
        self.transport_required = int(rule["transport_required"])
        self.shipping_required = shipping_required
        self.transport_requirement_status = rule["transport_requirement_status"]
        self.transport_requirement_notes = rule["transport_requirement_notes"]

        self.freight_borne_by = rule["freight_borne_by"]
        self.insurance_borne_by = rule["insurance_borne_by"]
        self.transport_arranged_by = rule["transport_arranged_by"]
        self.shipping_arranged_by = shipping_arranged_by
        self.insurance_required = int(rule["insurance_required"])
        self.risk_transfer_point = rule["risk_transfer_point"]

        # Initial transport / shipping status only when not already set
        # to a more advanced value by downstream sync.
        if not self.transport_status or self.transport_status in ("", "Pending Review"):
            self.transport_status = "Pending Booking" if self.transport_required else "Not Required"

        if not self.shipping_status or self.shipping_status in ("", "Pending Review"):
            if self.shipping_required:
                self.shipping_status = "Pending Shipping Booking"
            else:
                self.shipping_status = "Not Required"

    def validate_insurance_on_confirm(self):
        # Only enforce on Confirmed-or-later, so users can still draft.
        if not self.insurance_required:
            return
        if self.status not in ("Confirmed", "In Progress", "Completed"):
            return
        if not self.insurance_policy_no:
            frappe.throw(
                _(
                    "Incoterm {0} requires APC to procure cargo insurance. "
                    "Set Insurance Policy No. before confirming this Job Order."
                ).format(self.terms_of_delivery)
            )

    def sync_booking_flags(self):
        if self.transport_schedule:
            # When a TS is linked, the TS's transport_status is authoritative —
            # never assume "Scheduled". Mapping a still-unassigned TS
            # ("Pending Assignment") to "Pending Booking" is what surfaces it
            # in the Transportation Console "Pending Transport Bookings" queue.
            from apc_operations.shipping.transport_events import (
                TRANSPORT_TO_JOB_ORDER_STATUS,
            )

            self.transport_required = 1
            ts_status = frappe.db.get_value(
                "Transport Schedule", self.transport_schedule, "transport_status"
            )
            if ts_status:
                self.transport_status = TRANSPORT_TO_JOB_ORDER_STATUS.get(
                    ts_status, "Pending Booking"
                )
        elif not self.transport_required and self.transport_status == "Scheduled":
            self.transport_status = "Not Required"

        if self.shipping_booking:
            self.shipping_status = self.get_default_shipping_status()
            self.shipping_required = 1
        elif not self.shipping_required and self.shipping_status == "Pending Shipping Booking":
            self.shipping_status = "Not Required"

    def create_or_link_on_business_confirmation(self):
        """Called when status changes to Confirmed via on_update."""
        if self.status != "Confirmed":
            return

        # Prevent duplicate execution
        if frappe.flags.in_create_operational_booking:
            return

        self.create_or_link_operational_booking()

    def ensure_operational_booking_links(self):
        """Ensure confirmed orders have the required operational links."""
        if self.status != "Confirmed":
            return

        # Prevent duplicate execution during nested lifecycle callbacks.
        if frappe.flags.in_create_operational_booking:
            return

        needs_shipping = bool(
            self.shipping_required and not (self.shipping_booking or self.get_existing_shipping_booking())
        )
        needs_transport = bool(
            self.transport_required and not (self.transport_schedule or self.get_existing_transport_schedule())
        )

        if needs_shipping or needs_transport:
            self.create_or_link_operational_booking()

    def create_or_link_operational_booking(self):
        # Drive auto-creation off the derived flags rather than the raw
        # incoterm. This keeps the controller honest about WHY documents
        # are being created.
        if frappe.flags.in_create_operational_booking:
            return

        frappe.flags.in_create_operational_booking = True
        try:
            if self.shipping_required:
                self.create_or_link_shipping_booking()
                # Ensure TS exists immediately for APC transport obligations
                # (e.g. FOB/CFR/CIF), rather than waiting for CRO-driven flows.
                if self.transport_required and not self.transport_schedule:
                    self.create_or_link_transport_schedule()
                return

            if self.transport_required:
                self.create_or_link_transport_schedule()
                return
        finally:
            frappe.flags.in_create_operational_booking = False

    def get_existing_transport_schedule(self):
        if not self.name:
            return None
        ttype = get_primary_transport_type_for_job_order(self.commercial_movement)
        rows = frappe.get_all(
            "Transport Schedule",
            filters={
                "job_order": self.name,
                "transport_type": ttype,
                "transport_status": ["!=", "Cancelled"],
            },
            pluck="name",
            order_by="modified desc",
            limit=1,
        )
        return rows[0] if rows else None

    def get_existing_shipping_booking(self):
        if not self.name:
            return None
        return frappe.db.get_value("Shipping Booking", {"job_order": self.name}, "name")

    def create_or_link_transport_schedule(self):
        # We import the TS→JO status map lazily to avoid a circular import
        # between job_order.py and transport_events.py.
        from apc_operations.shipping.transport_events import TRANSPORT_TO_JOB_ORDER_STATUS

        linked_schedule = self.transport_schedule or self.get_existing_transport_schedule()
        if linked_schedule:
            self.db_set("transport_schedule", linked_schedule, update_modified=False)
            existing_ts_status = frappe.db.get_value(
                "Transport Schedule", linked_schedule, "transport_status"
            )
            mapped_status = TRANSPORT_TO_JOB_ORDER_STATUS.get(
                existing_ts_status, "Pending Booking"
            )
            self.db_set("transport_status", mapped_status, update_modified=False)
            return linked_schedule

        schedule = frappe.new_doc("Transport Schedule")
        schedule.source_document_type = "Job Order"
        schedule.job_order = self.name
        schedule.customer = self.customer
        if self._is_import_movement() and self.supplier:
            schedule.supplier = frappe.db.get_value("Supplier", self.supplier, "supplier_name") or self.supplier
        schedule.incoterm = self.terms_of_delivery
        schedule.port_of_loading = self.port_of_loading
        schedule.port_of_discharge = self.port_of_discharge
        schedule.pickup_location = self.port_of_loading or ""
        schedule.delivery_location = self.port_of_discharge or ""
        schedule.scheduled_pickup_date = self.date or today()
        schedule.scheduled_delivery_date = self.date or today()
        schedule.transport_status = "Pending Assignment"
        if self._is_import_movement():
            schedule.transport_type = "Inward"
        else:
            schedule.transport_type = "Outward"
            schedule.outward_type = self.get_transport_outward_type()
        if self.shipping_booking:
            schedule.shipping_booking = self.shipping_booking
        schedule.material_description = self.get_material_description()
        schedule.special_instructions = self.loading_instructions
        schedule.notes = self.loading_remarks
        schedule.insert(ignore_permissions=True)

        self.db_set("transport_schedule", schedule.name, update_modified=False)
        # JO.transport_status mirrors the TS via TRANSPORT_TO_JOB_ORDER_STATUS;
        # for "Pending Assignment" that's "Pending Booking".
        self.db_set("transport_status", "Pending Booking", update_modified=False)
        return schedule.name

    def _is_import_movement(self):
        return (self.commercial_movement or "").strip() == "Import"

    @frappe.whitelist()
    def create_inward_transport_schedule(self):
        """Create (or return) an Inward Transport Schedule for the sea/import leg.

        For **Import** Job Orders, the primary ``transport_schedule`` is Inward;
        this method ensures one exists and links it on the Job Order.

        For **Outward** Job Orders, the primary link stays Outward; this only
        creates a secondary Inward leg when needed and does **not** replace
        ``transport_schedule``.
        """
        self.check_permission("write")
        if (self.mode_of_transport or "").strip() != "Sea":
            frappe.throw(
                _("Inward transport scheduling is only available when Mode of Transport is Sea.")
            )

        existing = frappe.get_all(
            "Transport Schedule",
            filters={
                "job_order": self.name,
                "transport_type": "Inward",
                "docstatus": ["!=", 2],
            },
            pluck="name",
            limit=1,
        )
        if existing:
            name = existing[0]
            if self._is_import_movement() and not self.transport_schedule:
                self.db_set("transport_schedule", name, update_modified=False)
            return {"created": False, "transport_schedule": name}

        schedule = frappe.new_doc("Transport Schedule")
        schedule.source_document_type = "Job Order"
        schedule.job_order = self.name
        schedule.customer = self.customer
        if self._is_import_movement() and self.supplier:
            schedule.supplier = frappe.db.get_value("Supplier", self.supplier, "supplier_name") or self.supplier
        schedule.incoterm = self.terms_of_delivery
        schedule.port_of_loading = self.port_of_loading
        schedule.port_of_discharge = self.port_of_discharge
        schedule.pickup_location = self.port_of_loading or ""
        schedule.delivery_location = self.port_of_discharge or ""
        schedule.scheduled_pickup_date = self.date or today()
        schedule.scheduled_delivery_date = self.date or today()
        schedule.transport_status = "Pending Assignment"
        schedule.transport_type = "Inward"
        schedule.inward_import_leg = "Initial Import Leg"
        if self.shipping_booking:
            schedule.shipping_booking = self.shipping_booking
        schedule.material_description = self.get_material_description()
        schedule.special_instructions = self.loading_instructions
        schedule.notes = self.loading_remarks
        schedule.insert(ignore_permissions=True)

        if self._is_import_movement():
            self.db_set("transport_schedule", schedule.name, update_modified=False)

        return {"created": True, "transport_schedule": schedule.name}

    def create_or_link_shipping_booking(self):
        linked_booking = self.shipping_booking or self.get_existing_shipping_booking()
        if linked_booking:
            self.db_set("shipping_booking", linked_booking, update_modified=False)
            return linked_booking

        # Build a placeholder Shipping Booking. Vessel name and the
        # vessel/cutoff/pull-out dates are intentionally LEFT BLANK — they
        # get filled in by Logistics once the real vessel is booked.
        #
        # Why blank instead of a "TBD" sentinel:
        #   1. The "TO BOOK VESSEL" KPI on the Shipping Dashboard counts
        #      Shipping Bookings with vessel_name in ('', NULL). A magic
        #      string would silently exclude these placeholders from the
        #      pending-bookings count.
        #   2. Pre-populating the dates with reference_date is dangerous
        #      because the cutoff/vessel ordering invariant (cutoff < vessel)
        #      can't be guaranteed without a real schedule, and
        #      Shipping Booking.validate_dates() will throw on save.
        shipping_booking = frappe.new_doc("Shipping Booking")
        shipping_booking.job_order = self.name
        shipping_booking.customer = self.customer
        if self._is_import_movement():
            shipping_booking.supplier = self.supplier
        shipping_booking.port_of_loading = self.port_of_loading
        shipping_booking.port_of_discharge = self.port_of_discharge
        shipping_booking.cargo_description = self.get_material_description() or "To be updated from Job Order"
        shipping_booking.cargo_weight = 0
        shipping_booking.container_count = cint(self.container_quantity) or 1
        shipping_booking.freight_rate = 0
        shipping_booking.notes = self.loading_remarks
        if self._is_import_movement():
            shipping_booking.booking_status = "Tracking"
            shipping_booking.vessel_status = shipping_booking.vessel_status or "In Transit"
        shipping_booking.insert(ignore_permissions=True, ignore_mandatory=True)

        self.db_set("shipping_booking", shipping_booking.name, update_modified=False)
        self.db_set("shipping_status", self.get_default_shipping_status(), update_modified=False)
        return shipping_booking.name

    def get_default_shipping_status(self):
        # Whoever books the vessel determines the wording shown to APC ops.
        if (self.shipping_arranged_by or "").strip() == "Customer":
            return "Pending Shipping Review"
        return "Pending Shipping Booking"

    def get_transport_outward_type(self):
        transport_mode = (self.mode_of_transport or "").strip().lower()
        text = " ".join(
            filter(None, [self.loading_instructions, self.loading_remarks, self.get_material_description()])
        ).lower()

        if "tanker" in text:
            return "Tanker Delivery"
        if "trailer" in text:
            return "Trailer Delivery"
        if transport_mode == "road":
            return "Local Delivery"

        return "Export Container"

    def get_material_description(self):
        item_lines = []
        for row in self.get("items") or []:
            value = row.get("item_name") or row.get("item_code")
            if value:
                item_lines.append(value)

        if item_lines:
            return ", ".join(item_lines[:8])

        return self.loading_remarks or self.loading_instructions or ""


# Module-level handler functions for hooks.py doc_events

def validate_job_order(doc, method):
    """Hook handler for Job Order validate event."""
    doc.fetch_customer_name()
    doc.determine_booking_requirement()
    doc.sync_booking_flags()
    doc.validate_insurance_on_confirm()


@frappe.whitelist()
def refresh_logistics_cost_summary_api(job_order: str):
    from apc_operations.shipping.services.logistics_cost_service import (
        get_logistics_cost_html_for_job_order,
    )

    return {"html": get_logistics_cost_html_for_job_order(job_order)}


@frappe.whitelist()
def refresh_container_capacity_summary_api(job_order: str):
    from apc_operations.shipping.services.container_capacity_service import (
        get_container_capacity_html_for_job_order,
    )

    return {"html": get_container_capacity_html_for_job_order(job_order)}


def on_submit_job_order(doc, method):
    """Hook handler for Job Order on_submit event."""
    doc.create_or_link_operational_booking()

    from apc_operations.services.batch_allocation import reserve_stock_for_job_order

    reserve_stock_for_job_order(doc.name)


def on_cancel_job_order(doc, method):
    """Release any stock reserved by reserve_stock_for_job_order() back to
    free stock. release_allocation() itself already refuses to release an
    allocation that's been partially/fully dispatched, so this is safe even
    if the Job Order is cancelled after some (but not all) of it shipped."""
    if not doc.sales_demand:
        return

    from apc_operations.services.batch_allocation import release_allocation

    allocations = frappe.get_all(
        "APC Batch Allocation",
        filters={
            "sales_demand": doc.sales_demand,
            "allocation_status": ["not in", ["Released", "Cancelled"]],
        },
        pluck="name",
    )
    for allocation_name in allocations:
        try:
            release_allocation(allocation_name)
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"Job Order {doc.name} cancel: failed to release allocation {allocation_name}",
            )
