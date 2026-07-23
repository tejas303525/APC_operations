/* Shipping Console — APC Operations
 *
 * Three card queues:
 *   - Pending Bookings  (vessel not set)
 *   - Pending CRO       (vessel set but CRO not generated)
 *   - Open CRO Schedule (CRO generated/issued)
 */

frappe.pages["shipping-console"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Shipping"),
		single_column: true,
	});

	const router = new APCConsoleRouter(page, { rootClass: "apc-console apc-console-shipping" });
	router.reset({
		title: __("Shipping"),
		render($root) {
			APCConsoleUI.hubButtons($root, [
				{
					label: __("Pending Bookings"),
					subtitle: __("Vessel not assigned yet"),
					onClick: () => router.push(buildPendingBookingsScreen()),
				},
				{
					label: __("Pending CRO"),
					subtitle: __("Vessel assigned, CRO awaited"),
					onClick: () => router.push(buildPendingCroScreen()),
				},
				{
					label: __("Open CRO Schedule"),
					subtitle: __("CRO issued — schedule + cutoffs"),
					onClick: () => router.push(buildOpenCroScheduleScreen()),
				},
			]);
		},
	});
};

// ---------------------------------------------------------------------------
// Pending Bookings
// ---------------------------------------------------------------------------

function buildPendingBookingsScreen() {
	return {
		title: __("Pending Bookings"),
		render($root, router) {
			renderCardScreen($root, {
				listApi: "apc_operations.shipping.api.get_pending_bookings",
				searchPlaceholder: __("Search by JO / Customer / Line"),
				toCard: (sb) => ({
					title: sb.job_order_number || sb.shipping_booking,
					subtitle: sb.customer_name || sb.customer || "-",
					body_html: `
						<div class="apc-kv-label">${__("POL")}</div>
						<div>${frappe.utils.escape_html(sb.pol || "-")}</div>
						<div class="apc-kv-label">${__("POD")}</div>
						<div>${frappe.utils.escape_html(sb.pod || "-")}</div>
						<div class="apc-kv-label">${__("Line")}</div>
						<div>${frappe.utils.escape_html(sb.shipping_line || "-")}</div>
					`,
					badges: [
						APCConsoleUI.statusBadge(sb.booking_status, sb.booking_status === "Confirmed" ? "success" : "warn"),
						APCConsoleUI.statusBadge(__("Vessel Missing"), "danger"),
					],
					raw: sb,
				}),
				onCardClick: (item) =>
					openBookingEditorModal(item.raw, () => router.refresh(), {
						titlePrefix: __("Pending Booking"),
						primaryLabel: __("Save Booking"),
					}),
			});
		},
	};
}

// ---------------------------------------------------------------------------
// Pending CRO
// ---------------------------------------------------------------------------

function buildPendingCroScreen() {
	return {
		title: __("Pending CRO"),
		render($root, router) {
			renderCardScreen($root, {
				listApi: "apc_operations.shipping.api.get_pending_cros",
				searchPlaceholder: __("Search by JO / Customer / Vessel"),
				toCard: (sb) => ({
					title: sb.job_order_number || sb.shipping_booking,
					subtitle: sb.customer_name || sb.customer || "-",
					body_html: `
						<div class="apc-kv-label">${__("Line")}</div>
						<div>${frappe.utils.escape_html(sb.shipping_line || "-")}</div>
						<div class="apc-kv-label">${__("Vessel")}</div>
						<div>${frappe.utils.escape_html(sb.vessel || "-")}</div>
						<div class="apc-kv-label">${__("ETD")}</div>
						<div>${APCConsoleUI.formatDate(sb.etd)}</div>
					`,
					badges: [
						APCConsoleUI.statusBadge(
							sb.cro_status || "Pending",
							sb.cro_status === "Generated" || sb.cro_status === "Issued" ? "success" : "warn"
						),
					],
					raw: sb,
				}),
				onCardClick: (item) =>
					openBookingEditorModal(item.raw, () => router.refresh(), {
						titlePrefix: __("Pending CRO"),
						primaryLabel: __("Save CRO"),
					}),
			});
		},
	};
}

