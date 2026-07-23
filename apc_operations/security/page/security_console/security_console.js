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

			APCConsoleUI.hubButtons($root, [
				{
					label: __("New Delivery Orders"),
					subtitle: __("DO created — awaiting security draft"),
					onClick: () =>
						router.push(
							buildDoQueueScreen(
								__("New Delivery Orders"),
								"apc_operations.security.api.get_security_new_dos"
							)
						),
				},
				{
					label: __("Pending Delivery Orders"),
					subtitle: __("SDDN verification in progress"),
					onClick: () =>
						router.push(
							buildDoQueueScreen(
								__("Pending Delivery Orders"),
								"apc_operations.security.api.get_security_pending_dos"
							)
						),
				},
				{
					label: __("In Progress Delivery Orders"),
					subtitle: __("Verified — loading / QC handoff"),
					onClick: () =>
						router.push(
							buildDoQueueScreen(
								__("In Progress Delivery Orders"),
								"apc_operations.security.api.get_security_in_progress_dos"
							)
						),
				},
				{
					label: __("Completed Delivery Orders"),
					subtitle: __("Handed off to QC or closed"),
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
					label: __("Gate In / Gate Out"),
					subtitle: __("Active gate movements"),
					onClick: () => router.push(buildGatePassScreen()),
				},
				{
					label: __("Draft Notes (SDDN)"),
					subtitle: __("Legacy SDDN lists"),
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

function doItemToCard(item) {
	const jo = frappe.utils.escape_html(item.job_order_number || item.job_order || "-");
	const badges = [
		APCConsoleUI.statusBadge(item.operational_status, item.operational_status_tone),
	];
	if (item.sddn_status) {
		badges.push(APCConsoleUI.statusBadge(item.sddn_status, item.sddn_status_tone));
	}
	if (item.ldn_status && item.ldn) {
		badges.push(APCConsoleUI.statusBadge(item.ldn_status, item.ldn_status_tone));
	}
	return {
		title: item.delivery_order || item.name,
		subtitle: item.customer_name || item.customer || "-",
		body_html: `
			<div class="apc-kv-label">${__("Job Order")}</div>
			<div>${jo}</div>
			<div class="apc-kv-label">${__("SDDN")}</div>
			<div>${frappe.utils.escape_html(item.sddn || "-")}</div>
			<div class="apc-kv-label">${__("LDN")}</div>
			<div>${frappe.utils.escape_html(item.ldn || item.loading_delivery_note || "-")}</div>
		`,
		badges,
		raw: item,
	};
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
					options: renderKvGrid(data, [
						["Delivery Order", data.delivery_order],
						["Job Order", data.job_order_number || data.job_order],
						["Customer", data.customer_name || data.customer],
						["Incoterm", data.terms_of_delivery || "—"],
						["Status", data.do_shipping_status_label || data.status],
						["Pipeline", data.operational_status || "—"],
						["SDDN", data.sddn || "—"],
						["SDDN Status", data.sddn_status || "—"],
						["LDN", data.loading_delivery_note || "—"],
						["LDN Status", data.ldn_status || "—"],
					]),
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
		if (data.loading_delivery_note) {
			d.add_custom_action(__("Open LDN"), () => {
				frappe.set_route("Form", "Loading Delivery Note", data.loading_delivery_note);
			});
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
					subtitle: sddn.customer || sddn.job_order_number || sddn.job_order || "-",
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
					subtitle: sddn.customer || sddn.job_order_number || sddn.job_order || "-",
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
				["Customer", data.customer],
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
				APCConsoleUI.callApi(
					"apc_operations.security.api.create_loading_delivery_note",
					{ sddn: data.sddn }
				)
					.then((res) => {
						frappe.show_alert({
							message: __("LDN created: {0}", [res && res.loading_delivery_note]),
							indicator: "green",
						});
						d.hide();
						refresh && refresh();
					})
					.catch((err) => frappe.msgprint(err));
			});
		}

		if (hasLdn) {
			d.add_custom_action(__("Send LDN to QC"), () => {
				APCConsoleUI.callApi(
					"apc_operations.security.api.send_loading_delivery_note_to_qc",
					{ ldn: data.loading_delivery_note }
				)
					.then(() => {
						frappe.show_alert({ message: __("LDN sent to QC"), indicator: "green" });
						d.hide();
						refresh && refresh();
					})
					.catch((err) => frappe.msgprint(err));
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

// ---------------------------------------------------------------------------
// Security checklist — editable grid embedded inside the SDDN dialog
// ---------------------------------------------------------------------------

function renderSecurityChecklist(items, editable) {
	if (!items || !items.length) {
		return `<div class="apc-empty-block">${frappe.utils.escape_html(
			__("No checklist items configured.")
		)}</div>`;
	}
	const safe = (v) => (v === null || v === undefined ? "" : frappe.utils.escape_html(String(v)));
	const disabledAttr = editable ? "" : "disabled";
	const readonlyAttr = editable ? "" : "readonly";

	const rows = items
		.map((item, idx) => {
			const completed = item.completed ? "checked" : "";
			const requiredPill = item.required
				? `<span class="apc-checklist-required">${__("Required")}</span>`
				: "";
			return `
				<tr data-checklist-idx="${idx}"
				    data-checklist-name="${safe(item.name || "")}"
				    data-checklist-required="${item.required ? 1 : 0}"
				    data-checklist-item="${safe(item.checklist_item || "")}">
					<td class="apc-checklist-label">
						<div class="apc-checklist-item-text">${safe(item.checklist_item || "")}</div>
						${requiredPill}
					</td>
					<td class="apc-checklist-completed-cell">
						<input type="checkbox" class="apc-checklist-completed" ${completed} ${disabledAttr}>
					</td>
					<td class="apc-checklist-remarks-cell">
						<input type="text"
						       class="apc-checklist-remarks form-control input-xs"
						       value="${safe(item.remarks || "")}"
						       placeholder="${__("Remarks (optional)")}"
						       ${readonlyAttr}>
					</td>
				</tr>
			`;
		})
		.join("");

	return `
		<div class="apc-checklist-wrapper">
			<table class="apc-checklist-table">
				<thead>
					<tr>
						<th>${__("Checklist Item")}</th>
						<th class="apc-checklist-completed-cell">${__("Done")}</th>
						<th class="apc-checklist-remarks-cell">${__("Remarks")}</th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>
		</div>
	`;
}

function collectSecurityChecklist(dialog, fallback) {
	const $root = dialog.$wrapper.find(".apc-checklist-table tbody tr[data-checklist-idx]");
	if (!$root.length) {
		return Array.isArray(fallback) ? fallback : [];
	}
	const out = [];
	$root.each(function () {
		const $tr = $(this);
		const idx = parseInt($tr.attr("data-checklist-idx"), 10);
		const original = (fallback && fallback[idx]) || {};
		out.push({
			name: $tr.attr("data-checklist-name") || original.name || null,
			checklist_item: $tr.attr("data-checklist-item") || original.checklist_item || "",
			required: parseInt($tr.attr("data-checklist-required"), 10) || 0,
			completed: $tr.find(".apc-checklist-completed").is(":checked") ? 1 : 0,
			remarks: $tr.find(".apc-checklist-remarks").val() || "",
		});
	});
	return out;
}
