// Copyright (c) 2026, APC and contributors
// For license information, please see license.txt

function movement_is_import(frm) {
	return (frm.doc.commercial_movement || "Outward") === "Import";
}

function toggle_counterparty_visibility(frm) {
	const imp = movement_is_import(frm);
	frm.set_df_property("customer", "hidden", imp ? 1 : 0);
	frm.set_df_property("customer_name", "hidden", imp ? 1 : 0);
	frm.set_df_property("supplier", "hidden", imp ? 0 : 1);
	frm.set_df_property("supplier_name", "hidden", imp ? 0 : 1);
}

const LEGACY_BANK_ACCOUNT_MAP = {
	HABIB: "HABIB - HABIB",
};

function renderJobOrderLogisticsCostSummary(frm) {
	if (frm.is_new() || !frm.fields_dict.logistics_cost_html) {
		return;
	}
	frappe
		.call({
			method:
				"apc_operations.shipping.doctype.job_order.job_order.refresh_logistics_cost_summary_api",
			args: { job_order: frm.doc.name },
		})
		.then((r) => {
			const html = (r.message && r.message.html) || "<p class='text-muted'>No logistics cost data.</p>";
			frm.get_field("logistics_cost_html").$wrapper.html(html);
		});
}

function renderJobOrderContainerCapacitySummary(frm) {
	if (!frm.fields_dict.container_capacity_html) {
		return;
	}
	// Live, not DB-driven: built from the form's current in-memory items so
	// it reflects unsaved edits too, not just what's already been saved.
	frappe
		.call({
			method:
				"apc_operations.shipping.services.container_capacity_service.get_live_container_capacity_html",
			args: {
				container_type: frm.doc.container_type,
				container_quantity: frm.doc.container_quantity,
				items: frm.doc.items || [],
			},
		})
		.then((r) => {
			const html = (r.message && r.message.html) || "<p class='text-muted'>No container capacity data.</p>";
			frm.get_field("container_capacity_html").$wrapper.html(html);
		});
}

function apc_container_number_options(frm) {
	const count = cint(frm.doc.container_quantity);
	if (!count || count <= 0) {
		return "";
	}
	const options = [];
	for (let i = 1; i <= count; i++) {
		options.push(String(i));
	}
	return "\n" + options.join("\n");
}

function apc_refresh_container_number_options(frm) {
	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	if (!grid) {
		return;
	}
	const options = apc_container_number_options(frm);
	grid.update_docfield_property("planned_container_no", "options", options);
	(grid.grid_rows || []).forEach((row) => {
		if (row.refresh_field) {
			row.refresh_field("planned_container_no");
		}
		// Belt and braces: Select is documented to re-read df.options on every
		// refresh (control_select.js set_formatted_input -> set_options()),
		// but this Frappe setup has repeatedly surprised us on inline-grid
		// refresh behavior, so force it directly too rather than trust it.
		apc_set_autocomplete_options(row, "planned_container_no", options);
	});
}

// Autocomplete controls only read df.options once, at creation
// (frappe/public/js/frappe/form/controls/autocomplete.js make_input ->
// set_options()) — unlike Select, refresh()/refresh_field() does not
// re-read them. So for an already-rendered inline grid cell, updating the
// docfield alone (grid.update_docfield_property) is not enough; the live
// control instance's set_options() must be called directly too. Works for
// any control with a set_options() method, not just Autocomplete.
function apc_set_autocomplete_options(grid_row, fieldname, options) {
	if (!grid_row) {
		return;
	}
	const docfield = (grid_row.docfields || []).find((d) => d.fieldname === fieldname);
	if (docfield) {
		docfield.options = options;
	}
	const inline_field = grid_row.on_grid_fields_dict && grid_row.on_grid_fields_dict[fieldname];
	if (inline_field) {
		inline_field.df.options = options;
		inline_field.set_options && inline_field.set_options();
	}
	const form_field = grid_row.grid_form && grid_row.grid_form.fields_dict[fieldname];
	if (form_field) {
		form_field.df.options = options;
		form_field.set_options && form_field.set_options();
	}
}

