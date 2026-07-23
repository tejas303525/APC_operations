frappe.pages['job-dashboard'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Job Order Dashboard'),
		single_column: true,
	});

	frappe.job_dashboard = new JobDashboard(page, wrapper);
};

frappe.pages['job-dashboard'].on_page_show = function () {
	if (frappe.job_dashboard) {
		frappe.job_dashboard.refresh();
	}
};

class JobDashboard {
	constructor(page, wrapper) {
		this.page    = page;
		this.wrapper = wrapper;
		this.data    = {};
		this._all_rows      = [];
		this._current_page  = 1;
		this._per_page      = 20;
		this._setup_page_actions();
		this._build_layout();
		this.refresh();
		this._start_auto_refresh();
	}

	// ── Page-level header actions ───────────────────────────────────────

	_setup_page_actions() {
		this.page.set_primary_action(__('+ New Job Order'), () => {
			frappe.new_doc('Job Order');
		}, 'plus');

		this.page.set_secondary_action(__('Export'), () => {
			frappe.set_route('List', 'Job Order');
		}, 'download');

		this.page.add_menu_item(__('View All Job Orders'), () => {
			frappe.set_route('List', 'Job Order');
		});

		this.page.add_menu_item(__('Import Job Orders'), () => {
			frappe.set_route('data-import-tool', { doctype: 'Job Order' });
		});

		this.page.add_menu_item(__('View Reports'), () => {
			frappe.set_route('List', 'Report', { module: 'Shipping' });
		});

		this.page.add_menu_item(__('Pending Approvals'), () => {
			frappe.set_route('List', 'Job Order', { status: 'Draft' });
		});

		this.page.add_menu_item(__('Refresh'), () => this.refresh());
	}

	// ── Layout scaffold ────────────────────────────────────────────────

	_build_layout() {
		const root = $(this.wrapper).find('.page-content');
		root.css({ padding: '0 24px 40px' });

		this.$root = $('<div class="jd-dashboard"></div>').appendTo(root);

		// Subtitle line
		this.$root.append(`
			<p class="jd-subtitle">${__('Manage and create job orders')}</p>
		`);

		// KPI strip
		this.$kpi_strip = $('<div class="jd-kpi-strip"></div>').appendTo(this.$root);
		this._render_kpi_skeleton();

		// Two-column: main content + sidebar
		this.$main_grid  = $('<div class="jd-main-grid"></div>').appendTo(this.$root);
		this.$content    = $('<div class="jd-content"></div>').appendTo(this.$main_grid);
		this.$sidebar    = $('<div class="jd-sidebar"></div>').appendTo(this.$main_grid);

		// Filters bar
		this.$filters_bar = $('<div class="jd-filters-bar"></div>').appendTo(this.$content);
		this._build_filters();

		// Table card (placeholder)
		this.$table_card  = $('<div class="jd-table-card"></div>').appendTo(this.$content);
		this._render_table_skeleton();

		// Sidebar cards
		this.$quick_actions   = $('<div class="jd-card"></div>').appendTo(this.$sidebar);
		this.$recent_activity = $('<div class="jd-card jd-activity-card"></div>').appendTo(this.$sidebar);
	}

	// ── Skeletons ──────────────────────────────────────────────────────

	_render_kpi_skeleton() {
		this.$kpi_strip.empty();
		for (let i = 0; i < 5; i++) {
			this.$kpi_strip.append(`
				<div class="jd-kpi-card">
					<div class="jd-skeleton" style="width:55%;height:11px;"></div>
					<div class="jd-skeleton" style="width:38%;height:32px;margin:8px 0 4px;"></div>
					<div class="jd-skeleton" style="width:60%;height:10px;"></div>
				</div>
			`);
		}
	}

	_render_table_skeleton() {
		this.$table_card.html(`
			<div class="jd-skeleton" style="width:100%;height:260px;border-radius:8px;"></div>
		`);
	}

	// ── Filters ────────────────────────────────────────────────────────

