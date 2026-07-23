frappe.query_reports['Batch Stock Ledger'] = {
	filters: [
		{
			fieldname: 'batch',
			label: __('Batch'),
			fieldtype: 'Link',
			options: 'APC Batch',
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
			fieldname: 'batch_status',
			label: __('Batch Status'),
			fieldtype: 'Select',
			options: '\nActive\nOn Hold\nBlocked\nExpired\nCancelled\nDepleted',
		},
		{
			fieldname: 'quality_status',
			label: __('Quality Status'),
			fieldtype: 'Select',
			options: '\nPending QC\nUnder Review\nApproved\nRejected',
		},
	],
};
