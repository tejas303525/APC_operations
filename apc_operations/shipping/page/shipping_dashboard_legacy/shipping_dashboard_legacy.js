frappe.pages['shipping-dashboard-legacy'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Shipping'),
		single_column: true,
	});

	page.set_secondary_action(__('Customize'), () => {
		frappe.msgprint(__('Customization options coming soon.'));
	}, 'edit');

	frappe.shipping_dashboard = new ShippingDashboard(page, wrapper);
};

frappe.pages['shipping-dashboard-legacy'].on_page_show 	= function () {
	if (frappe.shipping_dashboard) {
		frappe.shipping_dashboard.refresh();
	}
};

class ShippingDashboard {
	constructor(page, wrapper) {
		this.page    = page;
		this.wrapper = wrapper;
		this.data    = {};
		this.wizard_step = 1;
		this._build_layout();
		this.refresh();
		this._start_auto_refresh();
	}

	// ── Layout scaffold ────────────────────────────────────────────────

	_build_layout() {
		const root = $(this.wrapper).find('.page-content');
		root.css({ padding: '20px 24px' });

		this.$root = $('<div class="shipping-dashboard"></div>').appendTo(root);

		// Overview KPI strip
		this.$kpi_strip = $('<div class="sd-overview-strip"></div>').appendTo(this.$root);
		this._render_kpi_skeleton();

		// Focus section
		this.$focus = $('<div class="sd-focus-section"><h6>What you should focus on today</h6><div class="focus-items"></div></div>').appendTo(this.$root);

		// Pipeline
		this.$pipeline_wrap = $('<div class="sd-pipeline-section"><h6>Shipping Pipeline</h6><div class="sd-pipeline"></div></div>').appendTo(this.$root);

		// Bottom two-column grid
		this.$bottom = $('<div class="sd-bottom-grid"></div>').appendTo(this.$root);
		this.$milestones = $('<div class="sd-section-card"></div>').appendTo(this.$bottom);
		this.$recent_cros = $('<div class="sd-section-card"></div>').appendTo(this.$bottom);

		// Full-width recent job orders
		this.$job_orders = $('<div class="sd-full-card"></div>').appendTo(this.$root);
	}

	_render_kpi_skeleton() {
		const skeletons = [
			'To Book Vessel', 'DG/NDG To Confirm', 'SI To Create', 'ED Due', 'Pull Out Date Today',
		];
		skeletons.forEach(() => {
			this.$kpi_strip.append(`
				<div class="sd-kpi-card">
					<div class="sd-skeleton" style="width:70%;height:11px;"></div>
					<div class="sd-skeleton" style="width:40%;height:32px;margin:8px 0 4px;"></div>
					<div class="sd-skeleton" style="width:55%;height:10px;"></div>
				</div>
			`);
		});
	}

	// ── Data refresh ───────────────────────────────────────────────────