	_build_filters() {
		this.$filters_bar.html(`
			<div class="jd-search-wrap">
				<svg class="jd-search-icon" viewBox="0 0 16 16" fill="none">
					<circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" stroke-width="1.4"/>
					<path d="M10 10l3.5 3.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
				</svg>
				<input type="text" class="jd-search-input" placeholder="${__('Search job orders...')}">
			</div>
			<div class="jd-filter-group">
				<div class="jd-filter-wrap">
					<select class="jd-filter-select jd-status-filter">
						<option value="">${__('Status')}</option>
						<option value="Confirmed">${__('Open')}</option>
						<option value="In Progress">${__('In Progress')}</option>
						<option value="Draft">${__('Draft')}</option>
						<option value="Completed">${__('Completed')}</option>
						<option value="Cancelled">${__('Cancelled')}</option>
					</select>
					<svg class="jd-select-caret" viewBox="0 0 10 6" fill="none">
						<path d="M1 1l4 4 4-4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
					</svg>
				</div>
				<div class="jd-filter-wrap">
					<select class="jd-filter-select jd-jobtype-filter">
						<option value="">${__('Job Type')}</option>
						<option value="Sea">${__('Sea')}</option>
						<option value="Air">${__('Air')}</option>
						<option value="Road">${__('Road')}</option>
						<option value="Rail">${__('Rail')}</option>
						<option value="Export Container">${__('Export Container')}</option>
						<option value="Tanker Delivery">${__('Tanker Delivery')}</option>
						<option value="Trailer Delivery">${__('Trailer Delivery')}</option>
						<option value="Local Delivery">${__('Local Delivery')}</option>
					</select>
					<svg class="jd-select-caret" viewBox="0 0 10 6" fill="none">
						<path d="M1 1l4 4 4-4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
					</svg>
				</div>
				<div class="jd-daterange-wrap">
					<svg class="jd-cal-icon" viewBox="0 0 16 16" fill="none">
						<rect x="1.5" y="3" width="13" height="11" rx="1.5" stroke="currentColor" stroke-width="1.3"/>
						<path d="M1.5 6.5h13" stroke="currentColor" stroke-width="1.3"/>
						<path d="M5 1.5v3M11 1.5v3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
					</svg>
					<input type="date" class="jd-filter-date jd-date-from" title="${__('From')}">
					<span class="jd-date-sep">—</span>
					<input type="date" class="jd-filter-date jd-date-to" title="${__('To')}">
				</div>
				<div class="jd-filter-wrap">
					<select class="jd-filter-select jd-assigned-filter">
						<option value="">${__('Assigned To')}</option>
					</select>
					<svg class="jd-select-caret" viewBox="0 0 10 6" fill="none">
						<path d="M1 1l4 4 4-4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
					</svg>
				</div>
				<button class="jd-clear-btn">${__('Clear Filters')}</button>
			</div>
		`);

		this.$filters_bar.find('.jd-search-input').on('keyup', () => this._apply_filters());
		this.$filters_bar.find('.jd-status-filter, .jd-jobtype-filter, .jd-date-from, .jd-date-to, .jd-assigned-filter').on('change', () => this._apply_filters());
		this.$filters_bar.find('.jd-clear-btn').on('click', () => {
			this.$filters_bar.find('.jd-search-input').val('');
			this.$filters_bar.find('select').val('');
			this.$filters_bar.find('.jd-date-from, .jd-date-to').val('');
			this._apply_filters();
		});
	}

	// ── Data refresh ───────────────────────────────────────────────────

	refresh() {
		frappe.call({
			method: 'apc_operations.shipping.api.get_job_dashboard_data',
			freeze: false,
			callback: (r) => {
				if (r.message) {
					this.data = r.message;
					this._render_all();
				}
			},
			error: () => {
				this.data = this._placeholder_data();
				this._render_all();
			},
		});
	}

	_start_auto_refresh() {
		this._refresh_timer = setInterval(() => this.refresh(), 300_000);
	}

