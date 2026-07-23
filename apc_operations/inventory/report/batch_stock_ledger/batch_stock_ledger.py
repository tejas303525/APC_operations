import frappe


def execute(filters=None):
	filters = filters or {}
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": "Batch", "fieldname": "batch", "fieldtype": "Link", "options": "APC Batch", "width": 150},
		{"label": "ERPNext Batch", "fieldname": "erpnext_batch", "fieldtype": "Link", "options": "Batch", "width": 150},
		{"label": "Product", "fieldname": "product", "fieldtype": "Link", "options": "Item", "width": 160},
		{"label": "Grade", "fieldname": "grade", "fieldtype": "Data", "width": 100},
		{"label": "Specification", "fieldname": "specification", "fieldtype": "Data", "width": 140},
		{"label": "Packaging", "fieldname": "packaging_type", "fieldtype": "Data", "width": 110},
		{"label": "Warehouse", "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 160},
		{"label": "Batch Qty", "fieldname": "batch_quantity", "fieldtype": "Float", "width": 110},
		{"label": "Allocated Qty", "fieldname": "allocated_quantity", "fieldtype": "Float", "width": 120},
		{"label": "Available Qty", "fieldname": "available_quantity", "fieldtype": "Float", "width": 120},
		{"label": "Batch Status", "fieldname": "batch_status", "fieldtype": "Data", "width": 110},
		{"label": "Quality Status", "fieldname": "quality_status", "fieldtype": "Data", "width": 110},
		{"label": "COA", "fieldname": "linked_coa", "fieldtype": "Link", "options": "APC COA", "width": 140},
		{"label": "MFG Date", "fieldname": "manufacturing_date", "fieldtype": "Date", "width": 100},
		{"label": "Expiry Date", "fieldname": "expiry_date", "fieldtype": "Date", "width": 100},
	]


def get_data(filters):
	conditions = []
	params = {}

	for field in ("batch", "product", "warehouse", "batch_status", "quality_status"):
		if filters.get(field):
			db_field = "name" if field == "batch" else field
			conditions.append(f"{db_field} = %({field})s")
			params[field] = filters.get(field)

	where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

	return frappe.db.sql(f"""
		SELECT
			name AS batch,
			erpnext_batch,
			product,
			grade,
			specification,
			packaging_type,
			warehouse,
			batch_quantity,
			allocated_quantity,
			available_quantity,
			batch_status,
			quality_status,
			linked_coa,
			manufacturing_date,
			expiry_date
		FROM `tabAPC Batch`
		{where_clause}
		ORDER BY product ASC, grade ASC, specification ASC, manufacturing_date ASC, creation ASC
	""", params, as_dict=True)
