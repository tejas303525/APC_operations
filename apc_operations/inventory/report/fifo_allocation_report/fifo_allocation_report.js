frappe.query_reports['FIFO Allocation Report'] = {
	filters: [
		{
			fieldname: 'sales_demand',
			label: __('Sales Demand'),
			fieldtype: 'Link',
			options: 'APC Sales Demand',
		},
		{
			fieldname: 'product',
			label: __('Product'),
			fieldtype: 'Link',
			options: 'Item',
		},
		{
			fieldname: 'warehouse',
			label: __('Warehouse'),
			fieldtype: 'Link',
			options: 'Warehouse',
		},
		{
			fieldname: 'show_shortages_only',
			label: __('Show Shortages Only'),
			fieldtype: 'Check',
			default: 0,
		},
	],
};
