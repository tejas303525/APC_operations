import frappe


def execute(filters=None):
	filters = filters or {}
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": "Product", "fieldname": "product", "fieldtype": "Link", "options": "Item", "width": 170},
		{"label": "Grade", "fieldname": "grade", "fieldtype": "Data", "width": 100},
		{"label": "Specification", "fieldname": "specification", "fieldtype": "Data", "width": 140},
		{"label": "Packaging", "fieldname": "packaging_type", "fieldtype": "Data", "width": 110},
		{"label": "Warehouse", "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 160},
		{"label": "Batch Count", "fieldname": "batch_count", "fieldtype": "Int", "width": 100},
		{"label": "Batch Qty", "fieldname": "batch_quantity", "fieldtype": "Float", "width": 120},
		{"label": "Allocated Qty", "fieldname": "allocated_quantity", "fieldtype": "Float", "width": 120},
		{"label": "Available Qty", "fieldname": "available_quantity", "fieldtype": "Float", "width": 120},
		{"label": "Oldest MFG Date", "fieldname": "oldest_manufacturing_date", "fieldtype": "Date", "width": 120},
		{"label": "Next Expiry Date", "fieldname": "next_expiry_date", "fieldtype": "Date", "width": 120},
	]


def get_data(filters):
	conditions = ["batch_status IN ('Active', 'On Hold')"]
	params = {}

	if filters.get("approved_only"):
		conditions.append("quality_status = 'Approved'")
	if filters.get("product"):
		conditions.append("product = %(product)s")
		params["product"] = filters.get("product")
	if filters.get("grade"):
		conditions.append("grade = %(grade)s")
		params["grade"] = filters.get("grade")
	if filters.get("warehouse"):
		conditions.append("warehouse = %(warehouse)s")
		params["warehouse"] = filters.get("warehouse")

	return frappe.db.sql(f"""
		SELECT
			product,
			grade,
			specification,
			packaging_type,
			warehouse,
			COUNT(name) AS batch_count,
			SUM(batch_quantity) AS batch_quantity,
			SUM(allocated_quantity) AS allocated_quantity,
			SUM(available_quantity) AS available_quantity,
			MIN(manufacturing_date) AS oldest_manufacturing_date,
			MIN(NULLIF(expiry_date, '')) AS next_expiry_date
		FROM `tabAPC Batch`
		WHERE {" AND ".join(conditions)}
		GROUP BY product, grade, specification, packaging_type, warehouse
		ORDER BY product ASC, grade ASC, warehouse ASC
	""", params, as_dict=True)
