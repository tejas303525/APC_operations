frappe.pages['qc-dashboard'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('QC Dashboard'),
		single_column: true,
	});

	frappe.qc_dashboard = new QCDashboard(page, wrapper);
};

frappe.pages['qc-dashboard'].on_page_show = function () {
	if (frappe.qc_dashboard) {
		frappe.qc_dashboard.refresh();
	}
};

class QCDashboard {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.active_tab = 'requests';
		this.search_term = '';
		this.status_filter = '';
		this.selected_request = null;
		this.qc_requests = [];
		this.pending_loading_dns = [];
		this.batches = [];
		this.coas = [];
		this.fifo_product_control = null;

		this._build_layout();
		this.refresh();
	}

	_build_layout() {
		this.$root = $(frappe.render_template('qc_dashboard', {})).appendTo(
			$(this.wrapper).find('.page-content').empty()
		);

		this._bind_events();
		this._make_fifo_product_control();
	}

	_bind_events() {
		this.$root.find('.qcd-btn-refresh').on('click', () => this.refresh());

		this.$root.find('.qcd-btn-new-request').on('click', () => {
			frappe.new_doc('QC Report Request');
		});

		this.$root.find('.qcd-tab').on('click', (event) => {
			const tab = $(event.currentTarget).data('tab');
			this.switch_tab(tab);
		});

		this.$root.find('.qcd-search').on('input', frappe.utils.debounce((event) => {
			this.search_term = event.target.value || '';
			this.render_active_tab();
		}, 250));

		this.$root.find('.qcd-status-filter').on('change', (event) => {
			this.status_filter = event.target.value || '';
			this.render_active_tab();
		});

		this.$root.find('.qcd-fifo-preview').on('click', () => this.run_fifo_preview());
	}

	_make_fifo_product_control() {
		const $wrap = this.$root.find('.qcd-fifo-product-wrap');
		$wrap.append('<label class="qcd-control-label">Product</label>');
		const $field_wrap = $('<div></div>').appendTo($wrap);

		this.fifo_product_control = frappe.ui.form.make_control({
			df: {
				fieldname: 'product',
				label: __('Product'),
				fieldtype: 'Link',
				options: 'Item',
			},
			parent: $field_wrap,
			render_input: true,
		});

		this.fifo_product_control.$input.on('change', () => {
			this.$root.find('.qcd-fifo-result').hide();
			this.$root.find('.qcd-fifo-confirm').prop('disabled', true);
		});
	}

	switch_tab(tab) {
		this.active_tab = tab;
		this.$root.find('.qcd-tab').removeClass('qcd-tab-active');
		this.$root.find(`.qcd-tab[data-tab="${tab}"]`).addClass('qcd-tab-active');
		this.$root.find('.qcd-content').hide();
		this.$root.find(`.qcd-content-${tab}`).show();
		this.render_active_tab();
	}

	refresh() {
		return Promise.all([
			this.load_stats(),
			this.load_qc_requests(),
			this.load_pending_loading_dns(),
			this.load_batches(),
			this.load_coas(),
		]).then(() => {
			this.render_kpis();
			this.render_active_tab();
		});
	}

	load_stats() {
		return frappe.call({
			method: 'apc_operations.services.dashboard.get_qc_dashboard_stats',
		}).then(r => {
			this.stats = r.message || {};
		}).catch(() => {
			this.stats = {};
		});
	}

	load_qc_requests() {
		return frappe.db.get_list('QC Report Request', {
			fields: [
				'name', 'security_inspection', 'job_order', 'loading_delivery_note',
				'inspection_type', 'container_number', 'material_description',
				'vehicle_number', 'driver_name', 'qc_status', 'requested_on', 'requested_by',
			],
			order_by: 'requested_on desc',
			limit: 200,
		}).then(rows => {
			this.qc_requests = rows || [];
		});
	}

	load_pending_loading_dns() {
		return frappe.db.get_list('Loading Delivery Note', {
			fields: [
				'name', 'security_inspection', 'job_order', 'material_description',
				'vehicle', 'driver', 'qc_status', 'delivery_note_status',
				'creation', 'qc_report_request',
			],
			filters: {
				qc_status: 'Pending QC',
				docstatus: ['!=', 2],
			},
			order_by: 'creation desc',
			limit: 200,
		}).then(rows => {
			this.pending_loading_dns = rows || [];
		});
	}

	get_request_rows() {
		const request_rows = (this.qc_requests || []).map(row => ({
			...row,
			display_id: row.name,
			is_loading_dn_pending: false,
		}));

		const linked_ldns = new Set(
			request_rows.map(row => row.loading_delivery_note).filter(Boolean)
		);

		const ldn_rows = (this.pending_loading_dns || [])
			.filter(ldn => !linked_ldns.has(ldn.name))
			.map(ldn => ({
				name: `PENDING-${ldn.name}`,
				display_id: `Pending: ${ldn.name}`,
				security_inspection: ldn.security_inspection,
				job_order: ldn.job_order,
				loading_delivery_note: ldn.name,
				inspection_type: 'Preshipment QC',
				container_number: ldn.vehicle || '',
				material_description: ldn.material_description,
				vehicle_number: ldn.vehicle,
				driver_name: ldn.driver,
				qc_status: 'Pending QC',
				requested_on: ldn.creation,
				requested_by: '',
				is_loading_dn_pending: true,
			}));

		return [...request_rows, ...ldn_rows];
	}

	load_batches() {
		return frappe.db.get_list('APC Batch', {
			fields: [
				'name', 'batch_number', 'product', 'grade', 'packaging_type',
				'batch_status', 'quality_status', 'warehouse', 'linked_coa',
				'batch_quantity', 'available_quantity', 'allocated_quantity',
				'uom', 'manufacturing_date', 'expiry_date',
			],
			filters: { batch_status: ['in', ['Active', 'On Hold', 'Pending QC']] },
			order_by: 'manufacturing_date asc, creation asc',
			limit: 200,
		}).then(rows => {
			this.batches = rows || [];
		});
	}

	load_coas() {
		return frappe.db.get_list('APC COA', {
			fields: [
				'name', 'coa_number', 'batch', 'batch_number', 'product', 'product_name',
				'job_order', 'status', 'approval_status', 'coa_date', 'coa_pdf',
				'approved_by', 'approved_on',
			],
			order_by: 'creation desc',
			limit: 100,
		}).then(rows => {
			this.coas = rows || [];
		});
	}

	render_kpis() {
		const stats = this.stats || {};
		const pending = stats.pending !== undefined
			? stats.pending
			: this.qc_requests.filter(r => ['Pending QC', 'In Progress'].includes(r.qc_status)).length;
		const cleared = stats.cleared !== undefined
			? stats.cleared
			: this.qc_requests.filter(r => r.qc_status === 'QC Cleared').length;
		const rejected = stats.rejected !== undefined
			? stats.rejected
			: this.qc_requests.filter(r => r.qc_status === 'QC Rejected').length;
		const coa_count = stats.coa_count !== undefined ? stats.coa_count : this.coas.length;

		this.$root.find('.qcd-kpi-pending').text(pending);
		this.$root.find('.qcd-kpi-cleared').text(cleared);
		this.$root.find('.qcd-kpi-rejected').text(rejected);
		this.$root.find('.qcd-kpi-coas').text(coa_count);
	}

	render_active_tab() {
		switch (this.active_tab) {
			case 'requests': return this.render_requests();
			case 'batches': return this.render_batches();
			case 'fifo': return this.render_fifo_tab();
			case 'coa': return this.render_coas();
		}
	}

	get_filtered_requests() {
		let rows = this.get_request_rows();

		if (this.status_filter) {
			rows = rows.filter(r => r.qc_status === this.status_filter);
		}

		if (this.search_term) {
			const term = this.search_term.toLowerCase();
			rows = rows.filter(r => [
				r.name, r.job_order, r.security_inspection, r.loading_delivery_note,
				r.inspection_type, r.container_number, r.material_description, r.vehicle_number,
			].some(v => String(v || '').toLowerCase().includes(term)));
		}

		return rows;
	}

	get_filtered_batches() {
		if (!this.search_term) {
			return this.batches;
		}
		const term = this.search_term.toLowerCase();
		return this.batches.filter(b => [
			b.name, b.batch_number, b.product, b.grade, b.warehouse,
		].some(v => String(v || '').toLowerCase().includes(term)));
	}

	get_filtered_coas() {
		if (!this.search_term) {
			return this.coas;
		}
		const term = this.search_term.toLowerCase();
		return this.coas.filter(c => [
			c.name, c.coa_number, c.batch, c.batch_number, c.product, c.job_order,
		].some(v => String(v || '').toLowerCase().includes(term)));
	}

	render_requests() {
		const rows = this.get_filtered_requests();
		const $tbody = this.$root.find('.qcd-requests-tbody').empty();
		const $empty = this.$root.find('.qcd-requests-empty');
		const $table = this.$root.find('.qcd-content-requests .qcd-table-wrap');

		if (!rows.length) {
			$table.hide();
			$empty.show();
			return;
		}

		$empty.hide();
		$table.show();

		rows.forEach(row => {
			const is_active = this.selected_request?.name === row.name;
			const source_label = row.security_inspection || row.loading_delivery_note || '—';
			const $tr = $(`
				<tr class="${is_active ? 'qcd-row-active' : ''}" data-name="${frappe.utils.escape_html(row.name)}">
					<td>
						<div class="qcd-cell-primary">${frappe.utils.escape_html(row.display_id || row.name)}</div>
						<div class="qcd-cell-secondary">${this.format_datetime(row.requested_on)}</div>
					</td>
					<td>
						<div class="qcd-type-badge qcd-type-${row.inspection_type === 'Production' ? 'prod' : 'pre'}">
							${frappe.utils.escape_html(row.inspection_type || 'Preshipment QC')}
						</div>
					</td>
					<td>
						<div>${frappe.utils.escape_html(source_label)}</div>
					</td>
					<td>
						${row.job_order
							? `<a href="/app/job-order/${row.job_order}" class="qcd-link">${frappe.utils.escape_html(row.job_order)}</a>`
							: '<span class="qcd-muted">—</span>'
						}
					</td>
					<td class="qcd-cell-material">${frappe.utils.escape_html(row.material_description || '—')}</td>
					<td>${this.status_badge(row.qc_status || 'Pending QC')}</td>
					<td class="text-right">
						<button class="btn btn-default btn-xs qcd-row-open">Open</button>
					</td>
				</tr>
			`);

			$tr.find('.qcd-row-open').on('click', () => {
				this.select_request(row);
			});

			$tr.on('click', event => {
				if (!$(event.target).is('.qcd-row-open')) {
					this.select_request(row);
				}
			});

			$tbody.append($tr);
		});

		if (this.selected_request) {
			const still_exists = rows.some(r => r.name === this.selected_request.name);
			if (!still_exists) {
				this.selected_request = null;
				this.render_request_detail();
			}
		}
	}

	select_request(row) {
		this.selected_request = row;
		this.render_requests();
		this.render_request_detail();
	}

	render_request_detail() {
		const $placeholder = this.$root.find('.qcd-detail-placeholder');
		const $content = this.$root.find('.qcd-detail-content');

		if (!this.selected_request) {
			$placeholder.show();
			$content.hide();
			return;
		}

		const req = this.selected_request;
		$placeholder.hide();
		$content.show();

		const source = req.security_inspection || req.loading_delivery_note || '—';
		$content.find('.qcd-detail-id').text(req.name);
		$content.find('.qcd-detail-meta').text(
			`${req.inspection_type || 'QC'} · ${frappe.utils.escape_html(source)}`
		);
		$content.find('.qcd-detail-status').html(this.status_badge(req.qc_status || 'Pending QC'));
		$content.find('.qcd-detail-jo').text(req.job_order || '—');
		$content.find('.qcd-detail-type').text(req.inspection_type || '—');
		$content.find('.qcd-detail-container').text(req.container_number || req.vehicle_number || '—');
		$content.find('.qcd-detail-date').text(this.format_datetime(req.requested_on));
		$content.find('.qcd-detail-material-text').text(req.material_description || 'No material description recorded.');

		const record_url = req.is_loading_dn_pending
			? `/app/loading-delivery-note/${req.loading_delivery_note}`
			: `/app/qc-report-request/${req.name}`;
		$content.find('.qcd-detail-open-link').attr('href', record_url);

		if (req.job_order) {
			$content.find('.qcd-detail-jo-link').attr('href', `/app/job-order/${req.job_order}`).show();
		} else {
			$content.find('.qcd-detail-jo-link').hide();
		}
	}

	render_batches() {
		const rows = this.get_filtered_batches();
		const $tbody = this.$root.find('.qcd-batches-tbody').empty();
		const $empty = this.$root.find('.qcd-batches-empty');
		const $table = this.$root.find('.qcd-content-batches .qcd-table-wrap');

		if (!rows.length) {
			$table.hide();
			$empty.show();
			return;
		}

		$empty.hide();
		$table.show();

		let fifo_rank = 0;
		rows.forEach(batch => {
			const is_fifo_eligible = batch.quality_status === 'Approved' && flt(batch.available_quantity) > 0;
			if (is_fifo_eligible) fifo_rank++;
			const rank = is_fifo_eligible ? fifo_rank : null;

			$tbody.append(`
				<tr>
					<td>
						${rank
							? `<span class="qcd-fifo-badge">#${rank}</span>`
							: '<span class="qcd-muted">—</span>'
						}
					</td>
					<td>
						<a href="/app/apc-batch/${batch.name}" class="qcd-link qcd-mono">
							${frappe.utils.escape_html(batch.batch_number || batch.name)}
						</a>
					</td>
					<td>${frappe.utils.escape_html(batch.product || '—')}</td>
					<td>${frappe.utils.escape_html(batch.warehouse || '—')}</td>
					<td>${this.format_date(batch.manufacturing_date)}</td>
					<td>${this.format_date(batch.expiry_date)}${this.expiry_warning(batch.expiry_date)}</td>
					<td class="text-right qcd-mono">
						${frappe.format(batch.available_quantity, { fieldtype: 'Float' })}
						/ ${frappe.format(batch.batch_quantity, { fieldtype: 'Float' })}
						${frappe.utils.escape_html(batch.uom || '')}
					</td>
					<td>${this.status_badge(batch.quality_status || 'Pending QC')}</td>
					<td>${this.status_badge(batch.batch_status || '—')}</td>
					<td>
						${batch.linked_coa
							? `<a href="/app/apc-coa/${batch.linked_coa}" class="qcd-coa-badge">${frappe.utils.escape_html(batch.linked_coa)}</a>`
							: `<span class="qcd-muted-badge">No COA</span>`
						}
					</td>
				</tr>
			`);
		});
	}

	render_fifo_tab() {
		// keep controls visible; result hidden until Preview is run
	}

	run_fifo_preview() {
		const product = this.fifo_product_control ? this.fifo_product_control.get_value() : '';
		const qty = parseFloat(this.$root.find('.qcd-fifo-qty').val()) || 0;

		if (!product) {
			frappe.msgprint(__('Please select a product.'));
			return;
		}
		if (qty <= 0) {
			frappe.msgprint(__('Please enter a valid required quantity.'));
			return;
		}

		const eligible = this.batches
			.filter(b => b.product === product
				&& b.quality_status === 'Approved'
				&& flt(b.available_quantity) > 0)
			.sort((a, b) => {
				const da = a.manufacturing_date || a.name;
				const db = b.manufacturing_date || b.name;
				return da < db ? -1 : da > db ? 1 : 0;
			});

		let remaining = qty;
		const plan = [];
		eligible.forEach(batch => {
			if (remaining <= 0) return;
			const allocate = Math.min(flt(batch.available_quantity), remaining);
			remaining -= allocate;
			plan.push({ ...batch, allocate });
		});

		this._render_fifo_plan(plan, qty, remaining);
	}

	_render_fifo_plan(plan, required_qty, short_qty) {
		const $tbody = this.$root.find('.qcd-fifo-tbody').empty();
		const $result = this.$root.find('.qcd-fifo-result').show();
		const $summary = this.$root.find('.qcd-fifo-summary');

		if (!plan.length) {
			$tbody.append(`<tr><td colspan="6" class="text-center qcd-muted">No approved stock found for this product.</td></tr>`);
		} else {
			plan.forEach((row, index) => {
				$tbody.append(`
					<tr>
						<td><span class="qcd-fifo-badge">${index + 1}</span></td>
						<td>
							<a href="/app/apc-batch/${row.name}" class="qcd-link qcd-mono">
								${frappe.utils.escape_html(row.batch_number || row.name)}
							</a>
						</td>
						<td>${this.format_date(row.manufacturing_date)}</td>
						<td class="text-right qcd-mono">
							${frappe.format(row.available_quantity, { fieldtype: 'Float' })} ${frappe.utils.escape_html(row.uom || 'MT')}
						</td>
						<td class="text-right qcd-mono qcd-alloc-qty">
							${frappe.format(row.allocate, { fieldtype: 'Float' })} ${frappe.utils.escape_html(row.uom || 'MT')}
						</td>
						<td>
							${row.linked_coa
								? `<a href="/app/apc-coa/${row.linked_coa}" class="qcd-coa-badge">${frappe.utils.escape_html(row.linked_coa)}</a>`
								: `<span class="qcd-muted-badge">No COA</span>`
							}
						</td>
					</tr>
				`);
			});
		}

		if (short_qty > 0) {
			$summary.html(`
				<div class="qcd-fifo-alert qcd-alert-danger">
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="qcd-alert-icon"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
					Insufficient approved stock. Short by <strong>${frappe.format(short_qty, { fieldtype: 'Float' })} MT</strong>.
					A production requirement may be needed.
				</div>
			`);
			this.$root.find('.qcd-fifo-confirm').prop('disabled', true);
		} else {
			const allocated_qty = frappe.format(required_qty, { fieldtype: 'Float' });
			const coa_count = plan.filter(r => r.linked_coa).length;
			$summary.html(`
				<div class="qcd-fifo-alert qcd-alert-success">
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="qcd-alert-icon"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/></svg>
					FIFO plan valid. ${allocated_qty} MT allocated across <strong>${plan.length} batch(es)</strong>.
					${coa_count === plan.length
						? 'All batches have COAs.'
						: `<span class="qcd-warn-inline">${plan.length - coa_count} batch(es) missing COA — resolve before dispatch.</span>`
					}
				</div>
			`);
			this.$root.find('.qcd-fifo-confirm').prop('disabled', coa_count < plan.length);
		}
	}

	render_coas() {
		const rows = this.get_filtered_coas();
		const $tbody = this.$root.find('.qcd-coa-tbody').empty();
		const $empty = this.$root.find('.qcd-coa-empty');
		const $table = this.$root.find('.qcd-content-coa .qcd-table-wrap');

		if (!rows.length) {
			$table.hide();
			$empty.show();
			return;
		}

		$empty.hide();
		$table.show();

		rows.forEach(coa => {
			$tbody.append(`
				<tr>
					<td>
						<a href="/app/apc-coa/${coa.name}" class="qcd-link qcd-mono qcd-purple">
							${frappe.utils.escape_html(coa.coa_number || coa.name)}
						</a>
					</td>
					<td>
						<a href="/app/apc-batch/${coa.batch}" class="qcd-link qcd-mono">
							${frappe.utils.escape_html(coa.batch_number || coa.batch || '—')}
						</a>
					</td>
					<td>${frappe.utils.escape_html(coa.product_name || coa.product || '—')}</td>
					<td>
						${coa.job_order
							? `<a href="/app/job-order/${coa.job_order}" class="qcd-link">${frappe.utils.escape_html(coa.job_order)}</a>`
							: '<span class="qcd-muted">—</span>'
						}
					</td>
					<td>${this.status_badge(coa.status || '—')}</td>
					<td>${this.approval_badge(coa.approval_status)}</td>
					<td>${this.format_date(coa.coa_date)}</td>
					<td class="text-right">
						<div class="qcd-coa-actions">
							<a href="/app/apc-coa/${coa.name}" class="btn btn-default btn-xs">
								<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="qcd-xs-icon"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
								View
							</a>
							${coa.coa_pdf
								? `<a href="${coa.coa_pdf}" target="_blank" class="btn btn-default btn-xs">
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="qcd-xs-icon"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>
										PDF
									</a>`
								: `<button class="btn btn-default btn-xs" disabled>PDF</button>`
							}
						</div>
					</td>
				</tr>
			`);
		});
	}

	// ── Helpers ──────────────────────────────────────────────────────────────

	status_badge(value) {
		const tone = {
			'Pending QC': 'amber',
			'In Progress': 'blue',
			'QC Cleared': 'emerald',
			'QC Rejected': 'red',
			'Approved': 'emerald',
			'Rejected': 'red',
			'On Hold': 'amber',
			'Active': 'emerald',
			'Draft': 'slate',
			'Submitted': 'blue',
			'Cancelled': 'slate',
		}[value] || 'slate';
		return `<span class="qcd-badge qcd-badge-${tone}">${frappe.utils.escape_html(value || '—')}</span>`;
	}

	approval_badge(value) {
		const tone_map = { 'Approved': 'emerald', 'Rejected': 'red', 'Pending': 'amber' };
		const tone = tone_map[value] || 'slate';
		return `<span class="qcd-badge qcd-badge-${tone}">${frappe.utils.escape_html(value || 'Pending')}</span>`;
	}

	format_date(date) {
		return date ? frappe.datetime.str_to_user(date) : '<span class="qcd-muted">—</span>';
	}

	format_datetime(dt) {
		if (!dt) return '—';
		return frappe.datetime.str_to_user(dt.split(' ')[0]) + ' ' + (dt.split(' ')[1] || '').slice(0, 5);
	}

	days_until(date) {
		if (!date) return 9999;
		return frappe.datetime.get_diff(date, frappe.datetime.get_today());
	}

	expiry_warning(date) {
		const days = this.days_until(date);
		if (days <= 0) return ` <span class="qcd-expiry-danger">(Expired)</span>`;
		if (days <= 30) return ` <span class="qcd-expiry-warn">(${days}d)</span>`;
		return '';
	}
}
