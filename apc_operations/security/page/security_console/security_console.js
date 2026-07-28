/* Security Console — APC Operations
 *
 * Hub -> Delivery Order queues (New / Pending / In progress / Completed)
 *   -> DO detail -> SDDN / LDN / gate modals.
 * Draft notes (SDDN) lists remain under "Draft notes".
 */

frappe.pages["security-console"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Security"),
		single_column: true,
	});

	const router = new APCConsoleRouter(page, { rootClass: "apc-console apc-console-security" });
	router.reset(buildSecurityHubScreen(router));
};

function buildSecurityHubScreen(router) {
	return {
		title: __("Security"),
		render($root) {
			const $bannerHolder = $('<div class="apc-pending-holder"></div>').appendTo($root);
			APCConsoleUI.callApi("apc_operations.security.api.get_security_console_counts")
				.then((counts) => {
					APCConsoleUI.pendingBanner($bannerHolder, {
						transport: counts.new || 0,
						do: counts.pending || 0,
						sddn: counts.in_progress || 0,
					}, (filterId) => {
						if (filterId === "transport") {
							router.push(buildDoQueueScreen(__("New Delivery Orders"), "apc_operations.security.api.get_security_new_dos"));
						} else if (filterId === "do") {
							router.push(buildDoQueueScreen(__("Pending Delivery Orders"), "apc_operations.security.api.get_security_pending_dos"));
						} else if (filterId === "sddn") {
							router.push(buildDoQueueScreen(__("In Progress Delivery Orders"), "apc_operations.security.api.get_security_in_progress_dos"));
						}
					});
					$bannerHolder.find(".apc-pending-tile").eq(0).find(".apc-pending-tile-label").text(__("New DOs"));
					$bannerHolder.find(".apc-pending-tile").eq(1).find(".apc-pending-tile-label").text(__("Pending DOs"));
					$bannerHolder.find(".apc-pending-tile").eq(2).find(".apc-pending-tile-label").text(__("In Progress"));
				})
				.catch(() => {});

			APCConsoleUI.hubButtonsWithDailyWork($root, "security", [
				{
					queueKey: "new_dos",
					label: __("New Delivery Orders"),
					fallback: __("DO created — awaiting security draft"),
					onClick: () =>
						router.push(
							buildDoQueueScreen(
								__("New Delivery Orders"),
								"apc_operations.security.api.get_security_new_dos"
							)
						),
				},
				{
					queueKey: "pending_dos",
					label: __("Pending Delivery Orders"),
					fallback: __("SDDN verification in progress"),
					onClick: () =>
						router.push(
							buildDoQueueScreen(
								__("Pending Delivery Orders"),
								"apc_operations.security.api.get_security_pending_dos"
							)
						),
				},
				{
					queueKey: "in_progress_dos",
					label: __("In Progress Delivery Orders"),
					fallback: __("Verified — loading / QC handoff"),
					onClick: () =>
						router.push(
							buildDoQueueScreen(
								__("In Progress Delivery Orders"),
								"apc_operations.security.api.get_security_in_progress_dos"
							)
						),
				},
				{
					queueKey: "completed_dos",
					label: __("Completed Delivery Orders"),
					fallback: __("DN issued — gate out or closed"),
					onClick: () =>
						router.push(
							buildDoQueueScreen(
								__("Completed Delivery Orders"),
								"apc_operations.security.api.get_security_completed_dos",
								true
							)
						),
				},
				{
					label: __("Completed Delivery Notes"),
					fallback: __("Issued LDNs — view and print"),
					onClick: () => router.push(buildCompletedDeliveryNotesScreen()),
				},
				{
					label: __("Gate In / Gate Out"),
					fallback: __("Active gate movements"),
					onClick: () => router.push(buildGatePassScreen()),
				},
				{
					label: __("Loading Bay Console"),
					fallback: __("Issue Delivery Note after QC approval"),
					onClick: () => router.push(buildLoadingBayScreen()),
				},
				{
					label: __("Import GRN"),
					fallback: __("Import only — QC & security cleared, confirm receipt"),
					onClick: () => frappe.set_route("import-grn-console"),
				},
				{
					label: __("Draft Notes (SDDN)"),
					fallback: __("Legacy SDDN lists"),
					onClick: () => router.push(buildSddnLegacyHubScreen(router)),
				},
			]);
		},
	};
}

function buildSddnLegacyHubScreen(router) {
	return {
		title: __("Draft Notes (SDDN)"),
		render($root) {
			APCConsoleUI.hubButtons($root, [
				{
					label: __("Pending SDDNs"),
					subtitle: __("Verify truck, driver, container"),
					onClick: () => router.push(buildPendingSddnsScreen()),
				},
				{
					label: __("Verified Draft Notes"),
					subtitle: __("Ready to create Loading DN"),
					onClick: () => router.push(buildVerifiedSddnsScreen()),
				},
				{
					label: __("Loading Delivery Notes"),
					subtitle: __("Send to QC"),
					onClick: () => router.push(buildLdnQueueScreen()),
				},
			]);
		},
	};
}

function buildDoQueueScreen(title, listApi, readOnly) {
	return {
		title,
		render($root, router) {
			renderCardScreen($root, {
				listApi,
				searchPlaceholder: __("Search by DO / JO / Customer / Truck"),
				toCard: (item) => doItemToCard(item),
				onCardClick: (item) => openDoModal(item.raw, !!readOnly, () => router.refresh()),
			});
		},
	};
}

const APC_SDDN_VERIFIED_STATUSES = [
	"Verified",
	"Approved",
	"LDN Created",
	"Sent to QC",
	"Completed",
];

function apcSecurityIsSddnVerified(rawStatus) {
	return APC_SDDN_VERIFIED_STATUSES.indexOf(rawStatus || "") !== -1;
}

function apcSecurityPromptSendLdnToQc(ldnName, refresh) {
	frappe.confirm(
		__(
			"Send {0} to QC now? This creates a QC Report Request and notifies QC (Pending Delivery Orders).",
			[ldnName]
		),
		() => {
			APCConsoleUI.callApi(
				"apc_operations.security.api.send_loading_delivery_note_to_qc",
				{ ldn: ldnName }
			)
				.then((res) => {
					frappe.show_alert({
						message: __("Sent to QC: {0}", [
							(res && res.qc_report_request) || ldnName,
						]),
						indicator: "green",
					});
					refresh && refresh();
				})
				.catch((err) => frappe.msgprint(err));
		},
		() => {
			APCConsoleUI.callApi(
				"apc_operations.security.api.queue_loading_delivery_note_for_qc",
				{ ldn: ldnName }
			)
				.then(() => {
					frappe.msgprint({
						title: __("Queued for QC"),
						message: __(
							"LDN {0} is queued. Open QC Console → New Delivery Orders to start QC.",
							[ldnName]
						),
						indicator: "green",
					});
					refresh && refresh();
				})
				.catch((err) => frappe.msgprint(err));
		},
		__("Send to QC?")
	);
}

