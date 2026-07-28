/* Import GRN Console — import receipts after QC + security clearance */

const APC_IMPORT_GRN_PRINT_FORMAT = "Standard Import GRN";

function apcImportGrnPrintUrl(name) {
	const lang = (frappe.boot && frappe.boot.lang) || "en";
	return `/printview?doctype=${encodeURIComponent("Import GRN")}&name=${encodeURIComponent(
		name
	)}&format=${encodeURIComponent(APC_IMPORT_GRN_PRINT_FORMAT)}&no_letterhead=0&_lang=${encodeURIComponent(lang)}`;
}

frappe.pages["import-grn-console"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Import GRN"),
		single_column: true,
	});

	const router = new APCConsoleRouter(page, {
		rootClass: "apc-console apc-console-import-grn",
	});
	router.reset(buildImportGrnHubScreen(router));
};

function buildImportGrnHubScreen(router) {
	return {
		title: __("Import GRN"),
		render($root) {
			const $bannerHolder = $('<div class="apc-pending-holder"></div>').appendTo($root);
			APCConsoleUI.callApi("apc_operations.security.grn_api.get_import_grn_counts")
				.then((counts) => {
					APCConsoleUI.pendingBanner(
						$bannerHolder,
						{
							transport: counts.pending || 0,
							do: counts.completed || 0,
						},
						(filterId) => {
							if (filterId === "transport") {
								router.push(buildImportGrnListScreen("pending", router));
							} else if (filterId === "do") {
								router.push(buildImportGrnListScreen("completed", router));
							}
						}
					);
					$bannerHolder
						.find(".apc-pending-tile")
						.eq(0)
						.find(".apc-pending-tile-label")
						.text(__("Pending GRN"));
					$bannerHolder
						.find(".apc-pending-tile")
						.eq(1)
						.find(".apc-pending-tile-label")
						.text(__("Completed"));
				})
				.catch(() => {});

			APCConsoleUI.hubButtons($root, [
				{
					label: __("Pending GRN"),
					subtitle: __("QC & security cleared — approve goods receipt"),
					onClick: () => router.push(buildImportGrnListScreen("pending", router)),
				},
				{
					label: __("Completed GRN"),
					subtitle: __("Approved and posted to Zoho (stub or live)"),
					onClick: () => router.push(buildImportGrnListScreen("completed", router)),
				},
			]);
		},
	};
}

function buildImportGrnListScreen(kind, router) {
	const isPending = kind === "pending";
	return {
		title: isPending ? __("Pending Import GRN") : __("Completed Import GRN"),
		render($root) {
			if (!isPending) {
				const $hint = $(
					`<div class="alert alert-info" style="margin-bottom:12px;font-size:13px;">
						${__(
							"New receipts appear under <strong>Pending GRN</strong> after QC and Security are both Passed. Completed shows approved/posted GRNs only."
						)}
					</div>`
				);
				$root.append($hint);
				APCConsoleUI.callApi("apc_operations.security.grn_api.get_import_grn_counts").then(
					(counts) => {
						if ((counts.pending || 0) > 0) {
							$hint.append(
								`<div style="margin-top:8px;">
									<button type="button" class="btn btn-xs btn-primary apc-grn-go-pending">
										${__("View {0} pending GRN(s)", [counts.pending])}
									</button>
								</div>`
							);
							$hint.find(".apc-grn-go-pending").on("click", () => {
								router.push(buildImportGrnListScreen("pending", router));
							});
						}
					}
				);
			}
			importGrnRenderCardScreen($root, {
				listApi: isPending
					? "apc_operations.security.grn_api.get_pending_import_grns"
					: "apc_operations.security.grn_api.get_completed_import_grns",
				searchPlaceholder: __("Search by GRN / DO / JO / Supplier / Product"),
				onCardClick: (item) =>
					openImportGrnModal(item.raw, () => router.refresh()),
			});
		},
	};
}

function importGrnRenderCardScreen($root, options) {
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
		const items = (visible || []).map((r) => importGrnToCard(r));
		$cards.empty();
		APCConsoleUI.cardList($cards, items, (item) =>
			options.onCardClick && options.onCardClick(item)
		);
	}
}

