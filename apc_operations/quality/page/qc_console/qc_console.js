/* QC Console — APC Operations
 *
 * Hub -> {New DO, Pending DO, Completed DO, Rejected DO}
 *   -> card queues (Delivery Order title, LDN/QC detail on drill-down)
 *   -> QC entry modal with Approve / Reject / Generate COA / Upload COA.
 */

frappe.pages["qc-console"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Quality Control"),
		single_column: true,
	});

	const router = new APCConsoleRouter(page, { rootClass: "apc-console apc-console-qc" });
	router.reset(buildQcHubScreen(router));
};

function buildQcHubScreen(router) {
	return {
		title: __("QC"),
		render($root) {
			const $bannerHolder = $('<div class="apc-pending-holder"></div>').appendTo($root);
			APCConsoleUI.callApi("apc_operations.quality.api.get_qc_console_counts")
				.then((counts) => {
					APCConsoleUI.pendingBanner(
						$bannerHolder,
						{
							transport: counts.new || 0,
							do: counts.pending || 0,
							sddn: counts.completed || 0,
						},
						(filterId) => {
							if (filterId === "transport") {
								router.push(buildQcScreen("new"));
							} else if (filterId === "do") {
								router.push(buildQcScreen("pending"));
							} else if (filterId === "sddn") {
								router.push(buildQcScreen("completed"));
							}
						}
					);
					$bannerHolder.find(".apc-pending-tile").eq(0).find(".apc-pending-tile-label").text(__("New DO"));
					$bannerHolder.find(".apc-pending-tile").eq(1).find(".apc-pending-tile-label").text(__("Pending DO"));
					$bannerHolder.find(".apc-pending-tile").eq(2).find(".apc-pending-tile-label").text(__("Completed"));
				})
				.catch(() => {});

			APCConsoleUI.hubButtons($root, [
				{
					label: __("New Delivery Orders"),
					subtitle: __("Sent to QC — QC not started"),
					onClick: () => router.push(buildQcScreen("new")),
				},
				{
					label: __("Pending Delivery Orders"),
					subtitle: __("QC in progress"),
					onClick: () => router.push(buildQcScreen("pending")),
				},
				{
					label: __("Completed Delivery Orders"),
					subtitle: __("QC cleared"),
					onClick: () => router.push(buildQcScreen("completed")),
				},
				{
					label: __("Rejected Delivery Orders"),
					subtitle: __("QC rejected"),
					onClick: () => router.push(buildQcScreen("rejected")),
				},
			]);
		},
	};
}

const QC_SCREEN_DEFS = {
	new: {
		title: () => __("New Delivery Orders"),
		api: "apc_operations.quality.api.get_new_dos_without_qc",
	},
	pending: {
		title: () => __("Pending Delivery Orders"),
		api: "apc_operations.quality.api.get_pending_qc_dos",
	},
	completed: {
		title: () => __("Completed Delivery Orders"),
		api: "apc_operations.quality.api.get_completed_qc_dos",
	},
	rejected: {
		title: () => __("Rejected Delivery Orders"),
		api: "apc_operations.quality.api.get_rejected_qc_dos",
	},
};

/** Print format names — match ``Print Format`` records in Shipping / Security modules. */
const QC_PRINT_FORMATS = {
	LDN: "Standard Loading Delivery Note",
	SDDN: "Draft Delivery Note",
};

function qcPrintUrl(doctype, name, format) {
	const lang = (frappe.boot && frappe.boot.lang) || "en";
	return `/printview?doctype=${encodeURIComponent(doctype)}&name=${encodeURIComponent(
		name
	)}&format=${encodeURIComponent(format)}&no_letterhead=0&_lang=${encodeURIComponent(lang)}`;
}

