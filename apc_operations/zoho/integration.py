# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import today, getdate, now


# =============================================================================
# Zoho Books Integration API
# =============================================================================

@frappe.whitelist()
def import_sales_order_from_zoho(zoho_sales_order_id):
    """
    Import a sales order from Zoho Books and create APC Sales Demand.

    Args:
        zoho_sales_order_id: The Zoho Books sales order ID

    Returns:
        dict: Result with created demand name or error
    """
    # Check if already imported
    existing = frappe.db.exists("APC Sales Demand", {"zoho_sales_order_id": zoho_sales_order_id})
    if existing:
        return {
            "success": False,
            "message": "Sales order already imported",
            "demand": existing
        }

    # Get sales order from Zoho (placeholder for actual API call)
    zoho_data = get_zoho_sales_order(zoho_sales_order_id)

    if not zoho_data:
        return {
            "success": False,
            "message": "Sales order not found in Zoho"
        }

    # Create sales demand
    demand = frappe.new_doc("APC Sales Demand")
    demand.zoho_sales_order_id = zoho_sales_order_id
    demand.zoho_sales_order_number = zoho_data.get("salesorder_number")
    demand.zoho_sync_status = "Synced"
    demand.zoho_sync_date = now()

    # Map customer
    customer = get_or_create_customer(zoho_data.get("customer_id"), zoho_data.get("customer_name"))
    demand.customer = customer

    # Map dates
    demand.sales_order_date = getdate(zoho_data.get("date")) if zoho_data.get("date") else today()
    demand.required_dispatch_date = getdate(zoho_data.get("expected_shipment_date")) if zoho_data.get("expected_shipment_date") else None

    # Map line items
    for line_item in zoho_data.get("line_items", []):
        item = get_or_create_item(line_item.get("item_id"), line_item.get("name"))

        demand.append("items", {
            "item": item,
            "item_name": line_item.get("name"),
            "demand_quantity": line_item.get("quantity", 0),
            "uom": line_item.get("unit", "Nos")
        })

    demand.insert()

    # Log sync
    log_sync(
        sync_type="Sales Order Import",
        zoho_id=zoho_sales_order_id,
        apc_document_type="APC Sales Demand",
        apc_document=demand.name,
        sync_status="Success",
        request_data=zoho_data
    )

    return {
        "success": True,
        "message": "Sales order imported successfully",
        "demand": demand.name
    }


@frappe.whitelist()
def export_dispatch_to_zoho(dispatch_order):
    """
    Export a dispatch order to Zoho Books.

    Args:
        dispatch_order: Name of APC Dispatch Order

    Returns:
        dict: Result with Zoho ID or error
    """
    dispatch = frappe.get_doc("APC Dispatch Order", dispatch_order)

    if not dispatch.sales_demand:
        return {
            "success": False,
            "message": "Dispatch has no linked sales demand"
        }

    demand = frappe.get_doc("APC Sales Demand", dispatch.sales_demand)

    if not demand.zoho_sales_order_id:
        return {
            "success": False,
            "message": "Sales demand has no Zoho reference"
        }

    # Prepare data for Zoho
    zoho_data = {
        "salesorder_id": demand.zoho_sales_order_id,
        "dispatch_number": dispatch.dispatch_number or dispatch.name,
        "dispatch_date": dispatch.dispatch_date,
        "customer_id": demand.customer,
        "line_items": []
    }

    for detail in dispatch.batch_details:
        zoho_data["line_items"].append({
            "item_id": detail.item,
            "quantity": detail.quantity,
            "batch": detail.batch
        })

    # Call Zoho API (placeholder)
    result = create_zoho_delivery_note(zoho_data)

    if result.get("success"):
        # Update dispatch with Zoho reference
        dispatch.db_set("zoho_delivery_note_id", result.get("zoho_id"), update_modified=False)

        # Log sync
        log_sync(
            sync_type="Dispatch Export",
            zoho_id=result.get("zoho_id"),
            apc_document_type="APC Dispatch Order",
            apc_document=dispatch.name,
            sync_status="Success",
            request_data=zoho_data,
            response_data=result
        )

        return {
            "success": True,
            "message": "Dispatch exported to Zoho",
            "zoho_id": result.get("zoho_id")
        }
    else:
        # Log failed sync
        log_sync(
            sync_type="Dispatch Export",
            apc_document_type="APC Dispatch Order",
            apc_document=dispatch.name,
            sync_status="Failed",
            request_data=zoho_data,
            error_message=result.get("error")
        )

        return {
            "success": False,
            "message": result.get("error", "Export failed")
        }


