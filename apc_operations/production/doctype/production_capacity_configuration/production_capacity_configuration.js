// Copyright (c) 2026, APC and contributors
// For license information, please see license.txt

frappe.ui.form.on("Production Capacity Configuration", {
	refresh(frm) {
		frm.add_custom_button(__("Production Dashboard"), () => {
			frappe.set_route("production-dashboard");
		});

		frm.add_custom_button(__("Capacity Calendar"), () => {
			frappe.set_route("production-calendar");
		});
	},
});

frappe.listview_settings["Production Capacity Configuration"] = {
	add_fields: ["production_category", "max_quantity_per_day", "uom", "active"],
	get_indicator(doc) {
		if (!doc.active) {
			return [__("Inactive"), "gray", "active,=,0"];
		}
		return [__("Active"), "green", "active,=,1"];
	},
};