function apcSecurityPromptAfterLdnCreated(ldnName, refresh, onDialogHide) {
	frappe.confirm(
		__(
			"Loading Delivery Note {0} was created. Send to QC now?",
			[ldnName]
		),
		() => {
			APCConsoleUI.callApi(
				"apc_operations.security.api.send_loading_delivery_note_to_qc",
				{ ldn: ldnName }
			)
				.then((res) => {
					frappe.show_alert({
						message: __("Sent to QC: {0}", [
							(res && res.qc_report_request) || ldnName,
						]),
						indicator: "green",
					});
					onDialogHide && onDialogHide();
					refresh && refresh();
				})
				.catch((err) => frappe.msgprint(err));
		},
		() => {
			APCConsoleUI.callApi(
				"apc_operations.security.api.queue_loading_delivery_note_for_qc",
				{ ldn: ldnName }
			)
				.then(() => {
					frappe.msgprint({
						title: __("Queued for QC"),
						message: __(
							"LDN {0} is in QC Console → New Delivery Orders.",
							[ldnName]
						),
						indicator: "green",
					});
					onDialogHide && onDialogHide();
					refresh && refresh();
				})
				.catch((err) => frappe.msgprint(err));
		},
		__("Send to QC?")
	);
}

function apcSecurityCreateLoadingDn(sddn, refresh, onDialogHide) {
	return new Promise((resolve, reject) => {
		frappe.call({
			method: "apc_operations.security.api.create_loading_delivery_note",
			args: { sddn },
			freeze: true,
			freeze_message: __("Creating Loading Delivery Note..."),
			callback: (r) => {
				const res = r.message;
				const ldn = res && res.loading_delivery_note;
				frappe.show_alert({
					message: __("LDN created: {0}", [ldn]),
					indicator: "green",
				});
				if (ldn) {
					apcSecurityPromptAfterLdnCreated(ldn, refresh, onDialogHide);
				} else {
					onDialogHide && onDialogHide();
					refresh && refresh();
				}
				resolve(res);
			},
			error: (err) => {
				APCConsoleUI.showApiError(err, __("Could not create Loading Delivery Note."));
				reject(err);
			},
		});
	});
}

function doItemToCard(item) {
	const jo = frappe.utils.escape_html(item.job_order_number || item.job_order || "-");
	const badges = APCConsoleUI.consoleDeliveryBadges(item, [
		APCConsoleUI.statusBadge(item.operational_status, item.operational_status_tone),
	]);
	if (item.sddn_status) {
		badges.push(APCConsoleUI.statusBadge(item.sddn_status, item.sddn_status_tone));
	}
	if (item.ldn_status && item.ldn) {
		badges.push(APCConsoleUI.statusBadge(item.ldn_status, item.ldn_status_tone));
	}
	const qtyLabel = item.quantity_to_load
		? `${item.quantity_to_load}${item.uom ? " " + item.uom : ""}`
		: "-";
	return {
		title: item.delivery_order || item.name,
		subtitle: item.customer_name || item.customer || "-",
		body_html: `
			${APCConsoleUI.deliveryDueKvHtml(item)}
			<div class="apc-kv-label">${__("Job Order")}</div>
			<div>${jo}</div>
			<div class="apc-kv-label">${__("Truck")}</div>
			<div>${frappe.utils.escape_html(item.truck_number || "-")}</div>
			<div class="apc-kv-label">${__("Driver")}</div>
			<div>${frappe.utils.escape_html(item.driver_name || "-")}</div>
			<div class="apc-kv-label">${__("Product / Qty")}</div>
			<div>${frappe.utils.escape_html(item.product || "-")} / ${frappe.utils.escape_html(qtyLabel)}</div>
			<div class="apc-kv-label">${__("SDDN")}</div>
			<div>${frappe.utils.escape_html(item.sddn || "-")}</div>
			<div class="apc-kv-label">${__("LDN")}</div>
			<div>${frappe.utils.escape_html(item.ldn || item.loading_delivery_note || "-")}</div>
		`,
		badges,
		raw: item,
	};
}

function _formatQtyWithUom(qty, uom) {
	if (qty === null || qty === undefined || qty === "") {
		return "—";
	}
	return uom ? `${qty} ${uom}` : String(qty);
}

function _doModalKvPairs(data) {
	const pairs = [
		["Delivery Order", data.delivery_order],
		["Operation", data.commercial_movement || "Export"],
		["Job Order", data.job_order_number || data.job_order],
		["Customer", data.customer_name || data.customer],
		["Incoterm", data.terms_of_delivery || "—"],
		["Truck Number", data.truck_number || "—"],
		["Driver Name", data.driver_name || "—"],
		["Driver Number", data.driver_contact || "—"],
		["Product", data.product || "—"],
		["Qty to Load", _formatQtyWithUom(data.quantity_to_load, data.uom)],
		["Status", data.do_shipping_status_label || data.status],
		["Pipeline", data.operational_status || "—"],
		["Supplier", data.supplier_name || "—"],
		["Linked Export JO", data.linked_export_job_order || "—"],
		["SDDN", data.sddn || "—"],
		["SDDN Status", data.sddn_status || "—"],
		["LDN", data.loading_delivery_note || "—"],
		["LDN Status", data.ldn_status || "—"],
	];
	if (data.qc_report_request) {
		pairs.push(["QC Report", data.qc_report_request]);
		pairs.push(["QC Report Status", data.qc_report_status || "—"]);
	}
	return pairs;
}

