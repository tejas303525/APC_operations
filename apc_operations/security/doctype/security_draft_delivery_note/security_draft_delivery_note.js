// Copyright (c) 2026, APC and contributors
// For license information, please see license.txt

frappe.ui.form.on("Security Draft Delivery Note", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Print Draft Delivery Note"), () => {
			const url = `/printview?doctype=${encodeURIComponent(frm.doc.doctype)}&name=${encodeURIComponent(frm.doc.name)}&format=${encodeURIComponent("Draft Delivery Note")}&no_letterhead=0&_lang=en`;
			window.open(url, "_blank");
		}, __("Print"));

		frm.add_custom_button(__("Open Inspection Checklist"), () => {
			if (!frm.doc.transport_schedule) {
				frappe.msgprint(__("Transport Schedule is required."));
				return;
			}

			frappe.db.get_list("Security Inspection", {
				fields: ["name"],
				filters: { transportation_request: frm.doc.transport_schedule },
				limit: 1,
			}).then((rows) => {
				if (rows && rows.length) {
					frappe.set_route("Form", "Security Inspection", rows[0].name);
					return;
				}

				frappe.call({
					method: "apc_operations.security.doctype.security_inspection.security_inspection.create_security_inspection_from_draft_dn",
					args: { draft_dn_name: frm.doc.name },
					callback: (r) => {
						if (r.message && r.message.inspection) {
							frappe.set_route("Form", "Security Inspection", r.message.inspection);
						}
					},
				});
			});
		});
	},
});
