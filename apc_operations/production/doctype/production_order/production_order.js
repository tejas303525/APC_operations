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

		if (frm.doc.apc_batch && !frm.is_new()) {
			frm.add_custom_button(__("View Loading Delivery Notes"), () => {
				frappe.call({
					method: "apc_operations.production.api.get_loading_delivery_notes_for_production_order",
					args: { production_order: frm.doc.name },
					callback(r) {
						const rows = r.message || [];
						if (!rows.length) {
							frappe.msgprint(__("This batch hasn't been dispatched on any Loading Delivery Note yet."));
							return;
						}
						if (rows.length === 1) {
							frappe.set_route("Form", "Loading Delivery Note", rows[0].name);
							return;
						}
						const html = rows.map((row) => `
							<div style="padding:6px 0;border-bottom:1px solid var(--border-color);">
								<a href="/app/loading-delivery-note/${row.name}"><b>${row.name}</b></a>
								&nbsp;-&nbsp;${frappe.utils.escape_html(row.delivery_note_status || "-")}
								&nbsp;(${row.dispatched_qty || 0} / ${row.allocated_qty || 0} dispatched)
							</div>
						`).join("");
						frappe.msgprint({
							title: __("Loading Delivery Notes for this batch"),
							message: html,
							wide: true,
						});
					},
				});
			});
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
