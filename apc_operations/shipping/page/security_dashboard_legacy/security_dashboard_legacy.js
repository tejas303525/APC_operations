frappe.pages['security-dashboard-legacy'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Security Dashboard'),
		single_column: true,
	});

	frappe.security_dashboard = new SecurityDashboard(page, wrapper);
};

frappe.pages['security-dashboard-legacy'].on_page_show = function () {
	if (frappe.security_dashboard) {
		frappe.security_dashboard.refresh();
	}
};

class SecurityDashboard {
	constructor(page, wrapper) {
		this.page    = page;
		this.wrapper = wrapper;
		this.data    = {};
		this._setup_page_actions();
		this._build_layout();
		this.refresh();
		this._start_auto_refresh();
	}

	// ── Header action buttons ───────────────────────────────────────────

	_setup_page_actions() {
		this.page.set_primary_action(__('Review Draft DNs'), () => {
			frappe.set_route('List', 'Security Draft Delivery Note', { security_status: 'Pending Review' });
		}, 'plus');

		this.page.add_inner_button(__('Create Checklist'), () => {
			frappe.set_route('List', 'Security Inspection', { security_status: 'Pending Checklist' });
		});

		this.page.add_inner_button(__('Report to QC'), () => {
			frappe.set_route('List', 'Security Inspection', { security_status: 'Checklist Completed' });
		});

		this.page.add_inner_button(__('Prepare Loading DN'), () => {
			frappe.set_route('List', 'Security Inspection', { qc_status: 'QC Cleared' });
		});

		this.page.add_inner_button(__('View Draft DN'), () => {
			frappe.set_route('List', 'Security Draft Delivery Note');
		});

		this.page.add_inner_button(__('Gate Entry Log'), () => {
			frappe.set_route('List', 'Gate Pass');
		});

		this.page.set_secondary_action(__('Refresh'), () => this.refresh(), 'refresh');
	}

	// ── Layout scaffold ─────────────────────────────────────────────────

	_build_layout() {
		const root = $(this.wrapper).find('.page-content');
		root.css({ padding: '0 24px 32px' });

		this.$root = $('<div class="sec-dashboard"></div>').appendTo(root);

		// Subtitle
		this.$root.append(`
			<p class="sec-subtitle">${__('Manage gate security checks, container verification, ISO checks, weightment slips, QC reporting, loading DN preparation, and receivables notifications.')}</p>
		`);

		// Today's Actions
		this.$root.append(`<h6 class="sec-section-heading">${__("Today's Actions")}</h6>`);
		this.$actions_strip = $('<div class="sec-actions-strip"></div>').appendTo(this.$root);
		this._render_actions_skeleton();

		// KPI Counter Grid
		this.$kpi_grid = $('<div class="sec-kpi-grid"></div>').appendTo(this.$root);
		this._render_kpi_skeleton();

		// Bottom two-column: Quick Links (left) + Today's Queue (right)
		this.$bottom = $('<div class="sec-bottom-grid"></div>').appendTo(this.$root);
		this.$quick_links_card = $('<div class="sec-card"></div>').appendTo(this.$bottom);
		this.$today_queue_card = $('<div class="sec-card"></div>').appendTo(this.$bottom);

		// Quick links are static — render once
		this._render_quick_links();
	}

	_render_actions_skeleton() {
		this.$actions_strip.empty();
		for (let i = 0; i < 5; i++) {
			this.$actions_strip.append(`
				<div class="sec-action-card">
					<div class="sec-skeleton" style="width:40px;height:40px;border-radius:8px;"></div>
					<div style="flex:1;padding:0 12px;">
						<div class="sec-skeleton" style="width:60%;height:12px;margin-bottom:6px;"></div>
						<div class="sec-skeleton" style="width:80%;height:10px;"></div>
					</div>
					<div class="sec-skeleton" style="width:100px;height:28px;border-radius:6px;"></div>
				</div>
			`);
		}
	}

	_render_kpi_skeleton() {
		this.$kpi_grid.empty();
		for (let i = 0; i < 8; i++) {
			this.$kpi_grid.append(`
				<div class="sec-kpi-card">
					<div class="sec-skeleton" style="width:40px;height:40px;border-radius:8px;margin-bottom:12px;"></div>
					<div class="sec-skeleton" style="width:70%;height:11px;margin-bottom:8px;"></div>
					<div class="sec-skeleton" style="width:40%;height:28px;margin-bottom:6px;"></div>
					<div class="sec-skeleton" style="width:55%;height:10px;"></div>
				</div>
			`);
		}
	}

