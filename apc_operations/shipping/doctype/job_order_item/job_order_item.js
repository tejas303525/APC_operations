// Copyright (c) 2026, APC and contributors
// For license information, please see license.txt

function apc_recalc_job_order_item_packing(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.item) {
		return;
	}
	frappe.call({
		method: "apc_operations.shipping.services.packing_calculation_service.calculate_job_order_item_packing",
		args: { item_row: row, container_type: frm.doc.container_type },
		callback(r) {
			if (!r.message) {
				return;
			}
			const data = r.message;
			for (const field of [
				"packing_unit_type",
				"packing_profile",
				"quantity",
				"uom",
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
			frm.trigger("apc_refresh_container_capacity_summary");
		},
	});
}

function apc_container_number_options(frm) {
	const count = cint(frm.doc.container_quantity);
	if (!count || count <= 0) {
		return "";
	}
	const options = [];
	for (let i = 1; i <= count; i++) {
		options.push(String(i));
	}
	return "\n" + options.join("\n");
}

function apc_refresh_container_number_options(frm) {
	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	if (!grid) {
		return;
	}
	grid.update_docfield_property("planned_container_no", "options", apc_container_number_options(frm));
	(grid.grid_rows || []).forEach((row) => {
		if (row.refresh_field) {
			row.refresh_field("planned_container_no");
		}
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
	capacity_load_mode(frm, cdt, cdn) {
		apc_recalc_job_order_item_packing(frm, cdt, cdn);
	},
	quantity(frm, cdt, cdn) {
		apc_recalc_job_order_item_packing(frm, cdt, cdn);
	},
	uom(frm, cdt, cdn) {
		apc_recalc_job_order_item_packing(frm, cdt, cdn);
	},
	planned_container_no(frm) {
		frm.trigger("apc_refresh_container_capacity_summary");
	},
	items_add(frm) {
		apc_refresh_container_number_options(frm);
	},
});
