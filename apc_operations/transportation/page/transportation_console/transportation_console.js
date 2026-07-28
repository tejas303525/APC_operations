/* Transportation Console — APC Operations
 *
 * Single Frappe Page wrapping a page-on-page SPA built on
 * window.APCConsoleRouter (loaded via app_include_js).
 *
 * Hub -> Inward / Outward Export -> sub-hubs -> card queues ->
 * frappe.ui.Dialog modals with action footers.
 */

frappe.pages["transportation-console"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Transportation"),
		single_column: true,
	});

	const router = new APCConsoleRouter(page, { rootClass: "apc-console apc-console-transportation" });
	router.reset(buildHubScreen(page));
};

// ---------------------------------------------------------------------------
// Hub screens
// ---------------------------------------------------------------------------

function buildHubScreen(page) {
	return {
		title: __("Transportation"),
		render($root, router) {
			APCConsoleUI.hubButtons($root, [
				{
					label: __("Inward"),
					subtitle: __("Inbound shipments and trucking"),
					onClick: () => router.push(buildInwardHubScreen()),
				},
				{
					label: __("Outward Export"),
					subtitle: __("Local deliveries and export containers"),
					onClick: () => router.push(buildOutwardHubScreen(page)),
				},
			]);
		},
	};
}

function buildInwardHubScreen() {
	return {
		title: __("Inward"),
		render($root, router) {
			APCConsoleUI.hubButtons($root, [
				{
					label: __("Inward Import"),
					subtitle: __("Sea-mode inbound shipments"),
					onClick: () => router.push(buildInwardImportScreen()),
				},
				{
					label: __("Inward Land"),
					subtitle: __("Road inbound shipments"),
					onClick: () => router.push(buildInwardLandScreen()),
				},
			]);
		},
	};
}

function buildOutwardHubScreen(page) {
	return {
		title: __("Outward Export"),
		render($root, router) {
			const $bannerHolder = $(`<div class="apc-pending-holder"></div>`).appendTo($root);

			APCConsoleConsole_loadPendingCounts($bannerHolder, (filterId) => {
				if (filterId === "transport") {
					router.push(buildPendingTransportScreen());
				} else if (filterId === "do") {
					router.push(buildPendingDoScreen());
				} else if (filterId === "sddn") {
					router.push(buildPendingSddnScreen());
				}
			});

			APCConsoleUI.hubButtons($root, [
				{
					label: __("Local Deliveries"),
					subtitle: __("Tankers, trailers, local trucking"),
					onClick: () => router.push(buildLocalDeliveryScreen()),
				},
				{
					label: __("Export Containers"),
					subtitle: __("Container exports via shipping line"),
					onClick: () => router.push(buildExportContainerScreen()),
				},
			]);
		},
	};
}

function APCConsoleConsole_loadPendingCounts($target, onClick) {
	APCConsoleUI.loading($target);
	APCConsoleUI.callApi("apc_operations.transportation.api.get_transportation_pending_counts")
		.then((counts) => {
			$target.empty();
			APCConsoleUI.pendingBanner($target, counts || {}, onClick);
		})
		.catch((err) => APCConsoleUI.errorBlock($target, err));
}

// ---------------------------------------------------------------------------
// Inward Import
// ---------------------------------------------------------------------------

function buildInwardImportScreen() {
	return {
		title: __("Inward Import"),
		render($root, router) {
			renderCardScreen($root, {
				listApi: "apc_operations.transportation.api.get_inward_import_list",
				searchPlaceholder: __("Search by Job Order / Customer"),
				toCard: (item) => ({
					title: item.job_order_number || item.name,
					subtitle: item.customer_name || item.customer || "-",
					body_html: `
						<div class="apc-kv-label">${__("Product")}</div>
						<div>${frappe.utils.escape_html(item.products || "-")}</div>
						<div class="apc-kv-label">${__("ETA")}</div>
						<div>${APCConsoleUI.formatDate(item.eta)}</div>
						<div class="apc-kv-label">${__("Container")}</div>
						<div>${frappe.utils.escape_html(item.container_number || "-")}</div>
					`,
					badges: [
						APCConsoleUI.statusBadge(item.docs_status, item.docs_status_tone),
						APCConsoleUI.statusBadge(item.vessel_status, item.vessel_status_tone),
					],
					raw: item,
				}),
				onCardClick: (item) =>
					openInwardImportModal(item.raw, () => router.refresh()),
			});
		},
	};
}

