// Copyright (c) 2026, APC and contributors
// For license information, please see license.txt

frappe.ui.form.on('Loading Delivery Note', {
	refresh(frm) {
		_set_status_indicator(frm);

		if (!frm.is_new()) {
			frm.add_custom_button(__('Print Loading Delivery Note'), () => {
				const url = `/printview?doctype=${encodeURIComponent(frm.doc.doctype)}&name=${encodeURIComponent(frm.doc.name)}&format=${encodeURIComponent('Standard Loading Delivery Note')}&no_letterhead=0&_lang=en`;
				window.open(url, '_blank');
			}, __('Print'));
		}

		// --- View shortcuts ---
		if (frm.doc.security_inspection) {
			frm.add_custom_button(__('View Security Inspection'), () => {
				frappe.set_route('Form', 'Security Inspection', frm.doc.security_inspection);
			}, __('View'));
		}

		if (frm.doc.security_draft_delivery_note) {
			frm.add_custom_button(__('View Security Draft DN'), () => {
				frappe.set_route('Form', 'Security Draft Delivery Note', frm.doc.security_draft_delivery_note);
			}, __('View'));
		}

		if (frm.doc.job_order) {
			frm.add_custom_button(__('View Job Order'), () => {
				frappe.set_route('Form', 'Job Order', frm.doc.job_order);
			}, __('View'));
		}

		if (frm.doc.qc_report_request) {
			frm.add_custom_button(__('View QC Request'), () => {
				frappe.set_route('Form', 'QC Report Request', frm.doc.qc_report_request);
			}, __('View'));
		}

		// QC status banner
		if (frm.doc.qc_status === 'QC Rejected') {
			frm.dashboard.add_comment(
				__('QC Rejected — receivables reporting is blocked until QC is re-evaluated.'),
				'red',
				true
			);
		} else if (frm.doc.qc_status === 'Pending QC') {
			frm.dashboard.add_comment(__('Pending QC clearance from QC team.'), 'orange', true);
		}

		const isRejectedOrCancelled = ['QC Rejected', 'Cancelled'].includes(frm.doc.delivery_note_status);
		const isCompleted = ['Reported to Receivables', 'Completed', 'Dispatch Confirmed'].includes(frm.doc.delivery_note_status);

		// --- Batch Allocation buttons (always allowed while not QC-rejected/cancelled/completed) ---
		const canAllocate = !frm.doc.dispatch_confirmed && !isRejectedOrCancelled && !isCompleted;

		if (canAllocate) {
			if (frm.doc.job_order) {
				frm.add_custom_button(__('Sync from Job Order Allocation'), () => {
					frappe.call({
						doc: frm.doc,
						method: 'sync_batches_from_job_order',
						args: { force: 1 },
						freeze: true,
						freeze_message: __('Copying batch allocations from Job Order...'),
						callback(r) {
							const res = r.message || {};
							frm.reload_doc();
							frappe.show_alert({
								message: res.message || __('Batch allocations synced.'),
								indicator: res.rows && res.rows.length ? 'green' : 'orange',
							});
						},
					});
				}, __('Batch Allocation'));
			}

			frm.add_custom_button(__('Preview FIFO Allocation'), () => {
				frm.trigger('preview_fifo');
			}, __('Batch Allocation'));

			frm.add_custom_button(__('Allocate Batches (FIFO)'), () => {
				frm.trigger('run_fifo_allocation');
			}, __('Batch Allocation'));
		}

		// --- COA verify (available once QC cleared) ---
		const qcCleared = frm.doc.qc_status === 'QC Cleared';
		if (qcCleared && !frm.doc.dispatch_confirmed && frm.doc.batch_allocations && frm.doc.batch_allocations.length &&
			!frm.doc.coa_verified) {
			frm.add_custom_button(__('Verify COAs'), () => {
				frappe.call({
					doc: frm.doc,
					method: 'verify_coas',
					freeze: true,
					callback() { frm.reload_doc(); },
				});
			}, __('QC & COA'));
		}

		// --- Confirm Dispatch (only after QC cleared + COAs verified) ---
		if (qcCleared && !frm.doc.dispatch_confirmed && frm.doc.coa_verified &&
			frm.doc.batch_allocations && frm.doc.batch_allocations.length) {
			frm.add_custom_button(__('Confirm Dispatch'), () => {
				frm.trigger('confirm_dispatch');
			}, __('Dispatch'));
		}

		// --- Report to Receivables: ONLY after QC clearance ---
		const canReportReceivables = qcCleared &&
			!['Reported to Receivables', 'Completed', 'Cancelled'].includes(frm.doc.receivables_status);

		if (canReportReceivables) {
			const btn = frm.add_custom_button(__('Report to Receivables'), () => {
				frappe.confirm(
					__('Report this Loading DN to Receivables? QC has been cleared and COAs are attached.'),
					() => {
						frappe.call({
							doc: frm.doc,
							method: 'report_to_receivables',
							freeze: true,
							freeze_message: __('Reporting to Receivables...'),
							callback() { frm.reload_doc(); },
						});
					}
				);
			}, __('Dispatch'));
			// Highlight as primary action
			btn && btn.addClass('btn-primary');
		}
	},

	// ── FIFO Preview ────────────────────────────────────────────────────────
	preview_fifo(frm) {
		if (!frm.doc.quantity) {
			frappe.msgprint(__('Set Quantity on the Loading DN before previewing allocation.'));
			return;
		}

		frappe.prompt(
			[
				{ fieldname: 'product', fieldtype: 'Link', options: 'Item', label: __('Product'), reqd: 1 },
				{ fieldname: 'required_qty', fieldtype: 'Float', label: __('Required Quantity'), reqd: 1, default: frm.doc.quantity },
				{ fieldname: 'grade', fieldtype: 'Data', label: __('Grade') },
				{ fieldname: 'warehouse', fieldtype: 'Link', options: 'Warehouse', label: __('Warehouse') },
			],
			(values) => {
				frappe.call({
					method: 'apc_operations.services.batch_allocation.preview_fifo_allocation_for_loading_dn',
					args: {
						product: values.product,
						required_qty: values.required_qty,
						grade: values.grade || null,
						warehouse: values.warehouse || null,
					},
					freeze: true,
					callback(r) {
						const data = r.message || {};
						_show_fifo_preview_dialog(frm, data, values);
					},
				});
			},
			__('FIFO Allocation Preview'),
			__('Preview')
		);
	},

	// ── Run FIFO Allocation ──────────────────────────────────────────────────
	run_fifo_allocation(frm) {
		frappe.prompt(
			[
				{ fieldname: 'product', fieldtype: 'Link', options: 'Item', label: __('Product'), reqd: 1 },
				{ fieldname: 'required_qty', fieldtype: 'Float', label: __('Required Quantity'), reqd: 1, default: frm.doc.quantity },
				{ fieldname: 'grade', fieldtype: 'Data', label: __('Grade') },
				{ fieldname: 'specification', fieldtype: 'Data', label: __('Specification') },
				{ fieldname: 'packaging_type', fieldtype: 'Data', label: __('Packaging Type') },
				{ fieldname: 'warehouse', fieldtype: 'Link', options: 'Warehouse', label: __('Warehouse') },
			],
			(values) => {
				frappe.call({
					method: 'apc_operations.services.batch_allocation.create_loading_dn_batch_allocations',
					args: {
						loading_dn_name: frm.doc.name,
						product: values.product,
						required_qty: values.required_qty,
						grade: values.grade || null,
						specification: values.specification || null,
						packaging_type: values.packaging_type || null,
						warehouse: values.warehouse || null,
					},
					freeze: true,
					freeze_message: __('Allocating batches using FIFO...'),
					callback(r) {
						const res = r.message || {};
						frm.reload_doc();
						if (res.shortage > 0) {
							frappe.msgprint({
								title: __('Partial Allocation'),
								message: __('Allocated {0} units. Shortage of {1} units. Remaining batches may need production.', [res.total_allocated, res.shortage]),
								indicator: 'orange',
							});
						} else {
							frappe.msgprint({
								title: __('Allocation Complete'),
								message: __('Successfully allocated {0} batch row(s).', [res.rows ? res.rows.length : 0]),
								indicator: 'green',
							});
						}
					},
				});
			},
			__('FIFO Batch Allocation'),
			__('Allocate')
		);
	},

	// ── Confirm Dispatch ─────────────────────────────────────────────────────
	confirm_dispatch(frm) {
		frappe.confirm(
			__('Confirm dispatch? This will deduct stock from all allocated batches. This action cannot be undone.'),
			() => {
				frappe.call({
					doc: frm.doc,
					method: 'confirm_dispatch',
					freeze: true,
					freeze_message: __('Confirming dispatch and deducting stock...'),
					callback() { frm.reload_doc(); },
				});
			}
		);
	},
});

