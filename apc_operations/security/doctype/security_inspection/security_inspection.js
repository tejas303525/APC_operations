// Copyright (c) 2026, APC and contributors
// For license information, please see license.txt

frappe.ui.form.on("Security Inspection", {
	refresh(frm) {
		if (frm.is_new()) return;

		const status = frm.doc.security_status;
		const qc_status = frm.doc.qc_status;

		// ── Step 1: Checklist completed → Create Loading DN ─────────────────
		if (status === "Checklist Completed" && !frm.doc.loading_delivery_note) {
			frm.add_custom_button(__("Create Loading DN"), () => {
				frappe.confirm(
					__("Create the Loading Delivery Note for this inspection?"),
					() => {
						frm.call("create_loading_delivery_note").then(r => {
							if (r.message && r.message.success) {
								frappe.show_alert({
									message: __("Loading Delivery Note {0} created", [r.message.loading_delivery_note]),
									indicator: "green"
								});
								frm.reload_doc();
							}
						});
					}
				);
			}, __("Actions")).addClass("btn-primary");
		}

		const postChecklistStatuses = [
			"Checklist Completed",
			"Loading DN Created",
			"Reported to QC",
			"QC Cleared",
			"QC Rejected",
			"Reported to Receivables",
			"Completed",
		];
		if (frm.doc.transportation_request && postChecklistStatuses.includes(status)) {
			frappe.db
				.get_value("Transport Schedule", frm.doc.transportation_request, "gate_pass")
				.then((r) => {
					const gp = r.message && r.message.gate_pass;
					if (gp) {
						frm.add_custom_button(__("View Gate Pass"), () => {
							frappe.set_route("Form", "Gate Pass", gp);
						}, __("Links"));
					} else {
						frm.add_custom_button(__("Create Gate Pass"), () => {
							frappe.confirm(
								__(
									"Create an outbound Gate Pass for this transport? Vehicle and driver must be set on the inspection or Transport Schedule."
								),
								() => {
									frm.call("create_gate_pass").then((res) => {
										if (res.message && res.message.success) {
											frappe.show_alert({
												message: __("Gate Pass {0} created", [res.message.gate_pass]),
												indicator: "green",
											});
											frm.reload_doc();
										}
									});
								}
							);
						}, __("Actions"));
					}
				});
		}

		// ── Step 2: Loading DN exists → Report to QC ────────────────────────
		if (frm.doc.loading_delivery_note && !frm.doc.qc_report_request && status !== "Reported to QC") {
			frm.add_custom_button(__("Report to QC"), () => {
				frappe.confirm(
					__("Send this inspection to QC for clearance?"),
					() => {
						frm.call("report_to_qc").then(r => {
							if (r.message && r.message.success) {
								frappe.show_alert({
									message: __("QC Report Request {0} created", [r.message.qc_report_request]),
									indicator: "blue"
								});
								frm.reload_doc();
							}
						});
					}
				);
			}, __("Actions")).addClass("btn-primary");
		}

		// ── Quick links to related docs ─────────────────────────────────────
		if (frm.doc.qc_report_request) {
			frm.add_custom_button(__("View QC Report"), () => {
				frappe.set_route("Form", "QC Report Request", frm.doc.qc_report_request);
			}, __("Links"));
		}

		if (frm.doc.loading_delivery_note) {
			frm.add_custom_button(__("View Loading DN"), () => {
				frappe.set_route("Form", "Loading Delivery Note", frm.doc.loading_delivery_note);
			}, __("Links"));
		}

		// ── Status indicator colour ─────────────────────────────────────────
		const colour_map = {
			"Draft":                   "gray",
			"Pending Checklist":       "orange",
			"Checklist Completed":     "yellow",
			"Reported to QC":          "blue",
			"QC Cleared":              "green",
			"QC Rejected":             "red",
			"Loading DN Created":      "cyan",
			"Reported to Receivables": "purple",
			"Completed":               "green",
			"Cancelled":               "red",
		};
		const colour = colour_map[status] || "gray";
		frm.page.set_indicator(__(status), colour);
	},

	// Auto-advance status to Pending Checklist when checklist items exist
	checklist_items_add(frm) {
		if (frm.doc.security_status === "Draft") {
			frm.set_value("security_status", "Pending Checklist");
		}
	},
});