function apc_refresh_packaging_type_options(frm) {
	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	if (!grid) {
		return;
	}
	frappe.db
		.get_list("APC Packaging Type", {
			filters: { active: 1 },
			fields: ["name"],
			order_by: "name asc",
			limit: 0,
		})
		.then((rows) => {
			const options = (rows || []).map((r) => r.name).join("\n");
			grid.update_docfield_property("packaging_type", "options", options);
			(grid.grid_rows || []).forEach((row) => {
				apc_set_autocomplete_options(row, "packaging_type", options);
			});
		});
}

// Narrow each existing row's Packaging Type suggestions to what that row's
// item actually has a packing profile for. Runs after the unfiltered
// default above so rows with an item already set — e.g. on opening a saved
// Job Order — get the filtered list too, not just rows where Item is
// freshly picked.
function apc_refresh_all_row_packaging_type_options(frm) {
	(frm.doc.items || []).forEach((row) => {
		if (row.item) {
			apc_refresh_row_packaging_type_options(frm, row.doctype, row.name);
		}
	});
}

// Container fields (Container Type/Quantity, Capacity Load Mode, Planned
// Container No, the capacity widget) only make sense for Export shipments -
// Local shipments don't reference a container at all, so hide them rather
// than leave them sitting there unused. Packaging Qty stays editable either
// way (the existing Manual Packaging Qty checkbox already covers manual
// entry when the computed value isn't wanted).
function apc_toggle_container_fields_for_shipment_type(frm) {
	const is_export = frm.doc.shipment_type === "Export";
	frm.set_df_property("container_type", "hidden", is_export ? 0 : 1);
	frm.set_df_property("container_quantity", "hidden", is_export ? 0 : 1);
	frm.set_df_property("container_capacity_html", "hidden", is_export ? 0 : 1);
	frm.refresh_field("container_type");
	frm.refresh_field("container_quantity");
	frm.refresh_field("container_capacity_html");

	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	if (grid && grid.toggle_display) {
		grid.toggle_display("capacity_load_mode", is_export);
		grid.toggle_display("planned_container_no", is_export);
	}
}

// --- Job Order Item (child table) row logic ---
//
// NOTE: this doctype is istable:1, so Frappe's form-meta asset loader
// (frappe/desk/form/meta.py FormMeta.load_assets -> add_code) skips loading
// its own job_order_item.js entirely (`if not self.istable: self.add_code()`)
// — frappe.ui.form.on("Job Order Item", ...) registered there never runs.
// Child-table row handlers have to live in the parent doctype's own JS file
// to actually load, so all Job Order Item logic is defined here instead.

function apc_recalc_job_order_item_packing(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.item) {
		return;
	}
	frappe.call({
		method: "apc_operations.shipping.services.packing_calculation_service.calculate_job_order_item_packing",
		args: { item_row: row, container_type: frm.doc.container_type },
		callback(r) {
			if (!r.message) {
				return;
			}
			const data = r.message;
			for (const field of [
				"packaging_type",
				"packing_unit_type",
				"packing_profile",
				"quantity",
				"uom",
				"product_fill_kg",
				"empty_packaging_kg",
				"unit_gross_kg",
				"packaging_qty",
				"planned_product_kg",
				"planned_gross_kg",
				"net_weight",
			]) {
				if (data[field] !== undefined) {
					frappe.model.set_value(cdt, cdn, field, data[field]);
				}
			}
			frm.trigger("apc_refresh_container_capacity_summary");
		},
	});
}

function apc_refresh_row_packaging_type_options(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	const grid_row = grid && grid.grid_rows_by_docname[cdn];
	if (!row || !row.item || !grid_row) {
		return;
	}
	frappe.call({
		method: "apc_operations.shipping.services.packing_calculation_service.get_packaging_type_options_for_item",
		args: { item: row.item },
		callback(r) {
			const names = r.message || [];
			apc_set_autocomplete_options(grid_row, "packaging_type", names.join("\n"));
		},
	});
}

