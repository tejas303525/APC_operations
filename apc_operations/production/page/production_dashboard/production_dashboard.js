// Copyright (c) 2026, APC and contributors
// For license information, please see license.txt

frappe.pages["production-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Production Dashboard"),
		single_column: true,
	});

	page.set_primary_action(__("New Production Order"), () => {
		frappe.new_doc("Production Order");
	}, "add");

	page.set_secondary_action(__("Refresh"), () => {
		if (frappe.production_dashboard) {
			frappe.production_dashboard.refresh();
		}
	}, "refresh");

	frappe.production_dashboard = new ProductionDashboard(page, wrapper);
};

frappe.pages["production-dashboard"].on_page_show = function () {
	if (frappe.production_dashboard) {
		frappe.production_dashboard.refresh();
	}
};

class ProductionDashboard {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.data = {};
		this._build_layout();
		this.refresh();
		this._auto_refresh_timer = setInterval(() => this.refresh(), 5 * 60 * 1000);
	}

	_build_layout() {
		const root = $(this.wrapper).find(".page-content");
		root.css({ padding: "0" });

		this.$root = $('<div class="production-dashboard"></div>').appendTo(root);
		this.$root.html(`
			<div class="pd-hero">
				<div>
					<h2>${__("Production Dashboard")}</h2>
					<p>${__("Track manufacturing and filling requirements from Job Orders and batch-wise filling progress.")}</p>
				</div>
				<div class="pd-hero-actions">
					<button class="btn btn-default btn-sm" data-action="refresh">${__("Refresh")}</button>
					<button class="btn btn-primary btn-sm" data-action="new-production-order">${__("+ New Production Order")}</button>
				</div>
			</div>
			<div class="pd-kpi-strip"></div>
			<div class="pd-top-grid">
				<section class="pd-card pd-calendar-card">
					<div class="pd-card-header">
						<h5 class="pd-card-title">${__("Production Calendar")}</h5>
						<div class="pd-calendar-controls">
							<span class="pd-date-chip">${__("Today")}</span>
							<span class="pd-date-range"></span>
							<div class="pd-view-toggle">
								<span>${__("Month")}</span>
								<span class="active">${__("Week")}</span>
								<span>${__("Day")}</span>
							</div>
						</div>
					</div>
					<div class="pd-calendar-body"></div>
					<div class="pd-calendar-legend"></div>
				</section>
				<section class="pd-card pd-actions-card">
					<div class="pd-card-header">
						<h5 class="pd-card-title">${__("Today's Actions")}</h5>
					</div>
					<div class="pd-actions-body"></div>
				</section>
			</div>
			<div class="pd-category-grid"></div>
			<div class="pd-bottom-grid">
				<section class="pd-card">
					<div class="pd-card-header">
						<h5 class="pd-card-title">${__("Recent Production Orders")}</h5>
						<a class="pd-card-link" data-action="view-orders">${__("View All")}</a>
					</div>
					<div class="pd-orders-body"></div>
				</section>
				<section class="pd-card">
					<div class="pd-card-header">
						<h5 class="pd-card-title">${__("Alerts & Reminders")}</h5>
					</div>
					<div class="pd-alerts-body"></div>
				</section>
				<section class="pd-card">
					<div class="pd-card-header">
						<h5 class="pd-card-title">${__("Quick Links")}</h5>
					</div>
					<div class="pd-quick-links"></div>
				</section>
			</div>
		`);

		this.$root.find('[data-action="refresh"]').on("click", () => this.refresh());
		this.$root.find('[data-action="new-production-order"]').on("click", () =>
			frappe.new_doc("Production Order"));
		this.$root.find('[data-action="view-orders"]').on("click", () =>
			frappe.set_route("List", "Production Order"));
	}

	refresh() {
		frappe.call({
			method: "apc_operations.production.api.get_production_dashboard_data",
			freeze: false,
			callback: (r) => {
				this.data = r.message || {};
				this._render();
			},
			error: () => {
				this.data = {
					active_rules: [],
					alerts: [],
					calendar: {},
					categories: [],
					category_summaries: [],
					kpis: {},
					quick_links: [],
					recent_orders: [],
					today_actions: [],
				};
				this._render();
			},
		});
	}

	_render() {
		this._render_kpi(this.data.kpis || {});
		this._render_calendar(this.data.calendar || {});
		this._render_today_actions(this.data.today_actions || []);
		this._render_category_summaries(this.data.category_summaries || []);
		this._render_orders(this.data.recent_orders || []);
		this._render_alerts(this.data.alerts || this.data.capacity_alerts || []);
		this._render_quick_links(this.data.quick_links || []);
	}

	_render_kpi(kpi) {
		const cards = [
			{ label: __("Pending Production Orders"), value: kpi.pending_orders ?? 0, color: "blue", icon: "clipboard",
				trend: kpi.pending_trend || __("open orders"), route: ["List", "Production Order", { status: ["in", ["Draft", "Planned"]] }] },
			{ label: __("Partially Filled"), value: kpi.partially_filled ?? 0, color: "amber", icon: "folder-normal",
				trend: kpi.partially_filled_trend || __("in progress"), route: ["List", "Production Order", { status: "In Progress" }] },
			{ label: __("Completed Today"), value: kpi.completed_today ?? 0, color: "green", icon: "success",
				trend: kpi.completed_trend || __("completed today"), route: ["List", "Production Order", { status: "Completed", modified: [">=", frappe.datetime.get_today()] }] },
			{ label: __("Overdue Production"), value: kpi.overdue_orders ?? 0, color: "red", icon: "warning",
				trend: kpi.overdue_trend || __("past planned date"), route: ["List", "Production Order", { planned_date: ["<", frappe.datetime.get_today()], status: ["!=", "Completed"] }] },
			{ label: __("Lubricants Pending"), value: kpi.lubricants_pending ?? 0, color: "purple", icon: "drop",
				trend: kpi.lubricants_trend || __("open lubricant orders"), route: ["List", "Production Order", { production_capacity_category: "Lubricants" }] },
			{ label: __("Plasticizers Pending"), value: kpi.plasticizers_pending ?? 0, color: "indigo", icon: "lab-test",
				trend: kpi.plasticizers_trend || __("open plasticizer orders"), route: ["List", "Production Order", { production_capacity_category: "Plasticizers" }] },
			{ label: __("White Oil & Jellies Pending"), value: kpi.white_oil_pending ?? 0, color: "gold", icon: "package",
				trend: kpi.white_oil_trend || __("open white oil orders"), route: ["List", "Production Order", { production_capacity_category: "White Oil & Jellies" }] },
			{ label: __("Over Capacity Days"), value: kpi.over_capacity_days ?? 0, color: "red", icon: "alert-triangle",
				trend: kpi.capacity_trend || __("next 30 days"),
				route: ["List", "Production Order", { capacity_status: "Over Capacity" }] },
		];

		const $strip = this.$root.find(".pd-kpi-strip").empty();
		cards.forEach((c) => {
			const $card = $(`
				<div class="pd-kpi-card pd-accent-${c.color}">
					<div class="pd-kpi-icon">${frappe.utils.icon(c.icon, "md")}</div>
					<div class="pd-kpi-text">
						<div class="pd-kpi-count">${c.value}</div>
						<div class="pd-kpi-label">${frappe.utils.escape_html(c.label)}</div>
						<div class="pd-kpi-trend">${frappe.utils.escape_html(c.trend || "")}</div>
					</div>
				</div>
			`);
			$card.on("click", () => frappe.set_route(...c.route));
			$strip.append($card);
		});
	}

	_render_calendar(calendar) {
		const $body = this.$root.find(".pd-calendar-body").empty();
		const $range = this.$root.find(".pd-date-range");
		const $legend = this.$root.find(".pd-calendar-legend").empty();
		const days = calendar.days || [];
		const hours = ["8 AM", "10 AM", "12 PM", "2 PM", "4 PM", "6 PM"];

		$range.text(calendar.label || "");
		if (!days.length) {
			$body.append(`<div class="pd-empty">${__("No production orders scheduled this week.")}</div>`);
			return;
		}

		const $grid = $(`
			<div class="pd-calendar-grid" style="--pd-day-count: ${days.length}">
				<div class="pd-calendar-corner">${__("All Day")}</div>
				${days.map((day) => `
					<div class="pd-day-head ${day.is_today ? "today" : ""}">
						<span>${frappe.utils.escape_html(day.weekday || "")}</span>
						<strong>${frappe.utils.escape_html(day.day_label || "")}</strong>
					</div>
				`).join("")}
				${hours.map((hour) => `
					<div class="pd-hour-label">${hour}</div>
					${days.map((day) => `<div class="pd-day-cell" data-date="${frappe.utils.escape_html(day.date)}" data-hour="${hour}"></div>`).join("")}
				`).join("")}
			</div>
		`).appendTo($body);

		days.forEach((day) => {
			(day.orders || []).forEach((order, index) => {
				const top = Math.min(index % hours.length, hours.length - 1);
				const $cell = $grid.find(`[data-date="${day.date}"][data-hour="${hours[top]}"]`);
				const $event = $(`
					<div class="pd-calendar-event pd-cat-${this._slug(order.category)}">
						<div>${frappe.utils.escape_html(order.production_order_number || order.name)}</div>
						<strong>${frappe.utils.escape_html(order.item_description || order.category || __("Production"))}</strong>
						<span>${this._format_qty(order.qty, order.uom)}</span>
					</div>
				`);
				$event.on("click", () => frappe.set_route("Form", "Production Order", order.name));
				$cell.append($event);
			});
		});

		(calendar.legend || []).forEach((item) => {
			$legend.append(`
				<span><i class="pd-legend-dot pd-cat-${this._slug(item)}"></i>${frappe.utils.escape_html(item)}</span>
			`);
		});
	}

	_render_today_actions(actions) {
		const $body = this.$root.find(".pd-actions-body").empty();
		if (!actions.length) {
			$body.append(`<div class="pd-empty">${__("No priority actions for today.")}</div>`);
			return;
		}

		actions.forEach((action) => {
			const $item = $(`
				<div class="pd-action-item">
					<span class="pd-action-icon pd-accent-${action.color || "blue"}">${frappe.utils.icon(action.icon || "dot", "sm")}</span>
					<span class="pd-action-label">${frappe.utils.escape_html(action.label)}</span>
					<strong>${action.count || 0}</strong>
					${frappe.utils.icon("right", "xs")}
				</div>
			`);
			if (action.route) {
				$item.on("click", () => frappe.set_route(...action.route));
			}
			$body.append($item);
		});
	}

	_render_category_summaries(summaries) {
		const $grid = this.$root.find(".pd-category-grid").empty();
		if (!summaries.length) {
			$grid.append(`<section class="pd-card"><div class="pd-empty">${__("No production categories to show.")}</div></section>`);
			return;
		}

		summaries.forEach((summary) => {
			const $card = $(`
				<section class="pd-card pd-category-card">
					<div class="pd-card-header">
						<h5 class="pd-card-title pd-cat-title pd-cat-${this._slug(summary.category)}">
							${frappe.utils.escape_html(summary.category)}
							<span>${summary.count || 0}</span>
						</h5>
						<a class="pd-card-link">${__("View All")}</a>
					</div>
					<div class="pd-category-body"></div>
					<div class="pd-category-footer">${__("View All {0}", [summary.category])}</div>
				</section>
			`);
			$card.find(".pd-card-link, .pd-category-footer").on("click", () =>
				frappe.set_route("List", "Production Order", { production_capacity_category: summary.category }));
			const $body = $card.find(".pd-category-body");
			(summary.orders || []).forEach((order) => {
				const status_class = this._status_class(order.status, order.capacity_status);
				const $row = $(`
					<div class="pd-mini-order">
						<div>
							<strong>${frappe.utils.escape_html(order.production_order_number || order.name)}</strong>
							<span>${frappe.utils.escape_html(order.item_description || "—")}</span>
						</div>
						<div class="pd-mini-qty">
							<span>${this._format_qty(order.capacity_quantity || order.required_quantity, order.capacity_uom || order.uom)}</span>
							<em class="${status_class}">${frappe.utils.escape_html(order.status || __("Draft"))}</em>
						</div>
					</div>
				`);
				$row.on("click", () => frappe.set_route("Form", "Production Order", order.name));
				$body.append($row);
			});
			if (!(summary.orders || []).length) {
				$body.append(`<div class="pd-empty small">${__("No active orders in this category.")}</div>`);
			}
			$grid.append($card);
		});
	}

	_render_orders(orders) {
		const $body = this.$root.find(".pd-orders-body").empty();

		if (!orders.length) {
			$body.append(`<div class="pd-empty">${__("No production orders yet.")}</div>`);
			return;
		}

		const $table = $(`
			<table class="pd-table">
				<thead>
					<tr>
						<th>${__("Date")}</th>
						<th>${__("Order")}</th>
						<th>${__("Product")}</th>
						<th>${__("Category")}</th>
						<th class="num">${__("Amount")}</th>
						<th>${__("Status")}</th>
					</tr>
				</thead>
				<tbody></tbody>
			</table>
		`).appendTo($body);

		const $tbody = $table.find("tbody");
		orders.forEach((o) => {
			$tbody.append(`
				<tr>
					<td>${o.planned_date ? frappe.datetime.str_to_user(o.planned_date) : "—"}</td>
					<td><a href="/app/production-order/${encodeURIComponent(o.name)}">${frappe.utils.escape_html(o.production_order_number || o.name)}</a></td>
					<td>${frappe.utils.escape_html(o.item_description || "—")}</td>
					<td>${frappe.utils.escape_html(o.production_capacity_category || "—")}</td>
					<td class="num">${this._format_qty(o.capacity_quantity || o.required_quantity, o.capacity_uom || o.uom)}</td>
					<td><span class="pd-badge ${this._status_class(o.status, o.capacity_status)}">${frappe.utils.escape_html(o.status || "Draft")}</span></td>
				</tr>
			`);
		});
	}

	_render_alerts(alerts) {
		const $body = this.$root.find(".pd-alerts-body").empty();
		if (!alerts.length) {
			$body.append(`<div class="pd-empty">${__("No active production alerts.")}</div>`);
			return;
		}

		alerts.forEach((alert) => {
			const $alert = $(`
				<div class="pd-alert-item ${alert.color || "red"}">
					<span></span>
					<div>
						<strong>${frappe.utils.escape_html(alert.message || "")}</strong>
						<small>${frappe.utils.escape_html(alert.detail || "")}</small>
					</div>
				</div>
			`);
			if (alert.route) {
				$alert.on("click", () => frappe.set_route(...alert.route));
			}
			$body.append($alert);
		});
	}

	_render_quick_links(links) {
		const $body = this.$root.find(".pd-quick-links").empty();
		const default_links = [
			{ label: __("Production Orders"), route: ["List", "Production Order"] },
			{ label: __("Production Calendar"), route: ["production-calendar"] },
			{ label: __("Capacity Rules"), route: ["List", "Production Capacity Configuration"] },
		];
		(links.length ? links : default_links).forEach((link) => {
			const $link = $(`
				<div class="pd-quick-link">
					<span>${frappe.utils.escape_html(link.label)}</span>
					${frappe.utils.icon("right", "xs")}
				</div>
			`);
			$link.on("click", () => frappe.set_route(...link.route));
			$body.append($link);
		});
	}

	_format_qty(value, uom) {
		if (value === null || value === undefined || value === "") {
			return "—";
		}
		return `${frappe.format(value, { fieldtype: "Float" })}${uom ? " " + frappe.utils.escape_html(uom) : ""}`;
	}

	_slug(value) {
		return (value || "other").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
	}

	_status_class(status, capacity_status) {
		if (capacity_status === "Over Capacity") return "pd-badge-red";
		if (status === "Completed") return "pd-badge-green";
		if (status === "In Progress") return "pd-badge-amber";
		if (status === "Cancelled") return "pd-badge-gray";
		return "pd-badge-blue";
	}
}
