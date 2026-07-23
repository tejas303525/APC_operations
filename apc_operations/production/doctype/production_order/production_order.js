// Copyright (c) 2026, APC and contributors
// For license information, please see license.txt

frappe.ui.form.on("Production Order", {
	refresh(frm) {
		frm.add_custom_button(__("Production Dashboard"), () => {
			frappe.set_route("production-dashboard");
		});

		frm.add_custom_button(__("Capacity Calendar"), () => {
			frappe.set_route("production-calendar");
		});

		if (frm.doc.capacity_status === "Over Capacity") {
			frm.dashboard.add_indicator(
				__("Over Capacity"),
				"red",
			);
		} else if (frm.doc.capacity_status === "Within Capacity") {
			frm.dashboard.add_indicator(
				__("Within Capacity"),
				"green",
			);
		}
	},

	planned_date(frm) {
		frm.dirty();
	},

	production_capacity_category(frm) {
		frm.dirty();
	},

	required_quantity(frm) {
		if (!frm.doc.capacity_quantity) {
			frm.set_value("capacity_quantity", frm.doc.required_quantity);
		}
	},
});

frappe.listview_settings["Production Order"] = {
	add_fields: ["status", "capacity_status", "production_capacity_category", "planned_date"],
	get_indicator(doc) {
		if (doc.capacity_status === "Over Capacity") {
			return [__("Over Capacity"), "red", "capacity_status,=,Over Capacity"];
		}
		if (doc.capacity_status === "Within Capacity") {
			return [__("Within Capacity"), "green", "capacity_status,=,Within Capacity"];
		}
		return [__(doc.status || "Draft"), "blue", `status,=,${doc.status || "Draft"}`];
	},
};