function openInwardImportModal(item, onClose) {
	const refreshParent = () => onClose && onClose();
	const reloadModal = (jobOrder) => {
		openInwardImportModal({ job_order: jobOrder, name: jobOrder }, refreshParent);
	};

	APCConsoleUI.callApi(
		"apc_operations.transportation.api.get_inward_import_detail",
		{ job_order: item.job_order || item.name }
	)
		.then((data) => {
			const counterparty =
				data.supplier_name || data.supplier || data.customer_name || data.customer || "-";
			const nextStepHint = !data.vessel_cleared
				? `<p class="text-muted small">${__(
						"Set vessel status to Cleared when the shipment is cleared at port, then book inland transport."
				  )}</p>`
				: !data.is_transport_booked
				? `<p class="text-muted small">${__(
						"Vessel cleared — book inland transport (vehicle and driver), then security review will be prepared."
				  )}</p>`
				: !data.sddn
				? `<p class="text-muted small">${__(
						"Transport booked — create or send the Security Draft Delivery Note for gate-in review."
				  )}</p>`
				: `<p class="text-muted small">${__(
						"Continue in Security Console: promote SDDN to inspection, complete checklist, then report to QC."
				  )}</p>`;

			const d = new frappe.ui.Dialog({
				title: `${__("Inward Import")} — ${data.job_order_number || data.job_order}`,
				size: "large",
				fields: [
					{
						fieldtype: "HTML",
						fieldname: "summary",
						options:
							renderKvGrid(data, [
								["Job Order", data.job_order_number || data.job_order],
								["Supplier", counterparty],
									["Product", data.products || "-"],
								["ETA", APCConsoleUI.formatDate(data.eta)],
								["Cutoff Date", APCConsoleUI.formatDate(data.cutoff_date)],
								["POL", data.port_of_loading],
								["POD", data.port_of_discharge],
								["Shipping Booking", data.shipping_booking],
								["Transport Schedule", data.transport_schedule],
								["Container", data.container_number],
								["Vehicle", data.vehicle_number],
								["Driver", data.driver_name],
								["Transport Status", data.transport_status],
								["SDDN", data.sddn || "-"],
								["Security Inspection", data.security_inspection || "-"],
								["QC Status", data.qc_status || "-"],
							]) +
							renderStatusChain([
								{ label: data.docs_status, tone: data.docs_status_tone },
								{ label: data.vessel_status, tone: data.vessel_status_tone },
								{
									label: data.transport_booking_label,
									tone: data.transport_booking_tone,
								},
								...(data.sddn_status
									? [{ label: data.sddn_status, tone: data.sddn_status_tone }]
									: []),
							]) +
							nextStepHint,
					},
					{ fieldtype: "Section Break", label: __("Vessel tracking") },
					{
						fieldtype: "Date",
						fieldname: "eta",
						label: __("ETA"),
						default: data.eta,
					},
					{
						fieldtype: "Date",
						fieldname: "cutoff_date",
						label: __("Cutoff Date"),
						default: data.cutoff_date,
					},
					{
						fieldtype: "Select",
						fieldname: "vessel_status",
						label: __("Vessel Status"),
						options: "\nIn Transit\nBerthed\nCleared",
						default: data.vessel_status_value || data.vessel_status || "In Transit",
					},
					{
						fieldtype: "Small Text",
						fieldname: "remarks",
						label: __("Remarks"),
						default: data.remarks,
					},
				],
				primary_action_label: __("Save"),
				primary_action: (values) => {
					APCConsoleUI.callApi(
						"apc_operations.transportation.api.update_inward_import_tracking",
						{
							job_order: data.job_order,
							vessel_status: values.vessel_status,
							eta: values.eta,
							cutoff_date: values.cutoff_date,
							remarks: values.remarks,
						}
					)
						.then(() => {
							frappe.show_alert({
								message: __("Updated"),
								indicator: "green",
							});
							reloadModal(data.job_order);
						})
						.catch((err) => frappe.msgprint(err));
				},
			});

			if (data.transport_schedule) {
				attachBookTransportAction(d, data, () => reloadModal(data.job_order));
			}
			buildSddnActionFooter(d, data, () => reloadModal(data.job_order));

			if (data.security_inspection) {
				d.add_custom_action(__("Open Security Inspection"), () => {
					frappe.set_route("Form", "Security Inspection", data.security_inspection);
				});
			}

			d.show();
		})
		.catch((err) => frappe.msgprint(err));
}

