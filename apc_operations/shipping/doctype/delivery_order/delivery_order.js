// Copyright (c) 2026, APC and contributors
// For license information, please see license.txt

frappe.ui.form.on("Delivery Order", {
	refresh(frm) {
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
		}
	},

	job_order(frm) {
		if (!frm.doc.job_order) {
			return;
		}
		frappe.db.get_doc("Job Order", frm.doc.job_order).then((jo) => {
			if (jo.customer && !frm.doc.customer) {
				frm.set_value("customer", jo.customer);
			}
			if (jo.terms_of_delivery) {
				frm.set_value("terms_of_delivery", jo.terms_of_delivery);
			}
		});
	},
});
