// Copyright (c) 2026, APC and contributors

const APC_IMPORT_GRN_PRINT_FORMAT = "Standard Import GRN";

function apcImportGrnPrintUrl(name) {
	const lang = (frappe.boot && frappe.boot.lang) || "en";
	return `/printview?doctype=${encodeURIComponent("Import GRN")}&name=${encodeURIComponent(
		name
	)}&format=${encodeURIComponent(APC_IMPORT_GRN_PRINT_FORMAT)}&no_letterhead=0&_lang=${encodeURIComponent(lang)}`;
}

function apcImportGrnSyncReceiptTotals(frm) {
	let expected = 0;
	let arrived = 0;
	(frm.doc.items || []).forEach((row) => {
		expected += flt(row.qty);
		arrived += flt(row.arrived_qty);
	});
	if (flt(frm.doc.total_arrived_qty) > 0 && (frm.doc.items || []).length === 1) {
		arrived = flt(frm.doc.total_arrived_qty);
		frm.doc.items[0].arrived_qty = arrived;
	} else if (arrived > 0) {
		frm.doc.total_arrived_qty = arrived;
	}
	frm.set_value("total_expected_qty", expected, null, true);
	frm.set_value("total_arrived_qty", arrived, null, true);
	const pending = Math.max(expected - arrived, 0);
	frm.set_value("pending_qty", pending, null, true);
	if (arrived <= 0) {
		frm.set_value("receipt_type", "Pending", null, true);
		frm.set_value("is_partial_receipt", 0, null, true);
	} else if (pending > 0) {
		frm.set_value("receipt_type", "Partial", null, true);
		frm.set_value("is_partial_receipt", 1, null, true);
	} else {
		frm.set_value("receipt_type", "Full", null, true);
		frm.set_value("is_partial_receipt", 0, null, true);
	}
	frm.refresh_fields(["items", "total_expected_qty", "total_arrived_qty", "pending_qty", "receipt_type", "is_partial_receipt"]);
}

frappe.ui.form.on("Import GRN", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		frm.add_custom_button(__("Print GRN"), () => {
			window.open(apcImportGrnPrintUrl(frm.doc.name), "_blank", "noopener,noreferrer");
		}, __("Print"));
		if (frm.doc.delivery_order) {
			frm.add_custom_button(__("Delivery Order"), () => {
				frappe.set_route("Form", "Delivery Order", frm.doc.delivery_order);
			});
		}
		if (frm.doc.is_partial_receipt) {
			frm.dashboard.add_indicator(__("Partial Receipt — balance pending on this GRN"), "orange");
		}
	},
	total_arrived_qty(frm) {
		apcImportGrnSyncReceiptTotals(frm);
	},
});

frappe.ui.form.on("Import GRN Item", {
	arrived_qty(frm) {
		apcImportGrnSyncReceiptTotals(frm);
	},
	qty(frm) {
		apcImportGrnSyncReceiptTotals(frm);
	},
	items_remove(frm) {
		apcImportGrnSyncReceiptTotals(frm);
	},
});
