frappe.ui.form.on('APC COA', {
	test_results_add(frm, cdt, cdn) {
		apc_operations.inventory.qc_spec.clear_spec_limits(cdt, cdn);
	},

	refresh(frm) {
		// -- View shortcuts --
		if (frm.doc.batch) {
			frm.add_custom_button(__('View Batch'), () => {
				frappe.set_route('Form', 'APC Batch', frm.doc.batch);
			}, __('View'));
		}

		if (frm.doc.loading_delivery_note) {
			frm.add_custom_button(__('View Loading DN'), () => {
				frappe.set_route('Form', 'Loading Delivery Note', frm.doc.loading_delivery_note);
			}, __('View'));
		}

		if (frm.doc.quality_inspection) {
			frm.add_custom_button(__('View Quality Inspection'), () => {
				frappe.set_route('Form', 'Quality Inspection', frm.doc.quality_inspection);
			}, __('View'));

			frm.add_custom_button(__('Sync Quality Inspection'), () => {
				frappe.call({
					method: 'apc_operations.inventory.doctype.apc_coa.apc_coa.sync_quality_inspection_status',
					args: { coa: frm.doc.name },
					freeze: true,
					callback() { frm.reload_doc(); },
				});
			}, __('Actions'));
		}

		// -- Load Template button (QC User, always visible when no results yet) --
		if (!frm.is_new() && frm.doc.coa_template && !['Approved', 'Rejected', 'Cancelled'].includes(frm.doc.status)) {
			frm.add_custom_button(__('Load Template'), () => {
				frm.trigger('coa_template');
			}, __('Actions'));
		}

		if (!frm.is_new() && !frm.doc.coa_template && !['Approved', 'Rejected', 'Cancelled'].includes(frm.doc.status)) {
			frm.add_custom_button(__('Load Template'), () => {
				frappe.prompt(
					[{ fieldname: 'template', fieldtype: 'Link', options: 'COA Template', label: __('COA Template'), reqd: 1 }],
					(values) => {
						frm.set_value('coa_template', values.template);
						frm.save().then(() => frm.trigger('coa_template'));
					},
					__('Select COA Template')
				);
			}, __('Actions'));
		}

		// -- Approve / Reject: Quality Manager and System Manager only --
		const isQCManager = frappe.user.has_role('Quality Manager') || frappe.user.has_role('System Manager');

		if (isQCManager && !frm.is_new() && frm.doc.status === 'Passed' && frm.doc.approval_status !== 'Approved') {
			frm.add_custom_button(__('Approve COA'), () => {
				frm.trigger('approve_coa');
			}, __('QC Actions'));
		}

		if (isQCManager && !frm.is_new() && !['Rejected', 'Cancelled'].includes(frm.doc.status) && frm.doc.approval_status !== 'Rejected') {
			frm.add_custom_button(__('Reject COA'), () => {
				frm.trigger('reject_coa');
			}, __('QC Actions'));
		}

		// -- Visual status indicator --
		_set_status_color(frm);
	},

	batch(frm) {
		if (!frm.doc.batch) {
			return;
		}

		frappe.db.get_value(
			'APC Batch',
			frm.doc.batch,
			['batch_number', 'product', 'manufacturing_date', 'production_order'],
			(batch) => {
				if (!batch) {
					return;
				}
				frm.set_value('batch_number', batch.batch_number || frm.doc.batch);
				frm.set_value('product', batch.product);
				frm.set_value('manufacturing_date', batch.manufacturing_date);
				frm.set_value('production_order', batch.production_order);
				if (batch.product) {
					frm.trigger('product');
				}
			}
		);
	},

	product(frm) {
		if (!frm.doc.product || frm.doc.product_name) {
			return;
		}

		frappe.db.get_value('Item', frm.doc.product, ['item_name', 'item_group'], (item) => {
			if (!item) {
				return;
			}
			frm.set_value('product_name', item.item_name || frm.doc.product);
			if (!frm.doc.product_group) {
				frm.set_value('product_group', normalize_product_group(item.item_group));
			}
		});
	},

	product_name(frm) {
		apc_try_autoload_coa_template(frm);
	},

	product_group(frm) {
		apc_try_autoload_coa_template(frm);
	},

	coa_template(frm) {
		if (!frm.doc.coa_template) {
			return;
		}

		const load_template = () => {
			frappe.call({
				method: 'apc_operations.inventory.doctype.apc_coa.apc_coa.get_template_parameters',
				args: { coa_template: frm.doc.coa_template },
				freeze: true,
				callback(r) {
					frm.clear_table('test_results');
					(r.message || []).forEach((result) => {
						const row = frm.add_child('test_results');
						Object.assign(row, result);
						row.min_value = apc_operations.inventory.qc_spec.optional_spec_value(result.min_value);
						row.max_value = apc_operations.inventory.qc_spec.optional_spec_value(result.max_value);
					});
					frm.set_value('status', 'Pending Testing');
					frm.refresh_field('test_results');
				},
			});
		};

		if ((frm.doc.test_results || []).length) {
			frappe.confirm(
				__('Replace existing test results with parameters from this template?'),
				load_template
			);
		} else {
			load_template();
		}
	},

	quality_inspection(frm) {
		if (!frm.doc.quality_inspection) {
			return;
		}

		frappe.db.get_value('Quality Inspection', frm.doc.quality_inspection, ['item_code', 'batch_no', 'status'], (inspection) => {
			if (!inspection) {
				return;
			}
			if (inspection.item_code && frm.doc.product && inspection.item_code !== frm.doc.product) {
				frappe.msgprint(__('The selected Quality Inspection belongs to item {0}.', [inspection.item_code]));
				return;
			}
			if (inspection.status === 'Accepted') {
				frm.set_value('status', 'Passed');
			} else if (inspection.status === 'Rejected') {
				frm.set_value('status', 'Failed');
			}
		});
	},

	approve_coa(frm) {
		frappe.prompt(
			[{ fieldname: 'remarks', fieldtype: 'Small Text', label: __('QC Remarks') }],
			(values) => {
				frappe.call({
					doc: frm.doc,
					method: 'approve_coa',
					args: { remarks: values.remarks },
					freeze: true,
					callback() {
						frm.reload_doc();
					},
				});
			},
			__('Approve COA'),
			__('Approve')
		);
	},

	reject_coa(frm) {
		frappe.prompt(
			[{ fieldname: 'reason', fieldtype: 'Small Text', label: __('Rejection Reason'), reqd: 1 }],
			(values) => {
				frappe.call({
					doc: frm.doc,
					method: 'reject_coa',
					args: { reason: values.reason },
					freeze: true,
					callback() {
						frm.reload_doc();
					},
				});
			},
			__('Reject COA'),
			__('Reject')
		);
	},
});

