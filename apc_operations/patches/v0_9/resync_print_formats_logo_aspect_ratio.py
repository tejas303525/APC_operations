# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""Re-import every print format that displays the company logo, after
	fixing the logo box dimensions to match the real image's aspect ratio
	(675x259px, ~2.61:1). Every format's logo/stamp box was set to
	something much closer to square, relying on object-fit: contain to
	avoid distortion - but wkhtmltopdf's WebKit engine largely ignores
	object-fit and just stretches the image to fill the box, squeezing it
	horizontally. Fixed by giving each box explicit width/height already in
	the correct ratio instead of depending on object-fit. force=True since
	every one of these records already exists - reload_doc silently no-ops
	on an update without it."""
	for module, folder in [
		("shipping", "standard_invoice"),
		("shipping", "standard_loading_delivery_note"),
		("shipping", "standard_qc_report_request"),
		("shipping", "standard_delivery_order"),
		("shipping", "standard_job_order"),
		("shipping", "standard_import_po"),
		("shipping", "standard_transport_po"),
		("shipping", "apc_coa_standard_certificate"),
	]:
		frappe.reload_doc(module, "print_format", folder, force=True)