// ---------------------------------------------------------------------------
// Inward Land
// ---------------------------------------------------------------------------

function buildInwardLandScreen() {
	return {
		title: __("Inward Land"),
		render($root, router) {
			renderCardScreen($root, {
				listApi: "apc_operations.transportation.api.get_inward_land_list",
				searchPlaceholder: __("Search by Job Order / Customer / Origin"),
				toCard: (item) => ({
					title: item.job_order_number || item.job_order || item.name,
					subtitle: item.customer_name || item.customer || "-",
					body_html: `
						<div class="apc-kv-label">${__("Pull-out")}</div>
						<div>${APCConsoleUI.formatDate(item.pull_out_date)}</div>
						<div class="apc-kv-label">${__("Origin")}</div>
						<div>${frappe.utils.escape_html(item.origin || "-")}</div>
						<div class="apc-kv-label">${__("Destination")}</div>
						<div>${frappe.utils.escape_html(item.destination || "-")}</div>
					`,
					badges: [
						APCConsoleUI.statusBadge(item.transport_status || "-", item.transport_status_tone),
					],
					raw: item,
				}),
				onCardClick: (item) => openInwardLandModal(item.raw, () => router.refresh()),
			});
		},
	};
}

function openInwardLandModal(item, onClose) {
	APCConsoleUI.callApi(
		"apc_operations.transportation.api.get_inward_land_detail",
		{ job_order: item.job_order || item.name }
	).then((data) => {
		const d = new frappe.ui.Dialog({
			title: `${__("Inward Land")} — ${data.job_order_number || data.job_order}`,
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					options: renderKvGrid(data, [
						["Job Order", data.job_order_number || data.job_order],
						["Customer", data.customer_name || data.customer],
						["Transport Schedule", data.transport_schedule],
						["Pull-out Date", APCConsoleUI.formatDate(data.pull_out_date)],
						["Origin", data.origin],
						["Destination", data.destination],
						["Current Location", data.current_location],
						["Vehicle", data.vehicle_number],
						["Driver", data.driver_name],
						["Driver Contact", data.driver_contact],
						["Transport Status", data.transport_status],
					]),
				},
				{ fieldtype: "Section Break" },
				{
					fieldtype: "Small Text",
					fieldname: "remarks",
					label: __("Remarks"),
					default: data.remarks,
				},
			],
			primary_action_label: __("Close"),
			primary_action: () => {
				d.hide();
				onClose && onClose();
			},
		});

		attachBookTransportAction(d, data, () => {
			d.hide();
			onClose && onClose();
		});

		d.show();
	});
}

// ---------------------------------------------------------------------------
// Local Deliveries
// ---------------------------------------------------------------------------

function buildLocalDeliveryScreen() {
	return {
		title: __("Local Deliveries"),
		render($root, router) {
			renderCardScreen($root, {
				listApi: "apc_operations.transportation.api.get_local_delivery_list",
				searchPlaceholder: __("Search by Job Order / Customer / Destination"),
				toCard: (item) => ({
					title: item.job_order_number || item.job_order || item.name,
					subtitle: item.customer_name || item.customer || "-",
					body_html: `
						<div class="apc-kv-label">${__("Delivery")}</div>
						<div>${frappe.utils.escape_html(item.delivery_location || "-")}</div>
						<div class="apc-kv-label">${__("Date")}</div>
						<div>${APCConsoleUI.formatDate(item.scheduled_delivery_date)}</div>
					`,
					badges: [
						APCConsoleUI.statusBadge(item.transport_booking_label, item.transport_booking_tone),
						APCConsoleUI.statusBadge(item.sddn_status, item.sddn_status_tone),
					],
					raw: item,
				}),
				onCardClick: (item) => openLocalDeliveryModal(item.raw, () => router.refresh()),
			});
		},
	};
}