frappe.ui.form.on("Job Order Item", {
	item(frm, cdt, cdn) {
		apc_recalc_job_order_item_packing(frm, cdt, cdn);
		apc_refresh_row_packaging_type_options(frm, cdt, cdn);
	},
	packaging_type(frm, cdt, cdn) {
		apc_recalc_job_order_item_packing(frm, cdt, cdn);
	},
	packing_unit_type(frm, cdt, cdn) {
		apc_recalc_job_order_item_packing(frm, cdt, cdn);
	},
	capacity_load_mode(frm, cdt, cdn) {
		apc_recalc_job_order_item_packing(frm, cdt, cdn);
	},
	quantity(frm, cdt, cdn) {
		apc_recalc_job_order_item_packing(frm, cdt, cdn);
	},
	uom(frm, cdt, cdn) {
		apc_recalc_job_order_item_packing(frm, cdt, cdn);
	},
	planned_container_no(frm) {
		frm.trigger("apc_refresh_container_capacity_summary");
	},
	items_add(frm) {
		apc_refresh_container_number_options(frm);
		apc_refresh_packaging_type_options(frm);
		frm.trigger("apc_refresh_container_capacity_summary");
	},
	items_remove(frm) {
		frm.trigger("apc_refresh_container_capacity_summary");
	},
});

frappe.ui.form.on("Job Order", {
	setup(frm) {
		frm.set_query("bank_account", () => ({
			filters: { disabled: 0, is_company_account: 1 },
		}));
	},

	onload(frm) {
		apc_toggle_container_fields_for_shipment_type(frm);
		apc_refresh_container_number_options(frm);
		apc_refresh_packaging_type_options(frm);
		apc_refresh_all_row_packaging_type_options(frm);
	},

	shipment_type(frm) {
		apc_toggle_container_fields_for_shipment_type(frm);
	},

	container_type(frm) {
		frm.trigger("apc_refresh_container_capacity_summary");
	},

	container_quantity(frm) {
		apc_refresh_container_number_options(frm);
		frm.trigger("apc_refresh_container_capacity_summary");
	},

	apc_refresh_container_capacity_summary(frm) {
		renderJobOrderContainerCapacitySummary(frm);
	},

	before_save(frm) {
		const bank_account = (frm.doc.bank_account || "").trim();
		if (LEGACY_BANK_ACCOUNT_MAP[bank_account]) {
			frm.set_value("bank_account", LEGACY_BANK_ACCOUNT_MAP[bank_account]);
		}
	},

	refresh(frm) {
		toggle_counterparty_visibility(frm);
		apc_toggle_container_fields_for_shipment_type(frm);
		apc_refresh_container_number_options(frm);
		apc_refresh_packaging_type_options(frm);
		apc_refresh_all_row_packaging_type_options(frm);
		renderJobOrderContainerCapacitySummary(frm);

		const bank_account = (frm.doc.bank_account || "").trim();
		if (LEGACY_BANK_ACCOUNT_MAP[bank_account]) {
			frm.set_value("bank_account", LEGACY_BANK_ACCOUNT_MAP[bank_account]);
		}

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

		if (!frm.is_new()) {
			frm.add_custom_button(
				__("Print Job Order"),
				() => {
					const printUrl = `/printview?doctype=${encodeURIComponent("Job Order")}&name=${encodeURIComponent(
						frm.doc.name
					)}&format=${encodeURIComponent("Standard Job Order")}&no_letterhead=0`;
					window.open(printUrl, "_blank", "noopener,noreferrer");
				},
				__("Print")
			);

			renderJobOrderLogisticsCostSummary(frm);

			frm.add_custom_button(__("Batch Allocation Dashboard"), () => {
				frappe.route_options = { job_order: frm.doc.name };
				frappe.set_route("batch-allocation-dashboard");
			}, __("View"));

			if (frm.doc.sales_demand) {
				frm.add_custom_button(__("Sales Demand"), () => {
					frappe.set_route("Form", "APC Sales Demand", frm.doc.sales_demand);
				}, __("Linked Documents"));
			}
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

		if (!frm.is_new() && frappe.model.can_delete("Job Order")) {
			frm.add_custom_button(__("Delete"), () => {
				apcConfirmDeleteJobOrder(frm.doc.name, () => {
					frappe.set_route("List", "Job Order");
				});
			}, __("Actions"));
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
