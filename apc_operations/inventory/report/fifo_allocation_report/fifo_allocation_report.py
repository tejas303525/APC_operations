import frappe
from frappe.utils import flt

from apc_operations.services.batch_allocation import calculate_free_stock, get_available_batches


def execute(filters=None):
	filters = filters or {}
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": "Sales Demand", "fieldname": "sales_demand", "fieldtype": "Link", "options": "APC Sales Demand", "width": 150},
		{"label": "Customer", "fieldname": "customer_name", "fieldtype": "Data", "width": 160},
		{"label": "Demand Item", "fieldname": "sales_demand_item", "fieldtype": "Data", "width": 140},
		{"label": "Product", "fieldname": "item", "fieldtype": "Link", "options": "Item", "width": 160},
		{"label": "Required Date", "fieldname": "required_dispatch_date", "fieldtype": "Date", "width": 110},
		{"label": "Pending Qty", "fieldname": "pending_quantity", "fieldtype": "Float", "width": 110},
		{"label": "FIFO Sequence", "fieldname": "fifo_sequence", "fieldtype": "Int", "width": 100},
		{"label": "Recommended Batch", "fieldname": "batch", "fieldtype": "Link", "options": "APC Batch", "width": 150},
		{"label": "MFG Date", "fieldname": "manufacturing_date", "fieldtype": "Date", "width": 100},
		{"label": "Warehouse", "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 150},
		{"label": "Recommended Qty", "fieldname": "recommended_quantity", "fieldtype": "Float", "width": 130},
		{"label": "Shortage Qty", "fieldname": "shortage_quantity", "fieldtype": "Float", "width": 120},
		{"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 120},
	]


def get_data(filters):
	demand_items = get_pending_demand_items(filters)
	rows = []

	for item in demand_items:
		pending_qty = flt(item.pending_quantity)
		remaining_qty = pending_qty
		fifo_sequence = 0

		batches = get_available_batches(
			product=item.item,
			grade=item.grade,
			specification=item.specification,
			packaging_type=item.packaging_type,
			warehouse=item.warehouse,
		)

		for batch in batches:
			if remaining_qty <= 0:
				break

			free_stock = flt(calculate_free_stock(batch.name))
			if free_stock <= 0:
				continue

			recommended_qty = min(remaining_qty, free_stock)
			fifo_sequence += 1
			rows.append(build_row(item, {
				"fifo_sequence": fifo_sequence,
				"batch": batch.name,
				"manufacturing_date": batch.manufacturing_date,
				"warehouse": batch.warehouse,
				"recommended_quantity": recommended_qty,
				"shortage_quantity": 0,
				"status": "Recommended",
			}))
			remaining_qty -= recommended_qty

		if remaining_qty > 0:
			rows.append(build_row(item, {
				"fifo_sequence": None,
				"batch": None,
				"manufacturing_date": None,
				"warehouse": item.warehouse,
				"recommended_quantity": 0,
				"shortage_quantity": remaining_qty,
				"status": "Shortage",
			}))

	if filters.get("show_shortages_only"):
		rows = [row for row in rows if row.get("shortage_quantity")]

	return rows


def get_pending_demand_items(filters):
	conditions = [
		"parent.status NOT IN ('Completed', 'Cancelled', 'Fully Dispatched')",
		"(item.demand_quantity - item.allocated_quantity) > 0",
	]
	params = {}

	if filters.get("sales_demand"):
		conditions.append("parent.name = %(sales_demand)s")
		params["sales_demand"] = filters.get("sales_demand")
	if filters.get("product"):
		conditions.append("item.item = %(product)s")
		params["product"] = filters.get("product")
	if filters.get("warehouse"):
		conditions.append("item.warehouse = %(warehouse)s")
		params["warehouse"] = filters.get("warehouse")

	return frappe.db.sql(f"""
		SELECT
			parent.name AS sales_demand,
			parent.customer_name,
			parent.customer,
			parent.required_dispatch_date,
			item.name AS sales_demand_item,
			item.item,
			item.item_name,
			item.grade,
			item.specification,
			item.packaging_type,
			item.warehouse,
			item.demand_quantity,
			item.allocated_quantity,
			(item.demand_quantity - item.allocated_quantity) AS pending_quantity
		FROM `tabAPC Sales Demand Item` item
		INNER JOIN `tabAPC Sales Demand` parent ON parent.name = item.parent
		WHERE {" AND ".join(conditions)}
		ORDER BY parent.required_dispatch_date ASC, parent.creation ASC, item.idx ASC
	""", params, as_dict=True)


def build_row(item, allocation):
	row = {
		"sales_demand": item.sales_demand,
		"customer_name": item.customer_name or item.customer,
		"sales_demand_item": item.sales_demand_item,
		"item": item.item,
		"required_dispatch_date": item.required_dispatch_date,
		"pending_quantity": item.pending_quantity,
	}
	row.update(allocation)
	return row