function openLocalDeliveryModal(item, onClose) {
	const refresh = () => onClose && onClose();
	APCConsoleUI.callApi(
		"apc_operations.transportation.api.get_local_delivery_detail",
		{ job_order: item.job_order || item.name }
	).then((data) => {
		const d = new frappe.ui.Dialog({
			title: `${__("Local Delivery")} — ${data.job_order_number || data.job_order}`,
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					options: renderKvGrid(data, [
						["Job Order", data.job_order_number || data.job_order],
						["Customer", data.customer_name || data.customer],
						["Delivery Location", data.delivery_location],
						["Scheduled Date", APCConsoleUI.formatDate(data.scheduled_delivery_date)],
						["Transport Schedule", data.transport_schedule],
						["Vehicle", data.vehicle_number],
						["Driver", data.driver_name],
						["Driver Contact", data.driver_contact],
						["Transport Status", data.transport_status],
						["SDDN", data.sddn || "-"],
						["DO Status", data.do_status],
					]) + renderStatusChain([
						{ label: data.transport_booking_label, tone: data.transport_booking_tone },
						{ label: data.sddn_status, tone: data.sddn_status_tone },
						{ label: data.do_status, tone: data.do_status_tone },
					]),
				},
			],
			primary_action_label: __("Close"),
			primary_action: () => d.hide(),
		});

		attachBookTransportAction(d, data, () => {
			d.hide();
			refresh();
		});
		buildSddnActionFooter(d, data, () => {
			d.hide();
			refresh();
		});

		d.show();
	});
}

// ---------------------------------------------------------------------------
// Export Containers
// ---------------------------------------------------------------------------

function buildExportContainerScreen() {
	return {
		title: __("Export Containers"),
		render($root, router) {
			renderCardScreen($root, {
				listApi: "apc_operations.transportation.api.get_export_container_list",
				searchPlaceholder: __("Search by JO / CRO / Customer"),
				toCard: (item) => ({
					title: item.job_order_number || item.job_order || item.name,
					subtitle: item.customer_name || item.customer || "-",
					body_html: `
						<div class="apc-kv-label">${__("CRO")}</div>
						<div>${frappe.utils.escape_html(item.cro_number || "-")}</div>
						<div class="apc-kv-label">${__("Line")}</div>
						<div>${frappe.utils.escape_html(item.shipping_line || "-")}</div>
						<div class="apc-kv-label">${__("POL → POD")}</div>
						<div>${frappe.utils.escape_html((item.pol || "-") + " → " + (item.pod || "-"))}</div>
					`,
					badges: [
						APCConsoleUI.statusBadge(item.transport_booking_label, item.transport_booking_tone),
						APCConsoleUI.statusBadge(item.sddn_status, item.sddn_status_tone),
						APCConsoleUI.statusBadge(item.do_status, item.do_status_tone),
					],
					raw: item,
				}),
				onCardClick: (item) => openExportContainerModal(item.raw, () => router.refresh()),
			});
		},
	};
}

function openExportContainerModal(item, onClose) {
	APCConsoleUI.callApi(
		"apc_operations.transportation.api.get_export_container_detail",
		{ job_order: item.job_order || item.name }
	).then((data) => {
		const d = new frappe.ui.Dialog({
			title: `${__("Export Container")} — ${data.job_order_number || data.job_order}`,
			size: "extra-large",
			fields: [
				{
					fieldtype: "HTML",
					options: renderKvGrid(data, [
						["Job Order", data.job_order_number || data.job_order],
						["Customer", data.customer_name || data.customer],
						["Shipping Booking", data.shipping_booking],
						["CRO Number", data.cro_number],
						["CRO Date", APCConsoleUI.formatDate(data.cro_date)],
						["Line", data.shipping_line],
						["POL", data.pol],
						["POD", data.pod],
						["Vessel", data.vessel],
						["Vessel Status", data.vessel_status],
						["ETD", APCConsoleUI.formatDate(data.etd)],
						["SI Cutoff", APCConsoleUI.formatDate(data.si_cutoff)],
						["Gate Cutoff", APCConsoleUI.formatDate(data.gate_cutoff)],
						["Pull-out Date", APCConsoleUI.formatDate(data.pull_out_date)],
						["Container Type", data.container_type],
						["Transport Schedule", data.transport_schedule],
						["Transport Status", data.transport_status],
						["Vehicle", data.vehicle_number],
						["Driver", data.driver_name],
						["Driver Contact", data.driver_contact],
						["SDDN", data.sddn],
						["DO", data.do_name],
					]) + renderStatusChain([
						{ label: data.transport_booking_label, tone: data.transport_booking_tone },
						{ label: data.sddn_status, tone: data.sddn_status_tone },
						{ label: data.do_status, tone: data.do_status_tone },
					]),
				},
			],
			primary_action_label: __("Close"),
			primary_action: () => d.hide(),
		});

		attachBookTransportAction(d, data, () => {
			d.hide();
			onClose && onClose();
		});
		buildSddnActionFooter(d, data, () => {
			d.hide();
			onClose && onClose();
		});

		if (data.can_generate_do && !data.do_name) {
			d.add_custom_action(__("Generate DO"), () => {
				APCConsoleUI.callApi(
					"apc_operations.shipping.api.generate_delivery_order_for_export",
					{ job_order: data.job_order }
				)
					.then((res) => {
						frappe.show_alert({
							message: __("Delivery Order created: {0}", [res && res.delivery_order]),
							indicator: "green",
						});
						d.hide();
						onClose && onClose();
					})
					.catch((err) => frappe.msgprint(err));
			});
		}

		d.show();
	});
}