@frappe.whitelist()
def sync_stock_to_zoho(items=None):
    """
    Sync APC batch stock quantities to Zoho Books.

    Args:
        items: List of item codes to sync (None = all)

    Returns:
        dict: Sync result with counts
    """
    filters = {"batch_status": ["in", ["Active", "On Hold"]], "quality_status": "Approved"}
    if items:
        filters["product"] = ["in", items]

    batches = frappe.get_all(
        "APC Batch",
        filters=filters,
        fields=["product", "available_quantity", "warehouse"]
    )

    # Group by product
    stock_by_product = {}
    for batch in batches:
        product = batch.product
        if product not in stock_by_product:
            stock_by_product[product] = 0
        stock_by_product[product] += batch.available_quantity

    # Sync to Zoho (placeholder)
    synced_count = 0
    for product, quantity in stock_by_product.items():
        result = update_zoho_stock(product, quantity)
        if result.get("success"):
            synced_count += 1

    return {
        "success": True,
        "synced_items": synced_count,
        "total_items": len(stock_by_product)
    }


# =============================================================================
# Zoho API Placeholders (Implement actual API calls)
# =============================================================================

def get_zoho_sales_order(zoho_id):
    """
    Fetch sales order from Zoho Books API.
    Placeholder - implement actual API integration.
    """
    # TODO: Implement actual Zoho API call
    # For now, return mock data for testing
    return {
        "salesorder_id": zoho_id,
        "salesorder_number": f"SO-{zoho_id}",
        "customer_id": "_Test Customer",
        "customer_name": "Test Customer",
        "date": today(),
        "expected_shipment_date": today(),
        "line_items": [
            {
                "line_item_id": 1,
                "item_id": "_Test Item",
                "name": "Test Item",
                "quantity": 100,
                "unit": "Nos"
            }
        ]
    }


def create_zoho_delivery_note(data):
    """
    Create delivery note in Zoho Books.
    Placeholder - implement actual API integration.
    """
    # TODO: Implement actual Zoho API call
    return {
        "success": True,
        "zoho_id": f"DN-{data.get('dispatch_number')}"
    }


def update_zoho_stock(item, quantity):
    """
    Update stock quantity in Zoho Books.
    Placeholder - implement actual API integration.
    """
    # TODO: Implement actual Zoho API call
    return {"success": True}


# =============================================================================
# Helper Functions
# =============================================================================

def get_or_create_customer(zoho_customer_id, customer_name):
    """Get or create an ERPNext Customer from Zoho master data."""
    customer_filters = {"zoho_customer_id": zoho_customer_id} if _has_field("Customer", "zoho_customer_id") else {}
    customer = frappe.db.get_value("Customer", customer_filters, "name") if customer_filters else None
    if customer:
        return customer

    if customer_name:
        customer = frappe.db.get_value("Customer", {"customer_name": customer_name}, "name")
        if customer:
            if zoho_customer_id and _has_field("Customer", "zoho_customer_id"):
                frappe.db.set_value("Customer", customer, "zoho_customer_id", zoho_customer_id, update_modified=False)
            return customer

    customer = frappe.new_doc("Customer")
    customer.customer_name = customer_name or zoho_customer_id
    customer.customer_type = "Company"
    _set_if_has_field(customer, "zoho_customer_id", zoho_customer_id)
    _set_if_has_field(customer, "customer_group", _get_default_customer_group())
    _set_if_has_field(customer, "territory", _get_default_territory())
    customer.insert(ignore_permissions=True)

    return customer.name


def get_or_create_item(zoho_item_id, item_name):
    """Get or create an ERPNext Item from Zoho master data."""
    item_filters = {"zoho_item_id": zoho_item_id} if _has_field("Item", "zoho_item_id") else {}
    item = frappe.db.get_value("Item", item_filters, "name") if item_filters else None
    if item:
        return item

    if zoho_item_id:
        item = frappe.db.get_value("Item", {"item_code": zoho_item_id}, "name")
        if item:
            if _has_field("Item", "zoho_item_id"):
                frappe.db.set_value("Item", item, "zoho_item_id", zoho_item_id, update_modified=False)
            return item

    item = frappe.new_doc("Item")
    item.item_code = zoho_item_id or frappe.generate_hash(length=10)
    item.item_name = item_name or item.item_code
    item.item_group = _get_default_item_group()
    item.stock_uom = _ensure_uom("Nos")
    item.is_stock_item = 1
    item.has_batch_no = 1
    item.batch_number_series = "BATCH-.YYYY.-.#####"
    _set_if_has_field(item, "zoho_item_id", zoho_item_id)
    item.insert(ignore_permissions=True)

    return item.name