frappe.ui.form.on('Loading Delivery Note', {
	tare_weight(frm) {
		_recalc_net_weight(frm);
	},
	gross_weight(frm) {
		_recalc_net_weight(frm);
	},
});

// ── Child table: FIFO override validation ───────────────────────────────────
frappe.ui.form.on('Loading DN Batch', {
	is_fifo_override(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.is_fifo_override) {
			// Check user has permission
			const isQCManager = frappe.user.has_role('Quality Manager') || frappe.user.has_role('System Manager');
			if (!isQCManager) {
				frappe.model.set_value(cdt, cdn, 'is_fifo_override', 0);
				frappe.msgprint(__('Only a Quality Manager or System Manager can override FIFO order.'));
				return;
			}
			// Prompt for reason
			frappe.prompt(
				[{ fieldname: 'reason', fieldtype: 'Small Text', label: __('Override Reason'), reqd: 1 }],
				(values) => {
					frappe.model.set_value(cdt, cdn, 'override_reason', values.reason);
				},
				__('FIFO Override Reason'),
				__('Confirm Override')
			);
		} else {
			frappe.model.set_value(cdt, cdn, 'override_reason', '');
		}
	},
});

// ── Helpers ──────────────────────────────────────────────────────────────────
function _recalc_net_weight(frm) {
	const gross = flt(frm.doc.gross_weight);
	const tare = flt(frm.doc.tare_weight);
	if (gross > 0 && tare > 0 && gross >= tare) {
		frm.set_value('net_weight', gross - tare);
	}
}

