// Copyright (c) 2026, APC and contributors

frappe.ui.form.on("Pre-Check Clearance", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.delivery_order) {
			return;
		}

		frappe.db.get_value(
			"Delivery Order",
			frm.doc.delivery_order,
			["commercial_movement", "import_grn", "job_order"],
			(r) => {
				const row = r.message || r;
				let movement = (row.commercial_movement || "").trim();
				const finish = () => {
					if (movement !== "Import") {
						return;
					}
					if (row.import_grn) {
						frm.add_custom_button(__("Open Import GRN"), () => {
							frappe.set_route("Form", "Import GRN", row.import_grn);
						});
						return;
					}
					if ((frm.doc.overall_status || "") !== "Authorized") {
						return;
					}
					frm.add_custom_button(__("Create Import GRN"), () => {
						frappe.call({
							method: "apc_operations.security.grn_api.create_import_grn_for_do",
							args: {
								delivery_order: frm.doc.delivery_order,
								pre_check_clearance: frm.doc.name,
							},
							freeze: true,
							callback(res) {
								const msg = res.message || {};
								frappe.show_alert({
									message: __("Import GRN {0} ready", [msg.import_grn]),
									indicator: "green",
								});
								frm.reload_doc();
							},
						});
					});
				};
				if (movement === "Import" || !row.job_order) {
					finish();
					return;
				}
				frappe.db.get_value("Job Order", row.job_order, "commercial_movement", (jo) => {
					const joRow = jo.message || jo;
					movement = (joRow.commercial_movement || joRow || "").trim();
					finish();
				});
			}
		);
	},
});
