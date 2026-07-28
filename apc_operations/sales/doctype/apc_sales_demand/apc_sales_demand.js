frappe.ui.form.on('APC Sales Demand', {
	refresh(frm) {
		frm.trigger('render_allocation_summary');

		if (!frm.is_new()) {
			frm.add_custom_button(__('Calculate Production Requirement'), () => {
				frappe.call({
					doc: frm.doc,
					method: 'calculate_production_requirement',
					freeze: true,
					callback(r) {
						frappe.show_alert({
							message: r.message?.message || __('Production requirements calculated.'),
							indicator: 'green',
						});
						frm.reload_doc();
					},
				});
			}, __('Actions'));

			frm.add_custom_button(__('Allocate Batches'), () => {
				frm.trigger('preview_and_allocate_batches');
			}, __('Actions'));

			frm.add_custom_button(__('Batch Allocation Dashboard'), () => {
				frappe.db.get_value('Job Order', { sales_demand: frm.doc.name }, 'name').then((r) => {
					frappe.route_options = r.message ? { job_order: r.message } : {};
					frappe.set_route('batch-allocation-dashboard');
				});
			}, __('View'));

			frm.add_custom_button(__('View Batch Allocations'), () => {
				frappe.set_route('List', 'APC Batch Allocation', { sales_demand: frm.doc.name });
			}, __('View'));
		}

		frm.trigger('refresh_stock_indicators');
	},

	render_allocation_summary(frm) {
		const demand = flt(frm.doc.total_demand_quantity);
		const allocated = flt(frm.doc.total_allocated_quantity);
		const production = flt(frm.doc.total_production_required_quantity);
		const pct = demand ? Math.min((allocated / demand) * 100, 100) : 0;

		frm.dashboard.clear_headline();
		frm.dashboard.set_headline_alert(`
			<div>
				<strong>${__('Demand')}:</strong> ${frappe.format(demand, { fieldtype: 'Float' })}
				&nbsp; | &nbsp;
				<strong>${__('Allocated')}:</strong> ${frappe.format(allocated, { fieldtype: 'Float' })} (${pct.toFixed(1)}%)
				&nbsp; | &nbsp;
				<strong>${__('Production Required')}:</strong> ${frappe.format(production, { fieldtype: 'Float' })}
			</div>
		`, pct >= 100 ? 'green' : 'orange');

		frm.dashboard.add_indicator(__('Allocation: {0}', [frm.doc.allocation_status || 'Not Allocated']), pct >= 100 ? 'green' : 'orange');
		frm.dashboard.add_indicator(__('Fulfillment: {0}', [frm.doc.fulfillment_status || 'Not Started']), 'blue');
	},

	refresh_stock_indicators(frm) {
		(frm.doc.items || []).forEach((row) => {
			if (row.item) {
				frm.events.update_item_free_stock(frm, row.doctype, row.name);
			}
		});
	},

	update_item_free_stock(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row?.item) {
			return;
		}

		frappe.call({
			method: 'apc_operations.services.dashboard.get_available_batches_for_dashboard',
			args: {
				filters: {
					product: row.item,
					grade: row.grade,
					specification: row.specification,
					packaging_type: row.packaging_type,
					warehouse: row.warehouse,
				},
			},
			callback(r) {
				const batches = r.message || [];
				const free_stock = batches.reduce((total, batch) => total + flt(batch.available_quantity), 0);
				frappe.model.set_value(cdt, cdn, 'free_stock_available', free_stock);
			},
		});
	},

	preview_and_allocate_batches(frm) {
		frappe.call({
			method: 'apc_operations.services.dashboard.preview_fifo_allocation',
			args: { sales_demand: frm.doc.name },
			freeze: true,
			callback(r) {
				const preview = r.message || {};
				const rows = preview.allocations || [];
				const shortages = preview.shortages || [];
				const allocation_html = rows.length
					? rows.map(row => `
						<tr>
							<td>${frappe.utils.escape_html(row.item || '')}</td>
							<td>${frappe.utils.escape_html(row.batch || '')}</td>
							<td>${row.manufacturing_date || ''}</td>
							<td class="text-right">${frappe.format(row.allocated_quantity, { fieldtype: 'Float' })}</td>
						</tr>
					`).join('')
					: `<tr><td colspan="4" class="text-muted text-center">${__('No stock available for allocation.')}</td></tr>`;
				const shortage_html = shortages.length
					? `<p class="text-danger">${__('Shortages')}: ${shortages.map(s => `${s.item}: ${s.required_qty}`).join(', ')}</p>`
					: '';

				const dialog = new frappe.ui.Dialog({
					title: __('FIFO Allocation Preview'),
					size: 'large',
					fields: [{
						fieldname: 'preview',
						fieldtype: 'HTML',
						options: `
							${shortage_html}
							<table class="table table-bordered">
								<thead>
									<tr>
										<th>${__('Item')}</th>
										<th>${__('Batch')}</th>
										<th>${__('MFG Date')}</th>
										<th class="text-right">${__('Allocate Qty')}</th>
									</tr>
								</thead>
								<tbody>${allocation_html}</tbody>
							</table>
						`,
					}],
					primary_action_label: __('Create Allocation'),
					primary_action() {
						frappe.call({
							doc: frm.doc,
							method: 'allocate_batches',
							freeze: true,
							callback(res) {
								dialog.hide();
								if (res.message?.allocation) {
									frappe.set_route('Form', 'APC Batch Allocation', res.message.allocation);
								} else {
									frappe.msgprint(res.message?.message || __('No allocation was created.'));
								}
							},
						});
					},
				});

				dialog.show();
				if (!rows.length) {
					dialog.get_primary_btn().prop('disabled', true);
				}
			},
		});
	},
});

frappe.ui.form.on('APC Sales Demand Item', {
	item(frm, cdt, cdn) {
		frm.events.update_item_free_stock(frm, cdt, cdn);
	},
	grade(frm, cdt, cdn) {
		frm.events.update_item_free_stock(frm, cdt, cdn);
	},
	specification(frm, cdt, cdn) {
		frm.events.update_item_free_stock(frm, cdt, cdn);
	},
	packaging_type(frm, cdt, cdn) {
		frm.events.update_item_free_stock(frm, cdt, cdn);
	},
	warehouse(frm, cdt, cdn) {
		frm.events.update_item_free_stock(frm, cdt, cdn);
	},
});
