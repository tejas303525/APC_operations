frappe.pages["stock-console"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Stock Console"),
		single_column: true,
	});

	page.set_secondary_action(__("Refresh"), () => {
		if (frappe.stock_console) frappe.stock_console.refresh();
	}, "refresh");

	frappe.stock_console = new StockConsole(page, wrapper);
};

frappe.pages["stock-console"].on_page_show = function () {
	if (frappe.stock_console) frappe.stock_console.refresh();
};

class StockConsole {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.expanded = {};
		this.batch_cache = {};
		this.filters = { search: "", stock: "all", min: null, max: null };
		this._build_layout();
		this.refresh();
	}

	_build_layout() {
		const root = $(this.wrapper).find(".page-content");
		root.css({ padding: "0" });

		this.$root = $('<div class="stock-console"></div>').appendTo(root);
		this.$root.html(`
			<div class="sc-hero">
				<div>
					<h2>${__("Stock Console")}</h2>
					<p>${__("Free stock, reservations, and in-transit quantities by product. Click a product to see its batches and what each reservation is held against.")}</p>
				</div>
			</div>
			<div class="sc-kpi-strip"></div>
			<div class="sc-toolbar">
				<input type="text" class="sc-search-input form-control" placeholder="${__("Search by product name or code...")}">
				<select class="sc-stock-filter form-control">
					<option value="all">${__("All Stock Levels")}</option>
					<option value="in_stock">${__("In Stock (> 0)")}</option>
					<option value="out_of_stock">${__("Out of Stock (0)")}</option>
					<option value="custom">${__("Custom Range...")}</option>
				</select>
				<div class="sc-custom-range" style="display:none;">
					<input type="number" class="sc-min-qty form-control" placeholder="${__("Min")}">
					<span>${__("to")}</span>
					<input type="number" class="sc-max-qty form-control" placeholder="${__("Max")}">
					<button class="btn btn-xs btn-default sc-apply-range">${__("Apply")}</button>
				</div>
				<span class="sc-result-count"></span>
			</div>
			<div class="sc-body">
				<table class="sc-table">
					<thead>
						<tr>
							<th style="width:28px;"></th>
							<th>${__("Product")}</th>
							<th class="num">${__("Stock In Hand")}</th>
							<th class="num">${__("Reserved")}</th>
							<th class="num">${__("Free / Excess")}</th>
							<th class="num">${__("In Transit")}</th>
						</tr>
					</thead>
					<tbody class="sc-product-body"></tbody>
				</table>
			</div>
		`);

		this._bind_toolbar();
	}

	_bind_toolbar() {
		const $toolbar = this.$root.find(".sc-toolbar");

		$toolbar.find(".sc-search-input").on("input", (e) => {
			this.filters.search = (e.target.value || "").trim().toLowerCase();
			this._apply_filters();
		});

		$toolbar.find(".sc-stock-filter").on("change", (e) => {
			this.filters.stock = e.target.value;
			$toolbar.find(".sc-custom-range").toggle(this.filters.stock === "custom");
			if (this.filters.stock !== "custom") {
				this.filters.min = null;
				this.filters.max = null;
				this._apply_filters();
			}
		});

		const apply_range = () => {
			const min = $toolbar.find(".sc-min-qty").val();
			const max = $toolbar.find(".sc-max-qty").val();
			this.filters.min = min === "" ? null : flt(min);
			this.filters.max = max === "" ? null : flt(max);
			this._apply_filters();
		};
		$toolbar.find(".sc-apply-range").on("click", apply_range);
		$toolbar.find(".sc-min-qty, .sc-max-qty").on("keydown", (e) => {
			if (e.key === "Enter") apply_range();
		});
	}

	refresh() {
		frappe.call({
			method: "apc_operations.inventory.api.get_stock_console_data",
			freeze: true,
			callback: (r) => {
				this.data = r.message || { kpis: {}, products: [] };
				this._render();
			},
		});
	}

	_render() {
		this._render_kpis(this.data.kpis || {});
		this._apply_filters();
	}

	_apply_filters() {
		const all_products = this.data.products || [];
		const { search, stock, min, max } = this.filters;

		const filtered = all_products.filter((p) => {
			if (search) {
				const haystack = `${p.product || ""} ${p.item_name || ""}`.toLowerCase();
				if (!haystack.includes(search)) return false;
			}

			const qty = flt(p.stock_in_hand);
			if (stock === "in_stock" && !(qty > 0)) return false;
			if (stock === "out_of_stock" && !(qty <= 0)) return false;
			if (stock === "custom") {
				if (min !== null && qty < min) return false;
				if (max !== null && qty > max) return false;
			}

			return true;
		});

		this.$root.find(".sc-result-count").text(
			__("{0} of {1} products", [filtered.length, all_products.length])
		);
		this._render_products(filtered);
	}

	_render_kpis(kpis) {
		const $strip = this.$root.find(".sc-kpi-strip").empty();
		const cards = [
			{ label: __("Products in Stock"), value: kpis.total_products || 0 },
			{ label: __("Stock In Hand (KG)"), value: this._fmt(kpis.total_stock_in_hand) },
			{ label: __("Reserved (KG)"), value: this._fmt(kpis.total_reserved) },
			{ label: __("Free / Excess (KG)"), value: this._fmt(kpis.total_free) },
			{ label: __("In Transit (KG)"), value: this._fmt(kpis.total_in_transit) },
		];
		cards.forEach((c) => {
			$strip.append(`
				<div class="sc-kpi-card">
					<div class="sc-kpi-label">${c.label}</div>
					<div class="sc-kpi-value">${c.value}</div>
				</div>
			`);
		});
	}

	_render_products(products) {
		const $body = this.$root.find(".sc-product-body").empty();

		if (!products.length) {
			const has_active_filter = this.filters.search || this.filters.stock !== "all";
			const message = has_active_filter
				? __("No products match the current search/filter.")
				: __("No batches recorded yet.");
			$body.append(`<tr><td colspan="6" class="sc-empty">${message}</td></tr>`);
			return;
		}

		products.forEach((p) => {
			const $row = $(`
				<tr class="sc-product-row" data-product="${frappe.utils.escape_html(p.product)}">
					<td><span class="sc-caret">&#9656;</span></td>
					<td>${frappe.utils.escape_html(p.item_name || p.product)}</td>
					<td class="num">${this._fmt(p.stock_in_hand)} <span class="sc-uom">${frappe.utils.escape_html(p.uom || "")}</span></td>
					<td class="num">${this._fmt(p.reserved_qty)} <span class="sc-uom">${frappe.utils.escape_html(p.uom || "")}</span></td>
					<td class="num">${this._fmt(p.free_qty)} <span class="sc-uom">${frappe.utils.escape_html(p.uom || "")}</span></td>
					<td class="num">${this._fmt(p.in_transit)} <span class="sc-uom">${frappe.utils.escape_html(p.uom || "")}</span></td>
				</tr>
				<tr class="sc-detail-row" style="display:none;"><td colspan="6"></td></tr>
			`);
			$body.append($row);
		});

		$body.find(".sc-product-row").on("click", (e) => {
			const $row = $(e.currentTarget);
			const product = $row.data("product");
			const $detail = $row.next(".sc-detail-row");
			const showing = $detail.is(":visible");

			$body.find(".sc-detail-row").hide();
			$body.find(".sc-product-row").removeClass("expanded");

			if (showing) return;

			$row.addClass("expanded");
			$detail.show();
			this._render_batch_detail(product, $detail.find("td"));
		});
	}

	_render_batch_detail(product, $target) {
		$target.html(`<div class="sc-loading">${__("Loading batches...")}</div>`);

		frappe.call({
			method: "apc_operations.inventory.api.get_batch_detail_for_product",
			args: { product },
			callback: (r) => {
				const batches = r.message || [];

				const $wrap = $('<div class="sc-batch-wrap"></div>');
				const $addBar = $(`
					<div class="sc-batch-head" style="margin-bottom:8px;">
						<div></div>
						<button class="btn btn-xs btn-primary sc-add-stock-btn">${__("+ Add Stock")}</button>
					</div>
				`);
				$addBar.find(".sc-add-stock-btn").on("click", () => this._open_add_stock_dialog(product, $target));
				$wrap.append($addBar);

				if (!batches.length) {
					$wrap.append(`<div class="sc-empty">${__("No batches for this product yet. Add stock to create one.")}</div>`);
					$target.empty().append($wrap);
					return;
				}

				batches.forEach((b) => {
					const $card = $(`
						<div class="sc-batch-card" data-batch="${frappe.utils.escape_html(b.name)}">
							<div class="sc-batch-head">
								<div>
									<div class="sc-batch-name">${frappe.utils.escape_html(b.batch_number || b.name)}</div>
									<div class="sc-batch-meta">
										${__("Mfg")}: ${b.manufacturing_date ? frappe.datetime.str_to_user(b.manufacturing_date) : "-"}
										&nbsp;&middot;&nbsp; ${frappe.utils.escape_html(b.warehouse || "-")}
										&nbsp;&middot;&nbsp; ${frappe.utils.escape_html(b.quality_status || "-")}
									</div>
								</div>
								<button class="btn btn-xs btn-default sc-adjust-btn">${__("Adjust Stock")}</button>
							</div>
							<div class="sc-batch-nums">
								<span>${__("Available")}<b>${this._fmt(b.available_quantity)} ${frappe.utils.escape_html(b.uom || "")}</b></span>
								<span>${__("Reserved")}<b>${this._fmt(b.allocated_quantity)}</b></span>
								<span>${__("Dispatched")}<b>${this._fmt(b.dispatched_quantity)}</b></span>
							</div>
							<div class="sc-reservations"></div>
						</div>
					`);

					const $res = $card.find(".sc-reservations");
					if (b.reservations && b.reservations.length) {
						b.reservations.forEach((res) => {
							$res.append(`
								<div class="sc-reservation-row">
									<span>
										${res.job_order
											? `<a href="/app/job-order/${encodeURIComponent(res.job_order)}">${frappe.utils.escape_html(res.job_order_number || res.job_order)}</a>`
											: __("(no Job Order linked)")}
										&nbsp;-&nbsp;${frappe.utils.escape_html(res.customer_name || res.customer || "-")}
									</span>
									<span>${this._fmt(res.remaining_quantity)}</span>
								</div>
							`);
						});
					} else {
						$res.append(`<div class="sc-empty">${__("Not reserved against any order.")}</div>`);
					}

					$card.find(".sc-adjust-btn").on("click", () => this._open_adjust_dialog(b, product));
					$wrap.append($card);
				});

				$target.empty().append($wrap);
			},
		});
	}

	_open_adjust_dialog(batch, product) {
		frappe.prompt(
			[
				{
					fieldname: "adjustment_qty",
					fieldtype: "Float",
					label: __("Adjustment (+ to add, - to subtract)"),
					reqd: 1,
				},
				{
					fieldname: "reason",
					fieldtype: "Small Text",
					label: __("Reason"),
					reqd: 1,
				},
			],
			(values) => {
				frappe.call({
					method: "apc_operations.inventory.api.adjust_batch_stock",
					args: {
						batch: batch.name,
						adjustment_qty: values.adjustment_qty,
						reason: values.reason,
					},
					freeze: true,
					callback: () => {
						frappe.show_alert({ message: __("Stock adjusted"), indicator: "green" });
						this.refresh();
					},
				});
			},
			__("Adjust Stock - {0}", [batch.batch_number || batch.name]),
			__("Apply")
		);
	}

	_open_add_stock_dialog(product) {
		frappe.prompt(
			[
				{
					fieldname: "quantity",
					fieldtype: "Float",
					label: __("Quantity"),
					reqd: 1,
				},
				{
					fieldname: "warehouse",
					fieldtype: "Link",
					options: "Warehouse",
					label: __("Warehouse"),
				},
				{
					fieldname: "manufacturing_date",
					fieldtype: "Date",
					label: __("Manufacturing / Stock-take Date"),
					default: frappe.datetime.get_today(),
				},
				{
					fieldname: "remarks",
					fieldtype: "Small Text",
					label: __("Remarks"),
				},
			],
			(values) => {
				frappe.call({
					method: "apc_operations.inventory.api.add_opening_stock",
					args: {
						product,
						quantity: values.quantity,
						warehouse: values.warehouse,
						manufacturing_date: values.manufacturing_date,
						remarks: values.remarks,
					},
					freeze: true,
					callback: () => {
						frappe.show_alert({ message: __("Stock added"), indicator: "green" });
						this.refresh();
					},
				});
			},
			__("Add Stock"),
			__("Add")
		);
	}

	_fmt(n) {
		n = flt(n);
		return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
	}
}
