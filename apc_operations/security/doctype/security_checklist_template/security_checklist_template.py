# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SecurityChecklistTemplate(Document):
	def validate(self):
		seen = set()
		for row in self.items:
			text = (row.checklist_item or "").strip()
			row.checklist_item = text
			key = text.casefold()
			if key in seen:
				frappe.throw(_("Row {0}: checklist item '{1}' is listed twice.").format(row.idx, text))
			seen.add(key)
