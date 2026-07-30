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
			APCConsoleUI.hubButtonsWithDailyWork($root, "transportation", [
				{
					queueKeys: ["inward_import", "inward_land", "grn_summary"],
					label: __("Inward"),
					fallback: __("Inbound shipments and trucking"),
					onClick: () => router.push(buildInwardHubScreen()),
				},
				{
					queueKeys: ["local_delivery", "export_container", "partial_followup"],
					label: __("Outward Export"),
					fallback: __("Local deliveries and export containers"),
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
			APCConsoleUI.hubButtonsWithDailyWork($root, "transportation", [
				{
					queueKey: "inward_import",
					label: __("Inward Import"),
					fallback: __("Sea-mode inbound shipments"),
					onClick: () => router.push(buildInwardImportScreen()),
				},
				{
					queueKey: "inward_land",
					label: __("Inward Land"),
					fallback: __("Road inbound shipments"),
					onClick: () => router.push(buildInwardLandScreen()),
				},
				{
					queueKey: "grn_summary",
					label: __("GRN Summary"),
					fallback: __("Partial import receipts — schedule remaining inward delivery"),
					onClick: () => router.push(buildGrnSummaryScreen()),
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

			APCConsoleUI.hubButtonsWithDailyWork($root, "transportation", [
				{
					queueKey: "local_delivery",
					label: __("Local Deliveries"),
					fallback: __("Tankers, trailers, local trucking"),
					onClick: () => router.push(buildLocalDeliveryScreen()),
				},
				{
					queueKey: "export_container",
					label: __("Export Containers"),
					fallback: __("Container exports via shipping line"),
					onClick: () => router.push(buildExportContainerScreen()),
				},
				{
					queueKey: "partial_followup",
					label: __("Partial Delivery Follow-up"),
					fallback: __("Schedule additional transport for remaining quantity"),
					onClick: () => router.push(buildPartialDeliveryFollowupScreen()),
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
						${renderProductPackagingCardRows(item)}
						${APCConsoleUI.deliveryDueKvHtml(item)}
						<div class="apc-kv-label">${__("ETA")}</div>
						<div>${APCConsoleUI.formatDate(item.eta)}</div>
						<div class="apc-kv-label">${__("Container")}</div>
						<div>${frappe.utils.escape_html(item.container_number || "-")}</div>
					`,
					badges: APCConsoleUI.consoleDeliveryBadges(item, [
						APCConsoleUI.statusBadge(item.docs_status, item.docs_status_tone),
						APCConsoleUI.statusBadge(item.vessel_status, item.vessel_status_tone),
					]),
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
				: !data.do_name
				? `<p class="text-muted small">${__(
						"Transport booked — issue Delivery Order to Security (or wait for auto-issue when vessel is cleared)."
				  )}</p>`
				: !data.sddn
				? `<p class="text-muted small">${__(
						"Delivery Order issued — Security will verify the truck and report to QC."
				  )}</p>`
				: `<p class="text-muted small">${__(
						"Continue in Security Console → New Delivery Orders: complete checklist, report to QC, then link or create an Export Job Order."
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
								["ETA", APCConsoleUI.formatDate(data.eta)],
								["Cutoff Date", APCConsoleUI.formatDate(data.cutoff_date)],
								["POL", data.port_of_loading],
								["POD", data.port_of_discharge],
								["Shipping Booking", data.shipping_booking],
								["Transport Schedule", data.transport_schedule],
								["Container", data.container_number],
								["Vehicle", data.vehicle_number],
								["Driver", data.driver_name],
								["Operation", data.commercial_movement || "Import"],
								["Transport Status", data.transport_status],
								["Delivery Order", data.do_name || "-"],
								["DO Status", data.do_status || "-"],
								["SDDN", data.sddn || "-"],
								["Security Inspection", data.security_inspection || "-"],
								["QC Status", data.qc_status || "-"],
								["Linked Export JO", data.linked_export_job_order || "-"],
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
				attachTransportPoPrintAction(d, data);
			}
			buildSddnActionFooter(d, data, () => reloadModal(data.job_order));
			attachIssueDoAction(d, data, () => reloadModal(data.job_order));
			attachImportHandoffActions(d, data, () => reloadModal(data.job_order));

			if (data.security_inspection) {
				d.add_custom_action(__("Open Security Inspection"), () => {
					frappe.set_route("Form", "Security Inspection", data.security_inspection);
				});
			}

			apcAddJobOrderDeleteAction(d, data.job_order, refreshParent);

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
						${renderProductPackagingCardRows(item)}
						${APCConsoleUI.deliveryDueKvHtml(item)}
						<div class="apc-kv-label">${__("Pull-out")}</div>
						<div>${APCConsoleUI.formatDate(item.pull_out_date)}</div>
						<div class="apc-kv-label">${__("Origin")}</div>
						<div>${frappe.utils.escape_html(item.origin || "-")}</div>
						<div class="apc-kv-label">${__("Destination")}</div>
						<div>${frappe.utils.escape_html(item.destination || "-")}</div>
					`,
					badges: APCConsoleUI.consoleDeliveryBadges(item, [
						...(item.is_import_purchase_order
							? [APCConsoleUI.statusBadge(__("Import Purchase Order"), "info")]
							: []),
						APCConsoleUI.statusBadge(item.transport_status || "-", item.transport_status_tone),
					]),
					raw: item,
				}),
				onCardClick: (item) => openInwardLandModal(item.raw, () => router.refresh()),
			});
		},
	};
}

function openInwardLandModal(item, onClose) {
	const refreshParent = () => onClose && onClose();
	const reloadModal = (jobOrder) => {
		openInwardLandModal({ job_order: jobOrder, name: jobOrder }, refreshParent);
	};

	APCConsoleUI.callApi(
		"apc_operations.transportation.api.get_inward_land_detail",
		{ job_order: item.job_order || item.name }
	)
		.then((data) => {
			const isImport = (data.commercial_movement || "").trim() === "Import";
			const counterparty = isImport
				? data.supplier_name || data.supplier || data.customer_name || data.customer || "-"
				: data.customer_name || data.customer || "-";
			const counterpartyLabel = isImport ? __("Supplier") : __("Customer");

			let nextStepHint = "";
			if (isImport) {
				if (!data.is_transport_booked) {
					nextStepHint = `<p class="text-muted small">${__(
						"Book inland transport (vehicle and driver), then issue Delivery Order to Security."
					)}</p>`;
				} else if (!data.do_name) {
					nextStepHint = `<p class="text-muted small">${__(
						"Transport booked — issue Delivery Order to Security (or wait for auto-issue when vehicle and driver are assigned)."
					)}</p>`;
				} else if (!data.sddn) {
					nextStepHint = `<p class="text-muted small">${__(
						"Delivery Order issued — Security will verify the truck and report to QC."
					)}</p>`;
				} else {
					nextStepHint = `<p class="text-muted small">${__(
						"Continue in Security Console → New Delivery Orders: complete checklist, report to QC, then link or create an Export Job Order."
					)}</p>`;
				}
			}

			const kvRows = [
				["Job Order", data.job_order_number || data.job_order],
				[
					"Booking Type",
					data.is_import_purchase_order ? __("Import Purchase Order") : __("Standard"),
				],
				[counterpartyLabel, counterparty],
				["Purchase Supplier", data.purchase_supplier || data.supplier_name || data.supplier],
				["Product", data.purchase_item || data.product_name],
				[
					"Quantity",
					data.quantity
						? `${data.quantity}${data.purchase_uom ? ` ${data.purchase_uom}` : ""}`
						: "-",
				],
				["Transport Schedule", data.transport_schedule],
				["Pull-out Date", APCConsoleUI.formatDate(data.pull_out_date)],
				["Origin", data.origin],
				["Destination", data.destination],
				["Current Location", data.current_location],
				["Vehicle", data.vehicle_number],
				["Driver", data.driver_name],
				["Driver Contact", data.driver_contact],
				["Operation", data.commercial_movement || "Import"],
				["Transport Status", data.transport_status],
				["Delivery Order", data.do_name || "-"],
				["DO Status", data.do_status || "-"],
				["SDDN", data.sddn || "-"],
			];
			if (isImport) {
				kvRows.push(
					["Security Inspection", data.security_inspection || "-"],
					["QC Status", data.qc_status || "-"],
					["Linked Export JO", data.linked_export_job_order || "-"]
				);
			}

			const statusChain = [
				...(data.is_import_purchase_order
					? [{ label: __("Import Purchase Order"), tone: "info" }]
					: []),
				{
					label: data.transport_booking_label,
					tone: data.transport_booking_tone,
				},
			];
			if (data.sddn_status) {
				statusChain.push({ label: data.sddn_status, tone: data.sddn_status_tone });
			}
			if (data.do_status) {
				statusChain.push({ label: data.do_status, tone: data.do_status_tone });
			}

			const d = new frappe.ui.Dialog({
				title: `${__("Inward Land")} — ${data.job_order_number || data.job_order}`,
				size: "large",
				fields: [
					{
						fieldtype: "HTML",
						fieldname: "summary",
						options:
							renderKvGrid(data, kvRows) +
							renderStatusChain(statusChain) +
							nextStepHint,
					},
					{ fieldtype: "Section Break" },
					{
						fieldtype: "Small Text",
						fieldname: "remarks",
						label: __("Remarks"),
						default: data.remarks,
						read_only: 1,
					},
				],
				primary_action_label: __("Close"),
				primary_action: () => {
					d.hide();
					refreshParent();
				},
			});

			if (data.transport_schedule) {
				attachBookTransportAction(d, data, () => reloadModal(data.job_order));
				attachTransportPoPrintAction(d, data);
			}
			buildSddnActionFooter(d, data, () => reloadModal(data.job_order));
			attachIssueDoAction(d, data, () => reloadModal(data.job_order));
			if (isImport) {
				attachImportHandoffActions(d, data, () => reloadModal(data.job_order));
			}

			if (data.security_inspection) {
				d.add_custom_action(__("Open Security Inspection"), () => {
					frappe.set_route("Form", "Security Inspection", data.security_inspection);
				});
			}

			apcAddJobOrderDeleteAction(d, data.job_order, refreshParent);

			d.show();
		})
		.catch((err) => frappe.msgprint(err));
}

// ---------------------------------------------------------------------------
// Import GRN Summary — partial receipt follow-up (new inward import leg)
// ---------------------------------------------------------------------------

function buildGrnSummaryScreen() {
	return {
		title: __("GRN Summary"),
		render($root, router) {
			renderCardScreen($root, {
				listApi: "apc_operations.transportation.api.get_grn_summary_list",
				searchPlaceholder: __("Search by Job Order / Supplier"),
				toCard: (item) => ({
					title: item.job_order_number || item.job_order || item.name,
					subtitle: item.supplier_name || item.supplier || "-",
					body_html: `
						${renderProductPackagingCardRows(item)}
						${APCConsoleUI.deliveryDueKvHtml(item)}
						<div class="apc-kv-label">${__("Pending Receipt Qty")}</div>
						<div>${frappe.utils.escape_html(String(item.pending_receipt_quantity || "-"))}</div>
						<div class="apc-kv-label">${__("Received so far")}</div>
						<div>${frappe.utils.escape_html(
							String(item.total_received_quantity || "-")
						)} / ${frappe.utils.escape_html(String(item.job_order_quantity || item.total_expected_quantity || "-"))}</div>
						<div class="apc-kv-label">${__("Last GRN")}</div>
						<div>${frappe.utils.escape_html(item.last_posted_grn || "-")}</div>
					`,
					badges: APCConsoleUI.consoleDeliveryBadges(item, [
						APCConsoleUI.statusBadge(__("Import Partial Receipt"), "warn"),
						item.followup_needed
							? APCConsoleUI.statusBadge(__("Follow-up Needed"), "info")
							: APCConsoleUI.statusBadge(__("Inward Trip Scheduled"), "success"),
					]),
					raw: item,
				}),
				onCardClick: (item) => openGrnSummaryModal(item.raw, () => router.refresh()),
			});
		},
	};
}

function openGrnSummaryModal(item, onClose) {
	const refresh = () => onClose && onClose();
	APCConsoleUI.callApi(
		"apc_operations.transportation.api.get_grn_summary_detail",
		{ job_order: item.job_order || item.name }
	).then((data) => {
		const grnRows = (data.import_grns || [])
			.map(
				(g) =>
					`<tr><td>${frappe.utils.escape_html(g.name || "-")}</td>` +
					`<td>${frappe.utils.escape_html(g.grn_status || "-")}</td>` +
					`<td>${frappe.utils.escape_html(String(g.total_arrived_qty || "-"))}</td>` +
					`<td>${frappe.utils.escape_html(g.receipt_type || "-")}</td></tr>`
			)
			.join("");
		const grnTable = grnRows
			? `<table class="table table-bordered table-sm mt-2"><thead><tr><th>${__(
					"GRN"
			  )}</th><th>${__("Status")}</th><th>${__("Arrived")}</th><th>${__(
					"Type"
			  )}</th></tr></thead><tbody>${grnRows}</tbody></table>`
			: "";

		const d = new frappe.ui.Dialog({
			title: `${__("GRN Summary")} — ${data.job_order_number || data.job_order}`,
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					options:
						renderKvGrid(data, [
							["Job Order", data.job_order_number || data.job_order],
							["Operation", data.commercial_movement || "Import"],
							["Supplier", data.supplier_name || data.supplier],
							["Pending Receipt Qty", data.pending_receipt_quantity],
							[
								"Received / Job Order Qty",
								`${data.total_received_quantity} / ${data.job_order_quantity || data.total_expected_quantity}`,
							],
							["Last Posted GRN", data.last_posted_grn],
							["Last GRN Receipt Type", data.last_grn_receipt_type],
							["Last Inward Trip", data.last_transport_schedule || data.last_completed_transport],
							["Last Trip Status", data.last_transport_status || data.last_completed_transport_status],
							["Last Inward Import Leg", data.last_inward_import_leg],
							["Active Inward Trip", data.active_transport_schedule || __("None")],
							["Active Import Leg", data.active_inward_import_leg || "-"],
						]) +
						grnTable +
						`<p class="text-muted small">${frappe.utils.escape_html(
							__(
								"Scheduling follow-up creates a new Inward Import transport leg marked as Partial Import Follow-up. Previous trips and GRNs are kept for traceability."
							)
						)}</p>`,
				},
			],
			primary_action_label: __("Close"),
			primary_action: () => d.hide(),
		});

		if (data.followup_needed) {
			d.add_custom_action(__("Schedule Import Follow-up Trip"), () => {
				d.hide();
				openScheduleImportGrnFollowupDialog(data, refresh);
			});
		} else if (data.active_transport_schedule) {
			d.add_custom_action(__("Open Active Inward Import Trip"), () => {
				d.hide();
				openBookTransportDialog(data.active_transport_schedule, refresh);
			});
		}

		apcAddJobOrderDeleteAction(d, data.job_order, refresh);
		d.show();
	});
}

function openScheduleImportGrnFollowupDialog(data, onSuccess) {
	const d = new frappe.ui.Dialog({
		title: `${__("Schedule Import Follow-up Trip")} — ${data.job_order_number || data.job_order}`,
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				options: `<p class="text-muted small">${frappe.utils.escape_html(
					__(
						"Creates a new Inward Import transport leg for the remaining {0} units AND issues its Delivery Order in the same step. It will appear on both QC's and Security's New Delivery Order queues for precheck.",
						[data.pending_receipt_quantity]
					)
				)}</p>`,
			},
			{
				fieldtype: "Date",
				fieldname: "scheduled_pickup_date",
				label: __("Scheduled Pickup Date"),
				default: data.scheduled_pickup_date || frappe.datetime.get_today(),
			},
			{
				fieldtype: "Date",
				fieldname: "scheduled_delivery_date",
				label: __("Scheduled Delivery Date"),
				default: data.scheduled_delivery_date || frappe.datetime.get_today(),
			},
			{
				fieldtype: "Data",
				fieldname: "pickup_location",
				label: __("Pickup Location"),
				default: data.port_of_discharge || data.pickup_location || "",
			},
			{
				fieldtype: "Data",
				fieldname: "delivery_location",
				label: __("Delivery Location (APC Site)"),
				default: data.delivery_location || "",
			},
			{
				fieldtype: "Float",
				fieldname: "quantity",
				label: __("Qty to Receive"),
				default: data.pending_receipt_quantity,
				description: __("Leave blank to use the full remaining pending quantity."),
			},
			{ fieldtype: "Section Break", label: __("Assignment") },
			{
				fieldtype: "Link",
				fieldname: "transporter",
				label: __("Transporter"),
				options: "Transporter",
				description: __("3rd-party carrier (optional if assigning APC vehicle)"),
			},
			{
				fieldtype: "Link",
				fieldname: "assigned_vehicle",
				label: __("Vehicle"),
				options: "Vehicle",
				reqd: 1,
			},
			{
				fieldtype: "Link",
				fieldname: "assigned_driver",
				label: __("Driver"),
				options: "Driver",
				reqd: 1,
			},
			{
				fieldtype: "Data",
				fieldname: "driver_phone",
				label: __("Driver Phone"),
			},
		],
		primary_action_label: __("Create Follow-up Trip & Issue DO"),
		primary_action(values) {
			d.disable_primary_action();
			const args = { job_order: data.job_order };
			[
				"scheduled_pickup_date",
				"scheduled_delivery_date",
				"pickup_location",
				"delivery_location",
				"quantity",
				"transporter",
				"assigned_vehicle",
				"assigned_driver",
				"driver_phone",
			].forEach((k) => {
				if (values[k]) {
					args[k] = values[k];
				}
			});

			APCConsoleUI.callApi(
				"apc_operations.transportation.api.create_import_partial_receipt_followup_transport_and_issue_do",
				args
			)
				.then((res) => {
					const doRes = res.delivery_order_result;
					if (doRes && doRes.delivery_order) {
						frappe.show_alert({
							message: __("Follow-up transport {0} created, Delivery Order {1} issued", [
								res.transport_schedule,
								doRes.delivery_order,
							]),
							indicator: "green",
						});
					} else {
						frappe.show_alert({
							message: __("Follow-up transport {0} created", [res.transport_schedule]),
							indicator: "green",
						});
						if (res.delivery_order_error) {
							frappe.msgprint(res.delivery_order_error);
						}
					}
					d.hide();
					onSuccess && onSuccess();
				})
				.catch((err) => {
					frappe.msgprint(err);
					d.enable_primary_action();
				});
		},
	});
	d.show();
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
						${renderProductPackagingCardRows(item)}
						${APCConsoleUI.deliveryDueKvHtml(item)}
						<div class="apc-kv-label">${__("Delivery")}</div>
						<div>${frappe.utils.escape_html(item.delivery_location || "-")}</div>
						<div class="apc-kv-label">${__("Scheduled")}</div>
						<div>${APCConsoleUI.formatDate(item.scheduled_delivery_date)}</div>
					`,
					badges: APCConsoleUI.consoleDeliveryBadges(item, [
						APCConsoleUI.statusBadge(item.transport_booking_label, item.transport_booking_tone),
						APCConsoleUI.statusBadge(item.sddn_status, item.sddn_status_tone),
						APCConsoleUI.statusBadge(item.do_status, item.do_status_tone),
					]),
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
		attachTransportPoPrintAction(d, data);
		buildSddnActionFooter(d, data, () => {
			d.hide();
			refresh();
		});
		apcAddJobOrderDeleteAction(d, data.job_order, () => {
			d.hide();
			refresh();
		});
		attachIssueDoAction(d, data, refresh);

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
						${renderProductPackagingCardRows(item)}
						${APCConsoleUI.deliveryDueKvHtml(item)}
						<div class="apc-kv-label">${__("CRO")}</div>
						<div>${frappe.utils.escape_html(item.cro_number || "-")}</div>
						<div class="apc-kv-label">${__("Line")}</div>
						<div>${frappe.utils.escape_html(item.shipping_line || "-")}</div>
						<div class="apc-kv-label">${__("POL → POD")}</div>
						<div>${frappe.utils.escape_html((item.pol || "-") + " → " + (item.pod || "-"))}</div>
					`,
					badges: APCConsoleUI.consoleDeliveryBadges(item, [
						APCConsoleUI.statusBadge(item.transport_booking_label, item.transport_booking_tone),
						APCConsoleUI.statusBadge(item.sddn_status, item.sddn_status_tone),
						APCConsoleUI.statusBadge(item.do_status, item.do_status_tone),
					]),
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
		attachTransportPoPrintAction(d, data);
		buildSddnActionFooter(d, data, () => {
			d.hide();
			onClose && onClose();
		});
		apcAddJobOrderDeleteAction(d, data.job_order, () => {
			d.hide();
			onClose && onClose();
		});

		attachIssueDoAction(d, data, () => {
			d.hide();
			onClose && onClose();
		});

		d.show();
	});
}

// ---------------------------------------------------------------------------
// Issue Delivery Order to Security
// ---------------------------------------------------------------------------

function apcConsoleShowError(err, fallback) {
	let message = fallback || __("Request failed");
	if (typeof err === "string") {
		message = err;
	} else if (err && err.message) {
		message = err.message;
	} else if (err && err._server_messages) {
		try {
			message = JSON.parse(JSON.parse(err._server_messages)[0]).message || message;
		} catch (e) {
			/* keep fallback */
		}
	} else if (err && err.exc) {
		const lines = String(err.exc).trim().split("\n");
		message = lines[lines.length - 1] || message;
	}
	frappe.msgprint({ title: __("Error"), message, indicator: "red" });
}

function attachIssueDoAction(dialog, data, refresh) {
	if (!data || !data.can_generate_do) {
		return;
	}
	const opStatus = (data.do_operational_status || "").trim();
	const isImport = (data.commercial_movement || "").trim() === "Import";
	const importIssuanceLocked =
		isImport &&
		opStatus &&
		["Gate Out Completed", "Cancelled", "On Hold"].includes(opStatus);
	const exportIssuanceLocked =
		!isImport && data.do_name && opStatus && opStatus !== "Draft";

	if (data.do_name) {
		dialog.add_custom_action(__("Open Delivery Order"), () => {
			frappe.set_route("Form", "Delivery Order", data.do_name);
		});
	}

	if (importIssuanceLocked || exportIssuanceLocked) {
		return;
	}

	const issueApi = isImport
		? "apc_operations.shipping.api.generate_delivery_order_for_import"
		: "apc_operations.shipping.api.generate_delivery_order_for_export";
	const thirdPartyLoading = !!data.third_party_loading;
	const issueLabel = isImport
		? __("ISSUE DO to Security (Import)")
		: thirdPartyLoading
		? __("ISSUE DO to QC")
		: __("ISSUE DO to security");
	dialog.add_custom_action(issueLabel, () => {
		dialog.get_primary_btn()?.prop("disabled", true);
		frappe.call({
			method: issueApi,
			args: { job_order: data.job_order },
			freeze: true,
			freeze_message: __("Issuing Delivery Order..."),
			callback: (r) => {
				const doName = r.message && r.message.delivery_order;
				const created = r.message && r.message.created !== false;
				frappe.show_alert({
					message: created
						? __("Delivery Order created: {0}", [doName])
						: __("Delivery Order: {0}", [doName]),
					indicator: "green",
				});
				dialog.hide();
				refresh && refresh();
			},
			error: (err) => apcConsoleShowError(err, __("Could not issue Delivery Order.")),
			always: () => dialog.get_primary_btn()?.prop("disabled", false),
		});
	});
}

function attachFollowupIssueDoAction(dialog, data, refresh) {
	if (!data || !data.can_issue_followup_do) {
		return;
	}
	dialog.add_custom_action(__("ISSUE DO to security"), () => {
		const args = { job_order: data.job_order };
		if (data.transport_schedule) {
			args.transport_schedule = data.transport_schedule;
		}
		frappe.call({
			method: "apc_operations.shipping.api.generate_followup_delivery_order_for_export",
			args,
			freeze: true,
			freeze_message: __("Issuing follow-up Delivery Order..."),
			callback: (r) => {
				frappe.show_alert({
					message: __("Follow-up Delivery Order created: {0}", [
						r.message && r.message.delivery_order,
					]),
					indicator: "green",
				});
				dialog.hide();
				refresh && refresh();
			},
			error: (err) =>
				apcConsoleShowError(err, __("Could not issue follow-up Delivery Order.")),
		});
	});
}

function attachImportHandoffActions(dialog, data, refresh) {
	if ((data.commercial_movement || "").trim() !== "Import") {
		return;
	}
	if (data.linked_export_job_order) {
		dialog.add_custom_action(__("Open Export Job Order"), () => {
			frappe.set_route("Form", "Job Order", data.linked_export_job_order);
		});
		return;
	}
	if (!data.can_link_export && !data.can_create_export) {
		return;
	}
	if (data.can_link_export) {
		dialog.add_custom_action(__("Link Export Job Order"), () => {
			const linkDlg = new frappe.ui.Dialog({
				title: __("Link Export Job Order"),
				fields: [
					{
						fieldtype: "Link",
						fieldname: "export_job_order",
						label: __("Export Job Order"),
						options: "Job Order",
						reqd: 1,
						get_query: () => ({
							filters: { commercial_movement: "Outward", docstatus: ["<", 2] },
						}),
					},
				],
				primary_action_label: __("Link"),
				primary_action: (values) => {
					APCConsoleUI.callApi(
						"apc_operations.shipping.api.link_import_to_export_job_order",
						{
							import_job_order: data.job_order,
							export_job_order: values.export_job_order,
						}
					)
						.then(() => {
							frappe.show_alert({ message: __("Linked"), indicator: "green" });
							linkDlg.hide();
							refresh && refresh();
						})
						.catch((err) => frappe.msgprint(err));
				},
			});
			linkDlg.show();
		});
	}
	if (data.can_create_export) {
		dialog.add_custom_action(__("Create Export Job Order"), () => {
			const createDlg = new frappe.ui.Dialog({
				title: __("Create Export Job Order"),
				fields: [
					{
						fieldtype: "Link",
						fieldname: "customer",
						label: __("Customer"),
						options: "Customer",
						reqd: 1,
					},
					{
						fieldtype: "Data",
						fieldname: "terms_of_delivery",
						label: __("Incoterm"),
						default: data.terms_of_delivery || "FOB",
					},
				],
				primary_action_label: __("Create"),
				primary_action: (values) => {
					APCConsoleUI.callApi(
						"apc_operations.shipping.api.create_export_job_order_from_import",
						{
							import_job_order: data.job_order,
							customer: values.customer,
							terms_of_delivery: values.terms_of_delivery,
						}
					)
						.then((res) => {
							frappe.show_alert({
								message: __("Export JO: {0}", [res.export_job_order]),
								indicator: "green",
							});
							createDlg.hide();
							refresh && refresh();
						})
						.catch((err) => frappe.msgprint(err));
				},
			});
			createDlg.show();
		});
	}
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
		const canUseImportPurchaseOrder =
			data.is_import_purchase_order ||
			(data.source_document_type === "Manual" && data.transport_type === "Inward");
		let d;
		d = new frappe.ui.Dialog({
			title: `${__("Book Transport")} — ${data.name}`,
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					options: renderKvGrid(data, [
						["Transport Schedule", data.name],
						["Current Status", data.transport_status],
						["Booking", data.transport_booking_label],
						["Pickup Location", data.pickup_location || "-"],
						["Delivery Location", data.delivery_location || "-"],
					]),
				},

				...(canUseImportPurchaseOrder
					? [
							{
								fieldtype: "Section Break",
								label: __("Import Purchase Order"),
							},
							{
								fieldtype: "Check",
								fieldname: "is_import_purchase_order",
								label: __("Import Purchase Order"),
								default: data.is_import_purchase_order ? 1 : 0,
								read_only: data.is_import_purchase_order ? 1 : 0,
								description: __(
									"Material purchased from an external supplier and received by APC."
								),
							},
							{
								fieldtype: "Data",
								fieldname: "import_purchase_customer",
								label: __("Customer"),
								default: data.is_import_purchase_order
									? data.customer_name || "APC"
									: "APC",
								read_only: 1,
								depends_on: "eval:doc.is_import_purchase_order",
							},
							{ fieldtype: "Column Break" },
							{
								fieldtype: "Link",
								fieldname: "purchase_supplier",
								label: __("Purchase Supplier"),
								options: "Supplier",
								default: data.purchase_supplier,
								mandatory_depends_on: "eval:doc.is_import_purchase_order",
								depends_on: "eval:doc.is_import_purchase_order",
							},
							{
								fieldtype: "Table",
								fieldname: "purchase_items",
								label: __("Products"),
								mandatory_depends_on: "eval:doc.is_import_purchase_order",
								depends_on: "eval:doc.is_import_purchase_order",
								cannot_add_rows: false,
								in_place_edit: true,
								data:
									data.purchase_items && data.purchase_items.length
										? data.purchase_items
										: data.purchase_item
										? [
												{
													item: data.purchase_item,
													quantity: data.qty_to_load,
													uom: data.purchase_uom,
												},
										  ]
										: [],
								fields: [
									{
										fieldtype: "Link",
										fieldname: "item",
										label: __("Product"),
										options: "Item",
										in_list_view: 1,
										reqd: 1,
										onchange() {
											const row = this.doc;
											if (!row || !row.item) return;
											frappe.db
												.get_value("Item", row.item, ["item_name", "stock_uom"])
												.then((r) => {
													const itemRow = r && r.message;
													if (!itemRow) return;
													frappe.model.set_value(
														row.doctype,
														row.name,
														"item_name",
														itemRow.item_name || row.item
													);
													if (itemRow.stock_uom && !row.uom) {
														frappe.model.set_value(row.doctype, row.name, "uom", itemRow.stock_uom);
													}
												});
										},
									},
									{
										fieldtype: "Data",
										fieldname: "item_name",
										label: __("Product Name"),
										in_list_view: 1,
										read_only: 1,
									},
									{
										fieldtype: "Link",
										fieldname: "packaging_type",
										label: __("Packaging Type"),
										options: "APC Packaging Type",
										in_list_view: 1,
									},
									{
										fieldtype: "Select",
										fieldname: "packing_unit_type",
										label: __("Packing Unit Type"),
										options: "\nDrum\nIBC\nBag\nCarton\nPail\nFlexi\nISO\nBulk",
										in_list_view: 1,
									},
									{
										fieldtype: "Int",
										fieldname: "packaging_qty",
										label: __("Expected Package Qty"),
										in_list_view: 1,
									},
									{
										fieldtype: "Float",
										fieldname: "quantity",
										label: __("Product Quantity"),
										in_list_view: 1,
										reqd: 1,
									},
									{
										fieldtype: "Link",
										fieldname: "uom",
										label: __("UOM"),
										options: "UOM",
										in_list_view: 1,
										reqd: 1,
									},
									{
										fieldtype: "Text",
										fieldname: "description",
										label: __("Description"),
									},
								],
							},
						]
					: []),

				{ fieldtype: "Section Break", label: __("Route") },
				{
					fieldtype: "Data",
					fieldname: "pickup_location",
					label: __("Pickup Location"),
					default: data.pickup_location,
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Data",
					fieldname: "delivery_location",
					label: __("Delivery Location"),
					default: data.delivery_location,
				},
				{
					fieldtype: "Float",
					fieldname: "qty_to_load",
					label: __("Qty to Load"),
					default: data.qty_to_load,
					description: __("Leave blank to use the full Job Order quantity."),
					mandatory_depends_on: "eval:doc.is_import_purchase_order",
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
				{
					fieldtype: "Check",
					fieldname: "third_party_loading",
					label: __("3rd Party Loading"),
					default: data.third_party_loading ? 1 : 0,
					description: __("Route the Delivery Order to QC when loading happens outside APC."),
				},
				{
					fieldtype: "Data",
					fieldname: "third_party_loader",
					label: __("3rd Party Loader"),
					default: data.third_party_loader,
					depends_on: "eval:doc.third_party_loading",
				},
				{
					fieldtype: "Data",
					fieldname: "third_party_loading_location",
					label: __("3rd Party Loading Location"),
					default: data.third_party_loading_location,
					depends_on: "eval:doc.third_party_loading",
				},
				{
					fieldtype: "Small Text",
					fieldname: "third_party_loading_notes",
					label: __("3rd Party Loading Notes"),
					default: data.third_party_loading_notes,
					depends_on: "eval:doc.third_party_loading",
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
					label: __("Toll Cost"),
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
					"pickup_location",
					"delivery_location",
					"qty_to_load",
					"third_party_loading",
					"third_party_loader",
					"third_party_loading_location",
					"third_party_loading_notes",
					"is_import_purchase_order",
					"purchase_supplier",
				].forEach((k) => {
					if (values[k] !== undefined && values[k] !== "") {
						args[k] = values[k];
					}
				});
				if (values.purchase_items !== undefined) {
					args.purchase_items = JSON.stringify(values.purchase_items || []);
				}
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
	TRANSPORT_PO: "Standard Transport PO",
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

function attachTransportPoPrintAction(dialog, data) {
	if (!data || !data.transport_schedule || !data.is_transport_booked) {
		return;
	}

	dialog.add_custom_action(__("Print Transport PO"), () => {
		const openPrint = (tpoName) => {
			if (!tpoName) {
				frappe.msgprint(__("Transport PO Request is not available yet."));
				return;
			}
			apcTransportConsoleOpenPrintDownload(
				apcTransportConsolePrintUrl(
					"Transport PO Request",
					tpoName,
					APC_TRANSPORT_PRINT_FORMATS.TRANSPORT_PO
				)
			);
		};

		if (data.transport_po_request) {
			openPrint(data.transport_po_request);
			return;
		}

		APCConsoleUI.callApi(
			"apc_operations.transportation.api.ensure_transport_po_for_schedule",
			{ transport_schedule: data.transport_schedule }
		)
			.then((res) => openPrint(res && res.transport_po_request))
			.catch((err) => frappe.msgprint(err));
	});
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
						${renderProductPackagingCardRows(item)}
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
						${renderProductPackagingCardRows(item)}
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
						${renderProductPackagingCardRows(item)}
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
// Partial delivery follow-up (new transport leg only)
// ---------------------------------------------------------------------------

function buildPartialDeliveryFollowupScreen() {
	return {
		title: __("Partial Delivery Follow-up"),
		render($root, router) {
			renderCardScreen($root, {
				listApi: "apc_operations.transportation.api.get_partial_delivery_followup_list",
				searchPlaceholder: __("Search by Job Order / Customer"),
				toCard: (item) => ({
					title: item.job_order_number || item.job_order || item.name,
					subtitle: item.customer_name || item.customer || "-",
					body_html: `
						${renderProductPackagingCardRows(item)}
						${APCConsoleUI.deliveryDueKvHtml(item)}
						<div class="apc-kv-label">${__("Pending Qty")}</div>
						<div>${frappe.utils.escape_html(String(item.pending_dispatch_quantity || "-"))}</div>
						<div class="apc-kv-label">${__("Delivered so far")}</div>
						<div>${frappe.utils.escape_html(
							String(item.total_dispatched_quantity || "-")
						)} / ${frappe.utils.escape_html(String(item.job_order_quantity || item.total_demand_quantity || "-"))}</div>
						<div class="apc-kv-label">${__("Last trip")}</div>
						<div>${frappe.utils.escape_html(item.last_completed_transport || "-")}</div>
					`,
					badges: APCConsoleUI.consoleDeliveryBadges(item, [
						APCConsoleUI.statusBadge(__("Partial Dispatch"), "warn"),
						item.followup_needed
							? APCConsoleUI.statusBadge(__("Follow-up Needed"), "info")
							: APCConsoleUI.statusBadge(__("Trip Scheduled"), "success"),
					]),
					raw: item,
				}),
				onCardClick: (item) =>
					openPartialDeliveryFollowupModal(item.raw, () => router.refresh()),
			});
		},
	};
}

function partialFollowupNextStepHint(data) {
	if (data.needs_followup_transport) {
		return __("Next: schedule a follow-up transport leg for the remaining quantity.");
	}
	if (data.needs_transport_booking) {
		return __("Next: book transport (vehicle / driver) before issuing DO to Security.");
	}
	if (data.do_name && !data.can_issue_followup_do) {
		return data.followup_do_reason || __("Complete the open Delivery Order before issuing a follow-up DO.");
	}
	if (data.can_issue_followup_do) {
		return __("Next: issue DO to Security for the remaining {0} units.", [
			data.pending_dispatch_quantity,
		]);
	}
	return data.followup_do_reason || "";
}

function openPartialDeliveryFollowupModal(item, onClose) {
	const refresh = () => onClose && onClose();
	APCConsoleUI.callApi(
		"apc_operations.transportation.api.get_partial_delivery_followup_detail",
		{ job_order: item.job_order || item.name }
	).then((data) => {
		const nextHint = partialFollowupNextStepHint(data);
		const d = new frappe.ui.Dialog({
			title: `${__("Partial Delivery Follow-up")} — ${data.job_order_number || data.job_order}`,
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					options:
						renderKvGrid(data, [
							["Job Order", data.job_order_number || data.job_order],
							["Customer", data.customer_name || data.customer],
							["Pending Quantity", data.pending_dispatch_quantity],
							[
								"Dispatched / Job Order Qty",
								`${data.total_dispatched_quantity} / ${data.job_order_quantity || data.total_demand_quantity}`,
							],
							["Outward Type", data.outward_type],
							["Delivery Location", data.delivery_location],
							["Last Completed Trip", data.last_completed_transport],
							["Last Trip Status", data.last_completed_transport_status],
							["Active Trip", data.transport_schedule || data.active_transport_schedule || __("None")],
							["Transport Status", data.transport_status || "-"],
							["Vehicle", data.vehicle_number || "-"],
							["Driver", data.driver_name || "-"],
							["SDDN", data.sddn || "-"],
							["DO", data.do_name || "-"],
						]) +
						renderStatusChain([
							{
								label: data.transport_booking_label || __("Pending"),
								tone: data.transport_booking_tone,
							},
							{ label: data.sddn_status || __("Draft"), tone: data.sddn_status_tone },
							{ label: data.do_status || __("Pending"), tone: data.do_status_tone },
						]) +
						(nextHint
							? `<p class="text-muted small">${frappe.utils.escape_html(nextHint)}</p>`
							: "") +
						`<p class="text-muted small">${frappe.utils.escape_html(
							__(
								"Scheduling follow-up always creates a new transport leg. Previous trips are kept for traceability."
							)
						)}</p>`,
				},
			],
			primary_action_label: __("Close"),
			primary_action: () => d.hide(),
		});

		if (data.followup_needed) {
			d.add_custom_action(__("Schedule Follow-up Trip"), () => {
				d.hide();
				openScheduleFollowupDialog(data, refresh);
			});
		}

		attachBookTransportAction(d, data, () => {
			d.hide();
			refresh();
		});
		attachTransportPoPrintAction(d, data);
		buildSddnActionFooter(d, data, () => {
			d.hide();
			refresh();
		});
		if (data.can_issue_followup_do) {
			attachFollowupIssueDoAction(d, data, refresh);
		} else if (data.can_generate_do) {
			attachIssueDoAction(d, data, refresh);
		}

		apcAddJobOrderDeleteAction(d, data.job_order, () => {
			d.hide();
			refresh();
		});
		d.show();
	});
}

function openScheduleFollowupDialog(data, onSuccess) {
	const d = new frappe.ui.Dialog({
		title: `${__("Schedule Follow-up Trip")} — ${data.job_order_number || data.job_order}`,
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				options: `<p class="text-muted small">${frappe.utils.escape_html(
					__(
						"A new transport schedule will be created for the remaining {0} units. Previous completed trips are kept for traceability.",
						[data.pending_dispatch_quantity]
					)
				)}</p>`,
			},
			{
				fieldtype: "Select",
				fieldname: "outward_type",
				label: __("Outward Type"),
				options:
					"\nLocal Delivery\nTanker Delivery\nTrailer Delivery\nExport Container",
				default: data.outward_type || "Local Delivery",
			},
			{
				fieldtype: "Float",
				fieldname: "quantity",
				label: __("Qty to Load"),
				default: data.pending_dispatch_quantity,
				description: __("Defaults to the full remaining quantity — lower it if even this trip can't carry all of it."),
			},
			{ fieldtype: "Section Break", label: __("Schedule") },
			{
				fieldtype: "Date",
				fieldname: "scheduled_pickup_date",
				label: __("Scheduled Pickup"),
				default: data.scheduled_pickup_date,
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Date",
				fieldname: "scheduled_delivery_date",
				label: __("Scheduled Delivery"),
				default: data.scheduled_delivery_date,
			},
			{
				fieldtype: "Data",
				fieldname: "pickup_location",
				label: __("Pickup Location"),
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Data",
				fieldname: "delivery_location",
				label: __("Delivery Location"),
				default: data.delivery_location,
			},
			{ fieldtype: "Section Break", label: __("Assignment (optional)") },
			{
				fieldtype: "Link",
				fieldname: "transporter",
				label: __("Transporter"),
				options: "Transporter",
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Link",
				fieldname: "assigned_vehicle",
				label: __("Vehicle"),
				options: "Vehicle",
			},
			{
				fieldtype: "Link",
				fieldname: "assigned_driver",
				label: __("Driver"),
				options: "Driver",
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Data",
				fieldname: "driver_phone",
				label: __("Driver Contact"),
			},
			{ fieldtype: "Section Break", label: __("Third Party Loading") },
			{
				fieldtype: "Check",
				fieldname: "third_party_loading",
				label: __("3rd Party Loading"),
				default: data.third_party_loading ? 1 : 0,
				description: __("Route the Delivery Order to QC when loading happens outside APC."),
			},
			{
				fieldtype: "Data",
				fieldname: "third_party_loader",
				label: __("3rd Party Loader"),
				default: data.third_party_loader,
				depends_on: "eval:doc.third_party_loading",
			},
			{
				fieldtype: "Data",
				fieldname: "third_party_loading_location",
				label: __("3rd Party Loading Location"),
				default: data.third_party_loading_location,
				depends_on: "eval:doc.third_party_loading",
			},
			{
				fieldtype: "Small Text",
				fieldname: "third_party_loading_notes",
				label: __("3rd Party Loading Notes"),
				default: data.third_party_loading_notes,
				depends_on: "eval:doc.third_party_loading",
			},
		],
		primary_action_label: __("Create Follow-up Trip & Issue DO"),
		primary_action: (values) => {
			d.disable_primary_action();
			const args = { job_order: data.job_order };
			[
				"outward_type",
				"quantity",
				"scheduled_pickup_date",
				"scheduled_delivery_date",
				"pickup_location",
				"delivery_location",
				"transporter",
				"assigned_vehicle",
				"assigned_driver",
				"driver_phone",
				"third_party_loading",
				"third_party_loader",
				"third_party_loading_location",
				"third_party_loading_notes",
			].forEach((k) => {
				if (values[k]) {
					args[k] = values[k];
				}
			});

			APCConsoleUI.callApi(
				"apc_operations.transportation.api.create_partial_delivery_followup_transport_and_issue_do",
				args
			)
				.then((res) => {
					const doRes = res.delivery_order_result;
					if (doRes && doRes.delivery_order) {
						frappe.show_alert({
							message: __("Follow-up transport {0} created, Delivery Order {1} issued", [
								res.transport_schedule,
								doRes.delivery_order,
							]),
							indicator: "green",
						});
					} else {
						frappe.show_alert({
							message: __("Follow-up transport {0} created", [res.transport_schedule]),
							indicator: "green",
						});
						if (res.delivery_order_error) {
							frappe.msgprint(res.delivery_order_error);
						}
					}
					d.hide();
					onSuccess && onSuccess();
					if (
						res.transport_schedule &&
						!values.assigned_driver &&
						!values.assigned_vehicle
					) {
						openBookTransportDialog(res.transport_schedule, onSuccess);
					}
				})
				.catch((err) => {
					frappe.msgprint(err);
					d.enable_primary_action();
				});
		},
	});
	d.show();
}

// ---------------------------------------------------------------------------
// Shared card-screen renderer
// ---------------------------------------------------------------------------

function renderCardScreen($root, options) {
	return APCConsoleUI.renderCardScreen($root, options);
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

function renderProductPackagingCardRows(item) {
	const product = item.product_name || item.product || item.material_description;
	const packaging = item.packaging_type || item.packing_unit_type || item.packing_material;
	if (!product && !packaging) {
		return "";
	}
	return `
		<div class="apc-kv-label">${__("Product")}</div>
		<div>${frappe.utils.escape_html(product || "-")}</div>
		<div class="apc-kv-label">${__("Packaging")}</div>
		<div>${frappe.utils.escape_html(packaging || "-")}</div>
	`;
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