def _has_field(doctype, fieldname):
    return frappe.get_meta(doctype).has_field(fieldname)


def _set_if_has_field(doc, fieldname, value):
    if value and doc.meta.has_field(fieldname):
        doc.set(fieldname, value)


def _get_default_item_group():
    return (
        frappe.db.exists("Item Group", "APC Products")
        or frappe.db.exists("Item Group", "Products")
        or frappe.db.get_value("Item Group", {"is_group": 0}, "name")
        or frappe.db.get_value("Item Group", {"is_group": 1}, "name")
    )


def _get_default_customer_group():
    return (
        frappe.db.exists("Customer Group", "Commercial")
        or frappe.db.exists("Customer Group", "All Customer Groups")
        or frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
        or frappe.db.get_value("Customer Group", {"is_group": 1}, "name")
    )


def _get_default_territory():
    return (
        frappe.db.exists("Territory", "All Territories")
        or frappe.db.get_value("Territory", {"is_group": 1}, "name")
        or frappe.db.get_value("Territory", {}, "name")
    )


def _ensure_uom(uom_name):
    if frappe.db.exists("UOM", uom_name):
        return uom_name

    uom = frappe.new_doc("UOM")
    uom.uom_name = uom_name
    uom.insert(ignore_permissions=True)
    return uom.name


def log_sync(sync_type, sync_status, zoho_id=None, apc_document_type=None,
             apc_document=None, request_data=None, response_data=None,
             error_message=None):
    """Log a sync attempt."""
    log = frappe.new_doc("Zoho Sync Log")
    log.sync_type = sync_type
    log.sync_status = sync_status
    log.sync_date = now()
    log.zoho_id = zoho_id
    log.apc_document_type = apc_document_type
    log.apc_document = apc_document

    if request_data:
        log.request_data = str(request_data)[:4000]  # Limit size
    if response_data:
        log.response_data = str(response_data)[:4000]
    if error_message:
        log.error_message = str(error_message)[:4000]

    log.insert(ignore_permissions=True)
    frappe.db.commit()


# =============================================================================
# Scheduled Jobs
# =============================================================================

def sync_pending_sales_orders():
    """Scheduled job to sync pending sales orders from Zoho."""
    # TODO: Implement scheduled sync
    pass


def retry_failed_syncs():
    """Scheduled job to retry failed syncs."""
    failed_syncs = frappe.get_all(
        "Zoho Sync Log",
        filters={"sync_status": "Failed", "retry_count": ["<", 3]},
        fields=["name", "sync_type", "zoho_id", "apc_document"],
        limit=50
    )

    for sync in failed_syncs:
        try:
            if sync.sync_type == "Sales Order Import":
                import_sales_order_from_zoho(sync.zoho_id)
            elif sync.sync_type == "Dispatch Export":
                export_dispatch_to_zoho(sync.apc_document)

            # Update retry count
            log = frappe.get_doc("Zoho Sync Log", sync.name)
            log.db_set("retry_count", log.retry_count + 1, update_modified=False)
        except Exception:
            pass


# =============================================================================
# Reports
# =============================================================================

@frappe.whitelist()
def get_zoho_sync_report(from_date=None, to_date=None, sync_type=None, status=None):
    """Get Zoho sync report."""
    filters = {}
    if from_date:
        filters["sync_date"] = [">=", from_date]
    if to_date:
        filters["sync_date"] = ["<=", to_date]
    if sync_type:
        filters["sync_type"] = sync_type
    if status:
        filters["sync_status"] = status

    syncs = frappe.get_all(
        "Zoho Sync Log",
        filters=filters,
        fields=["name", "sync_type", "sync_status", "sync_date", "zoho_id",
                "apc_document_type", "apc_document", "error_message"],
        order_by="sync_date DESC",
        limit=100
    )

    return syncs
