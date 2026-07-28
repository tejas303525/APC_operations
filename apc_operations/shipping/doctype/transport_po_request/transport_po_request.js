// Copyright (c) 2026, APC and contributors
// For license information, please see license.txt

frappe.ui.form.on("Transport PO Request", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		frm.add_custom_button(
			__("Print Transport PO"),
			() => {
				const printUrl = `/printview?doctype=${encodeURIComponent(
					"Transport PO Request"
				)}&name=${encodeURIComponent(frm.doc.name)}&format=${encodeURIComponent(
					"Standard Transport PO"
				)}&no_letterhead=0`;
				window.open(printUrl, "_blank", "noopener,noreferrer");
			},
			__("Print")
		);
	},
});