// ---------------------------------------------------------------------------
// Open CRO Schedule
// ---------------------------------------------------------------------------

function buildOpenCroScheduleScreen() {
	return {
		title: __("Open CRO Schedule"),
		render($root, router) {
			renderCardScreen($root, {
				listApi: "apc_operations.shipping.api.get_open_cro_schedule",
				searchPlaceholder: __("Search by JO / Vessel / Line"),
				toCard: (sb) => ({
					title: `${sb.shipping_line || "-"} • ${sb.vessel || "-"}`,
					subtitle: `${sb.job_order_number || sb.shipping_booking}`,
					body_html: `
						<div class="apc-kv-label">${__("ETD")}</div>
						<div>${APCConsoleUI.formatDate(sb.etd)}</div>
						<div class="apc-kv-label">${__("SI Cutoff")}</div>
						<div>${APCConsoleUI.formatDate(sb.si_cutoff)}</div>
						<div class="apc-kv-label">${__("Gate Cutoff")}</div>
						<div>${APCConsoleUI.formatDate(sb.gate_cutoff)}</div>
						<div class="apc-kv-label">${__("Pull-out")}</div>
						<div>${APCConsoleUI.formatDate(sb.pull_out_date)}</div>
						<div class="apc-kv-label">${__("Containers")}</div>
						<div>${frappe.utils.escape_html(String(sb.container_count || "-"))}</div>
					`,
					badges: [APCConsoleUI.statusBadge(sb.cro_status, "success")],
					raw: sb,
				}),
				onCardClick: (item) =>
					openBookingEditorModal(item.raw, () => router.refresh(), {
						titlePrefix: __("CRO Schedule"),
						primaryLabel: __("Save Schedule"),
					}),
			});
		},
	};
}

// ---------------------------------------------------------------------------
// Unified Booking Editor
// ---------------------------------------------------------------------------
//
// One dialog used from all three list screens. Surfaces *every* editable
// Shipping Booking field so users can fix any field at any time and the doc
// always has the required values populated before save.
//
// The list rows differ (vessel set vs. CRO issued etc.) but the underlying
// record is the same Shipping Booking — so the editor stays consistent and
// the user never has to bounce out to the legacy form to enter a missing
// reqd field.

const BOOKING_EDITOR_FIELDS = [
	"shipping_line",
	"container_type",
	"container_count",
	"port_of_loading",
	"port_of_discharge",
	"cargo_description",
	"cargo_weight",
	"vessel_name",
	"vessel_date",
	"cutoff_date",
	"pull_out_date",
	"si_cutoff",
	"gate_cutoff",
	"vgm_cutoff",
	"gate_in_date",
	"cro_number",
	"cro_date",
	"cro_status",
	"freight_rate",
	"currency",
	"thc",
	"tluc",
	"export_declaration",
	"is_dangerous_goods",
	"dg_class",
	"un_number",
	"notes",
];

