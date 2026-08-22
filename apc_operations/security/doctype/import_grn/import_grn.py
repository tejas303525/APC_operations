# Copyright (c) 2026, APC and contributors

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, today

_COMPLETED_GRN_STATUSES = frozenset({"Approved", "Posted"})


class ImportGRN(Document):
	def validate(self):
		if (self.commercial_movement or "").strip() != "Import":
			frappe.throw(_("Import GRN is only for Import operations."))
		if self.delivery_order:
			movement = frappe.db.get_value(
				"Delivery Order", self.delivery_order, "commercial_movement"
			)
			if movement and movement != "Import":
				frappe.throw(
					_("Delivery Order {0} is not an Import movement.").format(self.delivery_order)
				)
		self._sync_receipt_totals()
		self._validate_arrived_quantities()

	def before_insert(self):
		if not self.posting_date:
			self.posting_date = today()

	def on_update(self):
		self._sync_transport_status_on_receipt()

	def _sync_transport_status_on_receipt(self):
		"""Goods received (GRN Approved/Posted) means transit ended for the
		inbound leg - mirrors the outward side, where dispatch confirmation
		sets Transport Status to Dispatched. Neither side of this was ever
		automatic before; both were manually-set dropdowns nobody reliably
		updated."""
		if self.grn_status not in _COMPLETED_GRN_STATUSES:
			return
		if not self.job_order:
			return

		transport_schedule = frappe.db.get_value("Job Order", self.job_order, "transport_schedule")
		if not transport_schedule:
			return

		current_status = frappe.db.get_value("Transport Schedule", transport_schedule, "transport_status")
		if current_status in ("Delivered", "Completed", "Cancelled"):
			return

		frappe.db.set_value(
			"Transport Schedule", transport_schedule, "transport_status", "Delivered",
			update_modified=False,
		)

	def _sync_receipt_totals(self):
		line_expected = 0.0
		line_arrived = 0.0
		for row in self.items or []:
			expected = flt(row.qty)
			line_expected += expected
			line_arrived += flt(row.arrived_qty)

		if not line_expected and flt(self.total_expected_qty) > 0:
			line_expected = flt(self.total_expected_qty)

		header_arrived = flt(self.total_arrived_qty)
		if header_arrived > 0 and len(self.items or []) == 1:
			self.items[0].arrived_qty = header_arrived
			line_arrived = header_arrived
		elif header_arrived <= 0 and line_arrived > 0:
			self.total_arrived_qty = line_arrived
		elif header_arrived > 0 and line_arrived <= 0 and len(self.items or []) == 1:
			line_arrived = header_arrived
		elif header_arrived > 0 and line_arrived > 0 and abs(header_arrived - line_arrived) > 0.0001:
			self.total_arrived_qty = line_arrived
		else:
			self.total_arrived_qty = line_arrived

		self.total_expected_qty = line_expected
		self.pending_qty = max(line_expected - flt(self.total_arrived_qty), 0)

		if flt(self.total_arrived_qty) <= 0:
			self.receipt_type = "Pending"
			self.is_partial_receipt = 0
		elif self.pending_qty > 0:
			self.receipt_type = "Partial"
			self.is_partial_receipt = 1
		else:
			self.receipt_type = "Full"
			self.is_partial_receipt = 0

	def _validate_arrived_quantities(self):
		if self.grn_status in _COMPLETED_GRN_STATUSES or self.flags.approving_grn:
			if flt(self.total_arrived_qty) <= 0:
				frappe.throw(_("Enter Total Arrived Qty before approving the GRN."))
			for row in self.items or []:
				if flt(row.arrived_qty) <= 0:
					frappe.throw(
						_("Arrived Qty is required for item {0} before approval.").format(
							row.item_code or row.item_name
						)
					)
				if flt(row.arrived_qty) > flt(row.qty):
					frappe.throw(
						_("Arrived Qty cannot exceed Expected Qty for item {0}.").format(
							row.item_code or row.item_name
						)
					)
			if flt(self.total_arrived_qty) > flt(self.total_expected_qty):
				frappe.throw(_("Total Arrived Qty cannot exceed Total Expected Qty."))

		for row in self.items or []:
			if flt(row.arrived_qty) > flt(row.qty):
				frappe.throw(
					_("Arrived Qty cannot exceed Expected Qty for item {0}.").format(
						row.item_code or row.item_name
					)
				)