	// ── Master render ──────────────────────────────────────────────────

	_render_all() {
		const { kpis, job_orders, recent_activity } = this.data;
		this._render_kpis(kpis || {});
		this._render_table(job_orders || []);
		this._render_quick_actions(kpis || {});
		this._render_recent_activity(recent_activity || []);
		this._populate_assigned_filter(job_orders || []);
	}

	// ── KPI Strip ──────────────────────────────────────────────────────

	_render_kpis(kpis) {
		const total = kpis.total || 0;
		const pct   = (n) => total ? `${((n / total) * 100).toFixed(1)}% ${__('of total')}` : `0% ${__('of total')}`;

		const cards = [
			{
				label: __('Total Job Orders'),
				count: kpis.total ?? 0,
				sub: __('All time'),
				icon: `<svg viewBox="0 0 20 20" fill="none"><rect x="3" y="2" width="14" height="16" rx="2" stroke="currentColor" stroke-width="1.5"/><path d="M7 6h6M7 10h6M7 14h4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>`,
				icon_cls: 'jd-icon-blue',
				count_cls: '',
				route: ['List', 'Job Order'],
			},
			{
				label: __('Open'),
				count: kpis.open ?? 0,
				sub: pct(kpis.open ?? 0),
				icon: `<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.5"/><path d="M7 10.5l2.5 2.5L13.5 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
				icon_cls: 'jd-icon-green',
				count_cls: 'jd-count-green',
				route: ['List', 'Job Order', { status: 'Confirmed' }],
			},
			{
				label: __('In Progress'),
				count: kpis.in_progress ?? 0,
				sub: pct(kpis.in_progress ?? 0),
				icon: `<svg viewBox="0 0 20 20" fill="none"><path d="M10 3v3M10 14v3M3 10h3M14 10h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="10" cy="10" r="3" stroke="currentColor" stroke-width="1.5"/></svg>`,
				icon_cls: 'jd-icon-amber',
				count_cls: 'jd-count-amber',
				route: ['List', 'Job Order', { status: 'In Progress' }],
			},
			{
				label: __('Pending Security Review'),
				count: kpis.pending_security ?? 0,
				sub: pct(kpis.pending_security ?? 0),
				icon: `<svg viewBox="0 0 20 20" fill="none"><path d="M10 2l7 3v5c0 4.4-3 7.7-7 9-4-1.3-7-4.6-7-9V5l7-3z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M10 8v4M10 13.5v.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,
				icon_cls: 'jd-icon-orange',
				count_cls: 'jd-count-orange',
				route: ['List', 'Job Order', { transport_requirement_status: 'Pending Review' }],
			},
			{
				label: __('Completed'),
				count: kpis.completed ?? 0,
				sub: pct(kpis.completed ?? 0),
				icon: `<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.5"/><path d="M6.5 10.5l2.5 2.5 4.5-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
				icon_cls: 'jd-icon-teal',
				count_cls: 'jd-count-teal',
				route: ['List', 'Job Order', { status: 'Completed' }],
			},
		];

		this.$kpi_strip.empty();
		cards.forEach(c => {
			const $card = $(`
				<div class="jd-kpi-card" title="${c.label}">
					<div class="jd-kpi-top">
						<span class="jd-kpi-label">${c.label}</span>
						<span class="jd-kpi-icon ${c.icon_cls}">${c.icon}</span>
					</div>
					<div class="jd-kpi-count ${c.count_cls}">${c.count}</div>
					<div class="jd-kpi-sub">${c.sub}</div>
				</div>
			`);
			$card.on('click', () => frappe.set_route(...c.route));
			this.$kpi_strip.append($card);
		});
	}

	// ── Table ──────────────────────────────────────────────────────────

