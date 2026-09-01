# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now


class DeliveryOrder(Document):
	def validate(self):
		self.sync_from_job_order()
		self.set_buyer_from_customer()
		self.calculate_totals()
		self.sync_do_status_default()

	def before_print(self, print_settings=None):
		"""Fill Marks & Nos./Container No. and No. & Kind of Packages from the
		same container/transport/item resolution logic already used to build
		the print context (delivery_order_print_service.get_print_context),
		rather than leaving those two print columns permanently blank. Never
		let a resolution failure block printing."""
		self.refresh_packaging_display()

	def refresh_packaging_display(self):
		from apc_operations.shipping.services.delivery_order_print_service import get_print_context

		try:
			ctx = get_print_context(self.name)
		except Exception:
			frappe.log_error(
				title="Delivery Order print context failed",
				message=frappe.get_traceback(),
			)
			return

		if ctx.get("marks_and_nos"):
			self.marks_and_nos = ctx["marks_and_nos"]
		if ctx.get("no_and_kind_of_packages"):
			self.no_and_kind_of_packages = ctx["no_and_kind_of_packages"]

	def sync_from_job_order(self, *, force_items: bool = False) -> None:
		"""Pull header (and optionally items) from the linked Job Order."""
		from apc_operations.shipping.services.delivery_order_sync_service import (
			apply_job_order_to_delivery_order,
		)

		sync_items = force_items or not (self.items or [])
		apply_job_order_to_delivery_order(self, sync_items=sync_items)

	def sync_do_status_default(self):
		if not self.do_status:
			self.do_status = "Draft"

	def set_buyer_from_customer(self):
		if not self.buyer and self.customer:
			self.buyer = self.customer

	def calculate_totals(self):
		total_qty = 0.0
		total_net = 0.0
		total_gross = 0.0
		total_packages = 0
		for row in self.items or []:
			total_qty += flt(row.qty)
			total_net += flt(row.net_weight)
			total_gross += flt(row.gross_weight)
			total_packages += int(flt(row.no_of_packages))
		self.total_qty = total_qty
		self.total_net_weight = total_net
		self.total_gross_weight = total_gross
		if total_net > 0:
			self.planned_product_kg = total_net
		if total_gross > 0:
			self.planned_gross_kg = total_gross
		if total_packages > 0:
			self.expected_packaging_qty = total_packages
		if total_qty > 0 and not flt(self.planned_quantity):
			self.planned_quantity = total_qty

	def on_submit(self):
		"""On DO submit: stamp issuance metadata and sync lifecycle.

		Loading DN and batch allocation are created after the security checklist
		and Report to QC — not at issue time.
		"""
		self.db_set("issued_by", frappe.session.user, update_modified=False)
		self.db_set("issued_on", now(), update_modified=False)
		if (self.do_status or "Draft") in ("Draft",):
			self.db_set("do_status", "Issued", update_modified=False)

		from apc_operations.shipping.services.dispatch_lifecycle_service import (
			sync_dispatch_lifecycle_status,
		)

		sync_dispatch_lifecycle_status(self.name, update_modified=False)

	def _auto_allocate_loading_dn(self):
		from apc_operations.services.batch_allocation import (
			create_loading_dn_batch_allocations,
			sync_loading_dn_from_job_order_allocations,
		)

		if not self.job_order:
			return

		# Re-use an existing Loading DN for this Job Order if one is already
		# linked; otherwise create a minimal one so allocation has somewhere
		# to write rows.
		loading_dn = self.loading_delivery_note or frappe.db.get_value(
			"Loading Delivery Note",
			{"job_order": self.job_order, "dispatch_confirmed": 0},
			"name",
		)
		if not loading_dn:
			ldn = frappe.new_doc("Loading Delivery Note")
			ldn.job_order = self.job_order
			ldn.customer = self.customer
			ldn.loading_date = self.posting_date or frappe.utils.today()
			ldn.delivery_note_status = "Batch Allocation Pending"
			try:
				ldn.insert(ignore_permissions=True)
				loading_dn = ldn.name
			except Exception:
				frappe.log_error(
					frappe.get_traceback(),
					f"Delivery Order {self.name}: Loading DN creation failed",
				)
				return

		try:
			sync_result = sync_loading_dn_from_job_order_allocations(loading_dn)
			if not sync_result.get("rows"):
				create_loading_dn_batch_allocations(loading_dn_name=loading_dn)
			self.db_set("auto_allocation_run", 1, update_modified=False)
			self.db_set("loading_delivery_note", loading_dn, update_modified=False)
			# Also write the DO back-reference on the LDN for traceability.
			try:
				frappe.db.set_value(
					"Loading Delivery Note",
					loading_dn,
					"transport_delivery_order",
					self.name,
					update_modified=False,
				)
			except Exception:
				pass
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"Delivery Order {self.name}: auto allocation failed",
			)

	def _ensure_pre_check_clearance(self):
		"""Create a Pre-Check Clearance for this DO if one doesn't exist."""
		if self.pre_check_clearance:
			return
		existing = frappe.db.get_value(
			"Pre-Check Clearance", {"delivery_order": self.name}, "name"
		)
		if existing:
			self.db_set("pre_check_clearance", existing, update_modified=False)
			return

		try:
			pcc = frappe.new_doc("Pre-Check Clearance")
			pcc.delivery_order = self.name
			pcc.job_order = self.job_order
			pcc.qc_status = "Pending"
			pcc.security_status = "Pending"
			pcc.overall_status = "Pending"
			pcc.insert(ignore_permissions=True)
			self.db_set("pre_check_clearance", pcc.name, update_modified=False)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"Delivery Order {self.name}: Pre-Check creation failed",
			)


def mark_do_pre_check_cleared(do_name):
	"""Public hook called from Pre-Check Clearance when both signoffs land."""
	frappe.db.set_value(
		"Delivery Order",
		do_name,
		{"do_status": "Pre-Check Cleared"},
		update_modified=False,
	)
	from apc_operations.shipping.services.dispatch_lifecycle_service import (
		sync_dispatch_lifecycle_status,
	)

	sync_dispatch_lifecycle_status(do_name, update_modified=False)


@frappe.whitelist()
def pull_delivery_order_from_job_order(delivery_order: str, sync_items: int = 0) -> dict:
	"""Reload DO fields (and optionally line items) from the linked Job Order."""
	if not delivery_order:
		frappe.throw(_("delivery_order is required"))
	doc = frappe.get_doc("Delivery Order", delivery_order)
	if not doc.job_order:
		frappe.throw(_("Link a Job Order before syncing."))
	doc.sync_from_job_order(force_items=bool(int(sync_items or 0)))
	doc.save()
	return {
		"name": doc.name,
		"terms_of_delivery": doc.terms_of_delivery,
		"job_order_number": doc.job_order_number,
	}


@frappe.whitelist()
def ensure_import_grn(delivery_order: str) -> dict:
	"""Create Import GRN when import DO pre-check is Authorized."""
	from apc_operations.shipping.services.import_grn_service import (
		create_import_grn_for_delivery_order,
		resolve_commercial_movement_for_do,
	)

	if not delivery_order:
		frappe.throw(_("delivery_order is required"))
	return {
		**create_import_grn_for_delivery_order(delivery_order),
		"commercial_movement": resolve_commercial_movement_for_do(delivery_order),
	}
