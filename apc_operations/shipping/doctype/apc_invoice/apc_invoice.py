import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, money_in_words


class APCInvoice(Document):
	def validate(self):
		self.calculate_totals()
		self.set_amounts_in_words()

	def calculate_totals(self):
		taxable_value = 0.0
		vat_amount = 0.0

		for row in self.items:
			row.amount = flt(row.rate) * flt(row.quantity)
			row.taxable_value = row.amount
			row.vat_amount = row.amount * flt(row.vat_percentage) / 100 if self.mainland_uae_sale else 0.0
			row.total_incl_vat = row.taxable_value + row.vat_amount

			taxable_value += row.taxable_value
			vat_amount += row.vat_amount

		self.taxable_value = taxable_value
		self.vat_amount = vat_amount if self.mainland_uae_sale else 0.0
		self.grand_total = taxable_value + self.vat_amount

	def set_amounts_in_words(self):
		currency = self.currency or "AED"
		self.amount_in_words = money_in_words(self.grand_total, currency)
		self.vat_amount_in_words = money_in_words(self.vat_amount, currency) if self.vat_amount else ""
