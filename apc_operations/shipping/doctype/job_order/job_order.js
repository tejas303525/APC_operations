// Copyright (c) 2026, APC and contributors
// For license information, please see license.txt

function movement_is_import(frm) {
	return (frm.doc.commercial_movement || "Export") === "Import";
}

function toggle_counterparty_visibility(frm) {
	const imp = movement_is_import(frm);
	frm.set_df_property("customer", "hidden", imp ? 1 : 0);
	frm.set_df_property("customer_name", "hidden", imp ? 1 : 0);
	frm.set_df_property("supplier", "hidden", imp ? 0 : 1);
	frm.set_df_property("supplier_name", "hidden", imp ? 0 : 1);
}

frappe.ui.form.on("Job Order", {
	refresh(frm) {
		toggle_counterparty_visibility(frm);

		if (
			!frm.is_new() &&
			frm.doc.mode_of_transport === "Sea" &&
			frm.doc.docstatus !== 2
		) {
			frm.add_custom_button(__("Inward Transport Schedule"), () => {
				frm.call("create_inward_transport_schedule").then((r) => {
					if (r.exc) {
						return;
					}
					const msg = r.message || {};
					if (msg.transport_schedule) {
						if (msg.created) {
							frappe.show_alert({
								message: __("Inward transport schedule created"),
								indicator: "green",
							});
						}
						frappe.set_route("Form", "Transport Schedule", msg.transport_schedule);
					}
				});
			}, __("Transport"));
		}

		if (!frm.doc.terms_of_delivery) {
			return;
		}

		if (frm.doc.transport_schedule) {
			frm.add_custom_button(__("Transport Schedule"), () => {
				frappe.set_route("Form", "Transport Schedule", frm.doc.transport_schedule);
			}, __("Linked Documents"));
		}

		if (frm.doc.shipping_booking) {
			frm.add_custom_button(__("Shipping Booking"), () => {
				frappe.set_route("Form", "Shipping Booking", frm.doc.shipping_booking);
			}, __("Linked Documents"));
		}
	},

	commercial_movement(frm) {
		toggle_counterparty_visibility(frm);
		frm.set_value("customer", null);
		frm.set_value("customer_name", null);
		frm.set_value("supplier", null);
		frm.set_value("supplier_name", null);
	},
});

frappe.listview_settings["Job Order"] = {
	add_fields: [
		"commercial_movement",
		"customer",
		"customer_name",
		"supplier_name",
		"terms_of_delivery",
		"booking_requirement",
		"transport_status",
		"shipping_status",
		"status",
	],

	get_indicator(doc) {
		const prefix = doc.commercial_movement === "Import" ? "Import · " : "";
		if (doc.status === "Completed") {
			return [__(prefix + "Completed"), "green", "status,=,Completed"];
		}
		if (doc.status === "Cancelled") {
			return [__(prefix + "Cancelled"), "red", "status,=,Cancelled"];
		}
		if (doc.transport_status === "Pending Booking" || doc.shipping_status === "Pending Shipping Booking") {
			return [__(prefix + "Booking Pending"), "orange", "status,in,Draft,Confirmed,In Progress"];
		}
		return [__(prefix + (doc.status || "Draft")), "blue", `status,=,${doc.status || "Draft"}`];
	},
};