// ---------------------------------------------------------------------------
// Book Transport — assign vehicle/driver/transporter + pricing
// ---------------------------------------------------------------------------
//
// Shared dialog used by Inward Land, Local Delivery, and Export Container
// modals. On save, the Transport Schedule controller's
// update_status_from_assignment automatically flips transport_status from
// "Pending Assignment" to Vehicle/Driver Assigned, and the
// transport_events hook syncs that status back to Job Order + Shipping
// Booking. So a single save here cascades the whole chain.

function bookTransportButtonVisible(data) {
	if (!data || !data.transport_schedule) return false;
	const ts = data.transport_status || "";
	return ts !== "Completed" && ts !== "Cancelled";
}

function attachBookTransportAction(dialog, data, refresh) {
	if (!bookTransportButtonVisible(data)) return;
	const label = data.is_transport_booked
		? __("Edit Transport / Pricing")
		: __("Book Transport");
	dialog.add_custom_action(label, () => {
		openBookTransportDialog(data.transport_schedule, () => {
			refresh && refresh();
		});
	});
}

function openBookTransportDialog(transport_schedule_name, refresh) {
	APCConsoleUI.callApi(
		"apc_operations.transportation.api.get_transport_schedule_booking_detail",
		{ name: transport_schedule_name }
	).then((data) => {
		const d = new frappe.ui.Dialog({
			title: `${__("Book Transport")} — ${data.name}`,
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					options: renderKvGrid(data, [
						["Transport Schedule", data.name],
						["Current Status", data.transport_status],
						["Booking", data.transport_booking_label],
					]),
				},

				{ fieldtype: "Section Break", label: __("Assignment") },
				{
					fieldtype: "Link",
					fieldname: "transporter",
					label: __("Transporter"),
					options: "Transporter",
					default: data.transporter,
					description: __("3rd-party carrier (optional if assigning APC vehicle)"),
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Link",
					fieldname: "assigned_vehicle",
					label: __("Assigned Vehicle"),
					options: "Vehicle",
					default: data.assigned_vehicle,
				},
				{
					fieldtype: "Link",
					fieldname: "assigned_driver",
					label: __("Assigned Driver"),
					options: "Driver",
					default: data.assigned_driver,
				},

				{ fieldtype: "Section Break", label: __("Cutoffs & driver contact") },
				...(data.shipping_booking
					? [
							{
								fieldtype: "Date",
								fieldname: "si_cutoff",
								label: __("SI Cutoff"),
								default: data.si_cutoff,
							},
							{ fieldtype: "Column Break" },
						]
					: []),
				{
					fieldtype: "Date",
					fieldname: "gate_cutoff",
					label: __("Gate Cutoff"),
					default: data.gate_cutoff,
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Data",
					fieldname: "driver_phone",
					label: __("Driver contact"),
					default: data.driver_phone,
				},

				{ fieldtype: "Section Break", label: __("Charges") },
				{
					fieldtype: "Currency",
					fieldname: "transport_charges",
					label: __("Transport Charges"),
					default: data.transport_charges,
				},
				{
					fieldtype: "Currency",
					fieldname: "fuel_cost",
					label: __("Fuel Cost"),
					default: data.fuel_cost,
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Currency",
					fieldname: "additional_charges",
					label: __("Additional Charges"),
					default: data.additional_charges,
				},
				{
					fieldtype: "Link",
					fieldname: "currency",
					label: __("Currency"),
					options: "Currency",
					default: data.currency || "USD",
				},
			],
			primary_action_label: data.is_transport_booked
				? __("Save Changes")
				: __("Book Transport"),
			primary_action: (values) => {
				d.disable_primary_action();
				const args = { transport_schedule: data.name };
				[
					"transporter",
					"assigned_vehicle",
					"assigned_driver",
					"transport_charges",
					"fuel_cost",
					"additional_charges",
					"currency",
					"si_cutoff",
					"gate_cutoff",
				].forEach((k) => {
					if (values[k] !== undefined && values[k] !== "") {
						args[k] = values[k];
					}
				});
				if (values.driver_phone !== undefined) {
					args.driver_phone = values.driver_phone || "";
				}
				APCConsoleUI.callApi(
					"apc_operations.transportation.api.book_transport_schedule",
					args
				)
					.then((res) => {
						frappe.show_alert({
							message: __("Transport saved — status: {0}", [
								(res && res.transport_status) || "?",
							]),
							indicator: "green",
						});
						d.hide();
						refresh && refresh();
					})
					.catch(() => d.enable_primary_action());
			},
		});
		d.show();
	});
}

