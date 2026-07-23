// Copyright (c) 2026, APC and contributors
// For license information, please see license.txt

frappe.pages["production-calendar"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Production Capacity Calendar"),
		single_column: true,
	});

	page.set_secondary_action(__("Dashboard"), () => {
		frappe.set_route("production-dashboard");
	}, "dashboard");

	page.set_primary_action(__("Add Capacity Rule"), () => {
		frappe.new_doc("Production Capacity Configuration");
	}, "add");

	frappe.production_calendar = new ProductionCalendar(page, wrapper);
};

frappe.pages["production-calendar"].on_page_show = function () {
	if (frappe.production_calendar) {
		frappe.production_calendar.refresh();
	}
};

class ProductionCalendar {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());
		this.year = today.getFullYear();
		this.month = today.getMonth() + 1;
		this._build_layout();
		this.refresh();
	}

	_build_layout() {
		const root = $(this.wrapper).find(".page-content");
		root.css({ padding: "20px 24px" });

		this.$root = $('<div class="production-calendar"></div>').appendTo(root);

		this.$nav = $(`
			<div class="pc-nav">
				<button class="btn btn-default btn-sm pc-prev"><i class="fa fa-chevron-left"></i></button>
				<h4 class="pc-title">${__("Loading…")}</h4>
				<button class="btn btn-default btn-sm pc-next"><i class="fa fa-chevron-right"></i></button>
				<button class="btn btn-default btn-sm pc-today">${__("Today")}</button>
			</div>
		`).appendTo(this.$root);

		this.$nav.find(".pc-prev").on("click", () => this._shift(-1));
		this.$nav.find(".pc-next").on("click", () => this._shift(1));
		this.$nav.find(".pc-today").on("click", () => {
			const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());
			this.year = today.getFullYear();
			this.month = today.getMonth() + 1;
			this.refresh();
		});

		this.$summary = $('<div class="pc-summary"></div>').appendTo(this.$root);
		this.$grid = $('<div class="pc-grid"></div>').appendTo(this.$root);
	}

	_shift(delta) {
		this.month += delta;
		if (this.month < 1) {
			this.month = 12;
			this.year -= 1;
		} else if (this.month > 12) {
			this.month = 1;
			this.year += 1;
		}
		this.refresh();
	}

	refresh() {
		frappe.call({
			method: "apc_operations.production.api.get_production_calendar_data",
			args: { year: this.year, month: this.month },
			freeze: true,
			freeze_message: __("Loading capacity calendar…"),
			callback: (r) => {
				this.data = r.message || {};
				this._render();
			},
		});
	}

	_render() {
		this._render_title();
		this._render_summary();
		this._render_grid();
	}

	_render_title() {
		this.$nav.find(".pc-title").text(`${this.data.month_name || ""} ${this.data.year || this.year}`);
	}

	_render_summary() {
		const days = this.data.days || [];
		const over = days.filter((d) => d.status === "Over").length;
		const within = days.filter((d) => d.status === "Within").length;
		const planned = days.reduce((acc, d) => acc + Object.keys(d.totals || {}).length, 0);

		this.$summary.html(`
			<div class="pc-summary-card pc-summary-red">
				<div class="pc-summary-label">${__("Over Capacity Days")}</div>
				<div class="pc-summary-value">${over}</div>
			</div>
			<div class="pc-summary-card pc-summary-green">
				<div class="pc-summary-label">${__("Within Capacity Days")}</div>
				<div class="pc-summary-value">${within}</div>
			</div>
			<div class="pc-summary-card pc-summary-blue">
				<div class="pc-summary-label">${__("Planned Buckets")}</div>
				<div class="pc-summary-value">${planned}</div>
			</div>
		`);
	}

	_render_grid() {
		this.$grid.empty();

		const day_labels = [
			__("Mon"), __("Tue"), __("Wed"), __("Thu"), __("Fri"), __("Sat"), __("Sun"),
		];
		const $headers = $('<div class="pc-headers"></div>').appendTo(this.$grid);
		day_labels.forEach((d) => $headers.append(`<div class="pc-head">${d}</div>`));

		const $cells = $('<div class="pc-cells"></div>').appendTo(this.$grid);

		const first_weekday = this.data.first_weekday || 0;
		for (let i = 0; i < first_weekday; i++) {
			$cells.append('<div class="pc-cell pc-cell-empty"></div>');
		}

		const today_str = frappe.datetime.get_today();
		(this.data.days || []).forEach((day) => {
			const cell_classes = ["pc-cell"];
			if (day.status === "Over") cell_classes.push("pc-cell-over");
			else if (day.status === "Within") cell_classes.push("pc-cell-within");
			if (day.date === today_str) cell_classes.push("pc-cell-today");

			const totals = day.totals || {};
			const capacities = day.capacities || {};
			const lines = Object.keys(totals)
				.sort()
				.map((category) => {
					const planned = totals[category];
					const cap = capacities[category];
					const over = cap !== undefined && planned > cap;
					const ratio = cap !== undefined
						? `${frappe.format(planned, { fieldtype: "Float" })} / ${frappe.format(cap, { fieldtype: "Float" })}`
						: `${frappe.format(planned, { fieldtype: "Float" })}`;
					return `<div class="pc-line ${over ? "pc-line-over" : ""}">
						<span class="pc-line-cat">${frappe.utils.escape_html(category)}</span>
						<span class="pc-line-val">${ratio}</span>
					</div>`;
				})
				.join("");

			const badge = day.status === "Over"
				? `<div class="pc-badge pc-badge-red">${__("Over Capacity")}</div>`
				: "";

			const $cell = $(`
				<div class="${cell_classes.join(" ")}">
					<div class="pc-cell-head">
						<span class="pc-day-num">${day.day}</span>
						${badge}
					</div>
					<div class="pc-cell-body">${lines || `<div class="pc-line pc-line-empty">${__("No orders")}</div>`}</div>
				</div>
			`);
			$cell.on("click", () => this._show_day_details(day));
			$cells.append($cell);
		});
	}

	_show_day_details(day) {
		const orders = day.orders || [];
		const dialog = new frappe.ui.Dialog({
			title: __("Production on {0}", [frappe.datetime.str_to_user(day.date)]),
			size: "large",
			fields: [
				{ fieldname: "summary", fieldtype: "HTML" },
				{ fieldname: "orders", fieldtype: "HTML" },
			],
			primary_action_label: __("New Production Order"),
			primary_action: () => {
				dialog.hide();
				frappe.new_doc("Production Order", { planned_date: day.date });
			},
		});

		const totals = day.totals || {};
		const capacities = day.capacities || {};
		const summary_rows = Object.keys(totals).sort().map((cat) => {
			const planned = totals[cat];
			const cap = capacities[cat];
			const over = cap !== undefined && planned > cap;
			return `<tr class="${over ? "pd-alert-row" : ""}">
				<td>${frappe.utils.escape_html(cat)}</td>
				<td class="num">${frappe.format(planned, { fieldtype: "Float" })}</td>
				<td class="num">${cap !== undefined ? frappe.format(cap, { fieldtype: "Float" }) : "—"}</td>
				<td class="num">${over ? `<span class="pd-over">+${frappe.format(planned - cap, { fieldtype: "Float" })}</span>` : "—"}</td>
			</tr>`;
		}).join("");

		dialog.fields_dict.summary.$wrapper.html(`
			<table class="pd-table">
				<thead><tr>
					<th>${__("Category")}</th>
					<th class="num">${__("Planned")}</th>
					<th class="num">${__("Capacity")}</th>
					<th class="num">${__("Over by")}</th>
				</tr></thead>
				<tbody>${summary_rows || `<tr><td colspan="4">${__("No production planned.")}</td></tr>`}</tbody>
			</table>
		`);

		const order_rows = orders.map((o) => `
			<tr>
				<td><a href="/app/production-order/${encodeURIComponent(o.name)}">${frappe.utils.escape_html(o.production_order_number || o.name)}</a></td>
				<td>${frappe.utils.escape_html(o.item_description || "—")}</td>
				<td>${frappe.utils.escape_html(o.category || "—")}</td>
				<td class="num">${frappe.format(o.qty, { fieldtype: "Float" })} ${frappe.utils.escape_html(o.uom || "")}</td>
				<td>${frappe.utils.escape_html(o.status || "")}</td>
			</tr>
		`).join("");

		dialog.fields_dict.orders.$wrapper.html(`
			<h6 style="margin-top:14px;">${__("Production Orders")}</h6>
			<table class="pd-table">
				<thead><tr>
					<th>${__("Order")}</th>
					<th>${__("Item")}</th>
					<th>${__("Category")}</th>
					<th class="num">${__("Qty")}</th>
					<th>${__("Status")}</th>
				</tr></thead>
				<tbody>${order_rows || `<tr><td colspan="5">${__("No production orders for this date.")}</td></tr>`}</tbody>
			</table>
		`);

		dialog.show();
	}
}
