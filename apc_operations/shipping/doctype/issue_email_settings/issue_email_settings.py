# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import validate_email_address


class IssueEmailSettings(Document):
	def validate(self):
		for field in ("grn_recipients", "delivery_recipients"):
			for email in _split(self.get(field)):
				if not validate_email_address(email):
					frappe.throw(_("{0} is not a valid email address.").format(email))


def _split(value) -> list[str]:
	return [e.strip() for e in (value or "").replace(";", ",").replace("\n", ",").split(",") if e.strip()]
