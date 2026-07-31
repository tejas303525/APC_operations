// Copyright (c) 2026, APC and contributors
// For license information, please see license.txt

frappe.ui.form.on('COA Template', {
	parameters_add(frm, cdt, cdn) {
		apc_operations.inventory.qc_spec.clear_spec_limits(cdt, cdn);
	},
});

frappe.ui.form.on('COA Template Parameter', {
	parameter(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.parameter) {
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
});
