frappe.query_reports['Stock Availability Report'] = {
	filters: [
		{
			fieldname: 'product',
			label: __('Product'),
			fieldtype: 'Link',
			options: 'Item',
		},
		{
			fieldname: 'grade',
			label: __('Grade'),
			fieldtype: 'Data',
		},
		{
			fieldname: 'warehouse',
			label: __('Warehouse'),
			fieldtype: 'Link',
			options: 'Warehouse',
		},
		{
			fieldname: 'approved_only',
			label: __('Approved Stock Only'),
			fieldtype: 'Check',
			default: 1,
		},
	],
};
