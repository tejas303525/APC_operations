// Copyright (c) 2026, APC and contributors

function apc_port_label_from_get_value(result) {
	if (result == null || result === undefined) {
		return null;
	}
	if (typeof result === "string") {
		return result;
	}
	if (typeof result === "object") {
		if (result.port_name) {
			return result.port_name;
		}
		if (result.message && typeof result.message === "object" && result.message.port_name) {
			return result.message.port_name;
		}
		if (typeof result.message === "string") {
			return result.message;
		}
	}
	return null;
}

function apc_apply_job_order_to_delivery_order_form(frm, jo) {
	if (!jo) {
		return;
	}
	if (jo.customer && !frm.doc.customer) {
		frm.set_value("customer", jo.customer);
	}
	if (jo.customer_name) {
		frm.set_value("customer_name", jo.customer_name);
	}
	if (jo.customer && !frm.doc.buyer) {
		frm.set_value("buyer", jo.customer);
	}
	if (jo.terms_of_delivery) {
		frm.set_value("terms_of_delivery", jo.terms_of_delivery);
	}
	if (jo.job_order_number) {
		frm.set_value("job_order_number", jo.job_order_number);
	}
	if (jo.port_of_loading) {
		frappe.db.get_value("Port", jo.port_of_loading, "port_name").then((r) => {
			const port_name = apc_port_label_from_get_value(r) || jo.port_of_loading;
			frm.set_value("port_of_loading", port_name);
		});
	}
	if (jo.port_of_discharge) {
		frappe.db.get_value("Port", jo.port_of_discharge, "port_name").then((r) => {
			const label = apc_port_label_from_get_value(r) || jo.port_of_discharge;
			frm.set_value("port_of_discharge", label);
			if (!frm.doc.destination) {
				frm.set_value("destination", label);
			}
		});
	}
}

function apc_fetch_job_order_for_delivery_order(frm) {
	if (!frm.doc.job_order) {
		return Promise.resolve();
	}
	return frappe.db.get_doc("Job Order", frm.doc.job_order).then((jo) => {
		apc_apply_job_order_to_delivery_order_form(frm, jo);
	});
}

function apc_add_import_grn_button(frm) {
	if (frm.is_new()) {
		return;
	}
	const try_add = (movement) => {
		if ((movement || "").trim() !== "Import") {
			return;
		}
		if (frm.doc.import_grn) {
			frm.add_custom_button(__("Open Import GRN"), () => {
				frappe.set_route("Form", "Import GRN", frm.doc.import_grn);
			}, __("Import"));
			frm.add_custom_button(__("Print GRN"), () => {
				window.open(
					`/printview?doctype=${encodeURIComponent("Import GRN")}&name=${encodeURIComponent(
						frm.doc.import_grn
					)}&format=${encodeURIComponent("Standard Import GRN")}&no_letterhead=0&_lang=en`,
					"_blank",
					"noopener,noreferrer"
				);
			}, __("Import"));
			frm.add_custom_button(__("Import GRN Console"), () => {
				frappe.set_route("import-grn-console");
			}, __("Import"));
			return;
		}
		if (!frm.doc.pre_check_clearance) {
			return;
		}
		frm.add_custom_button(__("Create Import GRN"), () => {
			frappe.call({
				method: "apc_operations.shipping.doctype.delivery_order.delivery_order.ensure_import_grn",
				args: { delivery_order: frm.doc.name },
				freeze: true,
				callback(r) {
					const res = r.message || {};
					frappe.show_alert({
						message: __("Import GRN {0} created", [res.import_grn]),
						indicator: "green",
					});
					frm.reload_doc();
				},
			});
		}, __("Import"));
	};
	let movement = (frm.doc.commercial_movement || "").trim();
	if (movement === "Import" || !frm.doc.job_order) {
		try_add(movement);
		return;
	}
	frappe.db.get_value("Job Order", frm.doc.job_order, "commercial_movement", (r) => {
		const row = r.message || r;
		try_add((row.commercial_movement || row || movement).trim());
	});
}

frappe.ui.form.on("Delivery Order", {
	refresh(frm) {
		if (frm.doc.job_order) {
			apc_fetch_job_order_for_delivery_order(frm);
		}

		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(__("Print Delivery Order"), () => {
			const url = `/printview?doctype=${encodeURIComponent(frm.doc.doctype)}&name=${encodeURIComponent(
				frm.doc.name
			)}&format=${encodeURIComponent("Standard Delivery Order")}&no_letterhead=0&_lang=en`;
			window.open(url, "_blank");
		}, __("Print"));

		if (frm.doc.job_order) {
			frm.add_custom_button(__("Job Order"), () => {
				frappe.set_route("Form", "Job Order", frm.doc.job_order);
			});
			frm.add_custom_button(__("Sync from Job Order"), () => {
				frappe.confirm(
					__(
						"Reload incoterm, ports, and product lines from Job Order {0}? Existing line items will be replaced.",
						[frm.doc.job_order]
					),
					() => {
						frappe.call({
							method:
								"apc_operations.shipping.doctype.delivery_order.delivery_order.pull_delivery_order_from_job_order",
							args: {
								delivery_order: frm.doc.name,
								sync_items: 1,
							},
							callback() {
								frm.reload_doc();
								frappe.show_alert({
									message: __("Synced from Job Order"),
									indicator: "green",
								});
							},
						});
					}
				);
			});
		}

		apc_add_import_grn_button(frm);
	},

	job_order(frm) {
		apc_fetch_job_order_for_delivery_order(frm);
	},
});