	// ── Data refresh ────────────────────────────────────────────────────

	refresh() {
		frappe.call({
			method: 'apc_operations.shipping.api.get_security_dashboard_data',
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

	// ── Master render ───────────────────────────────────────────────────

	_render_all() {
		const kpis = this.data.kpis || {};
		this._render_actions_strip(kpis);
		this._render_kpi_grid(kpis);
		this._render_today_queue(this.data.today_queue || []);
	}

	// ── Today's Actions strip ───────────────────────────────────────────

	_render_actions_strip(kpis) {
		const actions = [
			{
				icon_class: 'sec-icon-truck', icon: '🚛',
				count: kpis.vehicles_at_gate ?? 0,
				label: __('vehicles waiting at gate'),
				btn: __('Start inspection →'),
				btn_class: 'btn-orange',
				route: ['List', 'Security Inspection', { security_status: 'Draft' }],
			},
			{
				icon_class: 'sec-icon-check', icon: '☑️',
				count: kpis.checklist_pending ?? 0,
				label: __('checklists pending'),
				btn: __('Complete now →'),
				btn_class: 'btn-teal',
				route: ['List', 'Security Inspection', { security_status: 'Pending Checklist' }],
			},
			{
				icon_class: 'sec-icon-shield', icon: '🛡️',
				count: kpis.qc_pending ?? 0,
				label: __('QC report pending'),
				btn: __('Send to QC →'),
				btn_class: 'btn-blue',
				route: ['List', 'QC Report Request', { qc_status: 'Pending QC' }],
			},
			{
				icon_class: 'sec-icon-doc', icon: '📄',
				count: kpis.draft_dns_pending_review ?? 0,
				label: __('draft DNs ready'),
				btn: __('Review & issue →'),
				btn_class: 'btn-purple',
				route: ['List', 'Security Draft Delivery Note', { security_status: 'Pending Review' }],
			},
			{
				icon_class: 'sec-icon-bell', icon: '🔔',
				count: kpis.pending_receivables ?? 0,
				label: __('receivables notification pending'),
				btn: __('Notify now →'),
				btn_class: 'btn-pink',
				route: ['List', 'Loading Delivery Note', { receivables_status: 'Pending Receivables' }],
			},
		];

		this.$actions_strip.empty();
		actions.forEach(a => {
			const $card = $(`
				<div class="sec-action-card">
					<div class="sec-action-icon ${a.icon_class}">${a.icon}</div>
					<div class="sec-action-body">
						<span class="sec-action-count">${a.count}</span>
						<span class="sec-action-label">${a.label}</span>
					</div>
					<button class="sec-action-btn ${a.btn_class}">${a.btn}</button>
				</div>
			`);
			$card.find('button').on('click', () => frappe.set_route(...a.route));
			this.$actions_strip.append($card);
		});
	}

	// ── KPI Counter Grid ────────────────────────────────────────────────

	_render_kpi_grid(kpis) {
		const cards = [
			{
				icon: '🚛', icon_class: 'kpi-icon-orange',
				label: __('Vehicles at Gate'),
				count: kpis.vehicles_at_gate ?? 0,
				sub: __('High priority'),
				sub_class: 'sub-red',
				route: ['List', 'Security Inspection', { security_status: 'Draft' }],
			},
			{
				icon: '☑️', icon_class: 'kpi-icon-teal',
				label: __('Pending Container Checklists'),
				count: kpis.checklist_pending ?? 0,
				sub: __('Due today'),
				sub_class: 'sub-orange',
				route: ['List', 'Security Inspection', { security_status: 'Pending Checklist' }],
			},
			{
				icon: '🛡️', icon_class: 'kpi-icon-blue',
				label: __('ISO Checks Pending'),
				count: kpis.iso_checks_pending ?? 0,
				sub: __('Due today'),
				sub_class: 'sub-orange',
				route: ['List', 'Security Inspection', { inspection_type: ['in', ['ISO Tank', 'Tanker']] }],
			},
			{
				icon: '⚖️', icon_class: 'kpi-icon-purple',
				label: __('Weightment Slips Pending'),
				count: kpis.weightment_slips_pending ?? 0,
				sub: __('Due today'),
				sub_class: 'sub-orange',
				route: ['List', 'Security Inspection', { security_status: ['in', ['Pending Checklist', 'Checklist Completed']] }],
			},
			{
				icon: '🛡️', icon_class: 'kpi-icon-green',
				label: __('QC Reports Pending'),
				count: kpis.qc_pending ?? 0,
				sub: __('Due today'),
				sub_class: 'sub-orange',
				route: ['List', 'QC Report Request', { qc_status: 'Pending QC' }],
			},
			{
				icon: '📄', icon_class: 'kpi-icon-amber',
				label: __('Loading DNs To Issue'),
				count: kpis.loading_dns_pending ?? 0,
				sub: __('Up from yesterday'),
				sub_class: 'sub-green',
				route: ['List', 'Loading Delivery Note', { delivery_note_status: ['not in', ['Completed', 'Cancelled']] }],
			},
			{
				icon: '📋', icon_class: 'kpi-icon-cyan',
				label: __('Draft Delivery Notes from Transportation'),
				count: kpis.draft_dns_pending_review ?? 0,
				sub: __('Ready for review'),
				sub_class: 'sub-blue',
				route: ['List', 'Security Draft Delivery Note', { security_status: 'Pending Review' }],
			},
			{
				icon: '🔔', icon_class: 'kpi-icon-pink',
				label: __('Receivables Notifications Pending'),
				count: kpis.pending_receivables ?? 0,
				sub: __('Due today'),
				sub_class: 'sub-orange',
				route: ['List', 'Loading Delivery Note', { receivables_status: 'Pending Receivables' }],
			},
		];

		this.$kpi_grid.empty();
		cards.forEach(c => {
			const $card = $(`
				<div class="sec-kpi-card" title="${c.label}">
					<div class="sec-kpi-icon ${c.icon_class}">${c.icon}</div>
					<div class="sec-kpi-label">${c.label}</div>
					<div class="sec-kpi-count">${c.count}</div>
					<div class="sec-kpi-sub ${c.sub_class}">
						<span class="sec-sub-dot"></span>${c.sub}
					</div>
				</div>
			`);
			$card.on('click', () => frappe.set_route(...c.route));
			this.$kpi_grid.append($card);
		});
	}

	// ── Quick Links (static) ────────────────────────────────────────────

	_render_quick_links() {
		const groups = [
			{
				title: __('Security Operations'),
				links: [
					{ label: __('Container Inspection'),  route: ['List', 'Security Inspection'] },
					{ label: __('Gate Entry Log'),         route: ['List', 'Gate Pass'] },
					{ label: __('ISO Verification'),       route: ['List', 'Security Inspection', { inspection_type: 'ISO Tank' }] },
					{ label: __('Checklist Review'),       route: ['List', 'Security Inspection', { security_status: 'Pending Checklist' }] },
				],
			},
			{
				title: __('Documents'),
				links: [
					{ label: __('Weightment Slip'),        route: ['List', 'Weighment Slip'] },
					{ label: __('Loading Delivery Note'),  route: ['List', 'Loading Delivery Note'] },
					{ label: __('Draft Delivery Notes'),   route: ['List', 'Security Draft Delivery Note'] },
					{ label: __('QC Dispatch Report'),     route: ['List', 'QC Report Request'] },
				],
			},
			{
				title: __('Reports'),
				links: [
					{ label: __("Today's Security Queue"),  route: ['List', 'Security Inspection', { modified: ['>=', frappe.datetime.get_today()] }] },
					{ label: __('Pending QC Reports'),       route: ['List', 'QC Report Request', { qc_status: 'Pending QC' }] },
					{ label: __('DN Status'),                route: ['List', 'Loading Delivery Note'] },
					{ label: __('Receivables Pending'),      route: ['List', 'Loading Delivery Note', { receivables_status: 'Pending Receivables' }] },
				],
			},
		];

		this.$quick_links_card.html(`
			<div class="sec-card-header">
				<span class="sec-card-title">${__('Quick Links')}</span>
			</div>
			<div class="sec-ql-wrapper"></div>
		`);

		const $wrapper = this.$quick_links_card.find('.sec-ql-wrapper');
		groups.forEach(g => {
			const $group = $(`
				<div class="sec-ql-group">
					<div class="sec-ql-group-title">${g.title}</div>
				</div>
			`);
			g.links.forEach(link => {
				const $link = $(`
					<div class="sec-ql-link">
						<svg class="sec-ql-arrow" viewBox="0 0 16 16" fill="none">
							<path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
						</svg>
						<span>${link.label}</span>
					</div>
				`);
				$link.on('click', () => frappe.set_route(...link.route));
				$group.append($link);
			});
			$wrapper.append($group);
		});
	}

	// ── Today's Queue table ─────────────────────────────────────────────

	_render_today_queue(queue) {
		this.$today_queue_card.html(`
			<div class="sec-card-header">
				<span class="sec-card-title">${__("Today's Queue")}</span>
				<span class="sec-card-link sec-view-all-queue">${__('View all')} →</span>
			</div>
			<div class="sec-table-wrap">
				<table class="sec-table">
					<thead>
						<tr>
							<th>${__('Reference')}</th>
							<th>${__('Type')}</th>
							<th>${__('Status')}</th>
							<th>${__('Deadline')}</th>
							<th>${__('Action')}</th>
						</tr>
					</thead>
					<tbody class="sec-queue-tbody"></tbody>
				</table>
			</div>
		`);

		this.$today_queue_card.find('.sec-view-all-queue').on('click', () => {
			frappe.set_route('List', 'Security Inspection');
		});

		const $tbody = this.$today_queue_card.find('.sec-queue-tbody');

		if (!queue.length) {
			$tbody.append(`
				<tr>
					<td colspan="5" class="sec-table-empty">
						${__('No pending items — all clear!')}
					</td>
				</tr>
			`);
			return;
		}

		queue.forEach(item => {
			const badge_class  = this._status_badge_class(item.status_color);
			const action_class = this._action_btn_class(item.status_color);
			const deadline_display = item.deadline && item.deadline.length >= 10
				? frappe.datetime.str_to_user(item.deadline.substring(0, 10))
				: (item.deadline || '—');

			$tbody.append(`
				<tr>
					<td>
						<a href="${item.route}" class="sec-ref-link">${item.reference}</a>
					</td>
					<td class="sec-type-cell">${__(item.type)}</td>
					<td>
						<span class="sec-badge ${badge_class}">${__(item.status)}</span>
					</td>
					<td class="sec-deadline-cell">
						<span class="sec-clock-icon">🕐</span>
						${deadline_display}
					</td>
					<td>
						<button class="sec-queue-btn ${action_class}" data-route="${item.route}">
							${__(item.action)}
						</button>
					</td>
				</tr>
			`);
		});

		$tbody.find('.sec-queue-btn').on('click', function () {
			window.location.href = $(this).data('route');
		});
	}

	_status_badge_class(color) {
		const map = {
			orange: 'badge-orange',
			yellow: 'badge-yellow',
			blue:   'badge-blue',
			green:  'badge-green',
			red:    'badge-red',
			purple: 'badge-purple',
		};
		return map[color] || 'badge-gray';
	}

	_action_btn_class(color) {
		const map = {
			orange: 'action-orange',
			yellow: 'action-yellow',
			blue:   'action-blue',
			green:  'action-green',
			red:    'action-red',
			purple: 'action-purple',
		};
		return map[color] || 'action-gray';
	}

	// ── Placeholder data for dev / empty DB ─────────────────────────────

	_placeholder_data() {
		return {
			kpis: {
				vehicles_at_gate:       2,
				checklist_pending:      3,
				iso_checks_pending:     1,
				weightment_slips_pending: 2,
				qc_pending:             1,
				loading_dns_pending:    2,
				draft_dns_pending_review: 4,
				pending_receivables:    1,
				completed_today:        0,
			},
			today_queue: [
				{
					reference: 'JO-2026-00124', type: 'Gate Inspection',
					status: 'Waiting at Gate', status_color: 'orange',
					deadline: frappe.datetime.get_today(),
					action: 'Start',
					route: '/app/security-inspection',
				},
				{
					reference: 'SB-2026-00013', type: 'Container Checklist',
					status: 'Pending', status_color: 'yellow',
					deadline: frappe.datetime.get_today(),
					action: 'Complete',
					route: '/app/security-inspection',
				},
				{
					reference: 'SB-2026-00014', type: 'QC Report',
					status: 'Pending QC', status_color: 'blue',
					deadline: frappe.datetime.get_today(),
					action: 'Report to QC',
					route: '/app/qc-report-request',
				},
				{
					reference: 'SB-2026-00015', type: 'Draft Delivery Note',
					status: 'Draft Ready', status_color: 'blue',
					deadline: frappe.datetime.get_today(),
					action: 'Review',
					route: '/app/security-draft-delivery-note',
				},
			],
		};
	}
}