// ---------------------------------------------------------------------------
// SDDN action footer (used by Local Delivery + Export Container modals)
// ---------------------------------------------------------------------------

const APC_TRANSPORT_PRINT_FORMATS = {
	SDDN: "Draft Delivery Note",
};

function apcTransportConsolePrintUrl(doctype, name, format) {
	const lang = (frappe.boot && frappe.boot.lang) || "en";
	return `/printview?doctype=${encodeURIComponent(doctype)}&name=${encodeURIComponent(
		name
	)}&format=${encodeURIComponent(format)}&no_letterhead=0&_lang=${encodeURIComponent(lang)}`;
}

function apcTransportConsoleOpenPrintDownload(url) {
	window.open(url, "_blank", "noopener,noreferrer");
}

function buildSddnActionFooter(dialog, data, refresh) {
	if (!data.sddn) {
		dialog.add_custom_action(__("Create SDDN"), () => {
			frappe.confirm(__("Create SDDN for Job Order {0}?", [data.job_order]), () => {
				APCConsoleUI.callApi(
					"apc_operations.transportation.api.create_security_delivery_draft_note",
					{ job_order: data.job_order }
				)
					.then((res) => {
						frappe.show_alert({
							message: __("SDDN created: {0}", [res && res.sddn]),
							indicator: "green",
						});
						refresh();
					})
					.catch((err) => frappe.msgprint(err));
			});
		});
	} else {
		dialog.add_custom_action(__("Download SDDN"), () => {
			apcTransportConsoleOpenPrintDownload(
				apcTransportConsolePrintUrl(
					"Security Draft Delivery Note",
					data.sddn,
					APC_TRANSPORT_PRINT_FORMATS.SDDN
				)
			);
		});
		dialog.add_custom_action(__("Send SDDN to Security"), () => {
			APCConsoleUI.callApi(
				"apc_operations.transportation.api.send_security_delivery_draft_note_to_security",
				{ sddn: data.sddn }
			)
				.then(() => {
					frappe.show_alert({
						message: __("SDDN sent to Security"),
						indicator: "green",
					});
					refresh();
				})
				.catch((err) => frappe.msgprint(err));
		});
	}
}

// ---------------------------------------------------------------------------
// Pending sub-screens (filtered views of existing queues)
// ---------------------------------------------------------------------------

function buildPendingTransportScreen() {
	return {
		title: __("Pending Transport Bookings"),
		render($root, router) {
			renderCardScreen($root, {
				listApi: "apc_operations.transportation.api.get_export_container_list",
				clientFilter: (rows) =>
					rows.filter((r) => r.transport_booking_label === "Pending"),
				searchPlaceholder: __("Search by JO / CRO"),
				toCard: (item) => ({
					title: item.job_order_number || item.job_order || item.name,
					subtitle: item.customer_name || item.customer || "-",
					body_html: `
						<div class="apc-kv-label">${__("CRO")}</div>
						<div>${frappe.utils.escape_html(item.cro_number || "-")}</div>
					`,
					badges: [APCConsoleUI.statusBadge(item.transport_booking_label, item.transport_booking_tone)],
					raw: item,
				}),
				onCardClick: (item) => openExportContainerModal(item.raw, () => router.refresh()),
			});
		},
	};
}