function _set_status_indicator(frm) {
	const statusColors = {
		'Draft': 'gray',
		'Pending QC': 'yellow',
		'Batch Allocation Pending': 'orange',
		'Batch Allocated': 'blue',
		'QC Cleared': 'green',
		'QC Rejected': 'red',
		'COA Attached': 'blue',
		'COA Verified': 'blue',
		'Ready for Receivables': 'green',
		'Loading Completed': 'green',
		'Dispatch Confirmed': 'green',
		'Reported to Receivables': 'purple',
		'Completed': 'green',
		'Cancelled': 'red',
	};
	const color = statusColors[frm.doc.delivery_note_status] || 'gray';
	frm.set_indicator_formatter && frm.set_indicator_formatter('delivery_note_status', () => color);
}

function _show_fifo_preview_dialog(frm, data, queryValues) {
	const rows = data.rows || [];
	const shortage = data.shortage || 0;

	let html = `<table class="table table-bordered table-condensed">
		<thead><tr>
			<th>#</th><th>${__('Batch')}</th><th>${__('Mfg Date')}</th>
			<th>${__('Allocated Qty')}</th><th>${__('COA')}</th>
		</tr></thead><tbody>`;

	rows.forEach(r => {
		html += `<tr>
			<td>${r.fifo_sequence}</td>
			<td>${r.batch_number || r.batch}</td>
			<td>${r.manufacturing_date || ''}</td>
			<td>${r.allocated_qty}</td>
			<td>${r.coa || ''}</td>
		</tr>`;
	});

	html += '</tbody></table>';

	if (shortage > 0) {
		html += `<div class="alert alert-warning">${__('Shortage: {0} units cannot be allocated from current stock.', [shortage])}</div>`;
	} else {
		html += `<div class="alert alert-success">${__('Full quantity can be allocated from {0} batch(es).', [rows.length])}</div>`;
	}

	const d = new frappe.ui.Dialog({
		title: __('FIFO Allocation Preview'),
		fields: [{ fieldtype: 'HTML', options: html }],
		primary_action_label: __('Apply Allocation'),
		primary_action() {
			d.hide();
			// Trigger actual allocation with same params
			frappe.call({
				method: 'apc_operations.services.batch_allocation.create_loading_dn_batch_allocations',
				args: {
					loading_dn_name: frm.doc.name,
					product: queryValues.product,
					required_qty: queryValues.required_qty,
					grade: queryValues.grade || null,
					warehouse: queryValues.warehouse || null,
				},
				freeze: true,
				callback() { frm.reload_doc(); },
			});
		},
	});
	d.show();
}
