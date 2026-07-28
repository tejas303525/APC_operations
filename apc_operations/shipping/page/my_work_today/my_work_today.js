/* My Work Today — cross-hub delivery-urgency rollup for operational consoles. */

frappe.pages["my-work-today"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("My Work Today"),
		single_column: true,
	});

	const $root = $(page.main).empty().addClass("apc-console apc-my-work-today");
	let activeFilter = "urgent";

	const $summary = $(`<div class="apc-work-today-summary"></div>`).appendTo($root);
	const $filters = $(`<div class="apc-work-today-filters"></div>`).appendTo($root);
	const $content = $(`<div class="apc-work-today-content"></div>`).appendTo($root);

	function renderFilterBar() {
		$filters.empty();
		if (typeof APCConsoleUI.filterChips === "function") {
			APCConsoleUI.filterChips(
				$filters,
				[
					{ id: "urgent", label: __("Overdue + Due Today") },
					{ id: "week", label: __("This Week") },
					{ id: "all", label: __("All Pending") },
				],
				{
					initial: activeFilter,
					onChange: (filterId) => {
						activeFilter = filterId;
						loadSummary();
					},
				}
			);
		}
	}

	function renderSummaryBanner(data) {
		const totals = (data && data.totals) || {};
		const parts = [];
		if (totals.overdue) {
			parts.push(
				`<span class="apc-work-today-stat apc-work-today-stat-danger">${totals.overdue} ${__(
					"overdue"
				)}</span>`
			);
		}
		if (totals.today) {
			parts.push(
				`<span class="apc-work-today-stat apc-work-today-stat-warn">${totals.today} ${__(
					"due today"
				)}</span>`
			);
		}
		if (!parts.length && totals.this_week) {
			parts.push(
				`<span class="apc-work-today-stat">${totals.this_week} ${__("this week")}</span>`
			);
		}

		const headline =
			parts.join('<span class="apc-work-today-stat-sep">·</span>') ||
			`<span class="apc-work-today-stat">${__("No urgent delivery deadlines")}</span>`;

		$summary.html(`
			<div class="apc-work-today-summary-inner">
				<div class="apc-work-today-summary-title">${__("Today's delivery priorities")}</div>
				<div class="apc-work-today-summary-stats">${headline}</div>
				<div class="apc-work-today-summary-meta">${__(
					"Sorted by Job Order delivery date across Shipping, Transportation, Security, and QC."
				)}</div>
			</div>
		`);
	}

	function queueSubtitle(queue) {
		const parts = [];
		if (queue.overdue) {
			parts.push(__("{0} overdue", [queue.overdue]));
		}
		if (queue.today) {
			parts.push(__("{0} due today", [queue.today]));
		}
		if (!parts.length && queue.this_week) {
			parts.push(__("{0} this week", [queue.this_week]));
		}
		if (!parts.length && queue.total) {
			parts.push(__("{0} pending", [queue.total]));
		}
		return parts.join(" · ");
	}

	function openConsole(pageName) {
		if (!pageName) {
			return;
		}
		frappe.set_route("page", pageName);
	}

	function renderHubs(data) {
		$content.empty();
		const hubs = (data && data.hubs) || [];

		if (!hubs.length) {
			$content.html(
				`<div class="apc-console-empty">${frappe.utils.escape_html(
					__("Nothing urgent in this view. Try another filter or check individual consoles.")
				)}</div>`
			);
			return;
		}

		hubs.forEach((hub) => {
			const $section = $(`<section class="apc-work-today-hub"></section>`).appendTo($content);
			const hubSubtitle = queueSubtitle(hub.totals || {});

			$section.append(`
				<div class="apc-work-today-hub-head">
					<div>
						<div class="apc-work-today-hub-title">${frappe.utils.escape_html(hub.label || "")}</div>
						<div class="apc-work-today-hub-subtitle">${frappe.utils.escape_html(hubSubtitle)}</div>
					</div>
					<button type="button" class="btn btn-default btn-sm apc-work-today-open-hub">
						${frappe.utils.escape_html(__("Open {0} Console", [hub.label || ""]))}
					</button>
				</div>
			`);

			$section.find(".apc-work-today-open-hub").on("click", () => openConsole(hub.console_page));

			const $list = $(`<div class="apc-work-today-queue-list"></div>`).appendTo($section);
			(hub.queues || []).forEach((queue) => {
				const $row = $(
					`<button type="button" class="apc-work-today-queue-row">
						<span class="apc-work-today-queue-label">${frappe.utils.escape_html(
							queue.label || queue.key || ""
						)}</span>
						<span class="apc-work-today-queue-counts">${frappe.utils.escape_html(
							queueSubtitle(queue)
						)}</span>
					</button>`
				);
				$row.on("click", () => openConsole(queue.console_page || hub.console_page));
				$list.append($row);
			});
		});
	}

	function loadSummary() {
		if (typeof APCConsoleUI.loading === "function") {
			APCConsoleUI.loading($content);
		} else {
			$content.html(`<div class="apc-console-loading">${__("Loading...")}</div>`);
		}

		const callApi =
			typeof APCConsoleUI.callApi === "function"
				? APCConsoleUI.callApi.bind(APCConsoleUI)
				: (method, args) =>
						new Promise((resolve, reject) => {
							frappe.call({
								method,
								args: args || {},
								callback: (r) => resolve(r && r.message),
								error: (err) => reject(err),
							});
						});

		callApi("apc_operations.services.console_api.get_my_work_today", {
			urgency_filter: activeFilter,
		})
			.then((data) => {
				renderSummaryBanner(data);
				renderHubs(data);
			})
			.catch((err) => {
				if (typeof APCConsoleUI.errorBlock === "function") {
					APCConsoleUI.errorBlock($content, err);
				} else {
					$content.html(`<div class="apc-console-empty">${__("Unable to load work summary")}</div>`);
				}
			});
	}

	renderFilterBar();
	loadSummary();
};