function openDoModal(doCard, readOnly, refresh) {
	const doName = doCard.delivery_order || doCard.name;
	APCConsoleUI.callApi("apc_operations.security.api.get_security_do_detail", {
		delivery_order: doName,
	}).then((data) => {
		const d = new frappe.ui.Dialog({
			title: `${__("Delivery Order")} — ${data.delivery_order || doName}`,
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					options: renderKvGrid(data, _doModalKvPairs(data)),
				},
			],
			primary_action_label: __("Close"),
			primary_action: () => d.hide(),
		});

		if (!readOnly && !data.read_only && data.sddn) {
			d.add_custom_action(__("Open SDDN"), () => {
				d.hide();
				openSddnModal(
					{
						sddn: data.sddn,
						raw_security_status: data.raw_sddn_status,
						job_order: data.job_order,
						job_order_number: data.job_order_number,
					},
					refresh
				);
			});
		}

		if (!readOnly && !data.read_only && data.can_report_to_qc) {
			d.add_custom_action(__("Report to QC"), () => {
				frappe.confirm(
					__(
						"Report Delivery Order {0} to QC? The security checklist must be completed.",
						[doName]
					),
					() => {
						APCConsoleUI.callApi(
							"apc_operations.security.api.report_delivery_order_to_qc",
							{ delivery_order: doName }
						)
							.then((res) => {
								frappe.show_alert({
									message: __("Reported to QC: {0}", [
										(res && res.qc_report_request) || doName,
									]),
									indicator: "green",
								});
								d.hide();
								refresh && refresh();
							})
							.catch((err) => frappe.msgprint(err));
					}
				);
			});
		}

		if (!readOnly && !data.read_only && data.can_create_ldn) {
			d.add_custom_action(__("Create Loading Delivery Note"), () => {
				apcSecurityCreateLoadingDn(data.sddn, refresh, () => d.hide());
			});
		}

		if (!readOnly && !data.read_only && data.loading_delivery_note && !data.can_report_to_qc) {
			if (data.can_queue_for_qc) {
				d.add_custom_action(__("Queue for QC (New DO)"), () => {
					APCConsoleUI.callApi(
						"apc_operations.security.api.queue_loading_delivery_note_for_qc",
						{ ldn: data.loading_delivery_note }
					)
						.then(() => {
							frappe.msgprint({
								title: __("Queued for QC"),
								message: __(
									"LDN {0} will appear in QC Console → New Delivery Orders.",
									[data.loading_delivery_note]
								),
								indicator: "green",
							});
							d.hide();
							refresh && refresh();
						})
						.catch((err) => frappe.msgprint(err));
				});
			}
			if (data.can_send_to_qc) {
				d.add_custom_action(__("Send LDN to QC"), () => {
					apcSecurityPromptSendLdnToQc(data.loading_delivery_note, () => {
						d.hide();
						refresh && refresh();
					});
				});
			}
		}

		if (data.loading_delivery_note) {
			d.add_custom_action(__("Open LDN"), () => {
				frappe.set_route("Form", "Loading Delivery Note", data.loading_delivery_note);
			});
			d.add_custom_action(
				__("Print Delivery Note"),
				() => {
					apcSecurityConsoleOpenPrintDownload(
						apcSecurityConsolePrintUrl(
							"Loading Delivery Note",
							data.loading_delivery_note,
							APC_SECURITY_PRINT_FORMATS.LDN
						)
					);
				},
				__("Documents")
			);
		}
		d.add_custom_action(__("Print Delivery Order"), () => {
			const url = `/printview?doctype=${encodeURIComponent("Delivery Order")}&name=${encodeURIComponent(
				doName
			)}&format=${encodeURIComponent("Standard Delivery Order")}&no_letterhead=0&_lang=en`;
			window.open(url, "_blank");
		});
		d.add_custom_action(__("Open DO Form"), () => {
			frappe.set_route("Form", "Delivery Order", doName);
		});

		if (!readOnly && !data.read_only && data.can_link_export_job_order) {
			d.add_custom_action(__("Link Export Job Order"), () => {
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
								filters: { commercial_movement: "Export", docstatus: ["<", 2] },
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
								d.hide();
								refresh && refresh();
							})
							.catch((err) => frappe.msgprint(err));
					},
				});
				linkDlg.show();
			});
		}
		if (!readOnly && !data.read_only && data.can_create_export_job_order) {
			d.add_custom_action(__("Create Export Job Order"), () => {
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
								d.hide();
								refresh && refresh();
							})
							.catch((err) => frappe.msgprint(err));
					},
				});
				createDlg.show();
			});
		}

		d.show();
	});
}

// ---------------------------------------------------------------------------
// Pending SDDNs
// ---------------------------------------------------------------------------

function buildPendingSddnsScreen() {
	return {
		title: __("Pending SDDNs"),
		render($root, router) {
			renderCardScreen($root, {
				listApi: "apc_operations.security.api.get_pending_security_delivery_draft_notes",
				searchPlaceholder: __("Search by SDDN / JO / Truck / Driver"),
				toCard: (sddn) => ({
					title: sddn.sddn,
					subtitle: sddn.customer_name || sddn.customer || sddn.job_order_number || sddn.job_order || "-",
					body_html: `
						<div class="apc-kv-label">${__("JO")}</div>
						<div>${frappe.utils.escape_html(sddn.job_order_number || sddn.job_order || "-")}</div>
						<div class="apc-kv-label">${__("Truck")}</div>
						<div>${frappe.utils.escape_html(sddn.truck_number || "-")}</div>
						<div class="apc-kv-label">${__("Driver")}</div>
						<div>${frappe.utils.escape_html(sddn.driver_name || "-")}</div>
						<div class="apc-kv-label">${__("Container")}</div>
						<div>${frappe.utils.escape_html(sddn.container_number || "-")}</div>
					`,
					badges: [APCConsoleUI.statusBadge(sddn.security_status, sddn.security_status_tone)],
					raw: sddn,
				}),
				onCardClick: (item) => openSddnModal(item.raw, () => router.refresh()),
			});
		},
	};
}

function buildVerifiedSddnsScreen() {
	return {
		title: __("Verified Draft Notes"),
		render($root, router) {
			renderCardScreen($root, {
				listApi: "apc_operations.security.api.get_verified_security_delivery_draft_notes",
				searchPlaceholder: __("Search by SDDN / JO / Customer"),
				toCard: (sddn) => ({
					title: sddn.sddn,
					subtitle: sddn.customer_name || sddn.customer || sddn.job_order_number || sddn.job_order || "-",
					body_html: `
						<div class="apc-kv-label">${__("JO")}</div>
						<div>${frappe.utils.escape_html(sddn.job_order_number || sddn.job_order || "-")}</div>
						<div class="apc-kv-label">${__("Truck")}</div>
						<div>${frappe.utils.escape_html(sddn.truck_number || "-")}</div>
						<div class="apc-kv-label">${__("LDN")}</div>
						<div>${frappe.utils.escape_html(sddn.loading_delivery_note || "-")}</div>
					`,
					badges: [
						APCConsoleUI.statusBadge(sddn.security_status, sddn.security_status_tone),
						APCConsoleUI.statusBadge(sddn.ldn_status, sddn.ldn_status_tone),
					],
					raw: sddn,
				}),
				onCardClick: (item) => openSddnModal(item.raw, () => router.refresh()),
			});
		},
	};
}

