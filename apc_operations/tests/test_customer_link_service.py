# Copyright (c) 2026, APC and contributors

import frappe
from frappe.tests.utils import FrappeTestCase

from apc_operations.services.customer_link_service import (
	apply_customer_from_sources,
	ensure_sddn_customer_links,
	get_sddn_customer_display,
	resolve_customer_docname,
)


class TestCustomerLinkService(FrappeTestCase):
	def setUp(self):
		self.customer_docname = frappe.db.get_value(
			"Customer", {"customer_name": ["like", "%"]}, "name"
		)
		if not self.customer_docname:
			cust = frappe.new_doc("Customer")
			cust.customer_name = "_Test Customer Link Resolve"
			cust.customer_group = frappe.db.get_value(
				"Customer Group", {"is_group": 0}, "name"
			)
			cust.insert(ignore_permissions=True)
			self.customer_docname = cust.name
		self.display_name = frappe.db.get_value(
			"Customer", self.customer_docname, "customer_name"
		)

	def test_resolve_by_docname(self):
		self.assertEqual(
			resolve_customer_docname(self.customer_docname),
			self.customer_docname,
		)

	def test_resolve_by_display_name(self):
		self.assertEqual(
			resolve_customer_docname(self.display_name),
			self.customer_docname,
		)

	def test_apply_customer_from_sources_clears_invalid(self):
		ts = frappe.new_doc("Transport Schedule")
		ts.customer = self.display_name
		if ts.customer == self.customer_docname:
			ts.customer = f"{self.display_name}-alias"
		apply_customer_from_sources(ts)
		if resolve_customer_docname(ts.customer):
			self.assertEqual(ts.customer, self.customer_docname)
		else:
			self.assertIn(ts.customer, (None, ""))

	def test_ensure_sddn_customer_links_from_display_name(self):
		sddn = frappe._dict(
			customer=self.display_name,
			buyer=None,
			job_order=None,
			transport_schedule=None,
		)
		ensure_sddn_customer_links(sddn, fix_transport=False)
		self.assertEqual(sddn.customer, self.customer_docname)

	def test_get_sddn_customer_display_fallback(self):
		info = get_sddn_customer_display(
			{
				"customer": self.display_name,
				"buyer": None,
				"job_order": None,
				"transport_schedule": None,
			}
		)
		self.assertEqual(info["customer"], self.customer_docname)
		self.assertEqual(info["customer_name"], self.display_name)