	_render_table(rows) {
		this.$table_card.html(`
			<div class="jd-table-header">
				<span class="jd-table-title">${__('Job Orders')}</span>
				<div class="jd-table-actions">
					<button class="jd-btn-create">${__('Create Job Order')}</button>
					<button class="jd-settings-btn" title="${__('Columns')}">
						<svg viewBox="0 0 16 16" fill="none" width="14" height="14">
							<circle cx="8" cy="4" r="1.3" stroke="currentColor" stroke-width="1.2"/>
							<circle cx="8" cy="8" r="1.3" stroke="currentColor" stroke-width="1.2"/>
							<circle cx="8" cy="12" r="1.3" stroke="currentColor" stroke-width="1.2"/>
						</svg>
					</button>
				</div>
			</div>
			<div class="jd-table-wrap">
				<table class="jd-table">
					<thead>
						<tr>
							<th class="jd-th-check"><input type="checkbox" class="jd-select-all"></th>
							<th class="jd-sortable" data-field="job_order_number">${__('Job Order Number')}<span class="jd-sort-icon">⇅</span></th>
							<th class="jd-sortable" data-field="customer_name">${__('Customer')}<span class="jd-sort-icon">⇅</span></th>
							<th>${__('Incoterm')}</th>
							<th>${__('Booking Requirement')}</th>
							<th>${__('Transport Status')}</th>
							<th>${__('Shipping Status')}</th>
							<th class="jd-sortable" data-field="date">${__('Date')}<span class="jd-sort-icon">⇅</span></th>
							<th>${__('Status')}</th>
							<th>${__('Assigned To')}</th>
							<th>${__('Actions')}</th>
						</tr>
					</thead>
					<tbody class="jd-tbody"></tbody>
				</table>
			</div>
			<div class="jd-table-footer">
				<span class="jd-row-count"></span>
				<div class="jd-pagination">
					<select class="jd-per-page">
						<option value="20">20 ${__('per page')}</option>
						<option value="50">50 ${__('per page')}</option>
						<option value="100">100 ${__('per page')}</option>
					</select>
					<button class="jd-page-btn jd-prev-btn" disabled>‹</button>
					<span class="jd-page-num">1</span>
					<button class="jd-page-btn jd-next-btn">›</button>
				</div>
			</div>
		`);

		this.$table_card.find('.jd-btn-create').on('click', () => frappe.new_doc('Job Order'));
		this.$table_card.find('.jd-select-all').on('change', function () {
			$(this).closest('table').find('tbody .jd-row-check').prop('checked', this.checked);
		});
		this.$table_card.find('.jd-sortable').on('click', (e) => {
			const field = $(e.currentTarget).data('field');
			this._sort_by(field);
		});

		this._all_rows     = rows;
		this._sort_field   = 'date';
		this._sort_dir     = 'desc';
		this._current_page = 1;
		this._apply_filters();
	}

	_sort_by(field) {
		if (this._sort_field === field) {
			this._sort_dir = this._sort_dir === 'asc' ? 'desc' : 'asc';
		} else {
			this._sort_field = field;
			this._sort_dir   = 'asc';
		}
		this._apply_filters();
	}

	_populate_assigned_filter(rows) {
		const users = [...new Set(rows.map(r => r.owner).filter(Boolean))];
		const $sel  = this.$filters_bar.find('.jd-assigned-filter');
		const cur   = $sel.val();
		$sel.find('option:not(:first)').remove();
		users.forEach(u => {
			const label = this._short_name(u);
			$sel.append(`<option value="${u}">${label}</option>`);
		});
		if (cur) $sel.val(cur);
	}