function openSddnModal(sddn, refresh) {
	APCConsoleUI.callApi(
		"apc_operations.security.api.get_security_delivery_draft_note_detail",
		{ name: sddn.sddn }
	).then((data) => {
		const gateFetch = data.transport_schedule
			? frappe.db.get_value("Transport Schedule", data.transport_schedule, "gate_pass")
			: Promise.resolve({ message: {} });

		gateFetch.then((gpRow) => {
			const existingGatePass = gpRow.message && gpRow.message.gate_pass;

			const isVerifiable = ["Draft", "Pending Review", "Pending Verification", "Sent to Security"].indexOf(
				data.raw_security_status
			) !== -1;
			const isVerified = ["Verified", "Approved", "LDN Created", "Sent to QC", "Completed"].indexOf(
				data.raw_security_status
			) !== -1;
			const hasLdn = !!data.loading_delivery_note;
			const checklistItems = Array.isArray(data.checklist_items) ? data.checklist_items : [];
			const checklistEditable = isVerifiable;

			const headerPairs = [
				[
					__("Job order number"),
					data.job_order_number || data.job_order || "—",
				],
				["Customer", data.customer_name || data.customer || "—"],
				["CRO Number", data.cro_number],
				["Container Number", data.container_number],
				["Truck Number", data.truck_number],
				["Driver Name", data.driver_name],
				["Driver Contact", data.driver_contact],
				["Pickup Location", data.pickup_location],
				["Destination", data.destination],
				["Transport Status", data.transport_status],
				["Security Status", data.security_status],
				["LDN", data.loading_delivery_note || "—"],
			];
			if (existingGatePass) {
				headerPairs.push(["Gate Pass", existingGatePass]);
			}

			const d = new frappe.ui.Dialog({
				title: `${__("SDDN")} — ${data.sddn}`,
				size: "large",
				fields: [
					{
						fieldtype: "HTML",
						options: renderKvGrid(data, headerPairs),
					},
				{ fieldtype: "Section Break", label: __("Security Checklist") },
				{
					fieldtype: "HTML",
					fieldname: "checklist_html",
					options: renderSecurityChecklist(checklistItems, checklistEditable),
				},
				{ fieldtype: "Section Break", label: __("Verification") },
				{
					fieldtype: "Check",
					fieldname: "truck_verified",
					label: __("Verify Truck"),
					default: data.verification && data.verification.truck_verified ? 1 : 0,
				},
				{
					fieldtype: "Check",
					fieldname: "driver_verified",
					label: __("Verify Driver"),
					default: data.verification && data.verification.driver_verified ? 1 : 0,
				},
				{
					fieldtype: "Check",
					fieldname: "container_verified",
					label: __("Verify Container"),
					default: data.verification && data.verification.container_verified ? 1 : 0,
				},
				{
					fieldtype: "Small Text",
					fieldname: "remarks",
					label: __("Remarks"),
					default: data.verification && data.verification.remarks,
				},
			],
			primary_action_label: __("Save Verification"),
			primary_action: (values) => {
				if (!isVerifiable && !isVerified) {
					d.hide();
					return;
				}
				if (!values.truck_verified || !values.driver_verified || !values.container_verified) {
					frappe.msgprint(__("All three checks must pass to verify the SDDN."));
					return;
				}
				const checklistPayload = collectSecurityChecklist(d, checklistItems);
				const pending = checklistPayload
					.filter((row) => row.required && !row.completed)
					.map((row) => row.checklist_item);
				if (pending.length) {
					frappe.msgprint({
						title: __("Checklist Incomplete"),
						message:
							__("Tick all required checklist items before verifying.") +
							"<br><br>" +
							pending.map((p) => `• ${frappe.utils.escape_html(p)}`).join("<br>"),
						indicator: "orange",
					});
					return;
				}
				APCConsoleUI.callApi(
					"apc_operations.security.api.verify_security_delivery_draft_note",
					{
						name: data.sddn,
						checks: JSON.stringify(values),
						checklist: JSON.stringify(checklistPayload),
					}
				)
					.then(() => {
						frappe.show_alert({ message: __("SDDN verified"), indicator: "green" });
						d.hide();
						refresh && refresh();
					})
					.catch((err) => frappe.msgprint(err));
			},
		});

		if (data.sddn) {
			d.add_custom_action(
				__("Download SDDN"),
				() => {
					apcSecurityConsoleOpenPrintDownload(
						apcSecurityConsolePrintUrl(
							"Security Draft Delivery Note",
							data.sddn,
							APC_SECURITY_PRINT_FORMATS.SDDN
						)
					);
				},
				__("Documents")
			);
		}
		if (hasLdn && data.loading_delivery_note) {
			d.add_custom_action(
				__("Download LDN"),
				() => {
					apcSecurityConsoleOpenPrintDownload(
						apcSecurityConsolePrintUrl(
							"Loading Delivery Note",
							data.loading_delivery_note,
							APC_SECURITY_PRINT_FORMATS.LDN
						)
					);
				},
				__("Documents")
			);
		}

		// "Save Checklist" lets a user persist partial progress without verifying.
		if (checklistEditable) {
			d.add_custom_action(__("Save Checklist Only"), () => {
				const checklistPayload = collectSecurityChecklist(d, checklistItems);
				APCConsoleUI.callApi(
					"apc_operations.security.api.save_security_checklist",
					{ name: data.sddn, checklist: JSON.stringify(checklistPayload) }
				)
					.then(() => {
						frappe.show_alert({
							message: __("Checklist saved"),
							indicator: "green",
						});
					})
					.catch((err) => frappe.msgprint(err));
			});
		}

		// Hold + Reject custom actions
		if (isVerifiable || isVerified) {
			d.add_custom_action(__("Hold"), () => {
				frappe.prompt(
					[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
					(v) =>
						APCConsoleUI.callApi(
							"apc_operations.security.api.hold_security_delivery_draft_note",
							{ name: data.sddn, reason: v.reason }
						).then(() => {
							frappe.show_alert({ message: __("SDDN on hold"), indicator: "orange" });
							d.hide();
							refresh && refresh();
						}),
					__("Hold SDDN")
				);
			});
			d.add_custom_action(__("Reject"), () => {
				frappe.prompt(
					[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
					(v) =>
						APCConsoleUI.callApi(
							"apc_operations.security.api.reject_security_delivery_draft_note",
							{ name: data.sddn, reason: v.reason }
						).then(() => {
							frappe.show_alert({ message: __("SDDN rejected"), indicator: "red" });
							d.hide();
							refresh && refresh();
						}),
					__("Reject SDDN")
				);
			});
		}

		// Create LDN (only when verified and no LDN yet)
		if (isVerified && !hasLdn) {
			d.add_custom_action(__("Create Loading Delivery Note"), () => {
				apcSecurityCreateLoadingDn(data.sddn, refresh, () => d.hide());
			});
		}

		if (hasLdn && !data.qc_report_request) {
			const rawLdnStatus = (data.raw_ldn_delivery_note_status || "").trim();
			const inQcQueue = ["Pending QC", "Sent to QC"].indexOf(rawLdnStatus) !== -1;
			if (!inQcQueue) {
				d.add_custom_action(__("Queue for QC (New DO)"), () => {
					APCConsoleUI.callApi(
						"apc_operations.security.api.queue_loading_delivery_note_for_qc",
						{ ldn: data.loading_delivery_note }
					)
						.then(() => {
							frappe.msgprint({
								title: __("Queued for QC"),
								message: __(
									"LDN {0} will appear in QC Console → New Delivery Orders.",
									[data.loading_delivery_note]
								),
								indicator: "green",
							});
							d.hide();
							refresh && refresh();
						})
						.catch((err) => frappe.msgprint(err));
				});
			}
			d.add_custom_action(__("Send LDN to QC"), () => {
				apcSecurityPromptSendLdnToQc(data.loading_delivery_note, () => {
					d.hide();
					refresh && refresh();
				});
			});
		}

		if (data.security_inspection && data.transport_schedule) {
			if (existingGatePass) {
				d.add_custom_action(__("View Gate Pass"), () => {
					frappe.set_route("Form", "Gate Pass", existingGatePass);
				}, __("Gate Pass"));
			} else {
				d.add_custom_action(__("Create Gate Pass"), () => {
					frappe.confirm(
						__(
							"Create an outbound Gate Pass for this transport? Vehicle and driver must be set on the Transport Schedule or Security Inspection."
						),
						() => {
							APCConsoleUI.callApi(
								"apc_operations.security.api.create_gate_pass_for_security_console",
								{ security_inspection: data.security_inspection }
							)
								.then((res) => {
									if (res && res.success) {
										frappe.show_alert({
											message: __("Gate Pass {0} created", [res.gate_pass]),
											indicator: "green",
										});
										d.hide();
										refresh && refresh();
									}
								})
								.catch((err) => frappe.msgprint(err));
						}
					);
				}, __("Gate Pass"));
			}
		}

			d.show();
		});
	});
}

// ---------------------------------------------------------------------------
// Loading Bay Console (issue DN after QC approval)
// ---------------------------------------------------------------------------

function buildLoadingBayScreen() {
	return {
		title: __("Loading Bay Console"),
		render($root, router) {
			renderCardScreen($root, {
				listApi: "apc_operations.services.consoles.get_loading_bay_queue",
				searchPlaceholder: __("Search by DO / Truck / Driver / Product"),
				toCard: (row) => loadingBayItemToCard(row),
				onCardClick: (item) => openLoadingBayModal(item.raw, () => router.refresh()),
			});
		},
	};
}

function loadingBayItemToCard(row) {
	const badges = [
		APCConsoleUI.statusBadge(row.operational_status, row.operational_status_tone),
	];
	if (row.qc_cleared) {
		badges.push(APCConsoleUI.statusBadge(__("QC Cleared"), "success"));
	} else {
		badges.push(APCConsoleUI.statusBadge(__("Awaiting QC"), "warn"));
	}
	const qtyLabel = _formatQtyWithUom(row.quantity_to_load, row.uom);
	return {
		title: row.delivery_order,
		subtitle: row.customer_name || row.customer || "-",
		body_html: `
			<div class="apc-kv-label">${__("Truck")}</div>
			<div>${frappe.utils.escape_html(row.truck_number || "-")}</div>
			<div class="apc-kv-label">${__("Driver")}</div>
			<div>${frappe.utils.escape_html(row.driver_name || "-")} ${row.driver_contact ? "(" + frappe.utils.escape_html(row.driver_contact) + ")" : ""}</div>
			<div class="apc-kv-label">${__("Product")}</div>
			<div>${frappe.utils.escape_html(row.product || "-")}</div>
			<div class="apc-kv-label">${__("Qty to Load")}</div>
			<div>${frappe.utils.escape_html(qtyLabel)}</div>
			<div class="apc-kv-label">${__("LDN")}</div>
			<div>${frappe.utils.escape_html(row.loading_delivery_note || "-")}</div>
			<div class="apc-kv-label">${__("QC Report")}</div>
			<div>${frappe.utils.escape_html(row.qc_report_request || "-")} — ${frappe.utils.escape_html(row.qc_report_status || row.qc_status || "-")}</div>
			<div class="apc-kv-label">${__("Weights (G/T/N)")}</div>
			<div>${row.gross_weight || 0} / ${row.tare_weight || 0} / ${row.net_weight || 0}</div>
		`,
		badges,
		raw: row,
	};
}

function openLoadingBayModal(row, refresh) {
	const d = new frappe.ui.Dialog({
		title: `${__("Loading Bay")} — ${row.delivery_order}`,
		size: "large",
		fields: [
			{
				fieldname: "summary_html",
				fieldtype: "HTML",
				options: renderKvGrid(row, [
					["Delivery Order", row.delivery_order],
					["Customer", row.customer_name || row.customer],
					["Truck Number", row.truck_number || "—"],
					["Driver Name", row.driver_name || "—"],
					["Driver Number", row.driver_contact || "—"],
					["Product", row.product || "—"],
					["Qty to Load", _formatQtyWithUom(row.quantity_to_load, row.uom)],
					["Loading DN", row.loading_delivery_note || "—"],
					["QC Report", row.qc_report_request || "—"],
					["QC Report Status", row.qc_report_status || row.qc_status || "—"],
					["LDN QC Status", row.qc_status || "—"],
					["Gross Weight", row.gross_weight || "—"],
					["Tare Weight", row.tare_weight || "—"],
					["Net Weight", row.net_weight || "—"],
					["Variance", row.weight_variance_status || "—"],
					["Pipeline", row.operational_status || "—"],
				]),
			},
			{
				fieldname: "readiness_html",
				fieldtype: "HTML",
				options: `<div class="text-muted">${__("Loading dispatch checklist…")}</div>`,
			},
		],
		primary_action_label: __("Close"),
		primary_action: () => d.hide(),
	});

	d.show();

	const bindActionsOnce = () => {
		if (d._loadingBayActionsBound) {
			return;
		}
		d._loadingBayActionsBound = true;
		_bindLoadingBayActions(d, row, refresh, reloadReadiness);
	};

	const reloadReadiness = () => {
		return APCConsoleUI.callApi("apc_operations.security.api.get_dispatch_readiness", {
			delivery_order: row.delivery_order,
		}).then((readiness) => {
			row.dispatch_readiness = readiness;
			row.loading_delivery_note = readiness.loading_delivery_note || row.loading_delivery_note;
			row.can_issue_dn = readiness.can_issue_dn;
			d.fields_dict.readiness_html.$wrapper.html(_renderDispatchReadiness(readiness));
			bindActionsOnce();
		});
	};

	reloadReadiness();
}

function _renderDispatchReadiness(readiness) {
	const steps = readiness.steps || [];
	if (!steps.length) {
		return `<div class="alert alert-warning">${__("No Loading DN linked to this Delivery Order.")}</div>`;
	}
	let html = `<div class="apc-dispatch-checklist"><h6>${__("Dispatch Checklist")}</h6><ul class="list-unstyled">`;
	steps.forEach((s) => {
		const icon = s.done ? "✓" : "○";
		const cls = s.done ? "text-success" : "text-danger";
		const detail = s.detail ? ` <small class="text-muted">(${frappe.utils.escape_html(s.detail)})</small>` : "";
		html += `<li class="${cls}">${icon} ${frappe.utils.escape_html(s.label)}${detail}</li>`;
	});
	html += "</ul></div>";
	if ((readiness.blocking || []).length) {
		html += `<div class="alert alert-warning"><strong>${__("Blocking")}:</strong> ${frappe.utils.escape_html(
			readiness.blocking.join("; ")
		)}</div>`;
	}
	return html;
}

function _bindLoadingBayActions(d, row, refresh, reloadReadiness) {
	const addAction = (label, handler, group) => {
		d.add_custom_action(label, handler, group || __("Workflow"));
	};

	if (row.qc_report_request) {
		addAction(__("Open QC Report"), () => {
			frappe.set_route("Form", "QC Report Request", row.qc_report_request);
		}, __("Links"));
	}
	if (row.loading_delivery_note) {
		addAction(__("Open LDN"), () => {
			frappe.set_route("Form", "Loading Delivery Note", row.loading_delivery_note);
		}, __("Links"));
	}

	addAction(__("Sync Batch & COA from QC"), () => {
		APCConsoleUI.callApi("apc_operations.security.api.sync_ldn_dispatch_prep", {
			delivery_order: row.delivery_order,
		}).then(() => {
			frappe.show_alert({ message: __("Batch and COA synced from QC"), indicator: "green" });
			reloadReadiness().then(() => refresh && refresh());
		});
	});

	addAction(__("Complete Loading"), () => {
		frappe.prompt(
			[
				{
					fieldname: "loaded_quantity",
					fieldtype: "Float",
					label: __("Loaded Quantity"),
					reqd: 1,
					default: row.quantity_to_load || 0,
				},
			],
			(values) => {
				APCConsoleUI.callApi("apc_operations.security.api.complete_loading", {
					delivery_order: row.delivery_order,
					loaded_quantity: values.loaded_quantity,
				}).then(() => {
					frappe.show_alert({ message: __("Loading completed"), indicator: "green" });
					reloadReadiness().then(() => refresh && refresh());
				});
			},
			__("Complete Loading"),
			__("Save")
		);
	});

	addAction(__("Record Tare Weight"), () => {
		frappe.prompt(
			[
				{
					fieldname: "tare_weight",
					fieldtype: "Float",
					label: __("Tare Weight (KG)"),
					reqd: 1,
					default: row.tare_weight || 0,
				},
			],
			(values) => {
				APCConsoleUI.callApi("apc_operations.security.api.record_tare_weight", {
					delivery_order: row.delivery_order,
					tare_weight: values.tare_weight,
				}).then(() => {
					frappe.show_alert({ message: __("Tare weight recorded"), indicator: "green" });
					reloadReadiness().then(() => refresh && refresh());
				});
			},
			__("Tare Weight"),
			__("Save")
		);
	});

	addAction(__("Record Gross Weight"), () => {
		frappe.prompt(
			[
				{
					fieldname: "gross_weight",
					fieldtype: "Float",
					label: __("Gross Weight (KG)"),
					reqd: 1,
					default: row.gross_weight || 0,
				},
			],
			(values) => {
				APCConsoleUI.callApi("apc_operations.security.api.record_gross_weight", {
					delivery_order: row.delivery_order,
					gross_weight: values.gross_weight,
				}).then(() => {
					frappe.show_alert({ message: __("Gross weight recorded"), indicator: "green" });
					reloadReadiness().then(() => refresh && refresh());
				});
			},
			__("Gross Weight"),
			__("Save")
		);
	});

	addAction(__("Issue Delivery Note"), () => {
		frappe.confirm(
			__(
				"Issue Loading Delivery Note and confirm dispatch for {0}? All checklist items must be complete.",
				[row.delivery_order]
			),
			() => {
				APCConsoleUI.callApi("apc_operations.services.consoles.issue_loading_dn", {
					delivery_order: row.delivery_order,
				})
					.then(() => {
						frappe.show_alert({
							message: __("Delivery Note issued"),
							indicator: "green",
						});
						d.hide();
						refresh && refresh();
					})
					.catch((err) => frappe.msgprint(err));
			}
		);
	}, __("Actions"));
}

// ---------------------------------------------------------------------------
// Gate In / Gate Out
// ---------------------------------------------------------------------------

function buildGatePassScreen() {
	return {
		title: __("Gate In / Gate Out"),
		render($root, router) {
			renderCardScreen($root, {
				listApi: "apc_operations.security.api.get_gate_pass_queue",
				searchPlaceholder: __("Search by Gate Pass / Truck / Driver"),
				toCard: (gp) => ({
					title: gp.gate_pass,
					subtitle: gp.customer_name || gp.customer || "-",
					body_html: `
						<div class="apc-kv-label">${__("Type")}</div>
						<div>${frappe.utils.escape_html(gp.gate_pass_type || "-")}</div>
						<div class="apc-kv-label">${__("Truck")}</div>
						<div>${frappe.utils.escape_html(gp.vehicle_no || "-")}</div>
						<div class="apc-kv-label">${__("Driver")}</div>
						<div>${frappe.utils.escape_html(gp.driver_name || "-")}</div>
					`,
					badges: [APCConsoleUI.statusBadge(gp.status, gp.status_tone)],
					raw: gp,
				}),
				onCardClick: (item) => openGatePassModal(item.raw, () => router.refresh()),
			});
		},
	};
}

function openGatePassModal(gp, refresh) {
	APCConsoleUI.callApi("apc_operations.security.api.get_gate_pass_detail", { name: gp.gate_pass }).then(
		(data) => {
			const d = new frappe.ui.Dialog({
				title: `${__("Gate Pass")} — ${data.gate_pass}`,
				size: "large",
				fields: [
					{
						fieldtype: "HTML",
						options: renderKvGrid(data, [
							["Type", data.gate_pass_type],
							["Date", data.posting_date],
							["Vehicle", data.vehicle_no],
							["Driver", data.driver_name],
							["Driver Phone", data.driver_phone],
							["Customer", data.customer_name || data.customer],
							["Delivery Order", data.delivery_order],
							["BOL", data.bill_of_lading],
							["Status", data.status],
						]),
					},
				],
				primary_action_label: __("Close"),
				primary_action: () => d.hide(),
			});
			d.add_custom_action(__("Edit"), () => {
				frappe.set_route("Form", "Gate Pass", data.gate_pass);
			});
			d.add_custom_action(__("Mark Gate In"), () =>
				APCConsoleUI.callApi("apc_operations.security.api.mark_gate_in", { gate_pass: data.gate_pass })
					.then(() => {
						frappe.show_alert({ message: __("Gate In recorded"), indicator: "green" });
						d.hide();
						refresh && refresh();
					})
					.catch((err) => frappe.msgprint(err))
			);
			d.add_custom_action(__("Mark Gate Out"), () =>
				APCConsoleUI.callApi("apc_operations.security.api.mark_gate_out", { gate_pass: data.gate_pass })
					.then(() => {
						frappe.show_alert({ message: __("Gate Out recorded"), indicator: "green" });
						d.hide();
						refresh && refresh();
					})
					.catch((err) => frappe.msgprint(err))
			);
			d.show();
		}
	);
}

// ---------------------------------------------------------------------------
// Completed Delivery Notes (issued LDNs)
// ---------------------------------------------------------------------------

function buildCompletedDeliveryNotesScreen() {
	return {
		title: __("Completed Delivery Notes"),
		render($root, router) {
			renderCardScreen($root, {
				listApi: "apc_operations.security.api.get_completed_delivery_notes",
				searchPlaceholder: __("Search by LDN / DO / JO / Customer / Truck"),
				toCard: (row) => {
					const badges = [
						APCConsoleUI.statusBadge(row.ldn_status, row.ldn_status_tone),
						APCConsoleUI.statusBadge(row.coa_status, row.coa_status_tone),
					];
					if (row.delivery_order) {
						badges.push(APCConsoleUI.statusBadge(row.delivery_order, "info"));
					}
					return {
						title: row.loading_delivery_note,
						subtitle: row.customer_name || row.customer || "-",
						body_html: `
							<div class="apc-kv-label">${__("Delivery Order")}</div>
							<div>${frappe.utils.escape_html(row.delivery_order || "—")}</div>
							<div class="apc-kv-label">${__("Job Order")}</div>
							<div>${frappe.utils.escape_html(row.job_order_number || row.job_order || "—")}</div>
							<div class="apc-kv-label">${__("Truck / Driver")}</div>
							<div>${frappe.utils.escape_html(row.truck_number || "—")} — ${frappe.utils.escape_html(row.driver_name || "—")}</div>
							<div class="apc-kv-label">${__("Product / Net Weight")}</div>
							<div>${frappe.utils.escape_html(row.product || "—")} · ${frappe.utils.escape_html(String(row.net_weight || row.quantity || "—"))} ${frappe.utils.escape_html(row.uom || "KG")}</div>
							<div class="apc-kv-label">${__("Issued On")}</div>
							<div>${frappe.utils.escape_html(row.dispatch_confirmed_on || row.loading_end_time || "—")}</div>
						`,
						badges,
						raw: row,
					};
				},
				onCardClick: (item) => openCompletedLdnModal(item.raw, () => router.refresh()),
			});
		},
	};
}

function openCompletedLdnModal(row, refresh) {
	const d = new frappe.ui.Dialog({
		title: `${__("Delivery Note")} — ${row.loading_delivery_note}`,
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				options: renderKvGrid(row, [
					["Loading DN", row.loading_delivery_note],
					["Delivery Order", row.delivery_order || "—"],
					["SDDN", row.sddn || "—"],
					["Job Order", row.job_order_number || row.job_order || "—"],
					["Customer", row.customer_name || row.customer || "—"],
					["Truck", row.truck_number || "—"],
					["Driver", row.driver_name || "—"],
					["Driver Phone", row.driver_contact || "—"],
					["Product", row.product || "—"],
					["Loaded Qty", _formatQtyWithUom(row.quantity, row.uom)],
					["Net Weight", row.net_weight || "—"],
					["Gross / Tare", `${row.gross_weight || "—"} / ${row.tare_weight || "—"}`],
					["Status", row.ldn_status || "—"],
					["Issued On", row.dispatch_confirmed_on || "—"],
					["Issued By", row.dispatch_confirmed_by || "—"],
					["QC Report", row.qc_report_request || "—"],
				]),
			},
		],
		primary_action_label: __("Close"),
		primary_action: () => d.hide(),
	});

	d.add_custom_action(
		__("Print Delivery Note"),
		() => {
			apcSecurityConsoleOpenPrintDownload(
				apcSecurityConsolePrintUrl(
					"Loading Delivery Note",
					row.loading_delivery_note,
					APC_SECURITY_PRINT_FORMATS.LDN
				)
			);
		},
		__("Documents")
	);

	d.add_custom_action(__("Open LDN Form"), () => {
		frappe.set_route("Form", "Loading Delivery Note", row.loading_delivery_note);
	});

	if (row.delivery_order) {
		d.add_custom_action(__("Open Delivery Order"), () => {
			frappe.set_route("Form", "Delivery Order", row.delivery_order);
		});
	}
	if (row.sddn) {
		d.add_custom_action(
			__("Print SDDN"),
			() => {
				apcSecurityConsoleOpenPrintDownload(
					apcSecurityConsolePrintUrl(
						"Security Draft Delivery Note",
						row.sddn,
						APC_SECURITY_PRINT_FORMATS.SDDN
					)
				);
			},
			__("Documents")
		);
	}

	d.show();
}