function buildPendingDoScreen() {
	return {
		title: __("Pending Delivery Orders"),
		render($root, router) {
			renderCardScreen($root, {
				listApi: "apc_operations.transportation.api.get_export_container_list",
				clientFilter: (rows) => rows.filter((r) => r.do_status === "Pending"),
				searchPlaceholder: __("Search by JO / Customer"),
				toCard: (item) => ({
					title: item.job_order_number || item.job_order || item.name,
					subtitle: item.customer_name || item.customer || "-",
					body_html: `
						<div class="apc-kv-label">${__("Transport")}</div>
						<div>${frappe.utils.escape_html(item.transport_booking_label || "-")}</div>
					`,
					badges: [
						APCConsoleUI.statusBadge(item.transport_booking_label, item.transport_booking_tone),
						APCConsoleUI.statusBadge(item.do_status, item.do_status_tone),
					],
					raw: item,
				}),
				onCardClick: (item) => openExportContainerModal(item.raw, () => router.refresh()),
			});
		},
	};
}

function buildPendingSddnScreen() {
	return {
		title: __("Pending SDDNs"),
		render($root, router) {
			renderCardScreen($root, {
				listApi: "apc_operations.transportation.api.get_export_container_list",
				clientFilter: (rows) =>
					rows.filter((r) => ["Draft", "Pending Verification", "Sent to Security"].indexOf(r.sddn_status) !== -1
						|| !r.sddn),
				searchPlaceholder: __("Search by JO / Customer"),
				toCard: (item) => ({
					title: item.job_order_number || item.job_order || item.name,
					subtitle: item.customer_name || item.customer || "-",
					body_html: `
						<div class="apc-kv-label">${__("SDDN")}</div>
						<div>${frappe.utils.escape_html(item.sddn || "-")}</div>
					`,
					badges: [
						APCConsoleUI.statusBadge(item.transport_booking_label, item.transport_booking_tone),
						APCConsoleUI.statusBadge(item.sddn_status, item.sddn_status_tone),
					],
					raw: item,
				}),
				onCardClick: (item) => openExportContainerModal(item.raw, () => router.refresh()),
			});
		},
	};
}

// ---------------------------------------------------------------------------
// Shared card-screen renderer
// ---------------------------------------------------------------------------

function renderCardScreen($root, options) {
	const { $row, $input } = APCConsoleUI.searchRow($root, {
		placeholder: options.searchPlaceholder,
		onChange: () => reload(),
	});
	const $cards = $(`<div class="apc-console-screen-cards"></div>`).appendTo($root);

	let rows = [];

	function reload() {
		APCConsoleUI.loading($cards);
		APCConsoleUI.callApi(options.listApi, options.listArgs || {})
			.then((data) => {
				rows = data || [];
				if (options.clientFilter) {
					rows = options.clientFilter(rows);
				}
				render();
			})
			.catch((err) => APCConsoleUI.errorBlock($cards, err));
	}

	function render() {
		const term = ($input.val() || "").trim().toLowerCase();
		let visible = rows;
		if (term) {
			visible = rows.filter((r) =>
				JSON.stringify(r).toLowerCase().indexOf(term) !== -1
			);
		}
		const items = (visible || []).map(options.toCard);
		$cards.empty();
		APCConsoleUI.cardList($cards, items, (item) =>
			options.onCardClick && options.onCardClick(item)
		);
	}

	reload();
}

// ---------------------------------------------------------------------------
// Misc render helpers
// ---------------------------------------------------------------------------

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

function renderStatusChain(badges) {
	const filtered = (badges || []).filter((b) => b && b.label);
	if (!filtered.length) {
		return "";
	}
	const html = filtered
		.map((b) => APCConsoleUI.statusBadge(b.label, b.tone || "neutral"))
		.join(" ");
	return `<div class="apc-modal-section">
				<div class="apc-modal-section-title">${frappe.utils.escape_html(__("Status Chain"))}</div>
				<div class="apc-modal-status-chain">${html}</div>
			</div>`;
}
