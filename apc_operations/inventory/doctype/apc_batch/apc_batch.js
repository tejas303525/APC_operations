frappe.ui.form.on('APC Batch', {
	refresh(frm) {
		frm.trigger('render_stock_summary');
		frm.trigger('render_stock_status_indicator');

		frm.add_custom_button(__('Batch Allocation Dashboard'), () => {
			frappe.set_route('batch-allocation-dashboard');
		}, __('View'));

		if (!frm.is_new()) {
			frm.add_custom_button(__('View Allocations'), () => {
				frappe.set_route('List', 'APC Batch Allocation', {
					name: ['in', frm._allocation_parents || []],
				});
				if (!frm._allocation_parents?.length) {
					frappe.msgprint(__('No active allocations were found for this batch.'));
				}
			}, __('View'));

			frm.add_custom_button(__('Stock Ledger'), () => {
				frappe.set_route('query-report', 'Batch Stock Ledger', { batch: frm.doc.name });
			}, __('View'));
		}

		if (frm.doc.linked_coa) {
			frm.add_custom_button(__('View COA'), () => {
				frappe.set_route('Form', 'APC COA', frm.doc.linked_coa);
			}, __('View'));
		} else if (!frm.is_new() && frm.doc.quality_status === 'Pending QC') {
			frm.add_custom_button(__('Create COA'), () => {
				frappe.call({
					method: 'apc_operations.inventory.doctype.apc_batch.apc_batch.create_coa_for_batch',
					args: { batch_name: frm.doc.name },
					freeze: true,
					callback() { frm.reload_doc(); },
				});
			}, __('QC'));
		}

		if (frm.doc.erpnext_batch) {
			frm.add_custom_button(__('View ERPNext Batch'), () => {
				frappe.set_route('Form', 'Batch', frm.doc.erpnext_batch);
			}, __('View'));
		}

		if (flt(frm.doc.allocated_quantity) > 0) {
			frm.add_custom_button(__('Release Allocation'), () => {
				frm.trigger('show_release_allocation_dialog');
			}, __('Actions'));
		}

		// Loading DNs that use this batch
		if (!frm.is_new()) {
			frm.add_custom_button(__('View Loading DNs'), () => {
				frappe.set_route('List', 'Loading Delivery Note', {
					'batch_allocations.batch': frm.doc.name,
				});
			}, __('View'));
		}
	},

	batch_status(frm) {
		if (['Blocked', 'Expired', 'Cancelled', 'Depleted'].includes(frm.doc.batch_status)
			&& flt(frm.doc.allocated_quantity) > 0) {
			frappe.msgprint({
				title: __('Allocated Batch'),
				indicator: 'orange',
				message: __('This batch has active allocated quantity. Release or dispatch allocations before blocking operational use.'),
			});
		}
	},

	linked_coa(frm) {
		if (!frm.doc.linked_coa) {
			return;
		}

		frappe.db.get_value('APC COA', frm.doc.linked_coa, ['approval_status', 'batch'], (coa) => {
			if (!coa) {
				return;
			}
			if (coa.batch && coa.batch !== frm.doc.name) {
				frappe.msgprint(__('The selected COA belongs to batch {0}.', [coa.batch]));
				return;
			}
			if (coa.approval_status === 'Approved') {
				frm.set_value('quality_status', 'QC Cleared');
				frm.set_value('stock_status', 'Available');
			}
		});
	},

	render_stock_status_indicator(frm) {
		if (frm.is_new()) return;

		const stockStatusColors = {
			'QC Hold': 'yellow',
			'Available': 'green',
			'Reserved': 'blue',
			'Dispatched': 'gray',
			'Rejected': 'red',
			'Cancelled': 'gray',
		};
		const qcColors = {
			'Pending QC': 'yellow',
			'Under Review': 'blue',
			'QC Cleared': 'green',
			'Approved': 'green',
			'On Hold': 'orange',
			'Retest Required': 'orange',
			'QC Rejected': 'red',
			'Rejected': 'red',
		};
		const coaColors = {
			'Not Generated': 'gray',
			'Pending': 'yellow',
			'Generated': 'blue',
			'Approved': 'green',
			'Rejected': 'red',
		};

		const stockColor = stockStatusColors[frm.doc.stock_status] || 'gray';
		const qcColor = qcColors[frm.doc.quality_status] || 'gray';
		const coaColor = coaColors[frm.doc.coa_status] || 'gray';

		frm.dashboard.add_indicator(__('Stock: {0}', [frm.doc.stock_status || 'Unknown']), stockColor);
		frm.dashboard.add_indicator(__('QC: {0}', [frm.doc.quality_status || 'Unknown']), qcColor);
		frm.dashboard.add_indicator(__('COA: {0}', [frm.doc.coa_status || 'Not Generated']), coaColor);
	},

	render_stock_summary(frm) {
		if (frm.is_new()) {
			return;
		}

		const batch_qty = flt(frm.doc.batch_quantity);
		const allocated_qty = flt(frm.doc.allocated_quantity);
		const available_qty = flt(frm.doc.available_quantity);
		const dispatched_qty = flt(frm.doc.dispatched_quantity || 0);
		const allocated_pct = batch_qty ? Math.min((allocated_qty / batch_qty) * 100, 100) : 0;

		frm.dashboard.clear_headline();
		frm.dashboard.set_headline_alert(`
			<div>
				<strong>${__('Available')}:</strong> ${frappe.format(available_qty, { fieldtype: 'Float' })}
				&nbsp; | &nbsp;
				<strong>${__('Allocated')}:</strong> ${frappe.format(allocated_qty, { fieldtype: 'Float' })}
				&nbsp; | &nbsp;
				<strong>${__('Dispatched')}:</strong> ${frappe.format(dispatched_qty, { fieldtype: 'Float' })}
				&nbsp; | &nbsp;
				<strong>${__('Allocated %')}:</strong> ${allocated_pct.toFixed(1)}%
			</div>
		`, available_qty > 0 ? 'green' : (dispatched_qty > 0 ? 'blue' : 'orange'));

		frm.dashboard.add_indicator(__('Status: {0}', [frm.doc.batch_status]), frm.doc.batch_status === 'Active' ? 'green' : 'orange');
		frm.dashboard.add_indicator(__('Quality: {0}', [frm.doc.quality_status]), ['Approved', 'QC Cleared'].includes(frm.doc.quality_status) ? 'green' : 'orange');

		frappe.call({
			method: 'apc_operations.inventory.doctype.apc_batch.apc_batch.get_batch_allocation_rows',
			args: { batch_name: frm.doc.name, limit: 50 },
		}).then((r) => {
			const rows = r.message || [];
			frm._allocation_parents = [...new Set(rows.map(row => row.parent))];
		});
	},

	show_release_allocation_dialog(frm) {
		frappe.call({
			method: 'apc_operations.inventory.doctype.apc_batch.apc_batch.get_batch_allocation_rows',
			args: { batch_name: frm.doc.name, limit: 20 },
		}).then((r) => {
			const rows = r.message || [];
			if (!rows?.length) {
				frappe.msgprint(__('No releasable allocations found for this batch.'));
				return;
			}

			const options = [...new Set(rows.map(row => row.parent))];
			const dialog = new frappe.ui.Dialog({
				title: __('Release Allocation'),
				fields: [
					{
						fieldname: 'allocation',
						fieldtype: 'Select',
						label: __('Allocation'),
						options,
						reqd: 1,
					},
				],
				primary_action_label: __('Release'),
				primary_action(values) {
					frappe.call({
						method: 'apc_operations.services.batch_allocation.release_allocation',
						args: { allocation_name: values.allocation },
						freeze: true,
						callback(r) {
							if (r.message?.success) {
								dialog.hide();
								frm.reload_doc();
							}
						},
					});
				},
			});
			dialog.show();
		});
	},
});