// ---------------------------------------------------------------------------
// Loading DN queue
// ---------------------------------------------------------------------------

function buildLdnQueueScreen() {
	return {
		title: __("Loading Delivery Notes"),
		render($root, router) {
			renderCardScreen($root, {
				listApi: "apc_operations.security.api.get_loading_dn_queue",
				searchPlaceholder: __("Search by LDN / SDDN / JO / Customer"),
				toCard: (ldn) => ({
					title: ldn.loading_delivery_note,
					subtitle: ldn.customer || ldn.job_order_number || ldn.job_order || "-",
					body_html: `
						<div class="apc-kv-label">${__("SDDN")}</div>
						<div>${frappe.utils.escape_html(ldn.sddn || "-")}</div>
						<div class="apc-kv-label">${__("JO")}</div>
						<div>${frappe.utils.escape_html(ldn.job_order_number || ldn.job_order || "-")}</div>
					`,
					badges: [
						APCConsoleUI.statusBadge(ldn.qc_status, ldn.qc_status_tone),
						APCConsoleUI.statusBadge(ldn.coa_status, ldn.coa_status_tone),
						APCConsoleUI.statusBadge(ldn.ldn_status, ldn.ldn_status_tone),
					],
					raw: ldn,
				}),
				onCardClick: (item) => openLdnModal(item.raw, () => router.refresh()),
			});
		},
	};
}