function qcFileHref(url) {
	if (!url) return "";
	if (/^https?:\/\//i.test(url)) return url;
	return url.startsWith("/") ? url : `/${url}`;
}

function qcCoaLinksHtml(coaName, coaPdf) {
	if (!coaName) {
		return `<span>—</span>`;
	}
	const esc = frappe.utils.escape_html;
	let html = `<a href="/app/apc-coa/${esc(coaName)}" target="_blank" rel="noopener">${esc(
		coaName
	)}</a>`;
	if (coaPdf) {
		html += ` · <a href="${esc(qcFileHref(coaPdf))}" target="_blank" rel="noopener">${__(
			"PDF"
		)}</a>`;
	}
	return html;
}

function qcCardDocLinksHtml(item) {
	const ldn = item.ldn || item.loading_delivery_note;
	if (!ldn) return "";
	const ldnHref = escAttr(qcPrintUrl("Loading Delivery Note", ldn, QC_PRINT_FORMATS.LDN));
	const ldnFormHref = escAttr(`/app/loading-delivery-note/${encodeURIComponent(ldn)}`);
	let html = `<div class="apc-qc-card-docs" style="margin-top:10px;padding-top:8px;border-top:1px solid var(--border-color);font-size:12px;">`;
	html += `<a href="${ldnFormHref}">${__("Open LDN")}</a>`;
	html += ` · <a href="${ldnHref}" target="_blank" rel="noopener">${__("Print LDN")}</a>`;
	const sddn = item.sddn;
	if (sddn) {
		const sddnHref = escAttr(
			qcPrintUrl("Security Draft Delivery Note", sddn, QC_PRINT_FORMATS.SDDN)
		);
		html += ` · <a href="${sddnHref}" target="_blank" rel="noopener">${__("Print SDDN")}</a>`;
	}
	html += `</div>`;
	return html;
}

function qcPromptAfterLdnCreated(ldnName, refresh, onDialogHide) {
	frappe.confirm(
		__("Loading Delivery Note {0} was created. Send to QC now?", [ldnName]),
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

function qcCreateLoadingDn(sddn, refresh, onDialogHide) {
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
					qcPromptAfterLdnCreated(ldn, refresh, onDialogHide);
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

function escAttr(s) {
	return frappe.utils.escape_html(String(s || ""));
}

function buildQcScreen(kind) {
	const def = QC_SCREEN_DEFS[kind];
	return {
		title: def.title(),
		render($root, router) {
			renderCardScreen($root, {
				listApi: def.api,
				searchPlaceholder: __("Search by DO / LDN / JO / Batch / Customer"),
				toCard: (item) => {
					const jo =
						item.job_order_number ||
						item.job_order ||
						(null);
					const subtitle =
						item.customer_name || item.customer || jo || "-";
					const joLine = frappe.utils.escape_html(jo || "-");
					const doTitle =
						item.delivery_order || item.ldn || item.loading_delivery_note;
					const coaBlock = `
						<div class="apc-kv-label">${__("COA")}</div>
						<div>${qcCoaLinksHtml(item.coa, item.coa_pdf)}</div>`;
					return {
						title: doTitle,
						subtitle,
						body_html: `
						<div class="apc-kv-label">${__("Loading DN")}</div>
						<div>${frappe.utils.escape_html(item.ldn || item.loading_delivery_note || "-")}</div>
						<div class="apc-kv-label">${__("Job Order")}</div>
						<div>${joLine}</div>
						<div class="apc-kv-label">${__("SDDN")}</div>
						<div>${frappe.utils.escape_html(item.sddn || "-")}</div>
						<div class="apc-kv-label">${__("Product")}</div>
						<div>${frappe.utils.escape_html(item.product || "-")}</div>
						<div class="apc-kv-label">${__("Batch")}</div>
						<div>${frappe.utils.escape_html(item.batch_number || "-")}</div>
						${coaBlock}
						${qcCardDocLinksHtml(item)}
					`,
						badges: [
							APCConsoleUI.statusBadge(item.qc_status, item.qc_status_tone),
							APCConsoleUI.statusBadge(item.coa_status, item.coa_status_tone),
						],
						raw: item,
					};
				},
				onCardClick: (item) =>
					openQcModal(item.raw, kind, () => router.refresh()),
			});
		},
	};
}

function qcDefaultCoaFromDetail(data) {
	const batches = data.batches || [];
	const primary = data.primary_batch;
	if (primary) {
		for (const b of batches) {
			if (b.batch === primary && b.coa) return b.coa;
		}
	}
	for (const b of batches) {
		if (b.coa) return b.coa;
	}
	return data.coa || "";
}

function openQcModal(item, kind, refresh) {
	const doName = item.delivery_order || item.name;
	const ldn = item.ldn || item.loading_delivery_note;

	if (doName && (!ldn || kind === "new")) {
		APCConsoleUI.callApi("apc_operations.quality.api.get_qc_do_detail", {
			delivery_order: doName,
		}).then((data) => {
			openQcDoDetailModal(data, kind, refresh);
		});
		return;
	}

	APCConsoleUI.callApi("apc_operations.quality.api.get_qc_item_detail", {
		loading_delivery_note: ldn,
	}).then((data) => {
		openQcLdnModal(data, item, kind, refresh);
	});
}

function openQcDoDetailModal(data, kind, refresh) {
	const doName = data.delivery_order || data.name;
	const readOnly = kind === "completed" || kind === "rejected" || data.read_only;
	const pcc = data.pcc_form || {};
	const verification = data.verification || {};
	const checklistItems = Array.isArray(data.checklist_items) ? data.checklist_items : [];
	const checklistEditable = !readOnly && data.can_verify_sddn;

	const kvRows = [
		["Delivery Order", doName],
		["Operation", data.commercial_movement || "Export"],
		["Job Order", data.job_order_number || data.job_order],
		["Customer", data.customer_name || data.customer],
		["Incoterm", data.terms_of_delivery || "—"],
		["Pipeline", data.operational_status || "—"],
		["SDDN", data.sddn || "—"],
		["SDDN Status", data.sddn_status || "—"],
		["Truck", data.sddn_truck_number || data.truck_number || "—"],
		["Driver", data.sddn_driver_name || data.driver_name || "—"],
		["Container", data.sddn_container_number || "—"],
		["Origin / Pickup", data.sddn_pickup_location || "—"],
		["Destination", data.sddn_destination || "—"],
	];

	const d = new frappe.ui.Dialog({
		title: `${__("QC & Security Review")} — ${doName}`,
		size: "extra-large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "summary_html",
				options: renderKvGrid(data, kvRows),
			},
			{ fieldtype: "Section Break", label: __("Security checklist (SDDN)") },
			{
				fieldtype: "HTML",
				fieldname: "checklist_html",
				options: frappe.apc.renderSecurityChecklist(checklistItems, checklistEditable),
			},
			{ fieldtype: "Section Break", label: __("Security verification") },
			{
				fieldtype: "Check",
				fieldname: "truck_verified",
				label: __("Verify Truck"),
				default: verification.truck_verified ? 1 : 0,
				read_only: checklistEditable ? 0 : 1,
			},
			{
				fieldtype: "Check",
				fieldname: "driver_verified",
				label: __("Verify Driver"),
				default: verification.driver_verified ? 1 : 0,
				read_only: checklistEditable ? 0 : 1,
			},
			{
				fieldtype: "Check",
				fieldname: "container_verified",
				label: __("Verify Container"),
				default: verification.container_verified ? 1 : 0,
				read_only: checklistEditable ? 0 : 1,
			},
			{
				fieldtype: "Small Text",
				fieldname: "security_remarks",
				label: __("Security Remarks"),
				default: verification.remarks || "",
				read_only: checklistEditable ? 0 : 1,
			},
			{ fieldtype: "Section Break", label: __("QC pre-check") },
			{
				fieldtype: "Check",
				fieldname: "product_confirmed",
				label: __("Product Confirmed"),
				default: pcc.product_confirmed ? 1 : 0,
				read_only: readOnly ? 1 : 0,
			},
			{
				fieldtype: "Link",
				fieldname: "batch_no",
				label: __("Batch"),
				options: "APC Batch",
				default: pcc.batch_no || data.pcc_batch_no,
				read_only: readOnly ? 1 : 0,
			},
			{
				fieldtype: "Select",
				fieldname: "coa_status",
				label: __("COA Status"),
				options: "Not Checked\nPresent\nApproved\nMissing\nRejected",
				default: pcc.coa_status || "Not Checked",
				read_only: readOnly ? 1 : 0,
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Select",
				fieldname: "tanker_cleanliness",
				label: __("Tanker Cleanliness"),
				options: "Not Checked\nClean\nAcceptable\nContaminated",
				default: pcc.tanker_cleanliness || "Not Checked",
				read_only: readOnly ? 1 : 0,
			},
			{
				fieldtype: "Select",
				fieldname: "odour_check",
				label: __("Odour Check"),
				options: "Not Applicable\nPassed\nFailed",
				default: pcc.odour_check || "Not Applicable",
				read_only: readOnly ? 1 : 0,
			},
			{
				fieldtype: "Select",
				fieldname: "seal_condition_before_loading",
				label: __("Seal Condition"),
				options: "Not Applicable\nIntact\nBroken",
				default: pcc.seal_condition_before_loading || "Not Applicable",
				read_only: readOnly ? 1 : 0,
			},
			{
				fieldtype: "Small Text",
				fieldname: "qc_remarks",
				label: __("QC Remarks"),
				default: pcc.qc_remarks || "",
				read_only: readOnly ? 1 : 0,
			},
		],
		primary_action_label: __("Close"),
		primary_action: () => d.hide(),
	});

	if (!readOnly && data.can_verify_sddn && data.sddn) {
		d.add_custom_action(__("Save Security Review"), () => {
			qcSaveSecurityReview(d, data, checklistItems, refresh);
		});
	}

	const showPrecheckActions =
		!readOnly &&
		data.pre_check_clearance &&
		(kind === "new" || data.can_pass_precheck || data.can_fail_precheck);

	if (showPrecheckActions && (kind === "new" || data.can_pass_precheck)) {
		d.add_custom_action(__("Pass QC Pre-Check"), () => {
			qcMarkPrecheckFromDialog(d, data, "Passed", refresh);
		});
	}
	if (showPrecheckActions && (kind === "new" || data.can_fail_precheck)) {
		d.add_custom_action(__("Fail QC Pre-Check"), () => {
			qcMarkPrecheckFromDialog(d, data, "Failed", refresh);
		});
	}

	if (!readOnly && !data.read_only && data.can_create_ldn && data.sddn && !data.is_import) {
		d.add_custom_action(__("Create Loading Delivery Note"), () => {
			qcCreateLoadingDn(data.sddn, refresh, () => d.hide());
		});
	}
	if (data.sddn) {
		d.add_custom_action(__("Print SDDN"), () => {
			window.open(
				qcPrintUrl("Security Draft Delivery Note", data.sddn, QC_PRINT_FORMATS.SDDN),
				"_blank"
			);
		});
	}
	d.add_custom_action(__("Open DO Form"), () => {
		frappe.set_route("Form", "Delivery Order", doName);
	});
	d.show();
}

function qcConsoleApiErrorMessage(err) {
	if (!err) {
		return __("Unknown error");
	}
	if (typeof err === "string") {
		return err;
	}
	if (err.message) {
		return err.message;
	}
	if (err._server_messages) {
		try {
			const msgs = JSON.parse(err._server_messages);
			return msgs.map((m) => JSON.parse(m).message).join("<br>");
		} catch (e) {
			return err._server_messages;
		}
	}
	return String(err);
}

function qcSaveSecurityReview(dialog, data, checklistItems, refresh) {
	const values = dialog.get_values();
	if (!values) {
		frappe.msgprint({
			title: __("Cannot save"),
			message: __("Fix the highlighted fields before saving the security review."),
			indicator: "orange",
		});
		return;
	}
	if (!values.truck_verified || !values.driver_verified || !values.container_verified) {
		frappe.msgprint(__("All three verification checks must be ticked."));
		return;
	}
	const checklistPayload = frappe.apc.collectSecurityChecklist(dialog, checklistItems);
	const pending = checklistPayload
		.filter((row) => row.required && !row.completed)
		.map((row) => row.checklist_item);
	if (pending.length) {
		frappe.msgprint({
			title: __("Checklist Incomplete"),
			message:
				__("Tick all required checklist items before saving.") +
				"<br><br>" +
				pending.map((p) => `• ${frappe.utils.escape_html(p)}`).join("<br>"),
			indicator: "orange",
		});
		return;
	}
	APCConsoleUI.callApi("apc_operations.security.api.verify_security_delivery_draft_note", {
		name: data.sddn,
		checks: JSON.stringify({
			truck_verified: values.truck_verified,
			driver_verified: values.driver_verified,
			container_verified: values.container_verified,
			remarks: values.security_remarks,
		}),
		checklist: JSON.stringify(checklistPayload),
	})
		.then(() => {
			frappe.show_alert({ message: __("Security review saved"), indicator: "green" });
			dialog.hide();
			refresh && refresh();
		})
		.catch((err) =>
			frappe.msgprint({
				title: __("Security review failed"),
				message: qcConsoleApiErrorMessage(err),
				indicator: "red",
			})
		);
}

function qcMarkPrecheckFromDialog(dialog, data, status, refresh) {
	if (!data.pre_check_clearance) {
		frappe.msgprint(__("No Pre-Check Clearance linked to this Delivery Order."));
		return;
	}
	const values = dialog.get_values();
	if (!values) {
		frappe.msgprint({
			title: __("Cannot save"),
			message: __("Fix the highlighted fields before passing QC pre-check."),
			indicator: "orange",
		});
		return;
	}
	let failure_reason = null;
	if (status === "Failed") {
		failure_reason = values.qc_remarks || prompt(__("Failure reason?"));
		if (failure_reason === null && !values.qc_remarks) {
			return;
		}
	}
	APCConsoleUI.callApi("apc_operations.quality.api.submit_qc_precheck", {
		pre_check_clearance: data.pre_check_clearance,
		result: status,
		product_confirmed: values.product_confirmed ? 1 : 0,
		batch_no: values.batch_no,
		coa_status: values.coa_status,
		tanker_cleanliness: values.tanker_cleanliness,
		odour_check: values.odour_check,
		seal_condition_before_loading: values.seal_condition_before_loading,
		qc_remarks: values.qc_remarks,
		failure_reason: failure_reason || undefined,
	})
		.then((res) => {
			let message = __("QC pre-check {0}", [status]);
			if (status === "Passed" && res) {
				if (res.overall_status === "Authorized") {
					message = __("QC pre-check passed. Truck cleared for loading.");
				} else if (res.is_import) {
					message = __(
						"QC pre-check passed. Open Transportation → Inward Import to link or create the Export Job Order."
					);
				} else {
					message = __("QC pre-check passed. Continue in Pending Delivery Orders.");
				}
			}
			frappe.show_alert({
				message,
				indicator: status === "Passed" ? "green" : "red",
			});
			dialog.hide();
			refresh && refresh();
		})
		.catch((err) =>
			frappe.msgprint({
				title: __("QC pre-check failed"),
				message: qcConsoleApiErrorMessage(err),
				indicator: "red",
			})
		);
}

function openQcLdnModal(data, item, kind, refresh) {
		const readOnly = kind === "completed" || kind === "rejected";

		const fields = [
			{
				fieldtype: "HTML",
				options: renderKvGrid(data, [
					["Delivery Order", data.delivery_order || "—"],
					["Loading DN", data.loading_delivery_note],
					["SDDN", data.security_draft_delivery_note],
					["Job Order", data.job_order_number || data.job_order || "—"],
					["Customer", data.customer_name || data.customer],
					["Product", data.product],
					["Quantity", `${data.quantity || "-"} ${data.uom || ""}`.trim()],
					["Container", data.container_number],
					["Truck", data.vehicle_number],
					["Driver", data.driver_name],
					["Batch", data.primary_batch || "—"],
					["QC Status", data.qc_status],
					["LDN Status", data.ldn_status_label || data.ldn_status],
					["SDDN Status", data.sddn_status_label || data.sddn_status],
				]),
			},
			{
				fieldtype: "HTML",
				options: renderQcDocumentsAndCoaSection(data),
			},
		];

		if (!readOnly) {
			fields.push(
				{ fieldtype: "Section Break", label: __("QC Entry") },
				{
					fieldtype: "Link",
					fieldname: "batch",
					label: __("Batch"),
					options: "APC Batch",
					default: data.primary_batch,
				},
				{
					fieldtype: "Link",
					fieldname: "coa",
					label: __("COA (from batch)"),
					options: "APC COA",
					read_only: 1,
					default: qcDefaultCoaFromDetail(data),
				},
				{
					fieldtype: "Select",
					fieldname: "qc_status",
					label: __("QC Result"),
					options: "QC Cleared\nQC Rejected\nPending QC",
					default: data.qc_status,
				},
				{
					fieldtype: "Small Text",
					fieldname: "qc_remarks",
					label: __("QC Remarks"),
					default: data.qc_remarks,
				},
				{
					fieldtype: "Check",
					fieldname: "generate_coa",
					label: __("Generate COA on Save"),
					default: 1,
				}
			);
		}

		const d = new frappe.ui.Dialog({
			title: `${__("QC")} — ${data.loading_delivery_note}`,
			size: "large",
			fields,
			primary_action_label: readOnly ? __("Close") : __("Save QC"),
			primary_action: (values) => {
				if (readOnly) {
					d.hide();
					return;
				}
				if (!values.qc_status || values.qc_status === "Pending QC") {
					frappe.msgprint(__("Choose a final QC result (Cleared or Rejected)."));
					return;
				}
				APCConsoleUI.callApi(
					"apc_operations.quality.api.submit_qc_for_loading_delivery_note",
					{
						loading_delivery_note: data.loading_delivery_note,
						batch: values.batch || data.primary_batch,
						qc_status: values.qc_status,
						qc_remarks: values.qc_remarks,
						generate_coa: values.generate_coa ? 1 : 0,
					}
				)
					.then((res) => {
						const msg =
							res && res.coa
								? __("QC saved. COA: {0}", [res.coa])
								: __("QC saved");
						frappe.show_alert({ message: msg, indicator: "green" });
						d.hide();
						refresh && refresh();
					})
					.catch((err) => frappe.msgprint(err));
			},
		});

		if (!readOnly && data.qc_report_request) {
			d.add_custom_action(__("Generate COA"), () => {
				APCConsoleUI.callApi("apc_operations.quality.api.generate_coa_for_qc", {
					qc_report_request: data.qc_report_request,
				})
					.then((res) => {
						frappe.show_alert({
							message: __("COA: {0}", [(res && res.coa) || "—"]),
							indicator: "green",
						});
						d.hide();
						refresh && refresh();
					})
					.catch((err) => frappe.msgprint(err));
			});

			d.add_custom_action(__("Upload COA"), () => {
				new frappe.ui.FileUploader({
					doctype: "APC COA",
					on_success: (file) => {
						APCConsoleUI.callApi("apc_operations.quality.api.upload_coa_for_qc", {
							qc_report_request: data.qc_report_request,
							file_url: file.file_url,
						})
							.then(() => {
								frappe.show_alert({ message: __("COA uploaded"), indicator: "green" });
								d.hide();
								refresh && refresh();
							})
							.catch((err) => frappe.msgprint(err));
					},
				});
			});
		}

		if (data.loading_delivery_note) {
			d.add_custom_action(__("Open LDN"), () => {
				frappe.set_route("Form", "Loading Delivery Note", data.loading_delivery_note);
			});
		}
		d.add_custom_action(__("Print LDN"), () => {
			window.open(
				qcPrintUrl("Loading Delivery Note", data.loading_delivery_note, QC_PRINT_FORMATS.LDN),
				"_blank"
			);
		});
		if (data.security_draft_delivery_note) {
			d.add_custom_action(__("Print SDDN"), () => {
				window.open(
					qcPrintUrl(
						"Security Draft Delivery Note",
						data.security_draft_delivery_note,
						QC_PRINT_FORMATS.SDDN
					),
					"_blank"
				);
			});
		}
		if (data.delivery_order) {
			d.add_custom_action(__("Open DO Form"), () => {
				frappe.set_route("Form", "Delivery Order", data.delivery_order);
			});
		}

		d.show();

		if (!readOnly && d.fields_dict.batch && d.fields_dict.coa) {
			const syncCoaFromBatch = () => {
				const batchVal = d.get_value("batch");
				if (!batchVal) {
					d.set_value("coa", "");
					return;
				}
				APCConsoleUI.callApi("apc_operations.quality.api.get_coa_for_qc_batch", {
					loading_delivery_note: data.loading_delivery_note,
					batch: batchVal,
				})
					.then((res) => {
						d.set_value("coa", (res && res.coa) || "");
					})
					.catch(() => {});
			};
			const $bin = d.fields_dict.batch.$input;
			if ($bin) {
				$bin.on("change", syncCoaFromBatch);
				$bin.on("awesomplete-selectcomplete", syncCoaFromBatch);
			}
			syncCoaFromBatch();
		}

		if (!readOnly) {
			d.add_custom_action(__("Approve COA"), () => {
				const coa = d.get_value("coa");
				if (!coa) {
					frappe.msgprint(
						__(
							"Pick a batch with a linked COA, or use Generate COA / Save QC first."
						)
					);
					return;
				}
				frappe.prompt(
					[
						{
							fieldname: "remarks",
							fieldtype: "Small Text",
							label: __("Remarks (optional)"),
						},
					],
					(v) => {
						APCConsoleUI.callApi("apc_operations.quality.api.set_coa_approval_from_qc", {
							coa,
							decision: "Approved",
							remarks: v.remarks || "",
						})
							.then(() => {
								frappe.show_alert({ message: __("COA approved"), indicator: "green" });
								refresh && refresh();
							})
							.catch((err) => frappe.msgprint(err));
					},
					__("Approve COA")
				);
			});
			d.add_custom_action(__("Reject COA"), () => {
				const coa = d.get_value("coa");
				if (!coa) {
					frappe.msgprint(__("Pick a batch with a linked COA."));
					return;
				}
				frappe.prompt(
					[
						{
							fieldname: "rejection_reason",
							fieldtype: "Small Text",
							label: __("Reason"),
							reqd: 1,
						},
					],
					(v) => {
						APCConsoleUI.callApi("apc_operations.quality.api.set_coa_approval_from_qc", {
							coa,
							decision: "Rejected",
							rejection_reason: v.rejection_reason,
						})
							.then(() => {
								frappe.show_alert({ message: __("COA rejected"), indicator: "orange" });
								refresh && refresh();
							})
							.catch((err) => frappe.msgprint(err));
					},
					__("Reject COA")
				);
			});
		}
}

function renderQcDocumentsAndCoaSection(data) {
	const esc = frappe.utils.escape_html;
	const ldn = data.loading_delivery_note;
	const ldnUrl = esc(qcPrintUrl("Loading Delivery Note", ldn, QC_PRINT_FORMATS.LDN));
	let docs = `<div class="apc-modal-section" style="margin-top:8px;">
		<div class="apc-modal-section-title">${__("Documents")}</div>
		<p style="margin:0 0 8px 0;">
			<a class="btn btn-xs btn-default" href="${ldnUrl}" target="_blank" rel="noopener">${__(
				"Print / PDF LDN"
			)}</a>`;
	if (data.security_draft_delivery_note) {
		const sddnUrl = esc(
			qcPrintUrl(
				"Security Draft Delivery Note",
				data.security_draft_delivery_note,
				QC_PRINT_FORMATS.SDDN
			)
		);
		docs += ` <a class="btn btn-xs btn-default" href="${sddnUrl}" target="_blank" rel="noopener">${__(
			"Print / PDF SDDN"
		)}</a>`;
	}
	docs += `</p></div>`;

	const batches = data.batches || [];
	const rows = [];
	for (const b of batches) {
		const batch = esc(b.batch || "—");
		let coaCell = "—";
		if (b.coa) {
			coaCell = qcCoaLinksHtml(b.coa, b.coa_pdf);
		}
		const status = esc(b.coa_label || "—");
		rows.push(`<tr><td class="apc-qc-td">${batch}</td><td class="apc-qc-td">${coaCell}</td><td class="apc-qc-td">${status}</td></tr>`);
	}
	if (!batches.length && data.coa) {
		const status = esc(data.qcr_coa_label || "—");
		rows.push(
			`<tr><td class="apc-qc-td">—</td><td class="apc-qc-td">${qcCoaLinksHtml(
				data.coa,
				data.coa_pdf
			)}</td><td class="apc-qc-td">${status}</td></tr>`
		);
	}
	if (!rows.length) {
		rows.push(
			`<tr><td colspan="3" class="apc-qc-td text-muted">${__("No batch lines on this LDN yet.")}</td></tr>`
		);
	}

	const table = `<div class="apc-modal-section">
		<div class="apc-modal-section-title">${__("Batch & COA")}</div>
		<table class="table table-bordered table-condensed" style="margin-bottom:0;font-size:12px;">
			<thead><tr>
				<th>${__("Batch")}</th>
				<th>${__("COA")}</th>
				<th>${__("COA status")}</th>
			</tr></thead>
			<tbody>${rows.join("")}</tbody>
		</table>
		<p class="text-muted small" style="margin-top:8px;margin-bottom:0;">${__(
			"Open COA to edit or re-upload the certificate; use PDF to download the attached file."
		)}</p>
	</div>`;

	return `${docs}${table}`;
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
