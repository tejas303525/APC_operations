frappe.ui.form.on('APC Batch Allocation', {
	refresh(frm) {
		frm.trigger('render_allocation_summary');

		if (frm.doc.sales_demand) {
			frm.add_custom_button(__('View Sales Demand'), () => {
				frappe.set_route('Form', 'APC Sales Demand', frm.doc.sales_demand);
			}, __('View'));
		}

		if (!frm.is_new()) {
			frm.add_custom_button(__('Batch Allocation Dashboard'), () => {
				frappe.set_route('batch-allocation-dashboard');
			}, __('View'));
		}

		if (!frm.is_new() && !['Released', 'Fully Dispatched', 'Partially Dispatched'].includes(frm.doc.allocation_status)) {
			frm.add_custom_button(__('Release Allocation'), () => {
				frappe.confirm(
					__('Release this allocation and return reserved quantities to the source batches?'),
					() => {
						frappe.call({
							doc: frm.doc,
							method: 'release_allocation',
							freeze: true,
							callback() {
								frm.reload_doc();
							},
						});
					}
				);
			}, __('Actions'));
		}

		if (!frm.is_new() && frm.doc.allocation_status !== 'Released') {
			frm.add_custom_button(__('Create Dispatch Order'), () => {
				frappe.call({
					method: 'apc_operations.dispatch.doctype.apc_dispatch_order.apc_dispatch_order.create_dispatch_from_allocation',
					args: { allocation: frm.doc.name },
					freeze: true,
					callback(r) {
						if (r.message) {
							frappe.set_route('Form', 'APC Dispatch Order', r.message);
						}
					},
				});
			}, __('Actions'));
		}
	},

	render_allocation_summary(frm) {
		const required = flt(frm.doc.total_required_quantity);
		const allocated = flt(frm.doc.total_allocated_quantity);
		const dispatched = flt(frm.doc.total_dispatched_quantity);
		const pct = required ? Math.min((allocated / required) * 100, 100) : 0;

		frm.dashboard.clear_headline();
		frm.dashboard.set_headline_alert(`
			<div>
				<strong>${__('Required')}:</strong> ${frappe.format(required, { fieldtype: 'Float' })}
				&nbsp; | &nbsp;
				<strong>${__('Allocated')}:</strong> ${frappe.format(allocated, { fieldtype: 'Float' })} (${pct.toFixed(1)}%)
				&nbsp; | &nbsp;
				<strong>${__('Dispatched')}:</strong> ${frappe.format(dispatched, { fieldtype: 'Float' })}
			</div>
		`, frm.doc.allocation_status === 'Released' ? 'red' : 'green');
	},

	allocation_details_add(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, 'fifo_sequence', (frm.doc.allocation_details || []).length);
	},
});

frappe.ui.form.on('APC Batch Allocation Detail', {
	batch(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.batch) {
			return;
		}

		frappe.db.get_value(
			'APC Batch',
			row.batch,
			['batch_number', 'linked_coa', 'manufacturing_date', 'warehouse', 'available_quantity', 'batch_status', 'quality_status'],
			(batch) => {
				if (!batch) {
					return;
				}
				frappe.model.set_value(cdt, cdn, 'batch_number', batch.batch_number);
				frappe.model.set_value(cdt, cdn, 'coa', batch.linked_coa);
				frappe.model.set_value(cdt, cdn, 'manufacturing_date', batch.manufacturing_date);
				frappe.model.set_value(cdt, cdn, 'warehouse', batch.warehouse);

				if (!['Active', 'On Hold'].includes(batch.batch_status) || batch.quality_status !== 'Approved') {
					frappe.msgprint(__('Selected batch is not available for allocation. Status: {0}, Quality: {1}', [
						batch.batch_status,
						batch.quality_status,
					]));
				}
			}
		);
	},

	allocated_quantity(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, 'remaining_quantity', flt(row.allocated_quantity) - flt(row.dispatched_quantity));
	},

	dispatched_quantity(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, 'remaining_quantity', flt(row.allocated_quantity) - flt(row.dispatched_quantity));
	},
});
