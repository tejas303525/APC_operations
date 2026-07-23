// Shared helpers for optional min/max limits on QC test rows.
frappe.provide("apc_operations.inventory.qc_spec");

apc_operations.inventory.qc_spec.optional_spec_value = function (value) {
	if (value === undefined || value === null || value === "") {
		return null;
	}
	return value;
};

apc_operations.inventory.qc_spec.clear_spec_limits = function (cdt, cdn) {
	frappe.model.set_value(cdt, cdn, "min_value", null);
	frappe.model.set_value(cdt, cdn, "max_value", null);
};