function importGrnToCard(row) {
	return {
		title: row.import_grn || row.name,
		subtitle: row.supplier_name || row.customer_name || "-",
		body_html: `
			<div class="apc-kv-label">${__("Delivery Order")}</div>
			<div>${frappe.utils.escape_html(row.delivery_order || "-")}</div>
			<div class="apc-kv-label">${__("Job Order")}</div>
			<div>${frappe.utils.escape_html(row.job_order_number || row.job_order || "-")}</div>
			<div class="apc-kv-label">${__("Product")}</div>
			<div>${frappe.utils.escape_html(row.product || "-")}</div>
			<div class="apc-kv-label">${__("Batch")}</div>
			<div>${frappe.utils.escape_html(row.batch_no || "-")}</div>
		`,
		badges: [
			APCConsoleUI.statusBadge(row.grn_status, row.grn_status_tone),
		],
		raw: row,
	};
}

function importGrnApiError(err) {
	if (!err) return __("Unknown error");
	if (typeof err === "string") return err;
	if (err.message) return err.message;
	if (err._server_messages) {
		try {
			return JSON.parse(err._server_messages)
				.map((m) => JSON.parse(m).message)
				.join("<br>");
		} catch (e) {
			return err._server_messages;
		}
	}
	return String(err);
}

function openImportGrnModal(item, refresh) {
	const grnName = item.import_grn || item.name;
	APCConsoleUI.callApi("apc_operations.security.grn_api.get_import_grn_detail_api", {
		name: grnName,
	}).then((data) => {
		const readOnly = data.read_only;
		const kvRows = [
			["Import GRN", data.import_grn],
			["Delivery Order", data.delivery_order],
			["Job Order", data.job_order_number || data.job_order],
			["Status", data.grn_status],
			["Customer", data.customer_name || "—"],
			["Supplier", data.supplier_name || "—"],
			["Product", data.product || "—"],
			["Batch", data.batch_no || "—"],
			["QC cleared", data.qc_check_time || "—"],
			["Security cleared", data.security_check_time || "—"],
			["Zoho receipt", data.zoho_import_receipt_id || "—"],
		];

		let itemsHtml = "";
		if (data.items && data.items.length) {
			const rows = data.items
				.map(
					(row) =>
						`<tr><td>${frappe.utils.escape_html(row.item_code || "")}</td>
						<td>${frappe.utils.escape_html(String(row.qty || ""))}</td>
						<td>${frappe.utils.escape_html(row.uom || "")}</td></tr>`
				)
				.join("");
			itemsHtml = `<table class="table table-bordered table-condensed" style="margin-top:12px;font-size:12px;">
				<thead><tr><th>${__("Item")}</th><th>${__("Qty")}</th><th>${__("UOM")}</th></tr></thead>
				<tbody>${rows}</tbody></table>`;
		}

		const d = new frappe.ui.Dialog({
			title: `${__("Import GRN")} — ${grnName}`,
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					options:
						importGrnKvGrid(kvRows) +
						itemsHtml +
						(data.linked_export_job_order
							? `<p class="text-muted small">${__(
									"Linked Export JO: {0}",
									[data.linked_export_job_order]
							  )}</p>`
							: ""),
				},
				{
					fieldtype: "Small Text",
					fieldname: "remarks",
					label: __("GRN Remarks"),
					default: data.remarks || "",
					read_only: readOnly ? 1 : 0,
				},
			],
			primary_action_label: __("Close"),
			primary_action: () => d.hide(),
		});

		if (data.can_approve) {
			d.add_custom_action(__("Approve GRN"), () => {
				const values = d.get_values() || {};
				APCConsoleUI.callApi("apc_operations.security.grn_api.approve_import_grn_api", {
					name: grnName,
					remarks: values.remarks,
				})
					.then((res) => {
						frappe.show_alert({
							message: __("GRN approved{0}", [
								res && res.zoho && res.zoho.zoho_receipt_id
									? ` (${res.zoho.zoho_receipt_id})`
									: "",
							]),
							indicator: "green",
						});
						d.hide();
						refresh && refresh();
					})
					.catch((err) =>
						frappe.msgprint({
							title: __("GRN approval failed"),
							message: importGrnApiError(err),
							indicator: "red",
						})
					);
			});
		}

		d.add_custom_action(__("Print GRN"), () => {
			window.open(apcImportGrnPrintUrl(grnName), "_blank", "noopener,noreferrer");
		});
		d.add_custom_action(__("Open DO Form"), () => {
			frappe.set_route("Form", "Delivery Order", data.delivery_order);
		});
		d.add_custom_action(__("Open GRN Form"), () => {
			frappe.set_route("Form", "Import GRN", grnName);
		});

		if (data.can_link_export || data.can_create_export) {
			d.add_custom_action(__("Open Transportation Import"), () => {
				frappe.set_route("transportation-console");
			});
		}

		d.show();
	});
}

function importGrnKvGrid(pairs) {
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
