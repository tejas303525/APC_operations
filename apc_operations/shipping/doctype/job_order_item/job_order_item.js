// Copyright (c) 2026, APC and contributors
// For license information, please see license.txt

function apc_recalc_job_order_item_packing(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.item) {
		return;
	}
	frappe.call({
		method: "apc_operations.shipping.services.packing_calculation_service.calculate_job_order_item_packing",
		args: { item_row: row },
		callback(r) {
			if (!r.message) {
				return;
			}
			const data = r.message;
			for (const field of [
				"packing_unit_type",
				"packing_profile",
				"product_fill_kg",
				"empty_packaging_kg",
				"unit_gross_kg",
				"packaging_qty",
				"planned_product_kg",
				"planned_gross_kg",
				"net_weight",
			]) {
				if (data[field] !== undefined) {
					frappe.model.set_value(cdt, cdn, field, data[field]);
				}
			}
		},
	});
}

frappe.ui.form.on("Job Order Item", {
	item(frm, cdt, cdn) {
		apc_recalc_job_order_item_packing(frm, cdt, cdn);
	},
	packaging_type(frm, cdt, cdn) {
		apc_recalc_job_order_item_packing(frm, cdt, cdn);
	},
	packing_unit_type(frm, cdt, cdn) {
		apc_recalc_job_order_item_packing(frm, cdt, cdn);
	},
	quantity(frm, cdt, cdn) {
		apc_recalc_job_order_item_packing(frm, cdt, cdn);
	},
	uom(frm, cdt, cdn) {
		apc_recalc_job_order_item_packing(frm, cdt, cdn);
	},
});