	_apply_filters() {
		if (!this._all_rows) return;

		const search    = (this.$filters_bar.find('.jd-search-input').val() || '').toLowerCase();
		const status    = this.$filters_bar.find('.jd-status-filter').val();
		const job_type  = this.$filters_bar.find('.jd-jobtype-filter').val();
		const date_from = this.$filters_bar.find('.jd-date-from').val();
		const date_to   = this.$filters_bar.find('.jd-date-to').val();
		const assigned  = this.$filters_bar.find('.jd-assigned-filter').val();

		let rows = this._all_rows.filter(r => {
			if (search) {
				const hay = `${r.job_order_number || ''} ${r.name} ${r.customer_name || ''} ${r.customer || ''} ${r.pi_number || ''}`.toLowerCase();
				if (!hay.includes(search)) return false;
			}
			if (status && r.status !== status) return false;
			if (job_type) {
				const jt = r.outward_type || r.mode_of_transport || '';
				if (jt !== job_type) return false;
			}
			if (date_from && r.date && r.date < date_from) return false;
			if (date_to   && r.date && r.date > date_to)   return false;
			if (assigned  && r.owner !== assigned)          return false;
			return true;
		});

		// Sort
		if (this._sort_field) {
			rows = [...rows].sort((a, b) => {
				const av = (a[this._sort_field] || '').toString().toLowerCase();
				const bv = (b[this._sort_field] || '').toString().toLowerCase();
				return this._sort_dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
			});
		}

		this._current_page = 1;
		this._filtered_rows = rows;
		this._render_rows();
	}

	_render_rows() {
		const rows    = this._filtered_rows || [];
		const per     = parseInt(this.$table_card.find('.jd-per-page').val()) || 20;
		const page    = this._current_page;
		const start   = (page - 1) * per;
		const slice   = rows.slice(start, start + per);
		const total   = rows.length;

		const $tbody  = this.$table_card.find('.jd-tbody');
		const $count  = this.$table_card.find('.jd-row-count');

		$tbody.empty();

		if (!slice.length) {
			$tbody.append(`
				<tr>
					<td colspan="11" class="jd-empty-row">
						${__('No job orders found')}
					</td>
				</tr>
			`);
		} else {
			slice.forEach(r => {
				const status   = this._derive_status(r);
				const assigned = this._short_name(r.owner);
				const d_date   = r.date ? frappe.datetime.str_to_user(r.date) : '—';
				const incoterm = r.terms_of_delivery || '—';
				const booking_requirement = r.booking_requirement || '—';
				const transport_status = r.transport_status || '—';
				const shipping_status = r.shipping_status || '—';
				const job_order_number = r.job_order_number || '—';

				$tbody.append(`
					<tr class="jd-row" data-name="${r.name}">
						<td class="jd-td-check"><input type="checkbox" class="jd-row-check"></td>
						<td><a href="/app/job-order/${r.name}" class="jd-link jd-id-link">${job_order_number}</a></td>
						<td class="jd-td-customer">${r.customer_name || r.customer || '—'}</td>
						<td class="jd-td-type">${incoterm}</td>
						<td>${booking_requirement}</td>
						<td>${transport_status}</td>
						<td>${shipping_status}</td>
						<td class="jd-td-date">${d_date}</td>
						<td><span class="jd-status-badge ${status.cls}"><span class="jd-dot"></span>${__(status.label)}</span></td>
						<td class="jd-td-user">${assigned}</td>
						<td class="jd-td-actions">
							<a href="/app/job-order/${r.name}" class="jd-act-icon" title="${__('Open')}">
								<svg viewBox="0 0 16 16" fill="none" width="13" height="13">
									<path d="M6 3H3a1 1 0 00-1 1v9a1 1 0 001 1h9a1 1 0 001-1v-3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
									<path d="M10 2h4v4M14 2L9 7" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
								</svg>
							</a>
							<button class="jd-act-icon jd-more-btn" data-name="${r.name}" title="${__('More')}">
								<svg viewBox="0 0 16 16" fill="none" width="13" height="13">
									<circle cx="4" cy="8" r="1.2" fill="currentColor"/>
									<circle cx="8" cy="8" r="1.2" fill="currentColor"/>
									<circle cx="12" cy="8" r="1.2" fill="currentColor"/>
								</svg>
							</button>
						</td>
					</tr>
				`);
			});
		}

		// Footer
		const from_n = total ? start + 1 : 0;
		const to_n   = Math.min(start + per, total);
		$count.text(__(`Showing ${from_n} to ${to_n} of ${total} entries`));

		// Pagination
		this.$table_card.find('.jd-prev-btn').prop('disabled', page <= 1);
		this.$table_card.find('.jd-next-btn').prop('disabled', start + per >= total);
		this.$table_card.find('.jd-page-num').text(page);

		this.$table_card.find('.jd-prev-btn').off('click').on('click', () => {
			if (this._current_page > 1) { this._current_page--; this._render_rows(); }
		});
		this.$table_card.find('.jd-next-btn').off('click').on('click', () => {
			if (start + per < total) { this._current_page++; this._render_rows(); }
		});
		this.$table_card.find('.jd-per-page').off('change').on('change', () => {
			this._current_page = 1;
			this._render_rows();
		});

		// Row actions menu
		this.$table_card.find('.jd-more-btn').on('click', (e) => {
			e.stopPropagation();
			const name = $(e.currentTarget).data('name');
			this._show_row_menu(name, e.currentTarget);
		});

		// Row click → form
		this.$table_card.find('.jd-row').on('click', (e) => {
			if ($(e.target).is('a, button, input, .jd-more-btn')) return;
			const name = $(e.currentTarget).data('name');
			frappe.set_route('Form', 'Job Order', name);
		});
	}