frappe.ui.form.on('COA Test Result', {
	parameter(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.parameter) {
			apc_operations.inventory.qc_spec.clear_spec_limits(cdt, cdn);
			return;
		}

		frappe.db.get_value(
			'COA Test Parameter',
			row.parameter,
			[
				'parameter_name',
				'uom',
				'value_type',
				'default_min_value',
				'default_max_value',
				'default_specification',
				'mandatory_by_default',
			],
			(parameter) => {
				if (!parameter) {
					return;
				}
				frappe.model.set_value(cdt, cdn, 'parameter_name', parameter.parameter_name);
				frappe.model.set_value(cdt, cdn, 'uom', parameter.uom);
				frappe.model.set_value(cdt, cdn, 'value_type', parameter.value_type);
				frappe.model.set_value(
					cdt,
					cdn,
					'min_value',
					apc_operations.inventory.qc_spec.optional_spec_value(parameter.default_min_value)
				);
				frappe.model.set_value(
					cdt,
					cdn,
					'max_value',
					apc_operations.inventory.qc_spec.optional_spec_value(parameter.default_max_value)
				);
				frappe.model.set_value(cdt, cdn, 'specification', parameter.default_specification);
				frappe.model.set_value(cdt, cdn, 'mandatory', parameter.mandatory_by_default);
			}
		);
	},

	numeric_result(frm, cdt, cdn) {
		evaluate_result_row(frm, cdt, cdn);
	},

	result_value(frm, cdt, cdn) {
		evaluate_result_row(frm, cdt, cdn);
	},

	text_result(frm, cdt, cdn) {
		evaluate_result_row(frm, cdt, cdn);
	},

	status(frm) {
		set_parent_status_from_results(frm);
	},
});

