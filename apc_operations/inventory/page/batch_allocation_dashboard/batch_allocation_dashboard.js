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
	}
};

class BatchAllocationDashboard {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.step = 'products';
		this.search_term = '';
		this.product_lines = [];
		this.selected_product = null;
		this.job_order_lines_data = null;
		this.selected_job_order = null;
		this.selected_line = null;
		this.batch_data = null;
		this.allocate_inputs = {};

		this._build_layout();
		this.apply_route_options();
		this.refresh_products();
	}

	_build_layout() {
		this.$root = $(frappe.render_template('batch_allocation_dashboard', {})).appendTo(
			$(this.wrapper).find('.page-content').empty()
		);

		this.$root.find('.bad-btn-refresh').on('click', () => this.refresh_current_step());
		this.$root.find('.bad-search-products').on(
			'input',
			frappe.utils.debounce((event) => {
				this.search_term = event.target.value || '';
				this.render_products();
			}, 250)
		);

		this.$root.find('.bad-step-tab-products').on('click', () => {
			if (!this.$root.find('.bad-step-tab-products').prop('disabled')) {
				this.go_to_step('products');
			}
		});
		this.$root.find('.bad-step-tab-job-orders').on('click', () => {
			if (!this.$root.find('.bad-step-tab-job-orders').prop('disabled') && this.selected_product) {
				this.go_to_step('job_orders');
			}
		});
		this.$root.find('.bad-back-to-products').on('click', () => this.go_to_step('products'));
		this.$root.find('.bad-back-to-job-orders').on('click', () => this.go_to_step('job_orders'));
		this.$root.find('.bad-auto-fifo').on('click', () => this.run_auto_fifo());
		this.$root.find('.bad-save-allocation').on('click', () => this.save_allocation());
		this.$root.find('.bad-batch-table tbody').on('click', '.bad-create-coa', (event) => {
			this.create_coa($(event.currentTarget).data('batch'));
		});
	}

	apply_route_options() {
		if (!frappe.route_options) {
			return;
		}
		const { job_order, job_order_item } = frappe.route_options;
		frappe.route_options = null;

		if (!job_order) {
			return;
		}

		frappe.call({
			method: 'apc_operations.services.job_order_allocation_dashboard.get_job_order_allocation_lines',
			args: { job_order },
			freeze: true,
		}).then((r) => {
			const lines = r.message?.lines || [];
			const line = job_order_item
				? lines.find((row) => row.job_order_item === job_order_item)
				: lines.find((row) => row.can_allocate) || lines[0];

			if (!line) {
				return;
			}

			this.selected_product = {
				product: line.item,
				item_name: line.item_name,
				grade: line.grade,
				specification: line.specification,
				packaging_type: line.packaging_type,
				warehouse: line.warehouse,
			};
			this.selected_job_order = job_order;
			this.selected_line = line;

			if (line.can_allocate) {
				this.load_batches(job_order, line.job_order_item);
			} else {
				this.load_job_orders_for_product(this.selected_product).then(() => this.go_to_step('job_orders'));
			}
		});
	}

	refresh_current_step() {
		if (this.step === 'products') {
			this.refresh_products();
		} else if (this.step === 'job_orders' && this.selected_product) {
			this.load_job_orders_for_product(this.selected_product);
		} else if (this.step === 'allocate' && this.selected_line) {
			this.load_batches(this.selected_job_order, this.selected_line.job_order_item);
		}
	}

	go_to_step(step) {
		this.step = step;
		this.$root.find('.bad-step-tab').removeClass('active');
		this.$root.find(`.bad-step-tab-${step === 'job_orders' ? 'job-orders' : step}`).addClass('active');

		this.$root.find('.bad-step').hide();
		this.$root.find(`.bad-step-${step === 'job_orders' ? 'job-orders' : step}`).show();

		this.$root.find('.bad-step-tab-products').prop('disabled', false);
		this.$root.find('.bad-step-tab-job-orders').prop('disabled', !this.selected_product);
		this.$root.find('.bad-step-tab-allocate').prop('disabled', !this.selected_line);

		this.render_context_bar();
	}

	refresh_products(keep_step = false) {
		return frappe.call({
			method: 'apc_operations.services.job_order_allocation_dashboard.get_product_lines_for_allocation_dashboard',
			args: { filters: { search: this.search_term || undefined } },
			freeze: true,
		}).then((r) => {
			this.product_lines = r.message || [];
			this.render_products();
			if (!keep_step) {
				this.go_to_step('products');
			}
		});
	}

	load_job_orders_for_product(product) {
		return frappe.call({
			method: 'apc_operations.services.job_order_allocation_dashboard.get_job_orders_for_product_line',
			args: {
				product: product.product,
				grade: product.grade,
				specification: product.specification,
				packaging_type: product.packaging_type,
				warehouse: product.warehouse,
			},
			freeze: true,
		}).then((r) => {
			this.job_order_lines_data = r.message || {};
			this.selected_product = product;
			this.render_job_orders();
			this.render_context_bar();
		});
	}

	load_batches(job_order, job_order_item) {
		return frappe.call({
			method: 'apc_operations.services.job_order_allocation_dashboard.get_batches_for_job_order_line',
			args: { job_order, job_order_item },
			freeze: true,
		}).then((r) => {
			this.batch_data = r.message || {};
			this.selected_job_order = job_order;
			this.allocate_inputs = {};
			(this.batch_data.batches || []).forEach((batch) => {
				this.allocate_inputs[batch.name] = 0;
			});
			this.render_batches();
			this.go_to_step('allocate');
		});
	}

	open_product(product) {
		this.selected_product = product;
		this.selected_job_order = null;
		this.selected_line = null;
		this.batch_data = null;
		this.load_job_orders_for_product(product).then(() => this.go_to_step('job_orders'));
	}

	open_allocation(line) {
		this.selected_job_order = line.job_order;
		this.selected_line = line;
		this.load_batches(line.job_order, line.job_order_item);
	}

	render_context_bar() {
		const $bar = this.$root.find('.bad-context-bar').empty();
		if (this.step === 'products') {
			return;
		}

		const product = this.selected_product || this.job_order_lines_data?.product || {};
		const product_label = product.item_name || product.product || '';
		const parts = [
			`<strong>${frappe.utils.escape_html(product_label)}</strong>`,
			product.grade ? `<span>${__('Grade')}: ${frappe.utils.escape_html(product.grade)}</span>` : '',
			product.warehouse ? `<span>${__('Warehouse')}: ${frappe.utils.escape_html(product.warehouse)}</span>` : '',
		];

		if (this.step === 'allocate' && this.batch_data?.context) {
			const ctx = this.batch_data.context;
			parts.push(
				`<span>${__('JO')}: ${frappe.utils.escape_html(ctx.job_order_number || ctx.job_order || '')}</span>`,
				`<span>${frappe.utils.escape_html(ctx.customer_name || '')}</span>`,
				ctx.date ? `<span>${__('Due')}: ${frappe.datetime.str_to_user(ctx.date)}</span>` : '',
				`<a href="/app/job-order/${ctx.job_order}" class="bad-context-link">${__('Open Job Order')}</a>`
			);
		}

		$bar.html(`<div class="bad-context-inner">${parts.filter(Boolean).join('')}</div>`);
	}

	render_products() {
		const $tbody = this.$root.find('.bad-products-table tbody').empty();
		const rows = this.get_filtered_products();

		if (!rows.length) {
			$tbody.append(`<tr><td colspan="9" class="text-center text-muted">${__('No pending product demand found.')}</td></tr>`);
			return;
		}

		rows.forEach((row) => {
			const tone = row.coverage_status === 'Covered' ? 'success'
				: row.coverage_status === 'Partial' ? 'warning'
					: row.coverage_status === 'Shortage' ? 'danger' : 'info';

			const $tr = $(`
				<tr>
					<td>
						<strong>${frappe.utils.escape_html(row.item_name || row.product || '')}</strong>
						<div class="bad-muted">${frappe.utils.escape_html(row.product || '')}</div>
					</td>
					<td>${frappe.utils.escape_html(row.grade || '')}</td>
					<td>
						<div>${frappe.utils.escape_html(row.specification || '')}</div>
						<div class="bad-muted">${frappe.utils.escape_html(row.packaging_type || '')}</div>
					</td>
					<td>${frappe.utils.escape_html(row.warehouse || '')}</td>
					<td class="text-right"><strong>${frappe.format(row.total_pending_qty, { fieldtype: 'Float' })}</strong></td>
					<td class="text-right">${frappe.format(row.available_fifo_stock, { fieldtype: 'Float' })}</td>
					<td>${row.job_order_count || 0} ${__('orders')} · ${row.lines_pending_count || 0} ${__('lines')}</td>
					<td>${this.get_status_pill(row.coverage_status, tone)}</td>
					<td class="text-right">
						<button type="button" class="btn btn-primary btn-xs bad-open-product">${__('Open')}</button>
					</td>
				</tr>
			`);

			$tr.find('.bad-open-product').on('click', () => this.open_product(row));
			$tbody.append($tr);
		});
	}

	render_job_orders() {
		const $tbody = this.$root.find('.bad-job-orders-table tbody').empty();
		const product = this.job_order_lines_data?.product || this.selected_product || {};
		const lines = this.job_order_lines_data?.lines || [];

		this.$root.find('.bad-job-orders-subtitle').text(
			`${product.item_name || product.product || ''} · ${__('Pending')}: ${frappe.format(product.total_pending_qty || 0, { fieldtype: 'Float' })} · ${__('FIFO stock')}: ${frappe.format(product.available_fifo_stock || 0, { fieldtype: 'Float' })}`
		);

		if (!lines.length) {
			$tbody.append(`<tr><td colspan="8" class="text-center text-muted">${__('No Job Orders with pending quantity for this product.')}</td></tr>`);
			return;
		}

		lines.forEach((line) => {
			const tone = line.line_status === 'Partial' ? 'warning' : 'info';
			const overdue = line.is_overdue ? `<span class="bad-pill bad-pill-danger">${__('Overdue')}</span>` : '';
			const $tr = $(`
				<tr class="${line.line_status === 'Complete' ? 'bad-row-muted' : ''}">
					<td>
						<a href="/app/job-order/${line.job_order}">${frappe.utils.escape_html(line.job_order_number || line.job_order)}</a>
						${overdue}
					</td>
					<td>${frappe.utils.escape_html(line.customer_name || '')}</td>
					<td>${line.date ? frappe.datetime.str_to_user(line.date) : ''}</td>
					<td class="text-right">${frappe.format(line.required_qty, { fieldtype: 'Float' })}</td>
					<td class="text-right">${frappe.format(line.allocated_qty, { fieldtype: 'Float' })}</td>
					<td class="text-right"><strong>${frappe.format(line.pending_qty, { fieldtype: 'Float' })}</strong></td>
					<td>${this.get_status_pill(line.line_status, tone)}</td>
					<td class="text-right">
						<button type="button" class="btn btn-primary btn-xs bad-open-line" ${line.can_allocate ? '' : 'disabled'}>${__('Allocate')}</button>
					</td>
				</tr>
			`);

			if (!line.can_allocate && line.allocation_block_reason) {
				$tr.find('.bad-open-line').attr('title', line.allocation_block_reason);
			}
			$tr.find('.bad-open-line').on('click', () => this.open_allocation(line));
			$tbody.append($tr);
		});

		this.$root.find('.bad-step-tab-job-orders').prop('disabled', false);
	}

	render_batches() {
		const ctx = this.batch_data?.context || {};
		const batches = this.batch_data?.batches || [];
		const $tbody = this.$root.find('.bad-batch-table tbody').empty();

		this.$root.find('.bad-allocate-subtitle').text(
			`${ctx.job_order_number || ctx.job_order || ''} · ${ctx.item_name || ctx.item || ''} · ${ctx.customer_name || ''}`
		);

		this.render_qty_summary(ctx);
		this.render_shortage_panel(ctx);

		const can_edit = ctx.can_allocate;
		this.$root.find('.bad-auto-fifo').prop('disabled', !can_edit);
		this.$root.find('.bad-save-allocation').prop('disabled', !can_edit);

		if (!ctx.can_allocate && ctx.allocation_block_reason) {
			$tbody.append(`
				<tr><td colspan="8" class="text-center text-muted">${frappe.utils.escape_html(ctx.allocation_block_reason)}</td></tr>
			`);
			return;
		}

		if (!batches.length) {
			$tbody.append(`
				<tr><td colspan="8" class="text-center text-muted">${__('No matching batches found for this product line.')}</td></tr>
			`);
			return;
		}

		batches.forEach((batch) => {
			const input_val = flt(this.allocate_inputs[batch.name]);
			const disabled = batch.can_allocate ? '' : 'disabled';
			const row_class = batch.can_allocate ? '' : 'bad-row-disabled';

			const $tr = $(`
				<tr class="${row_class}" data-batch="${frappe.utils.escape_html(batch.name)}">
					<td>${batch.fifo_sequence || ''}</td>
					<td><a href="/app/apc-batch/${batch.name}">${frappe.utils.escape_html(batch.batch_number || batch.name)}</a></td>
					<td>${batch.manufacturing_date ? frappe.datetime.str_to_user(batch.manufacturing_date) : ''}</td>
					<td>${batch.expiry_date ? frappe.datetime.str_to_user(batch.expiry_date) : ''}</td>
					<td class="text-right">${frappe.format(batch.free_stock, { fieldtype: 'Float' })}</td>
					<td class="text-right">${frappe.format(batch.already_allocated_on_line, { fieldtype: 'Float' })}</td>
					<td class="text-right">
						<input type="number" min="0" step="0.001" class="form-control input-sm bad-allocate-input text-right"
							value="${input_val}" ${disabled} data-batch="${frappe.utils.escape_html(batch.name)}">
					</td>
					<td>${this.render_coa_cell(batch)}</td>
				</tr>
			`);

			$tr.find('.bad-allocate-input').on('input', (event) => {
				const batch_name = $(event.target).data('batch');
				let value = flt(event.target.value);
				const max_qty = Math.min(flt(batch.free_stock), this.get_remaining_to_assign(ctx, batch_name));
				if (value > max_qty) {
					value = max_qty;
					event.target.value = value;
				}
				this.allocate_inputs[batch_name] = value;
				this.update_pending_progress(ctx);
			});

			$tbody.append($tr);
		});

		this.$root.find('.bad-step-tab-allocate').prop('disabled', false);
		this.update_pending_progress(ctx);
		this.render_context_bar();
	}

	render_qty_summary(ctx) {
		this.$root.find('.bad-qty-summary').html(`
			<div class="bad-qty-grid">
				<div><span>${__('Required')}</span><strong>${frappe.format(ctx.required_qty, { fieldtype: 'Float' })}</strong></div>
				<div><span>${__('Already Allocated')}</span><strong>${frappe.format(ctx.allocated_qty, { fieldtype: 'Float' })}</strong></div>
				<div><span>${__('Pending')}</span><strong>${frappe.format(ctx.pending_qty, { fieldtype: 'Float' })}</strong></div>
			</div>
		`);
	}

	render_coa_cell(batch) {
		const status = batch.coa_status || 'Missing';
		let tone = 'warning';
		if (status === 'Approved') tone = 'success';
		if (status === 'Missing' || status === 'Rejected') tone = 'danger';

		let action = '';
		if (!batch.coa && batch.can_create_coa !== false) {
			action = `<button type="button" class="btn btn-default btn-xs bad-create-coa" data-batch="${frappe.utils.escape_html(batch.name)}">${__('Create COA')}</button>`;
		} else if (batch.coa) {
			action = `<a href="/app/apc-coa/${batch.coa}" class="btn btn-default btn-xs">${__('View')}</a>`;
		}

		return `${this.get_status_pill(status, tone)} ${action}`;
	}

	render_shortage_panel(ctx) {
		const remaining = this.get_remaining_to_assign(ctx);
		const $panel = this.$root.find('.bad-shortage-panel').empty();

		if (remaining <= 0) {
			return;
		}

		$panel.html(`
			<div class="bad-alert bad-alert-warning">
				<strong>${__('Shortage')}: ${frappe.format(remaining, { fieldtype: 'Float' })} ${__('still unallocated')}</strong>
				<div class="bad-shortage-actions">
					${ctx.sales_demand ? `<button type="button" class="btn btn-default btn-xs bad-create-prod-req">${__('Create Production Requirement')}</button>` : ''}
					<button type="button" class="btn btn-default btn-xs bad-create-batch">${__('Create Batch')}</button>
				</div>
			</div>
		`);

		$panel.find('.bad-create-prod-req').on('click', () => {
			frappe.call({
				method: 'apc_operations.services.batch_allocation.create_production_requirement_if_shortage',
				args: { sales_demand: ctx.sales_demand },
				freeze: true,
				callback: (r) => {
					frappe.show_alert({
						message: r.message?.message || __('Production requirement processed.'),
						indicator: 'green',
					});
				},
			});
		});

		$panel.find('.bad-create-batch').on('click', () => {
			frappe.route_options = {
				product: ctx.item,
				grade: ctx.grade,
				specification: ctx.specification,
				packaging_type: ctx.packaging_type,
				warehouse: ctx.warehouse,
				job_order: ctx.job_order,
				batch_quantity: remaining,
				available_quantity: remaining,
			};
			frappe.new_doc('APC Batch');
		});
	}

	run_auto_fifo() {
		if (!this.selected_line) {
			return;
		}

		frappe.call({
			method: 'apc_operations.services.job_order_allocation_dashboard.auto_fifo_lines_for_job_order_line',
			args: {
				job_order: this.selected_job_order,
				job_order_item: this.selected_line.job_order_item,
			},
			freeze: true,
			callback: (r) => {
				const lines = r.message?.lines || [];
				this.allocate_inputs = {};
				(this.batch_data?.batches || []).forEach((batch) => {
					this.allocate_inputs[batch.name] = 0;
				});
				lines.forEach((line) => {
					this.allocate_inputs[line.batch] = flt(line.allocated_quantity);
				});
				this.render_batches();
				if (flt(r.message?.remaining_shortage) > 0) {
					frappe.show_alert({
						message: __('FIFO applied. Shortage: {0}', [
							frappe.format(r.message.remaining_shortage, { fieldtype: 'Float' }),
						]),
						indicator: 'orange',
					});
				}
			},
		});
	}

	save_allocation() {
		if (!this.selected_line || !this.batch_data?.context) {
			return;
		}

		const lines = Object.entries(this.allocate_inputs)
			.filter(([, qty]) => flt(qty) > 0)
			.map(([batch, allocated_quantity]) => ({ batch, allocated_quantity: flt(allocated_quantity) }));

		if (!lines.length) {
			frappe.msgprint(__('Enter at least one allocation quantity before saving.'));
			return;
		}

		frappe.call({
			method: 'apc_operations.services.job_order_allocation_dashboard.save_job_order_line_allocation',
			args: {
				job_order: this.selected_job_order,
				job_order_item: this.selected_line.job_order_item,
				lines,
			},
			freeze: true,
			callback: (r) => {
				if (!r.message?.success) {
					return;
				}

				frappe.show_alert({
					message: r.message.message || __('Allocation saved.'),
					indicator: 'green',
				});

				const refresh_jobs = this.load_job_orders_for_product(this.selected_product);
				const refresh_products = this.refresh_products(true);

				Promise.all([refresh_jobs, refresh_products]).then(() => {
					const refreshed = (this.job_order_lines_data?.lines || []).find(
						(row) => row.job_order_item === this.selected_line.job_order_item
					);
					if (refreshed && refreshed.can_allocate) {
						this.selected_line = refreshed;
						this.load_batches(this.selected_job_order, refreshed.job_order_item);
					} else {
						this.selected_line = refreshed || null;
						this.go_to_step('job_orders');
					}
				});
			},
		});
	}

	create_coa(batch_name) {
		frappe.call({
			method: 'apc_operations.inventory.doctype.apc_batch.apc_batch.create_coa_for_batch',
			args: { batch_name },
			freeze: true,
			callback: (r) => {
				if (r.message?.coa) {
					frappe.show_alert({
						message: __('COA created: {0}', [r.message.coa]),
						indicator: 'green',
					});
					this.load_batches(this.selected_job_order, this.selected_line.job_order_item);
				}
			},
		});
	}

	get_total_assigned(exclude_batch = null) {
		return Object.entries(this.allocate_inputs).reduce((total, [batch, qty]) => {
			if (exclude_batch && batch === exclude_batch) {
				return total;
			}
			return total + flt(qty);
		}, 0);
	}

	get_remaining_to_assign(ctx, exclude_batch = null) {
		const pending = flt(ctx?.pending_qty);
		const assigned = this.get_total_assigned(exclude_batch);
		return Math.max(0, pending - assigned);
	}

	update_pending_progress(ctx) {
		const pending = flt(ctx.pending_qty);
		const assigned = this.get_total_assigned();
		const remaining = Math.max(0, pending - assigned);
		const pct = pending ? Math.min(100, (assigned / pending) * 100) : 0;

		this.$root.find('.bad-progress-bar').css('width', `${pct}%`);
		this.$root.find('.bad-pending-label').text(
			`${__('Assigned in this session')}: ${frappe.format(assigned, { fieldtype: 'Float' })} · ${__('Remaining')}: ${frappe.format(remaining, { fieldtype: 'Float' })}`
		);
		this.render_shortage_panel(ctx);
	}

	get_filtered_products() {
		if (!this.search_term) {
			return this.product_lines;
		}
		const term = this.search_term.toLowerCase();
		return this.product_lines.filter((row) => [
			row.product, row.item_name, row.grade, row.specification,
			row.packaging_type, row.warehouse,
		].some((value) => String(value || '').toLowerCase().includes(term)));
	}

	get_status_pill(label, tone = 'info') {
		return `<span class="bad-pill bad-pill-${tone}">${frappe.utils.escape_html(label || '')}</span>`;
	}
}
