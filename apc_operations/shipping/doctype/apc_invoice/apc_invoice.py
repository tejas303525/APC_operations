import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, money_in_words


class APCInvoice(Document):
	def validate(self):
		self.calculate_totals()
		self.set_amounts_in_words()

	def before_print(self, print_settings=None):
		"""Re-read the customer's current address every time this invoice is
		printed, instead of trusting whatever was captured once at invoice
		generation time. consignee_name/buyer_name are left untouched since
		those may have been corrected manually on the invoice; only the
		address/phone/fax/emirate/country/place_of_supply fields are
		refreshed, and only when live data is actually found (never wipe an
		existing value with a blank)."""
		self.refresh_address_from_customer()

	def refresh_address_from_customer(self):
		if not self.customer:
			return

		from apc_operations.shipping.services.invoice_service import get_customer_address_block

		addr = get_customer_address_block(self.customer)

		if addr["address_line"]:
			self.consignee_address = addr["address_line"]
			self.buyer_address = addr["address_line"]
		if addr["phone"]:
			self.consignee_phone = addr["phone"]
			self.buyer_phone = addr["phone"]
		if addr["fax"]:
			self.consignee_fax = addr["fax"]
			self.buyer_fax = addr["fax"]
		if addr["emirate"]:
			self.buyer_emirate = addr["emirate"]
			self.place_of_supply = f"UAE, {addr['emirate']}"
		if addr["country"]:
			self.buyer_country = addr["country"]

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