function evaluate_result_row(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (row.value_type === 'Numeric') {
		const raw = row.numeric_result ?? row.result_value;
		if (raw === undefined || raw === null || raw === '') {
			frappe.model.set_value(cdt, cdn, 'status', 'Not Checked');
			return;
		}

		const value = flt(raw);
		let status = 'Pass';
		const minLimit = apc_operations.inventory.qc_spec.optional_spec_value(row.min_value);
		const maxLimit = apc_operations.inventory.qc_spec.optional_spec_value(row.max_value);
		if (minLimit !== null && value < flt(minLimit)) {
			status = 'Fail';
		}
		if (maxLimit !== null && value > flt(maxLimit)) {
			status = 'Fail';
		}
		frappe.model.set_value(cdt, cdn, 'result_value', row.result_value || String(value));
		frappe.model.set_value(cdt, cdn, 'status', status);
	} else {
		const result = (row.text_result || row.result_value || '').trim();
		const standard = (row.specification || '').trim();
		if (!result) {
			frappe.model.set_value(cdt, cdn, 'status', 'Not Checked');
		} else if (standard) {
			frappe.model.set_value(
				cdt,
				cdn,
				'status',
				result.toLowerCase() === standard.toLowerCase() ? 'Pass' : 'Fail'
			);
		}
	}

	set_parent_status_from_results(frm);
}

function set_parent_status_from_results(frm) {
	if (['Approved', 'Rejected', 'Cancelled'].includes(frm.doc.status)) {
		return;
	}

	const results = frm.doc.test_results || [];
	const mandatory = results.filter((row) => row.mandatory);
	const rowsToCheck = mandatory.length ? mandatory : results;

	if (mandatory.some((row) => row.status === 'Fail')) {
		frm.set_value('status', 'Failed');
	} else if (rowsToCheck.length && rowsToCheck.every((row) => row.status === 'Pass')) {
		frm.set_value('status', 'Passed');
	} else if (results.some((row) => ['Pass', 'Fail'].includes(row.status))) {
		frm.set_value('status', 'Pending Testing');
	}
}

function normalize_product_group(itemGroup) {
	if (!itemGroup) {
		return '';
	}

	const normalized = itemGroup.toLowerCase();
	const allowed = ['Solvent', 'Oil', 'Lubricant', 'Plasticizer', 'White Oil', 'Petroleum Jelly', 'Other'];
	return allowed.find((group) => normalized.includes(group.toLowerCase())) || '';
}

// Auto-detect a standard COA Template for this product (by Product Name +
// Product Group, matching a template someone has already set up) and load
// its parameters - same effect as manually picking one via the "Load
// Template" button, just without having to remember to do it every time.
// Never overrides a template the user already picked, and never clobbers
// test results that are already on the form.
function apc_try_autoload_coa_template(frm) {
	if (frm.doc.coa_template || !frm.doc.product_name || (frm.doc.test_results || []).length) {
		return;
	}

	frappe.call({
		method: 'apc_operations.inventory.doctype.apc_coa.apc_coa.find_matching_coa_template',
		args: {
			product_name: frm.doc.product_name,
			product_group: frm.doc.product_group,
		},
		callback(r) {
			if (r.message && !frm.doc.coa_template) {
				frm.set_value('coa_template', r.message);
			}
		},
	});
}

function _set_status_color(frm) {
	const colorMap = {
		'Draft': 'gray',
		'Pending Testing': 'yellow',
		'Passed': 'blue',
		'Failed': 'red',
		'Approved': 'green',
		'Rejected': 'red',
		'Cancelled': 'gray',
	};
	const color = colorMap[frm.doc.status] || 'gray';
	frm.get_field('status').$wrapper.find('.control-value').css('color', color === 'green' ? '#2E8B57' : color === 'red' ? '#c0392b' : color === 'blue' ? '#2980b9' : '');
}