function openLdnModal(ldn, refresh) {
	APCConsoleUI.callApi("apc_operations.security.api.get_loading_dn_detail", {
		name: ldn.loading_delivery_note,
	}).then((data) => {
		const tsName = data.transportation_request;
		const gateFetch = tsName
			? frappe.db.get_value("Transport Schedule", tsName, "gate_pass")
			: Promise.resolve({ message: {} });

		gateFetch.then((gpRow) => {
			const existingGatePass = gpRow.message && gpRow.message.gate_pass;

			const headerPairs = [
				["LDN", data.loading_delivery_note],
				["SDDN", data.sddn],
				[
					__("Job order number"),
					data.job_order_number || data.job_order || "—",
				],
				["Customer", data.customer_name || data.customer],
				["Container", data.container_number],
				["Truck", data.vehicle_number],
				["Driver", data.driver_name],
				["Product", data.product],
				["Batch", data.batch_number],
				["Quantity", `${data.quantity || "-"} ${data.uom || ""}`.trim()],
				["QC Status", data.qc_status],
				["COA Status", data.coa_status],
				["Dispatch Status", data.ldn_status],
			];
			if (existingGatePass) {
				headerPairs.push(["Gate Pass", existingGatePass]);
			}

			const d = new frappe.ui.Dialog({
				title: `${__("Loading DN")} — ${data.loading_delivery_note}`,
				size: "large",
				fields: [
					{
						fieldtype: "HTML",
						options: renderKvGrid(data, headerPairs),
					},
				],
				primary_action_label: __("Close"),
				primary_action: () => d.hide(),
			});

			d.add_custom_action(__("Send to QC"), () => {
				APCConsoleUI.callApi("apc_operations.security.api.send_loading_delivery_note_to_qc", {
					ldn: data.loading_delivery_note,
				})
					.then(() => {
						frappe.show_alert({ message: __("Sent to QC"), indicator: "green" });
						d.hide();
						refresh && refresh();
					})
					.catch((err) => frappe.msgprint(err));
			});

			d.add_custom_action(
				__("Download LDN"),
				() => {
					apcSecurityConsoleOpenPrintDownload(
						apcSecurityConsolePrintUrl(
							"Loading Delivery Note",
							data.loading_delivery_note,
							APC_SECURITY_PRINT_FORMATS.LDN
						)
					);
				},
				__("Documents")
			);
			if (data.sddn) {
				d.add_custom_action(
					__("Download SDDN"),
					() => {
						apcSecurityConsoleOpenPrintDownload(
							apcSecurityConsolePrintUrl(
								"Security Draft Delivery Note",
								data.sddn,
								APC_SECURITY_PRINT_FORMATS.SDDN
							)
						);
					},
					__("Documents")
				);
			}

			if (data.security_inspection && tsName) {
				if (existingGatePass) {
					d.add_custom_action(__("View Gate Pass"), () => {
						frappe.set_route("Form", "Gate Pass", existingGatePass);
					}, __("Gate Pass"));
				} else {
					d.add_custom_action(__("Create Gate Pass"), () => {
						frappe.confirm(
							__(
								"Create an outbound Gate Pass for this transport? Vehicle and driver must be set on the Transport Schedule or Security Inspection."
							),
							() => {
								APCConsoleUI.callApi(
									"apc_operations.security.api.create_gate_pass_for_security_console",
									{ security_inspection: data.security_inspection }
								)
									.then((res) => {
										if (res && res.success) {
											frappe.show_alert({
												message: __("Gate Pass {0} created", [res.gate_pass]),
												indicator: "green",
											});
											d.hide();
											refresh && refresh();
										}
									})
									.catch((err) => frappe.msgprint(err));
							}
						);
					}, __("Gate Pass"));
				}
			}

			d.show();
		});
	});
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

/** Print format names — match ``Print Format`` on SDDN / LDN DocTypes. */
const APC_SECURITY_PRINT_FORMATS = {
	LDN: "Standard Loading Delivery Note",
	SDDN: "Draft Delivery Note",
};

function apcSecurityConsolePrintUrl(doctype, name, format) {
	const lang = (frappe.boot && frappe.boot.lang) || "en";
	return `/printview?doctype=${encodeURIComponent(doctype)}&name=${encodeURIComponent(
		name
	)}&format=${encodeURIComponent(format)}&no_letterhead=0&_lang=${encodeURIComponent(lang)}`;
}

function apcSecurityConsoleOpenPrintDownload(url) {
	window.open(url, "_blank", "noopener,noreferrer");
}

function renderCardScreen($root, options) {
	return APCConsoleUI.renderCardScreen($root, options);
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

// ---------------------------------------------------------------------------
// Security checklist — editable grid embedded inside the SDDN dialog
// ---------------------------------------------------------------------------

function renderSecurityChecklist(items, editable) {
	return frappe.apc.renderSecurityChecklist(items, editable);
}

function collectSecurityChecklist(dialog, fallback) {
	return frappe.apc.collectSecurityChecklist(dialog, fallback);
}