function openBookingEditorModal(sb, refresh, opts) {
	opts = opts || {};
	const sbName = sb.shipping_booking || sb.name;

	APCConsoleUI.callApi("apc_operations.shipping.api.get_pending_booking_detail", {
		name: sbName,
	}).then((data) => {
		const d = new frappe.ui.Dialog({
			title: `${opts.titlePrefix || __("Shipping Booking")} — ${data.shipping_booking}`,
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					options: renderKvGrid(data, [
						["Job Order", data.job_order_number || data.job_order],
						["Customer", data.customer_name || data.customer],
						["Incoterm", data.incoterm],
						["Booking Status", data.booking_status],
						["Transport Status", data.transport_status],
					]),
				},

				// --- Shipping Line & Containers ---
				{ fieldtype: "Section Break", label: __("Shipping Line & Containers") },
				{
					fieldtype: "Link",
					fieldname: "shipping_line",
					label: __("Shipping Line"),
					options: "Shipping Line",
					reqd: 1,
					default: data.shipping_line,
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Select",
					fieldname: "container_type",
					label: __("Container Type"),
					reqd: 1,
					default: data.container_type,
					options:
						"\n20FT Standard\n40FT Standard\n40FT High Cube\n20FT Reefer\n40FT Reefer\n20FT Open Top\n40FT Open Top\n20FT Flat Rack\n40FT Flat Rack",
				},
				{
					fieldtype: "Int",
					fieldname: "container_count",
					label: __("Container Count"),
					reqd: 1,
					default: data.container_count || 1,
				},

				// --- Ports & Cargo ---
				{ fieldtype: "Section Break", label: __("Ports & Cargo") },
				{
					fieldtype: "Link",
					fieldname: "port_of_loading",
					label: __("Port of Loading (POL)"),
					options: "Port",
					reqd: 1,
					default: data.port_of_loading,
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Link",
					fieldname: "port_of_discharge",
					label: __("Port of Discharge (POD)"),
					options: "Port",
					reqd: 1,
					default: data.port_of_discharge,
				},
				{ fieldtype: "Section Break" },
				{
					fieldtype: "Small Text",
					fieldname: "cargo_description",
					label: __("Cargo Description"),
					reqd: 1,
					default: data.cargo_description,
				},
				{
					fieldtype: "Float",
					fieldname: "cargo_weight",
					label: __("Cargo Weight (MT)"),
					reqd: 1,
					default: data.cargo_weight,
				},

				// --- Vessel & Cutoffs ---
				{ fieldtype: "Section Break", label: __("Vessel & Cutoffs") },
				{
					fieldtype: "Data",
					fieldname: "vessel_name",
					label: __("Vessel Name"),
					default: data.vessel_name || data.vessel,
				},
				{
					fieldtype: "Date",
					fieldname: "vessel_date",
					label: __("Vessel Date (ETD)"),
					reqd: 1,
					default: data.vessel_date || data.etd,
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Date",
					fieldname: "cutoff_date",
					label: __("Cutoff Date"),
					reqd: 1,
					default: data.cutoff_date,
				},
				{
					fieldtype: "Date",
					fieldname: "pull_out_date",
					label: __("Pull Out Date"),
					reqd: 1,
					default: data.pull_out_date,
				},
				{ fieldtype: "Section Break" },
				{
					fieldtype: "Date",
					fieldname: "si_cutoff",
					label: __("SI Cutoff (Shipping Instructions)"),
					default: data.si_cutoff,
				},
				{
					fieldtype: "Date",
					fieldname: "gate_cutoff",
					label: __("Gate Cutoff"),
					default: data.gate_cutoff,
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Date",
					fieldname: "vgm_cutoff",
					label: __("VGM Cutoff"),
					default: data.vgm_cutoff,
				},
				{
					fieldtype: "Date",
					fieldname: "gate_in_date",
					label: __("Gate In Date"),
					default: data.gate_in_date,
				},

				// --- CRO ---
				{ fieldtype: "Section Break", label: __("CRO") },
				{
					fieldtype: "Data",
					fieldname: "cro_number",
					label: __("CRO Number"),
					default: data.cro_number,
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Date",
					fieldname: "cro_date",
					label: __("CRO Date"),
					default: data.cro_date,
				},
				{
					fieldtype: "Select",
					fieldname: "cro_status",
					label: __("CRO Status"),
					options: "Pending\nGenerated\nCompleted",
					default: data.cro_status || "Pending",
				},

				// --- Freight & Charges ---
				{ fieldtype: "Section Break", label: __("Freight & Charges") },
				{
					fieldtype: "Currency",
					fieldname: "freight_rate",
					label: __("Freight Rate (Per Container)"),
					reqd: 1,
					default: data.freight_rate,
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Link",
					fieldname: "currency",
					label: __("Currency"),
					options: "Currency",
					reqd: 1,
					default: data.currency || "USD",
				},
				{ fieldtype: "Section Break" },
				{
					fieldtype: "Currency",
					fieldname: "thc",
					label: __("THC (Terminal Handling Charge)"),
					default: data.thc,
					description: __("Optional — editable any time"),
				},
				{
					fieldtype: "Currency",
					fieldname: "tluc",
					label: __("TLUC (Terminal Loading/Unloading)"),
					default: data.tluc,
					description: __("Optional — editable any time"),
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Currency",
					fieldname: "export_declaration",
					label: __("Export Declaration (ED)"),
					default: data.export_declaration,
					description: __("Optional — editable any time"),
				},

				// --- Dangerous Goods (collapsible) ---
				{
					fieldtype: "Section Break",
					label: __("Dangerous Goods (DG)"),
					collapsible: 1,
					collapsible_depends_on: "eval:!doc.is_dangerous_goods",
				},
				{
					fieldtype: "Check",
					fieldname: "is_dangerous_goods",
					label: __("Dangerous Goods (DG)"),
					default: data.is_dangerous_goods || 0,
				},
				{
					fieldtype: "Select",
					fieldname: "dg_class",
					label: __("DG Class"),
					options:
						"\nClass 1 - Explosives\nClass 2 - Gases\nClass 3 - Flammable Liquids\nClass 4 - Flammable Solids\nClass 5 - Oxidizing Substances\nClass 6 - Toxic Substances\nClass 7 - Radioactive Materials\nClass 8 - Corrosive Substances\nClass 9 - Miscellaneous",
					depends_on: "eval:doc.is_dangerous_goods",
					default: data.dg_class,
				},
				{
					fieldtype: "Data",
					fieldname: "un_number",
					label: __("UN Number"),
					depends_on: "eval:doc.is_dangerous_goods",
					default: data.un_number,
				},

				// --- Notes (collapsible) ---
				{ fieldtype: "Section Break", label: __("Notes"), collapsible: 1 },
				{
					fieldtype: "Text Editor",
					fieldname: "notes",
					label: __("Notes"),
					default: data.notes,
				},
			],
			primary_action_label: opts.primaryLabel || __("Save"),
			primary_action: (values) => {
				const payload = {};
				BOOKING_EDITOR_FIELDS.forEach((k) => {
					if (values[k] !== undefined) payload[k] = values[k];
				});

				d.disable_primary_action();
				frappe.db
					.set_value("Shipping Booking", data.shipping_booking, payload)
					.then((r) => {
						d.enable_primary_action();
						if (r && r.message) {
							frappe.show_alert({
								message: __("Shipping Booking saved"),
								indicator: "green",
							});
							d.hide();
							refresh && refresh();
						}
					})
					.catch(() => {
						// Frappe's global ajax handler shows the validation
						// error; just unlock the button so the user can fix
						// the offending field and retry.
						d.enable_primary_action();
					});
			},
		});
		d.show();
	});
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function renderCardScreen($root, options) {
	const { $input } = APCConsoleUI.searchRow($root, {
		placeholder: options.searchPlaceholder,
		onChange: () => render(),
	});
	const $cards = $(`<div class="apc-console-screen-cards"></div>`).appendTo($root);

	let rows = [];

	APCConsoleUI.loading($cards);
	APCConsoleUI.callApi(options.listApi, options.listArgs || {})
		.then((data) => {
			rows = data || [];
			render();
		})
		.catch((err) => APCConsoleUI.errorBlock($cards, err));

	function render() {
		const term = ($input.val() || "").trim().toLowerCase();
		let visible = rows;
		if (term) {
			visible = rows.filter((r) => JSON.stringify(r).toLowerCase().indexOf(term) !== -1);
		}
		const items = (visible || []).map(options.toCard);
		$cards.empty();
		APCConsoleUI.cardList($cards, items, (item) =>
			options.onCardClick && options.onCardClick(item)
		);
	}
}

function renderKvGrid(data, pairs) {
	const safe = (v) =>
		v === null || v === undefined || v === "" ? "-" : frappe.utils.escape_html(String(v));
	const cells = pairs
		.map(
			([label, value]) =>
				`<div class="apc-kv-label">${frappe.utils.escape_html(__(label))}</div>
				 <div class="apc-kv-value">${safe(value)}</div>`
		)
		.join("");
	return `<div class="apc-modal-grid">${cells}</div>`;
}
