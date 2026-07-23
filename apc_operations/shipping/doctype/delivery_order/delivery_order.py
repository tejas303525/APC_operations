# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class DeliveryOrder(Document):
	def validate(self):
		self.set_buyer_from_customer()
		self.calculate_totals()

	def set_buyer_from_customer(self):
		if not self.buyer and self.customer:
			self.buyer = self.customer

	def calculate_totals(self):
		total_qty = 0.0
		total_net = 0.0
		total_gross = 0.0
		for row in self.items or []:
			total_qty += flt(row.qty)
			total_net += flt(row.net_weight)
			total_gross += flt(row.gross_weight)
		self.total_qty = total_qty
		self.total_net_weight = total_net
		self.total_gross_weight = total_gross