	_show_row_menu(name, btn) {
		$('.jd-row-menu').remove();
		const $menu = $(`
			<div class="jd-row-menu">
				<div class="jd-menu-item" data-action="view">${__('View')}</div>
				<div class="jd-menu-item" data-action="edit">${__('Edit')}</div>
				<div class="jd-menu-item jd-menu-danger" data-action="delete">${__('Delete')}</div>
			</div>
		`).appendTo('body');

		const rect = btn.getBoundingClientRect();
		$menu.css({
			top:  rect.bottom + window.scrollY + 4,
			left: rect.right  - $menu.outerWidth() + window.scrollX,
		});

		$menu.find('[data-action]').on('click', (e) => {
			const action = $(e.currentTarget).data('action');
			$menu.remove();
			if (action === 'view' || action === 'edit') {
				frappe.set_route('Form', 'Job Order', name);
			} else if (action === 'delete') {
				frappe.confirm(__('Delete this Job Order?'), () => {
					frappe.call({
						method:   'frappe.client.delete',
						args:     { doctype: 'Job Order', name },
						callback: () => {
							frappe.show_alert({ message: __('Deleted'), indicator: 'green' });
							this.refresh();
						},
					});
				});
			}
		});

		$(document).one('click', () => $menu.remove());
	}

	// ── Status / Priority helpers ──────────────────────────────────────

	_derive_status(row) {
		switch (row.status) {
			case 'Cancelled':  return { label: 'Cancelled',  cls: 'jd-s-cancelled' };
			case 'Completed':  return { label: 'Completed',  cls: 'jd-s-completed' };
			case 'In Progress': return { label: 'In Progress', cls: 'jd-s-progress' };
		}
		if (row.transport_requirement_status === 'Pending Review') {
			return { label: 'Pending Security Review', cls: 'jd-s-security' };
		}
		if (row.status === 'Confirmed') return { label: 'Open', cls: 'jd-s-open' };
		return { label: 'Draft', cls: 'jd-s-draft' };
	}

	_derive_priority(row) {
		const trs = row.transport_requirement_status || '';
		if (['Pending Review', 'Transport Required'].includes(trs)) {
			return { label: 'High', cls: 'jd-p-high' };
		}
		if (['Pending Shipping Booking', 'Pending Transport Request'].includes(trs)) {
			return { label: 'Medium', cls: 'jd-p-medium' };
		}
		return { label: 'Low', cls: 'jd-p-low' };
	}