	refresh() {
		frappe.call({
			method: 'apc_operations.shipping.api.get_shipping_dashboard_data',
			freeze: false,
			callback: (r) => {
				if (r.message) {
					this.data = r.message;
					this._render_all();
				}
			},
			error: () => {
				// Render placeholder data if API fails (dev / no-data mode)
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
		this._render_kpi(this.data.kpi || {});
		this._render_focus(this.data.focus_items || []);
		this._render_pipeline(this.data.pipeline || {});
		this._render_milestones(this.data.upcoming_milestones || {});
		this._render_recent_cros(this.data.recent_cros || []);
		this._render_job_orders(this.data.recent_job_orders || []);
	}

	// ── KPI Cards ─────────────────────────────────────────────────────

	_render_kpi(kpi) {
		const cards = [
			{
				label: 'To Book Vessel',
				count: kpi.to_book_vessel ?? 0,
				sub: 'Bookings pending',
				color: 'kpi-blue',
				route: ['List', 'Shipping Booking', { vessel_name: ['is', 'not set'] }],
			},
			{
				label: 'DG/NDG To Confirm',
				count: kpi.dg_to_confirm ?? 0,
				sub: 'Need classification',
				color: 'kpi-amber',
				route: ['List', 'Shipping Booking', { is_dangerous_goods: 1, dg_class: ['is', 'not set'] }],
			},
			{
				label: 'SI To Create',
				count: kpi.si_to_create ?? 0,
				sub: 'Shipping Instructions',
				color: 'kpi-teal',
				route: ['List', 'Shipping Booking', { cro_status: 'Generated' }],
			},
			{
				label: 'ED Due',
				count: kpi.ed_due ?? 0,
				sub: 'Documents due today',
				color: 'kpi-red',
				route: ['List', 'Shipping Booking', { cutoff_date: frappe.datetime.get_today() }],
			},
			{
				label: 'Pull Out Date Today',
				count: kpi.pull_out_today ?? 0,
				sub: 'Containers',
				color: 'kpi-green',
				route: ['List', 'Shipping Booking', { pull_out_date: frappe.datetime.get_today() }],
			},
		];

		this.$kpi_strip.empty();
		cards.forEach(c => {
			const $card = $(`
				<div class="sd-kpi-card">
					<div class="kpi-label">${__(c.label)}</div>
					<div class="kpi-count ${c.color}">${c.count}</div>
					<div class="kpi-sub">${__(c.sub)}</div>
				</div>
			`);
			$card.on('click', () => frappe.set_route(...c.route));
			this.$kpi_strip.append($card);
		});
	}

	// ── Focus Items ────────────────────────────────────────────────────

	_render_focus(items) {
		if (!items.length) {
			items = [
				{
					icon: '📦', icon_class: 'focus-icon-blue',
					title: `Book Vessel for ${this.data.kpi?.to_book_vessel ?? 0} shipments`,
					sub: 'Vessel not booked',
					btn: 'Book Vessel',
					action: 'book_vessel',
				},
				{
					icon: '⚠️', icon_class: 'focus-icon-amber',
					title: `Confirm DG/NDG for ${this.data.kpi?.dg_to_confirm ?? 0} shipments`,
					sub: 'Waiting for classification',
					btn: 'Confirm Now',
					action: 'confirm_dg',
				},
				{
					icon: '🕐', icon_class: 'focus-icon-teal',
					title: `Create SI for ${this.data.kpi?.si_to_create ?? 0} shipments`,
					sub: 'Shipping Instructions pending',
					btn: 'Create SI',
					action: 'create_si',
				},
				{
					icon: '📅', icon_class: 'focus-icon-red',
					title: 'Submit documents before Pull Out Date',
					sub: `${this.data.kpi?.ed_due ?? 0} shipment has ED due today`,
					btn: 'View ED List',
					action: 'view_ed',
				},
			];
		}

		const $container = this.$focus.find('.focus-items').empty();
		items.forEach(item => {
			const $row = $(`
				<div class="sd-focus-item">
					<div class="focus-icon ${item.icon_class}">${item.icon}</div>
					<div class="focus-text">
						<strong>${__(item.title)}</strong>
						<small>${__(item.sub)}</small>
					</div>
					<button class="focus-action-btn" data-action="${item.action}">${__(item.btn)}</button>
				</div>
			`);
			$row.find('[data-action]').on('click', (e) => {
				this._focus_action($(e.currentTarget).data('action'));
			});
			$container.append($row);
		});
	}

	_focus_action(action) {
		const actions = {
			book_vessel: () => frappe.set_route('List', 'Shipping Booking', { vessel_name: ['=', ''] }),
			confirm_dg:  () => frappe.set_route('List', 'Shipping Booking', { is_dangerous_goods: 1, dg_class: ['=', ''] }),
			create_si:   () => frappe.set_route('List', 'Shipping Booking', { cro_status: 'Generated' }),
			view_ed:     () => frappe.set_route('List', 'Shipping Booking', { cutoff_date: frappe.datetime.get_today() }),
		};
		(actions[action] || (() => {}))();
	}

	// ── Pipeline ───────────────────────────────────────────────────────

	_render_pipeline(p) {
		const stages = [
			{ icon: '📦', name: 'Freight Containers', count: p.freight_containers ?? 0, sub: 'Total',    class: '' },
			{ icon: '⚠️', name: 'DG / NDG',           count: p.dg_ndg ?? 0,            sub: 'Pending',  class: '' },
			{ icon: '📄', name: 'THC / TLUC / ED',    count: p.thc_tluc_ed ?? 0,       sub: 'Pending',  class: '' },
			{ icon: '📋', name: 'SI',                  count: p.si ?? 0,                sub: 'Pending',  class: '' },
			{ icon: '✅', name: 'CRO Generated',       count: p.cro_generated ?? 0,     sub: 'Completed', class: 'stage-completed' },
		];

		const $pipe = this.$pipeline_wrap.find('.sd-pipeline').empty();
		stages.forEach((s, i) => {
			$pipe.append(`
				<div class="pipeline-stage ${s.class}">
					<div class="stage-icon">${s.icon}</div>
					<div class="stage-name">${__(s.name)}</div>
					<div class="stage-count">${s.count}</div>
					<div class="stage-sub">${__(s.sub)}</div>
				</div>
			`);
			if (i < stages.length - 1) {
				$pipe.append('<div class="pipeline-arrow">›</div>');
			}
		});
	}

	// ── Upcoming Milestones ────────────────────────────────────────────

	_render_milestones(m) {
		const items = [
			{
				icon: '📅', icon_class: 'mi-red',
				label: 'ED Due Tomorrow',
				count: m.ed_tomorrow ?? 0,
				unit: 'shipments',
				badge_class: 'badge-red',
				route: ['List', 'Shipping Booking', { cutoff_date: frappe.datetime.add_days(frappe.datetime.get_today(), 1) }],
			},
			{
				icon: '🚛', icon_class: 'mi-amber',
				label: 'Pull Out Date in 3 Days',
				count: m.pull_out_3days ?? 0,
				unit: 'containers',
				badge_class: 'badge-amber',
				route: ['List', 'Shipping Booking', { pull_out_date: ['<=', frappe.datetime.add_days(frappe.datetime.get_today(), 3)] }],
			},
			{
				icon: '🚢', icon_class: 'mi-blue',
				label: 'Vessel ETD in 7 Days',
				count: m.etd_7days ?? 0,
				unit: 'shipments',
				badge_class: 'badge-blue',
				route: ['List', 'Shipping Booking', { vessel_date: ['<=', frappe.datetime.add_days(frappe.datetime.get_today(), 7)] }],
			},
		];

		this.$milestones.html(`
			<div class="section-header">
				<span class="section-title">${__('Upcoming Milestones')}</span>
			</div>
			<div class="milestone-list"></div>
			<div class="milestone-viewall">${__('View All Milestones')}</div>
		`);

		const $list = this.$milestones.find('.milestone-list');
		items.forEach(item => {
			const $row = $(`
				<div class="milestone-item" style="cursor:pointer;">
					<div class="milestone-left">
						<div class="milestone-icon ${item.icon_class}">${item.icon}</div>
						<span class="milestone-label">${__(item.label)}</span>
					</div>
					<span class="milestone-badge ${item.badge_class}">${item.count} ${__(item.unit)}</span>
				</div>
			`);
			$row.on('click', () => frappe.set_route(...item.route));
			$list.append($row);
		});

		this.$milestones.find('.milestone-viewall').on('click', () => {
			frappe.set_route('List', 'Shipping Booking');
		});
	}

	// ── Recent CROs ────────────────────────────────────────────────────

	_render_recent_cros(cros) {
		this.$recent_cros.html(`
			<div class="section-header">
				<span class="section-title">${__('Recent CROs')}</span>
				<span class="section-link view-all-cros">${__('View All')}</span>
			</div>
			<table class="sd-table">
				<thead>
					<tr>
						<th>${__('CRO No.')}</th>
						<th>${__('Vessel')}</th>
						<th>${__('ETD')}</th>
						<th>${__('Amount (USD)')}</th>
						<th>${__('Status')}</th>
					</tr>
				</thead>
				<tbody class="cro-tbody"></tbody>
			</table>
		`);

		this.$recent_cros.find('.view-all-cros').on('click', () => {
			frappe.set_route('List', 'Shipping Booking', { cro_status: ['!=', ''] });
		});

		const $tbody = this.$recent_cros.find('.cro-tbody');
		if (!cros.length) {
			$tbody.append(`<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:20px 0;">${__('No CROs found')}</td></tr>`);
			return;
		}

		cros.forEach(c => {
			const status_class = this._cro_status_class(c.cro_status);
			$tbody.append(`
				<tr>
					<td><a href="/app/shipping-booking/${c.name}">${c.cro_number || c.name}</a></td>
					<td>${c.vessel_name || '—'}</td>
					<td>${c.vessel_date ? frappe.datetime.str_to_user(c.vessel_date) : '—'}</td>
					<td>${c.total_freight_charges ? frappe.format(c.total_freight_charges, { fieldtype: 'Currency' }) : '—'}</td>
					<td><span class="status-badge ${status_class}">${__(c.cro_status || 'Draft')}</span></td>
				</tr>
			`);
		});
	}

	_cro_status_class(status) {
		const map = {
			'Generated': 'status-linked',
			'Issued':    'status-linked',
			'Linked':    'status-linked',
			'Pending':   'status-generated',
			'Draft':     'status-draft',
		};
		return map[status] || 'status-draft';
	}

	// ── Recent Freight Containers (with Job Order column) ─────────────

	_render_job_orders(rows) {
		this.$job_orders.html(`
			<div class="section-header">
				<span class="section-title">${__('Recent Freight Containers')}</span>
				<span class="section-link view-all-jo">${__('View All')}</span>
			</div>
			<table class="sd-table">
				<thead>
					<tr>
						<th>${__('Job Order')}</th>
						<th>${__('Shipping Line')}</th>
						<th>${__('POL')}</th>
						<th>${__('POD')}</th>
						<th>${__('Vessel')}</th>
						<th>${__('Status')}</th>
						<th>${__('Pull Out Date')}</th>
					</tr>
				</thead>
				<tbody class="jo-tbody"></tbody>
			</table>
		`);

		this.$job_orders.find('.view-all-jo').on('click', () => {
			frappe.set_route('List', 'Shipping Booking');
		});

		const $tbody = this.$job_orders.find('.jo-tbody');
		if (!rows.length) {
			$tbody.append(`<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:20px 0;">${__('No records found')}</td></tr>`);
			return;
		}

		rows.forEach(c => {
			const status_class = this._booking_status_class(c.booking_status, c.cro_status);
			const status_label = this._booking_status_label(c.booking_status, c.cro_status);
			const jo_text = c.job_order_number || c.job_order || '—';
			const jo_link = c.job_order
				? `<a href="/app/job-order/${c.job_order}">${jo_text}</a>`
				: `<span style="color:var(--text-muted)">—</span>`;
			$tbody.append(`
				<tr>
					<td>${jo_link}</td>
					<td>${c.shipping_line || '—'}</td>
					<td>${c.port_of_loading || '—'}</td>
					<td>${c.port_of_discharge || '—'}</td>
					<td>${c.vessel_name || '—'}</td>
					<td><span class="status-badge ${status_class}">${__(status_label)}</span></td>
					<td>${c.pull_out_date ? frappe.datetime.str_to_user(c.pull_out_date) : '—'}</td>
				</tr>
			`);
		});
	}

	_booking_status_label(booking_status, cro_status) {
		if (cro_status === 'Generated' || cro_status === 'Issued') return 'CRO Generated';
		if (!booking_status || booking_status === 'Draft') return 'Vessel Not Booked';
		if (booking_status === 'Confirmed') return 'SI Created';
		if (booking_status === 'Submitted') return 'In Transit';
		return booking_status || 'Draft';
	}

	_booking_status_class(booking_status, cro_status) {
		if (cro_status === 'Generated' || cro_status === 'Issued') return 'status-cro-generated';
		if (!booking_status || booking_status === 'Draft') return 'status-vessel-not-booked';
		if (booking_status === 'Confirmed') return 'status-si-created';
		if (booking_status === 'Submitted') return 'status-in-transit';
		return 'status-draft';
	}

	// ── Placeholder data (dev / offline mode) ─────────────────────────

	_placeholder_data() {
		return {
			kpi: { to_book_vessel: 3, dg_to_confirm: 2, si_to_create: 5, ed_due: 1, pull_out_today: 2 },
			focus_items: [],
			pipeline: { freight_containers: 12, dg_ndg: 8, thc_tluc_ed: 6, si: 5, cro_generated: 2 },
			upcoming_milestones: { ed_tomorrow: 2, pull_out_3days: 4, etd_7days: 3 },
			recent_cros: [],
			recent_job_orders: [],
		};
	}
}
