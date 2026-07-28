// QC Pre-Check Console
// --------------------
// One-click pass / fail for Pre-Check Clearance tickets. Also lists
// any Loading DNs that have dispatch_confirmed but no QC manager
// approval yet, so the QC manager can approve DN-COA binding from
// here.

frappe.pages["qc-precheck-console"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("QC Pre-Check"),
		single_column: true,
	});
	frappe.apc_qc_precheck = new QCPrecheckConsole(page, wrapper);
};

frappe.pages["qc-precheck-console"].on_page_show = function () {
	if (frappe.apc_qc_precheck) frappe.apc_qc_precheck.refresh();
};

class QCPrecheckConsole {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this._build();
		this.refresh();
	}

	_build() {
		const $content = $(this.wrapper).find(".page-content").empty();
		this.$root = $(`
			<div class="apc-qc-precheck">
				<div class="apc-toolbar" style="padding:10px 0;">
					<button class="btn btn-default btn-refresh">${__("Refresh")}</button>
				</div>
				<div class="alert alert-info" style="margin-top:12px;">
					${__(
						"Use <strong>QC Console → Delivery Order</strong> for the combined Security checklist + QC pre-check screen."
					)}
					<a href="/app/qc-console" class="btn btn-xs btn-default" style="margin-left:8px;">${__(
						"Open QC Console"
					)}</a>
				</div>
				<h4 style="margin-top:16px;">${__("Pre-Check Queue")}</h4>
				<div class="apc-precheck-list"></div>
				<h4 style="margin-top:24px;">${__("DN-COA Approvals Pending")}</h4>
				<div class="apc-approval-list"></div>
			</div>
		`).appendTo($content);

		this.$root.find(".btn-refresh").on("click", () => this.refresh());

		const css = `
			.apc-qc-precheck .apc-row {
				display:grid;
				grid-template-columns: 220px 1fr 160px 320px;
				gap:8px; padding:10px 12px; border-bottom:1px solid #eee; align-items:center;
			}
			.apc-qc-precheck .apc-row.head { font-weight:600; background:#fafafa; }
			.apc-pill { display:inline-block; padding:2px 8px; border-radius:10px; font-size:12px; }
			.apc-pill.pass  { background:#e3f9e5; color:#1b5e20; }
			.apc-pill.fail  { background:#fde2e1; color:#8a1f1c; }
			.apc-pill.pend  { background:#fff8e1; color:#7a5400; }
		`;
		const style = document.createElement("style");
		style.textContent = css;
		document.head.appendChild(style);
	}

	refresh() {
		return Promise.all([
			frappe.call({ method: "apc_operations.services.consoles.get_qc_precheck_queue" }),
			frappe.call({
				method: "frappe.client.get_list",
				args: {
					doctype: "Loading Delivery Note",
					filters: { dispatch_confirmed: 1, qc_manager_approved: 0 },
					fields: ["name", "customer", "loading_date", "net_weight", "transport_delivery_order"],
					limit_page_length: 50,
				},
			}),
		]).then(([qcResp, dnResp]) => {
			this._renderPrechecks(qcResp.message || []);
			this._renderApprovals(dnResp.message || []);
		});
	}

	_renderPrechecks(rows) {
		const $list = this.$root.find(".apc-precheck-list").empty();
		$list.append(`
			<div class="apc-row head">
				<div>${__("Pre-Check")}</div>
				<div>${__("DO / Customer / Status")}</div>
				<div>${__("Security")}</div>
				<div>${__("Action")}</div>
			</div>
		`);
		if (!rows.length) {
			$list.append(`<div class="apc-row"><em>${__("No pending pre-checks.")}</em></div>`);
			return;
		}
		rows.forEach((row) => {
			const pill =
				row.qc_status === "Passed"
					? '<span class="apc-pill pass">' + __("Passed") + "</span>"
					: row.qc_status === "Failed"
					? '<span class="apc-pill fail">' + __("Failed") + "</span>"
					: '<span class="apc-pill pend">' + __("Pending") + "</span>";

			const $row = $(`
				<div class="apc-row">
					<div>
						<a href="/app/pre-check-clearance/${row.pre_check_clearance}">${row.pre_check_clearance}</a><br/>
						${pill}
					</div>
					<div>
						<a href="/app/delivery-order/${row.delivery_order}">${row.delivery_order || "\u2014"}</a><br/>
						<small>${frappe.utils.escape_html(row.customer_name || "")}
						\u2014 ${frappe.utils.escape_html(row.do_status || "")}</small>
					</div>
					<div>${frappe.utils.escape_html(row.security_status || "Pending")}</div>
					<div>
						<button class="btn btn-sm btn-success btn-pass">${__("Pass")}</button>
						<button class="btn btn-sm btn-danger btn-fail">${__("Fail")}</button>
					</div>
				</div>
			`);
			$row.find(".btn-pass").on("click", () => this._mark(row.pre_check_clearance, "Passed"));
			$row.find(".btn-fail").on("click", () => this._mark(row.pre_check_clearance, "Failed"));
			$list.append($row);
		});
	}

	_renderApprovals(rows) {
		const $list = this.$root.find(".apc-approval-list").empty();
		$list.append(`
			<div class="apc-row head">
				<div>${__("Loading DN")}</div>
				<div>${__("Customer / DO")}</div>
				<div>${__("Net Weight")}</div>
				<div>${__("Action")}</div>
			</div>
		`);
		if (!rows.length) {
			$list.append(`<div class="apc-row"><em>${__("No DNs awaiting QC manager approval.")}</em></div>`);
			return;
		}
		rows.forEach((row) => {
			const $row = $(`
				<div class="apc-row">
					<div><a href="/app/loading-delivery-note/${row.name}">${row.name}</a></div>
					<div>
						${frappe.utils.escape_html(row.customer || "")}<br/>
						<small>${frappe.utils.escape_html(row.transport_delivery_order || "")}</small>
					</div>
					<div>${row.net_weight || 0}</div>
					<div>
						<button class="btn btn-sm btn-primary btn-approve">${__("Approve DN-COA")}</button>
					</div>
				</div>
			`);
			$row.find(".btn-approve").on("click", () => this._approve(row.name));
			$list.append($row);
		});
	}

	_mark(pre_check_clearance, status) {
		const reason = status === "Failed" ? prompt(__("Reason?")) : null;
		frappe.call({
			method: "apc_operations.services.consoles.qc_precheck_mark",
			args: { pre_check_clearance, status, remarks: reason },
		}).then(() => {
			frappe.show_alert({
				message: __("QC marked {0}", [status]),
				indicator: status === "Passed" ? "green" : "red",
			});
			this.refresh();
		});
	}

	_approve(loading_delivery_note) {
		frappe.confirm(__("Approve this DN-COA binding?"), () => {
			frappe.call({
				method: "apc_operations.services.consoles.qc_manager_approve_dn",
				args: { loading_delivery_note },
			}).then(() => {
				frappe.show_alert({ message: __("DN approved"), indicator: "green" });
				this.refresh();
			});
		});
	}
}
