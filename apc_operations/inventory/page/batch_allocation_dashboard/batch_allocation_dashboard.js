frappe.pages['batch-allocation-dashboard'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Batch Allocation'),
		single_column: true,
	});

	frappe.batch_allocation_dashboard = new BatchAllocationDashboard(page, wrapper);
};

frappe.pages['batch-allocation-dashboard'].on_page_show = function () {
	if (frappe.batch_allocation_dashboard) {
		frappe.batch_allocation_dashboard.apply_route_options();
		frappe.batch_allocation_dashboard.refresh();
	}
};

class BatchAllocationDashboard {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.filters = {};
		this.search_term = '';
		this.selected_demand = null;
		this.selected_batch = null;
		this.preview = null;
		this._build_layout();
		this.apply_route_options();
		this.refresh();
	}

	_build_layout() {
		this.$root = $(frappe.render_template('batch_allocation_dashboard', {})).appendTo(
			$(this.wrapper).find('.page-content').empty()
		);

		this._make_filters();
		this.$root.find('.bad-refresh').on('click', () => this.refresh());
		this.$root.find('.bad-clear').on('click', () => {
			this.filters = {};
			this.search_term = '';
			this.$root.find('.bad-search').val('');
			Object.values(this.filter_controls).forEach(control => control.set_value(''));
			this.selected_demand = null;
			this.selected_batch = null;
			this.preview = null;
			this.refresh();
		});
		this.$root.find('.bad-auto-allocate').on('click', () => this.auto_allocate_selected());
		this.$root.find('.bad-search').on('input', frappe.utils.debounce((event) => {
			this.search_term = event.target.value || '';
			this.render();
		}, 250));
	}

	_make_filters() {
		this.filter_controls = {};
		const fields = [
			{ fieldname: 'product', label: __('Product'), fieldtype: 'Link', options: 'Item' },
			{ fieldname: 'grade', label: __('Grade'), fieldtype: 'Data' },
			{ fieldname: 'warehouse', label: __('Warehouse'), fieldtype: 'Link', options: 'Warehouse' },
			{ fieldname: 'sales_demand', label: __('Sales Demand'), fieldtype: 'Link', options: 'APC Sales Demand' },
		];

		const $fields = this.$root.find('.bad-filter-fields');
		fields.forEach((df) => {
			const control = frappe.ui.form.make_control({
				df,
				parent: $('<div></div>').appendTo($fields),
				render_input: true,
			});
			control.$input.on('change', () => {
				this.filters[df.fieldname] = control.get_value();
			});
			this.filter_controls[df.fieldname] = control;
		});
	}

	apply_route_options() {
		if (!frappe.route_options) {
			return;
		}
		Object.entries(frappe.route_options).forEach(([key, value]) => {
			if (this.filter_controls?.[key]) {
				this.filter_controls[key].set_value(value);
				this.filters[key] = value;
			}
		});
		frappe.route_options = null;
	}

	refresh() {
		Promise.all([
			this.load_dashboard(),
			this.load_batches(),
			this.load_demands(),
		]).then(([dashboard, batches, demands]) => {
			this.dashboard = dashboard || {};
			this.batches = batches || [];
			this.demands = demands || [];
			if (!this.selected_batch || !this.batches.some(batch => batch.name === this.selected_batch.name)) {
				this.selected_batch = this.batches[0] || null;
			}
			if (this.selected_demand && !this.demands.some(demand => demand.sales_demand_item === this.selected_demand.sales_demand_item)) {
				this.selected_demand = null;
				this.preview = null;
			}
			this.render();
		});
	}

	load_dashboard() {
		return frappe.call({
			method: 'apc_operations.services.dashboard.get_batch_allocation_dashboard',
		}).then(r => r.message);
	}

	load_stock_status_summary() {
		return frappe.call({
			method: 'frappe.client.get_count',
			args: { doctype: 'APC Batch', filters: { stock_status: 'QC Hold', batch_status: 'Active' } },
		}).then(r1 => {
			return frappe.call({
				method: 'frappe.client.get_count',
				args: { doctype: 'APC Batch', filters: { stock_status: 'Available', batch_status: 'Active' } },
			}).then(r2 => {
				return frappe.call({
					method: 'frappe.client.get_count',
					args: { doctype: 'APC Batch', filters: { stock_status: 'Reserved' } },
				}).then(r3 => {
					return frappe.call({
						method: 'frappe.client.get_count',
						args: { doctype: 'APC Batch', filters: { stock_status: 'Dispatched' } },
					}).then(r4 => ({
						qc_hold: r1.message || 0,
						available: r2.message || 0,
						reserved: r3.message || 0,
						dispatched: r4.message || 0,
					}));
				});
			});
		});
	}

	render_stock_status_panel(counts) {
		if (!this.page) return;
		const html = `
		<div class="row" style="margin-bottom:16px">
			<div class="col-sm-3">
				<div class="stat-box" style="background:#fff3cd;border-radius:6px;padding:12px;text-align:center">
					<div style="font-size:1.8em;font-weight:bold;color:#856404">${counts.qc_hold}</div>
					<div style="color:#856404">${__('QC Hold')}</div>
				</div>
			</div>
			<div class="col-sm-3">
				<div class="stat-box" style="background:#d4edda;border-radius:6px;padding:12px;text-align:center">
					<div style="font-size:1.8em;font-weight:bold;color:#155724">${counts.available}</div>
					<div style="color:#155724">${__('Available')}</div>
				</div>
			</div>
			<div class="col-sm-3">
				<div class="stat-box" style="background:#cce5ff;border-radius:6px;padding:12px;text-align:center">
					<div style="font-size:1.8em;font-weight:bold;color:#004085">${counts.reserved}</div>
					<div style="color:#004085">${__('Reserved')}</div>
				</div>
			</div>
			<div class="col-sm-3">
				<div class="stat-box" style="background:#f8f9fa;border-radius:6px;padding:12px;text-align:center">
					<div style="font-size:1.8em;font-weight:bold;color:#495057">${counts.dispatched}</div>
					<div style="color:#495057">${__('Dispatched')}</div>
				</div>
			</div>
		</div>`;
		$(this.page).find('.stock-status-panel').html(html);
	}

	load_batches() {
		const filters = {
			batch_status: ['in', ['Active', 'On Hold']],
			quality_status: ['in', ['Approved', 'QC Cleared']],
			available_quantity: ['>', 0],
		};
		if (this.filters.product) filters.product = this.filters.product;
		if (this.filters.grade) filters.grade = this.filters.grade;
		if (this.filters.warehouse) filters.warehouse = this.filters.warehouse;

		return frappe.db.get_list('APC Batch', {
			filters,
			fields: [
				'name', 'batch_number', 'product', 'grade', 'specification', 'packaging_type',
				'available_quantity', 'allocated_quantity', 'manufacturing_date', 'expiry_date',
				'warehouse', 'linked_coa', 'erpnext_batch',
			],
			order_by: 'manufacturing_date asc, creation asc, name asc',
			limit: 100,
		});
	}

	load_demands() {
		return frappe.call({
			method: 'apc_operations.services.dashboard.get_pending_demands_for_allocation',
			args: { filters: this.filters },
		}).then(r => r.message || []);
	}

	render() {
		this.render_kpis();
		this.render_alerts();
		this.render_batches();
		this.render_demands();
		this.render_preview();
		this.render_suggestions();
		this.render_insights();
		this.render_batch_details();
	}

	render_kpis() {
		const kpis = this.dashboard.kpis || {};
		const pending_count = this.demands.length || kpis.total_pending_demand || 0;
		const batch_count = this.batches.length || kpis.total_active_batches || 0;
		const allocation_accuracy = this.get_allocation_accuracy();
		const fulfillment_rate = this.get_fulfillment_rate();
		const cards = [
			{ label: __('Pending Orders'), value: pending_count, icon: 'PO', tone: 'blue', helper: __('Need allocation') },
			{ label: __('Available Batches'), value: batch_count, icon: 'AB', tone: 'teal', helper: __('FIFO ready') },
			{ label: __('Allocation Accuracy'), value: allocation_accuracy, icon: 'AA', tone: 'purple', helper: __('Preview coverage'), suffix: '%' },
			{ label: __('Fulfillment Rate'), value: fulfillment_rate, icon: 'FR', tone: 'orange', helper: __('Allocated vs demand'), suffix: '%' },
		];

		this.$root.find('.bad-kpis').html(cards.map(card => `
			<div class="bad-kpi bad-kpi-${card.tone}">
				<div class="bad-kpi-icon">${card.icon}</div>
				<div>
					<div class="bad-kpi-label">${card.label}</div>
					<div class="bad-kpi-value">${frappe.format(card.value, { fieldtype: card.suffix ? 'Percent' : 'Int' })}${card.suffix ? '' : ''}</div>
					<div class="bad-kpi-helper">${card.helper}</div>
				</div>
			</div>
		`).join(''));
	}

	render_alerts() {
		const alerts = this.dashboard.alerts || [];
		this.$root.find('.bad-alerts').html(alerts.slice(0, 2).map(alert => `
			<div class="bad-alert bad-alert-${alert.type || 'info'}">
				<strong>${frappe.utils.escape_html(alert.title || '')}</strong>
				<span>${frappe.utils.escape_html(alert.message || '')}</span>
			</div>
		`).join(''));
	}

	render_batches() {
		const $tbody = this.$root.find('.bad-batches tbody').empty();
		const batches = this.get_filtered_batches();
		this.$root.find('.bad-batch-count').text(`(${batches.length})`);

		if (!batches.length) {
			$tbody.append(`<tr><td colspan="6" class="text-center text-muted">${__('No approved available batches found.')}</td></tr>`);
			return;
		}

		batches.forEach((batch) => {
			const is_active = this.selected_batch?.name === batch.name;
			const $row = $(`
				<tr class="${is_active ? 'active' : ''}" data-batch="${frappe.utils.escape_html(batch.name)}">
					<td>
						<div class="bad-radio-cell">
							<span class="bad-row-dot"></span>
							<a href="/app/apc-batch/${batch.name}">${frappe.utils.escape_html(batch.batch_number || batch.name)}</a>
						</div>
					</td>
					<td>${frappe.utils.escape_html(batch.erpnext_batch || batch.name || '')}</td>
					<td>${frappe.utils.escape_html(batch.warehouse || '')}</td>
					<td class="text-right">${frappe.format(batch.available_quantity, { fieldtype: 'Float' })}</td>
					<td>${this.format_date(batch.expiry_date)}</td>
					<td>${this.get_status_pill(batch.quality_status || __('Approved'), 'success')}</td>
				</tr>
			`);
			$row.on('click', (event) => {
				if (!$(event.target).is('a')) {
					this.selected_batch = batch;
					this.render_batches();
					this.render_batch_details();
				}
			});
			$tbody.append($row);
		});
	}

	render_demands() {
		const $tbody = this.$root.find('.bad-demands tbody').empty();
		const demands = this.get_filtered_demands();
		this.$root.find('.bad-demand-count').text(`(${demands.length})`);

		if (!demands.length) {
			$tbody.append(`<tr><td colspan="7" class="text-center text-muted">${__('No pending demand found.')}</td></tr>`);
			return;
		}

		demands.forEach((demand) => {
			const is_active = this.selected_demand?.sales_demand_item === demand.sales_demand_item;
			const priority = this.get_priority(demand.required_dispatch_date);
			const $row = $(`
				<tr class="${is_active ? 'active' : ''}" data-demand-item="${demand.sales_demand_item}">
					<td>
						<div class="bad-radio-cell">
							<span class="bad-row-dot"></span>
							<a href="/app/apc-sales-demand/${demand.sales_demand}">${frappe.utils.escape_html(demand.sales_demand)}</a>
						</div>
					</td>
					<td>${frappe.utils.escape_html(demand.item || '')}</td>
					<td>${frappe.utils.escape_html(demand.item_name || demand.item || '')}</td>
					<td class="text-right">${frappe.format(demand.pending_quantity, { fieldtype: 'Float' })}</td>
					<td>${this.format_date(demand.required_dispatch_date)}</td>
					<td>${this.get_status_pill(priority.label, priority.tone)}</td>
					<td>${this.get_status_pill(demand.status || __('Pending'), 'info')}</td>
				</tr>
			`);
			$row.on('click', (event) => {
				if (!$(event.target).is('a')) {
					this.selected_demand = demand;
					this.preview_selected_demand();
				}
			});
			$tbody.append($row);
		});
	}

	preview_selected_demand() {
		if (!this.selected_demand) {
			return;
		}

		frappe.call({
			method: 'apc_operations.services.dashboard.preview_fifo_allocation',
			args: {
				sales_demand: this.selected_demand.sales_demand,
				items: [this.selected_demand.sales_demand_item],
			},
			freeze: true,
		}).then((r) => {
			this.preview = r.message || {};
			this.render_kpis();
			this.render_demands();
			this.render_preview();
			this.render_suggestions();
		});
	}

	render_preview() {
		const rows = this.preview?.allocations || [];
		const shortages = this.preview?.shortages || [];
		const $empty = this.$root.find('.bad-preview-empty');
		const $table = this.$root.find('.bad-preview');
		const $tbody = $table.find('tbody').empty();
		const required_qty = this.selected_demand ? flt(this.selected_demand.pending_quantity) : 0;
		const allocated_qty = rows.reduce((total, row) => total + flt(row.allocated_quantity), 0);
		const progress = required_qty ? Math.min(100, (allocated_qty / required_qty) * 100) : 0;

		this.$root.find('.bad-progress-bar').css('width', `${progress}%`);
		this.$root.find('.bad-progress-percent').text(`${Math.round(progress)}%`);
		this.$root.find('.bad-selected-summary').text(
			this.selected_demand
				? `${this.selected_demand.sales_demand} - ${this.selected_demand.item || this.selected_demand.item_name || ''}`
				: __('Select a pending order to preview allocation.')
		);
		this.$root.find('.bad-workspace-meta').html(this.selected_demand ? `
			<span><strong>${__('Qty Required')}</strong>${frappe.format(required_qty, { fieldtype: 'Float' })}</span>
			<span><strong>${__('Allocated')}</strong>${frappe.format(allocated_qty, { fieldtype: 'Float' })}</span>
			<span><strong>${__('Shortage')}</strong>${frappe.format(Math.max(0, required_qty - allocated_qty), { fieldtype: 'Float' })}</span>
			<span><strong>${__('Due Date')}</strong>${this.format_date(this.selected_demand.required_dispatch_date)}</span>
		` : '');

		if (!rows.length) {
			$empty.show();
			$table.hide();
		} else {
			$empty.hide();
			$table.show();
			rows.forEach((row) => {
				const percent = required_qty ? (flt(row.allocated_quantity) / required_qty) * 100 : 0;
				$tbody.append(`
					<tr>
						<td><a href="/app/apc-batch/${row.batch}">${frappe.utils.escape_html(row.batch_number || row.batch)}</a></td>
						<td>${frappe.utils.escape_html(row.batch || '')}</td>
						<td>${frappe.utils.escape_html(row.warehouse || '')}</td>
						<td>${this.format_date(row.expiry_date || row.manufacturing_date)}</td>
						<td class="text-right">${frappe.format(row.allocated_quantity, { fieldtype: 'Float' })}</td>
						<td>
							<div class="bad-mini-progress">
								<span style="width: ${Math.min(100, percent)}%"></span>
							</div>
							<small>${frappe.format(percent, { fieldtype: 'Percent' })}</small>
						</td>
						<td>${this.get_status_pill(__('Recommended'), 'warning')}</td>
					</tr>
				`);
			});
		}

		this.$root.find('.bad-shortages').html(shortages.map(shortage => `
			<div class="bad-alert bad-alert-warning">
				${__('Shortage for {0}: {1}', [
					frappe.utils.escape_html(shortage.item || ''),
					frappe.format(shortage.required_qty, { fieldtype: 'Float' }),
				])}
			</div>
		`).join(''));
		this.$root.find('.bad-auto-allocate').prop('disabled', !this.selected_demand || !rows.length);
	}

	render_suggestions() {
		const rows = (this.preview?.allocations || []).slice(0, 3);
		const $suggestions = this.$root.find('.bad-suggestions').empty();

		if (!rows.length) {
			$suggestions.html(`<div class="bad-empty-card">${__('Select an order to see FIFO suggestions.')}</div>`);
			return;
		}

		rows.forEach((row, index) => {
			$suggestions.append(`
				<div class="bad-suggestion">
					<div>
						<strong>${frappe.utils.escape_html(row.batch_number || row.batch)}</strong>
						<span>${frappe.utils.escape_html(row.warehouse || '')} - ${this.format_date(row.manufacturing_date)}</span>
					</div>
					<div class="bad-suggestion-qty">${frappe.format(row.allocated_quantity, { fieldtype: 'Float' })}</div>
					${index === 0 ? '<span class="bad-badge best">Best Match</span>' : ''}
				</div>
			`);
		});
	}

	render_insights() {
		const total = this.batches.length;
		const expiring_soon = this.batches.filter(batch => this.days_until(batch.expiry_date) <= 30).length;
		const healthy = Math.max(0, total - expiring_soon);
		const utilization = total ? Math.round((healthy / total) * 100) : 0;

		this.$root.find('.bad-donut-value').text(total);
		this.$root.find('.bad-donut-ring').css('--bad-donut-fill', `${utilization}%`);
		this.$root.find('.bad-donut-legend').html(`
			<div><span class="dot high"></span>${__('Healthy stock')} <strong>${healthy}</strong></div>
			<div><span class="dot medium"></span>${__('Expiring soon')} <strong>${expiring_soon}</strong></div>
			<div><span class="dot low"></span>${__('Pending COA')} <strong>${this.dashboard.kpis?.pending_coa_approvals || 0}</strong></div>
		`);
		this.$root.find('.bad-expiry-insight').html(`
			<strong>${__('Expiry risk next 30 days')}</strong>
			<span>${expiring_soon ? __('{0} batch(es) need review.', [expiring_soon]) : __('No immediate expiry risk.')}</span>
		`);
	}

	render_batch_details() {
		const visible_batches = this.get_filtered_batches();
		const selected_is_visible = this.selected_batch
			&& visible_batches.some(batch => batch.name === this.selected_batch.name);
		const batch = selected_is_visible ? this.selected_batch : visible_batches[0];
		const $content = this.$root.find('.bad-details-content');

		if (!batch) {
			$content.html(`<div class="bad-empty-card">${__('No batch selected.')}</div>`);
			return;
		}

		this.selected_batch = batch;
		const reserved_qty = flt(batch.allocated_quantity);
		const available_qty = flt(batch.available_quantity);
		const total_qty = available_qty + reserved_qty;
		const reserved_percent = total_qty ? Math.round((reserved_qty / total_qty) * 100) : 0;

		$content.html(`
			<div class="bad-detail-title">
				<div>
					<h3>${frappe.utils.escape_html(batch.batch_number || batch.name)}</h3>
					<span>${this.get_status_pill(batch.quality_status || __('Approved'), 'success')}</span>
				</div>
				<a href="/app/apc-batch/${batch.name}" class="btn btn-default btn-xs">${__('Open')}</a>
			</div>
			<div class="bad-detail-tabs">
				<span class="active">${__('Overview')}</span>
				<span>${__('Quality')}</span>
				<span>${__('Movements')}</span>
				<span>${__('History')}</span>
			</div>
			${this.detail_row(__('Product'), batch.product)}
			${this.detail_row(__('Lot / ERP Batch'), batch.erpnext_batch || batch.name)}
			${this.detail_row(__('Warehouse'), batch.warehouse)}
			${this.detail_row(__('Available Quantity'), frappe.format(available_qty, { fieldtype: 'Float' }))}
			${this.detail_row(__('Reserved Quantity'), frappe.format(reserved_qty, { fieldtype: 'Float' }))}
			${this.detail_row(__('Expiry Date'), `${this.format_date(batch.expiry_date)} ${this.expiry_badge(batch.expiry_date)}`, true)}
			${this.detail_row(__('Mfg. Date'), this.format_date(batch.manufacturing_date))}
			${this.detail_row(__('Linked COA'), batch.linked_coa || __('Not linked'))}
			<div class="bad-detail-meter">
				<div><strong>${__('Reserved')}</strong><span>${reserved_percent}%</span></div>
				<div class="bad-progress-track"><div class="bad-progress-bar" style="width: ${reserved_percent}%"></div></div>
			</div>
			<a href="/app/apc-batch/${batch.name}" class="btn btn-primary btn-block">${__('View Full Details')}</a>
		`);
	}

	get_filtered_batches() {
		if (!this.search_term) {
			return this.batches;
		}
		const term = this.search_term.toLowerCase();
		return this.batches.filter(batch => [
			batch.name, batch.batch_number, batch.erpnext_batch, batch.product, batch.grade, batch.warehouse,
		].some(value => String(value || '').toLowerCase().includes(term)));
	}

	get_filtered_demands() {
		if (!this.search_term) {
			return this.demands;
		}
		const term = this.search_term.toLowerCase();
		return this.demands.filter(demand => [
			demand.sales_demand, demand.customer, demand.customer_name, demand.item, demand.item_name, demand.grade,
		].some(value => String(value || '').toLowerCase().includes(term)));
	}

	get_allocation_accuracy() {
		const rows = this.preview?.allocations || [];
		if (!this.selected_demand || !rows.length) {
			return 0;
		}
		const required_qty = flt(this.selected_demand.pending_quantity);
		const allocated_qty = rows.reduce((total, row) => total + flt(row.allocated_quantity), 0);
		return required_qty ? Math.round(Math.min(100, (allocated_qty / required_qty) * 100)) : 0;
	}

	get_fulfillment_rate() {
		const total_demand = this.demands.reduce((total, demand) => total + flt(demand.demand_quantity), 0);
		const allocated = this.demands.reduce((total, demand) => total + flt(demand.allocated_quantity), 0);
		return total_demand ? Math.round((allocated / total_demand) * 100) : 0;
	}

	get_priority(date) {
		const days = this.days_until(date);
		if (days < 0) return { label: __('Urgent'), tone: 'danger' };
		if (days <= 3) return { label: __('High'), tone: 'warning' };
		return { label: __('Low'), tone: 'success' };
	}

	get_status_pill(label, tone = 'info') {
		return `<span class="bad-pill bad-pill-${tone}">${frappe.utils.escape_html(label || '')}</span>`;
	}

	format_date(date) {
		return date ? frappe.datetime.str_to_user(date) : '';
	}

	days_until(date) {
		if (!date) {
			return 9999;
		}
		return frappe.datetime.get_diff(date, frappe.datetime.get_today());
	}

	expiry_badge(date) {
		const days = this.days_until(date);
		if (days <= 30) {
			return `<span class="bad-muted-warning">(${days} ${__('days left')})</span>`;
		}
		return '';
	}

	detail_row(label, value, allow_html = false) {
		const rendered_value = allow_html ? (value || '') : frappe.utils.escape_html(value || '');
		return `
			<div class="bad-detail-row">
				<span>${frappe.utils.escape_html(label || '')}</span>
				<strong>${rendered_value}</strong>
			</div>
		`;
	}

	auto_allocate_selected() {
		if (!this.selected_demand) {
			frappe.msgprint(__('Select a demand row first.'));
			return;
		}

		frappe.confirm(
			__('Create FIFO batch allocation for {0}?', [this.selected_demand.sales_demand]),
			() => {
				frappe.call({
					method: 'apc_operations.services.batch_allocation.allocate_batches_fifo',
					args: {
						sales_demand: this.selected_demand.sales_demand,
						items: [this.selected_demand.sales_demand_item],
					},
					freeze: true,
					callback: (r) => {
						if (r.message?.allocation) {
							frappe.set_route('Form', 'APC Batch Allocation', r.message.allocation);
						} else {
							frappe.msgprint(r.message?.message || __('No allocation was created.'));
						}
					},
				});
			}
		);
	}
}