	_short_name(email) {
		if (!email) return '—';
		const part = email.includes('@') ? email.split('@')[0] : email;
		return part.replace(/[._]/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
	}

	// ── Quick Actions sidebar ──────────────────────────────────────────

	_render_quick_actions(kpis) {
		this.$quick_actions.html(`
			<div class="jd-card-header">
				<span class="jd-card-title">${__('Quick Actions')}</span>
			</div>
			<div class="jd-qa-list">
				<div class="jd-qa-item" data-action="create">
					<span class="jd-qa-icon-wrap jd-qa-blue">
						<svg viewBox="0 0 16 16" fill="none" width="14" height="14">
							<path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
						</svg>
					</span>
					<span class="jd-qa-label">${__('Create Job Order')}</span>
					<svg class="jd-qa-arrow" viewBox="0 0 16 16" fill="none">
						<path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
					</svg>
				</div>
				<div class="jd-qa-item" data-action="import">
					<span class="jd-qa-icon-wrap jd-qa-teal">
						<svg viewBox="0 0 16 16" fill="none" width="14" height="14">
							<path d="M8 2v8M4 7l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
							<path d="M2 12v2h12v-2" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
						</svg>
					</span>
					<span class="jd-qa-label">${__('Import Job Orders')}</span>
					<svg class="jd-qa-arrow" viewBox="0 0 16 16" fill="none">
						<path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
					</svg>
				</div>
				<div class="jd-qa-item" data-action="reports">
					<span class="jd-qa-icon-wrap jd-qa-purple">
						<svg viewBox="0 0 16 16" fill="none" width="14" height="14">
							<rect x="2" y="1" width="12" height="14" rx="1.5" stroke="currentColor" stroke-width="1.3"/>
							<path d="M5 5h6M5 8h6M5 11h4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
						</svg>
					</span>
					<span class="jd-qa-label">${__('View Reports')}</span>
					<svg class="jd-qa-arrow" viewBox="0 0 16 16" fill="none">
						<path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
					</svg>
				</div>
				<div class="jd-qa-item" data-action="approvals">
					<span class="jd-qa-icon-wrap jd-qa-amber">
						<svg viewBox="0 0 16 16" fill="none" width="14" height="14">
							<circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.3"/>
							<path d="M8 5v3.5l2 1.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
						</svg>
					</span>
					<span class="jd-qa-label">${__('Pending Approvals')}</span>
					<span class="jd-qa-badge">${kpis.pending_approvals ?? 0}</span>
					<svg class="jd-qa-arrow" viewBox="0 0 16 16" fill="none">
						<path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
					</svg>
				</div>
			</div>
		`);

		const action_map = {
			create:    () => frappe.new_doc('Job Order'),
			import:    () => frappe.set_route('List', 'Job Order'),
			reports:   () => frappe.set_route('List', 'Report', { module: 'Shipping' }),
			approvals: () => frappe.set_route('List', 'Job Order', { status: 'Draft' }),
		};

		this.$quick_actions.find('.jd-qa-item').on('click', (e) => {
			const action = $(e.currentTarget).data('action');
			(action_map[action] || (() => {}))();
		});
	}

	// ── Recent Activity sidebar ────────────────────────────────────────

	_render_recent_activity(activity) {
		this.$recent_activity.html(`
			<div class="jd-card-header">
				<span class="jd-card-title">${__('Recent Activity')}</span>
				<span class="jd-card-link jd-view-all">${__('View all activity')}</span>
			</div>
			<div class="jd-activity-list"></div>
		`);

		this.$recent_activity.find('.jd-view-all').on('click', () => {
			frappe.set_route('List', 'Job Order');
		});

		const $list = this.$recent_activity.find('.jd-activity-list');

		if (!activity.length) {
			$list.append(`<div class="jd-activity-empty">${__('No recent activity')}</div>`);
			return;
		}

		activity.forEach(item => {
			const s      = this._derive_status(item);
			const ago    = frappe.datetime.comment_when
				? frappe.datetime.comment_when(item.modified)
				: (item.modified || '');
			const msg    = item._msg || `${__('Status changed to')} ${__(item.status)}`;

			$list.append(`
				<div class="jd-act-item" data-name="${item.name}">
					<span class="jd-act-dot ${s.cls}"></span>
					<div class="jd-act-body">
						<a href="/app/job-order/${item.name}" class="jd-act-ref">${item.name}</a>
						<span class="jd-act-msg">${msg}</span>
						<span class="jd-act-time">${ago}</span>
					</div>
					<svg class="jd-act-arrow" viewBox="0 0 16 16" fill="none">
						<path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
					</svg>
				</div>
			`);
		});

		this.$recent_activity.find('.jd-act-item').on('click', function (e) {
			if ($(e.target).is('a')) return;
			frappe.set_route('Form', 'Job Order', $(this).data('name'));
		});
	}

	// ── Placeholder data ───────────────────────────────────────────────

	_placeholder_data() {
		const today = frappe.datetime.get_today();
		return {
			kpis: {
				total: 128, open: 42, in_progress: 27,
				pending_security: 11, completed: 48, pending_approvals: 11,
			},
			job_orders: [
				{ name: 'JO-2026-00014', job_order_number: 'APC-0014', customer: 'acme-corp',    customer_name: 'Acme Corp',                  outward_type: 'Security Draft Delivery', transport_schedule: 'TRN-2026-00014', date: today, status: 'Confirmed',   transport_requirement_status: 'Transport Required',    owner: 'jane.smith@example.com' },
				{ name: 'JO-2026-00015', job_order_number: 'APC-0015', customer: 'global-mfg',   customer_name: 'Global Manufacturing Ltd.', outward_type: 'Security Draft Delivery', transport_schedule: 'TRN-2026-00015', date: today, status: 'In Progress', transport_requirement_status: 'Pending Review',        owner: 'john.doe@example.com' },
				{ name: 'JO-2026-00016', job_order_number: 'APC-0016', customer: 'technova',     customer_name: 'TechNova Solutions',        outward_type: 'Tamper Evident Seal',      transport_schedule: 'TRN-2026-00016', date: today, status: 'Confirmed',   transport_requirement_status: 'Pending Review',        owner: 'mike.johnson@example.com' },
				{ name: 'JO-2026-00017', job_order_number: 'APC-0017', customer: 'buildright',   customer_name: 'BuildRight Construction',   outward_type: 'Security Draft Delivery', transport_schedule: 'TRN-2026-00017', date: today, status: 'Draft',       transport_requirement_status: 'Pending Review',        owner: 'sarah.williams@example.com' },
				{ name: 'JO-2026-00018', job_order_number: 'APC-0018', customer: 'pharmacare',   customer_name: 'PharmaCare Inc.',           outward_type: 'Security Draft Delivery', transport_schedule: 'TRN-2026-00018', date: today, status: 'Completed',   transport_requirement_status: 'Transport Not Required', owner: 'jane.smith@example.com' },
				{ name: 'JO-2026-00019', job_order_number: 'APC-0019', customer: 'retailmart',   customer_name: 'RetailMart Philippines',    outward_type: 'Tamper Evident Seal',      transport_schedule: 'TRN-2026-00019', date: today, status: 'Confirmed',   transport_requirement_status: 'Transport Required',    owner: 'john.doe@example.com' },
			],
			recent_activity: [
				{ name: 'JO-2026-00016', status: 'Confirmed',   modified: frappe.datetime.now_datetime(), modified_by: 'mike.johnson@example.com',   _msg: 'Status changed to Pending Security Review' },
				{ name: 'JO-2026-00018', status: 'Completed',   modified: frappe.datetime.now_datetime(), modified_by: 'jane.smith@example.com',     _msg: 'Marked as Completed' },
				{ name: 'JO-2026-00015', status: 'In Progress', modified: frappe.datetime.now_datetime(), modified_by: 'john.doe@example.com',       _msg: 'Status changed to In Progress' },
				{ name: 'JO-2026-00017', status: 'Draft',       modified: frappe.datetime.now_datetime(), modified_by: 'sarah.williams@example.com', _msg: 'Job order created' },
			],
		};
	}
}
