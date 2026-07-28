# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

"""
Zoho Books Integration API

This module provides REST API endpoints for integration with Zoho Books.
Zoho developers should use these endpoints to sync data between Zoho Books
and APC Operations.

Base URL: https://your-domain.com/api/method/apc_operations.zoho.api

Authentication: Pass API key in header 'X-APC-API-Key'
"""

import frappe
import json
from frappe import _
from frappe.utils import today, getdate, now, flt
from frappe.utils.background_jobs import enqueue


# =============================================================================
# Authentication & Settings
# =============================================================================

def get_api_settings():
    """Get Zoho API settings."""
    return frappe.get_doc("APC Zoho Settings", "APC Zoho Settings")


def validate_api_key(func):
    """Decorator to validate API key."""
    def wrapper(*args, **kwargs):
        api_key = frappe.get_request_header("X-APC-API-Key")
        if not api_key:
            # For development, allow if no key is set
            try:
                settings = frappe.get_doc("APC Zoho Settings", "APC Zoho Settings")
                if not settings.api_key:
                    return func(*args, **kwargs)
            except:
                pass
            return {"success": False, "error": "Missing API key. Add 'X-APC-API-Key' header."}

        # Validate API key
        try:
            settings = frappe.get_doc("APC Zoho Settings", "APC Zoho Settings")
            if settings.api_key != api_key:
                return {"success": False, "error": "Invalid API key"}
        except:
            return {"success": False, "error": "API not configured"}

        return func(*args, **kwargs)
    return wrapper


# =============================================================================
# Sales Order / PFI Endpoints
# =============================================================================

@frappe.whitelist()
@validate_api_key
def get_sales_orders(status=None, from_date=None, to_date=None, limit=50):
    """
    Get list of Sales Orders from APC that need to be synced to Zoho.

    GET /api/method/apc_operations.zoho.api.get_sales_orders

    Query Parameters:
        status (str): Filter by status (optional)
        from_date (date): Filter from date (optional)
        to_date (date): Filter to date (optional)
        limit (int): Maximum records to return (default 50)

    Returns:
        JSON: List of sales orders with their items
    """
    filters = {"docstatus": 1}

    if status:
        filters["status"] = status
    if from_date:
        filters["sales_order_date"] = [">=", getdate(from_date)]
    if to_date:
        filters["sales_order_date"] = ["<=", getdate(to_date)]

    sales_orders = frappe.get_all(
        "APC Sales Demand",
        filters=filters,
        fields=[
            "name", "zoho_sales_order_id", "zoho_sales_order_number",
            "customer", "customer_name", "sales_order_date",
            "required_dispatch_date", "status", "total_demand_quantity",
            "total_allocated_quantity", "total_dispatched_quantity",
            "zoho_sync_status", "zoho_sync_date"
        ],
        order_by="sales_order_date DESC",
        limit_page_length=limit
    )

    # Get items for each sales order
    for order in sales_orders:
        items = frappe.get_all(
            "APC Sales Demand Item",
            filters={"parent": order.name},
            fields=["name", "item", "item_name", "grade", "specification",
                    "demand_quantity", "allocated_quantity", "uom"]
        )
        order["items"] = items

    return {
        "success": True,
        "count": len(sales_orders),
        "data": sales_orders
    }


@frappe.whitelist()
@validate_api_key
def import_pfi(pfi_data):
    """
    Import a PFI (Provisional Fuel Invoice) / Sales Order from Zoho Books.

    POST /api/method/apc_operations.zoho.api.import_pfi

    Request Body (JSON):
        {
            "zoho_pfi_id": "PFI-12345",
            "zoho_pfi_number": "PFI-2026-001",
            "customer_id": "CUST-001",
            "customer_name": "ABC Company",
            "pfi_date": "2026-05-01",
            "required_dispatch_date": "2026-05-15",
            "items": [
                {
                    "item_id": "ITEM-001",
                    "item_name": "Premium Diesel",
                    "grade": "Premium",
                    "specification": "Euro V",
                    "quantity": 10000,
                    "uom": "LTR"
                }
            ],
            "incoterms": "FOB",
            "port_of_loading": "Jebel Ali",
            "port_of_discharge": "Mundra",
            "mode_of_transport": "Sea"
        }

    Returns:
        JSON: Created sales demand or error
    """
    try:
        data = json.loads(pfi_data) if isinstance(pfi_data, str) else pfi_data

        # Check if already imported
        existing = frappe.db.exists(
            "APC Sales Demand",
            {"zoho_sales_order_id": data.get("zoho_pfi_id")}
        )
        if existing:
            return {
                "success": False,
                "error": "PFI already imported",
                "sales_demand": existing
            }

        # Get or create customer
        customer = get_or_create_customer(
            data.get("customer_id"),
            data.get("customer_name")
        )

        # Create Sales Demand
        sales_demand = frappe.new_doc("APC Sales Demand")
        sales_demand.zoho_sales_order_id = data.get("zoho_pfi_id")
        sales_demand.zoho_sales_order_number = data.get("zoho_pfi_number")
        sales_demand.zoho_sync_status = "Synced"
        sales_demand.zoho_sync_date = now()
        sales_demand.customer = customer
        sales_demand.sales_order_date = getdate(data.get("pfi_date")) if data.get("pfi_date") else today()
        sales_demand.required_dispatch_date = getdate(data.get("required_dispatch_date")) if data.get("required_dispatch_date") else None

        # Map items
        for item_data in data.get("items", []):
            item = get_or_create_item(
                item_data.get("item_id"),
                item_data.get("item_name")
            )

            sales_demand.append("items", {
                "item": item,
                "item_name": item_data.get("item_name"),
                "grade": item_data.get("grade"),
                "specification": item_data.get("specification"),
                "demand_quantity": flt(item_data.get("quantity", 0)),
                "uom": item_data.get("uom", "Nos")
            })

        sales_demand.insert()

        # Log sync
        log_sync(
            sync_type="PFI Import",
            zoho_id=data.get("zoho_pfi_id"),
            apc_document_type="APC Sales Demand",
            apc_document=sales_demand.name,
            sync_status="Success",
            request_data=data
        )

        return {
            "success": True,
            "message": "PFI imported successfully",
            "sales_demand": sales_demand.name,
            "sales_demand_url": f"/app/apc-sales-demand/{sales_demand.name}"
        }

    except Exception as e:
        frappe.db.rollback()
        log_sync(
            sync_type="PFI Import",
            sync_status="Failed",
            request_data=data if 'data' in locals() else {},
            error_message=str(e)
        )
        return {
            "success": False,
            "error": str(e)
        }


@frappe.whitelist()
@validate_api_key
def create_job_order_from_pfi(pfi_id):
    """
    Create a Job Order from an imported PFI/Sales Demand.

    POST /api/method/apc_operations.zoho.api.create_job_order_from_pfi

    Request Body (JSON):
        {
            "pfi_id": "PFI-12345"  // APC Sales Demand name or Zoho PFI ID
        }

    Returns:
        JSON: Created Job Order or error
    """
    try:
        # Find sales demand
        sales_demand = None

        # Try by name first
        if frappe.db.exists("APC Sales Demand", pfi_id):
            sales_demand = frappe.get_doc("APC Sales Demand", pfi_id)
        else:
            # Try by Zoho ID
            sales_demand_name = frappe.db.get_value(
                "APC Sales Demand",
                {"zoho_sales_order_id": pfi_id},
                "name"
            )
            if sales_demand_name:
                sales_demand = frappe.get_doc("APC Sales Demand", sales_demand_name)

        if not sales_demand:
            return {
                "success": False,
                "error": f"Sales Demand not found: {pfi_id}"
            }

        # Check if Job Order already linked
        if sales_demand.job_order:
            return {
                "success": False,
                "error": "Job Order already exists",
                "job_order": sales_demand.job_order,
                "job_order_url": f"/app/job-order/{sales_demand.job_order}"
            }

        # Get customer details
        customer = frappe.get_doc("Customer", sales_demand.customer)

        # Create Job Order
        job_order = frappe.new_doc("Job Order")
        job_order.commercial_movement = "Outward"
        job_order.customer = sales_demand.customer
        job_order.date = sales_demand.sales_order_date or today()
        job_order.status = "Draft"
        job_order.pi_number = sales_demand.zoho_sales_order_number

        # Copy items from sales demand
        for item in sales_demand.items:
            job_order.append("items", {
                "item_code": item.item,
                "item_name": item.item_name,
                "qty": item.demand_quantity,
                "uom": item.uom
            })

        job_order.insert()

        # Link sales demand to job order
        sales_demand.db_set("job_order", job_order.name, update_modified=False)

        return {
            "success": True,
            "message": "Job Order created successfully",
            "job_order": job_order.name,
            "job_order_url": f"/app/job-order/{job_order.name}"
        }

    except Exception as e:
        frappe.db.rollback()
        return {
            "success": False,
            "error": str(e)
        }


# =============================================================================
# Delivery Note / Dispatch Endpoints
# =============================================================================

@frappe.whitelist()
@validate_api_key
def sync_delivery_note(delivery_data):
    """
    Sync dispatch/delivery information back to Zoho Books.

    POST /api/method/apc_operations.zoho.api.sync_delivery_note

    Request Body (JSON):
        {
            "dispatch_order": "DISP-2026-0001",
            "zoho_delivery_note_id": "DN-12345",  // Optional - if creating new
            "dispatch_date": "2026-05-04",
            "vehicle_number": "ABC-1234",
            "driver_name": "John Doe",
            "lr_number": "LR-001",
            "items": [
                {
                    "batch_number": "BATCH-001",
                    "quantity": 5000,
                    "coa_number": "COA-001"
                }
            ]
        }

    Returns:
        JSON: Synced delivery note info or error
    """
    try:
        data = json.loads(delivery_data) if isinstance(delivery_data, str) else delivery_data

        dispatch_order_name = data.get("dispatch_order")
        if not dispatch_order_name:
            return {"success": False, "error": "dispatch_order is required"}

        dispatch = frappe.get_doc("APC Dispatch Order", dispatch_order_name)

        # If Zoho DN ID provided, update it
        if data.get("zoho_delivery_note_id"):
            # TODO: Call Zoho API to update delivery note
            # For now, just log the reference
            dispatch.db_set("zoho_delivery_note_id", data.get("zoho_delivery_note_id"), update_modified=False)

        # Log sync
        log_sync(
            sync_type="Delivery Note Export",
            zoho_id=data.get("zoho_delivery_note_id"),
            apc_document_type="APC Dispatch Order",
            apc_document=dispatch.name,
            sync_status="Success",
            request_data=data
        )

        return {
            "success": True,
            "message": "Delivery note synced",
            "dispatch_order": dispatch.name,
            "zoho_delivery_note_id": dispatch.zoho_delivery_note_id
        }

    except Exception as e:
        log_sync(
            sync_type="Delivery Note Export",
            sync_status="Failed",
            request_data=data if 'data' in locals() else {},
            error_message=str(e)
        )
        return {
            "success": False,
            "error": str(e)
        }


# =============================================================================
# Inventory / Stock Endpoints
# =============================================================================

@frappe.whitelist()
@validate_api_key
def get_inventory(product=None, warehouse=None, as_of_date=None):
    """
    Get current inventory/stock levels from APC.

    GET /api/method/apc_operations.zoho.api.get_inventory

    Query Parameters:
        product (str): Filter by product/item code (optional)
        warehouse (str): Filter by warehouse (optional)
        as_of_date (date): Stock as of date (optional, defaults to today)

    Returns:
        JSON: List of products with available quantities
    """
    filters = [
        ["batch_status", "in", ["Active", "On Hold"]],
        ["quality_status", "=", "Approved"],
        ["available_quantity", ">", 0]
    ]

    if product:
        filters.append(["product", "=", product])
    if warehouse:
        filters.append(["warehouse", "=", warehouse])

    batches = frappe.get_all(
        "APC Batch",
        filters=filters,
        fields=[
            "name", "batch_number", "product", "grade", "specification",
            "batch_quantity", "available_quantity", "allocated_quantity",
            "manufacturing_date", "warehouse", "quality_status"
        ],
        order_by="manufacturing_date ASC"
    )

    # Group by product
    stock_by_product = {}
    for batch in batches:
        product_key = batch.product
        if product_key not in stock_by_product:
            stock_by_product[product_key] = {
                "product": batch.product,
                "grade": batch.grade,
                "specification": batch.specification,
                "total_available": 0,
                "total_allocated": 0,
                "total_batch_quantity": 0,
                "batches": []
            }

        stock_by_product[product_key]["total_available"] += flt(batch.available_quantity)
        stock_by_product[product_key]["total_allocated"] += flt(batch.allocated_quantity)
        stock_by_product[product_key]["total_batch_quantity"] += flt(batch.batch_quantity)
        stock_by_product[product_key]["batches"].append({
            "batch_number": batch.batch_number,
            "available_quantity": batch.available_quantity,
            "allocated_quantity": batch.allocated_quantity,
            "manufacturing_date": batch.manufacturing_date,
            "warehouse": batch.warehouse
        })

    return {
        "success": True,
        "count": len(stock_by_product),
        "data": list(stock_by_product.values())
    }


@frappe.whitelist()
@validate_api_key
def get_batch_details(batch_number):
    """
    Get details of a specific batch.

    GET /api/method/apc_operations.zoho.api.get_batch_details

    Query Parameters:
        batch_number (str): Batch number to lookup

    Returns:
        JSON: Batch details including COA info
    """
    if not batch_number:
        return {"success": False, "error": "batch_number is required"}

    batch = frappe.get_doc("APC Batch", batch_number)

    return {
        "success": True,
        "data": {
            "name": batch.name,
            "batch_number": batch.batch_number,
            "product": batch.product,
            "grade": batch.grade,
            "specification": batch.specification,
            "batch_quantity": batch.batch_quantity,
            "available_quantity": batch.available_quantity,
            "allocated_quantity": batch.allocated_quantity,
            "manufacturing_date": batch.manufacturing_date,
            "expiry_date": batch.expiry_date,
            "warehouse": batch.warehouse,
            "quality_status": batch.quality_status,
            "batch_status": batch.batch_status,
            "linked_coa": batch.linked_coa
        }
    }


# =============================================================================
# Job Order Endpoints
# =============================================================================

@frappe.whitelist()
@validate_api_key
def get_job_orders(status=None, from_date=None, to_date=None, limit=50):
    """
    Get list of Job Orders.

    GET /api/method/apc_operations.zoho.api.get_job_orders

    Query Parameters:
        status (str): Filter by status (optional)
        from_date (date): Filter from date (optional)
        to_date (date): Filter to date (optional)
        limit (int): Maximum records (default 50)

    Returns:
        JSON: List of job orders
    """
    filters = {}

    if status:
        filters["status"] = status
    if from_date:
        filters["date"] = [">=", getdate(from_date)]
    if to_date:
        filters["date"] = ["<=", getdate(to_date)]

    job_orders = frappe.get_all(
        "Job Order",
        filters=filters,
        fields=[
            "name", "job_order_number", "customer", "customer_name",
            "date", "status", "terms_of_delivery", "mode_of_transport",
            "port_of_loading", "port_of_discharge",
            "transport_status", "shipping_status",
            "transport_schedule", "shipping_booking"
        ],
        order_by="date DESC",
        limit_page_length=limit
    )

    return {
        "success": True,
        "count": len(job_orders),
        "data": job_orders
    }


@frappe.whitelist()
@validate_api_key
def update_job_order_status(job_order, status, notes=None):
    """
    Update Job Order status from Zoho.

    POST /api/method/apc_operations.zoho.api.update_job_order_status

    Request Body (JSON):
        {
            "job_order": "JO-2026-0001",
            "status": "In Progress",
            "notes": "Status update from Zoho"
        }

    Returns:
        JSON: Updated job order info
    """
    try:
        if not job_order:
            return {"success": False, "error": "job_order is required"}

        jo = frappe.get_doc("Job Order", job_order)
        jo.status = status

        if notes:
            jo.add_comment("Comment", text=f"Status update from Zoho: {notes}")

        jo.save()

        return {
            "success": True,
            "message": "Job Order status updated",
            "job_order": jo.name,
            "status": jo.status
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# =============================================================================
# Shipping & Transport Endpoints
# =============================================================================

@frappe.whitelist()
@validate_api_key
def get_transport_schedule(job_order=None, status=None, limit=50):
    """
    Get Transport Schedules.

    GET /api/method/apc_operations.zoho.api.get_transport_schedule

    Query Parameters:
        job_order (str): Filter by Job Order
        status (str): Filter by transport status
        limit (int): Maximum records (default 50)

    Returns:
        JSON: List of transport schedules
    """
    filters = {}
    if job_order:
        filters["job_order"] = job_order
    if status:
        filters["transport_status"] = status

    transports = frappe.get_all(
        "Transport Schedule",
        filters=filters,
        fields=[
            "name", "job_order", "customer", "scheduled_pickup_date",
            "scheduled_delivery_date", "transport_status", "vehicle", "driver",
            "vehicle_number", "port_of_loading", "port_of_discharge"
        ],
        order_by="scheduled_pickup_date DESC",
        limit_page_length=limit
    )

    return {
        "success": True,
        "count": len(transports),
        "data": transports
    }


@frappe.whitelist()
@validate_api_key
def get_shipping_booking(job_order=None, status=None, limit=50):
    """
    Get Shipping Bookings.

    GET /api/method/apc_operations.zoho.api.get_shipping_booking

    Query Parameters:
        job_order (str): Filter by Job Order
        status (str): Filter by booking status
        limit (int): Maximum records (default 50)

    Returns:
        JSON: List of shipping bookings
    """
    filters = {}
    if job_order:
        filters["job_order"] = job_order
    if status:
        filters["booking_status"] = status

    bookings = frappe.get_all(
        "Shipping Booking",
        filters=filters,
        fields=[
            "name", "job_order", "customer", "vessel_name", "vessel_date",
            "cutoff_date", "pull_out_date", "booking_status", "cro_number",
            "port_of_loading", "port_of_discharge", "container_count"
        ],
        order_by="vessel_date DESC",
        limit_page_length=limit
    )

    return {
        "success": True,
        "count": len(bookings),
        "data": bookings
    }


# =============================================================================
# Helper Functions
# =============================================================================

def get_or_create_customer(zoho_customer_id, customer_name):
    """Get or create customer from Zoho data."""
    if zoho_customer_id:
        customer = frappe.db.get_value(
            "Customer",
            {"zoho_customer_id": zoho_customer_id},
            "name"
        )
        if customer:
            return customer

    if customer_name:
        customer = frappe.db.get_value(
            "Customer",
            {"customer_name": customer_name},
            "name"
        )
        if customer:
            if zoho_customer_id:
                frappe.db.set_value(
                    "Customer", customer, "zoho_customer_id", zoho_customer_id,
                    update_modified=False
                )
            return customer

    customer = frappe.new_doc("Customer")
    customer.customer_name = customer_name or zoho_customer_id
    customer.customer_type = "Company"

    if zoho_customer_id:
        customer.zoho_customer_id = zoho_customer_id

    # Set defaults
    customer.customer_group = "Commercial"
    customer.territory = "All Territories"

    customer.insert(ignore_permissions=True)
    return customer.name


def get_or_create_item(zoho_item_id, item_name):
    """Get or create item from Zoho data."""
    if zoho_item_id:
        item = frappe.db.get_value(
            "Item",
            {"zoho_item_id": zoho_item_id},
            "name"
        )
        if item:
            return item

    if zoho_item_id:
        item = frappe.db.get_value(
            "Item",
            {"item_code": zoho_item_id},
            "name"
        )
        if item:
            frappe.db.set_value(
                "Item", item, "zoho_item_id", zoho_item_id,
                update_modified=False
            )
            return item

    item = frappe.new_doc("Item")
    item.item_code = zoho_item_id or frappe.generate_hash(length=10)
    item.item_name = item_name or item.item_code
    item.item_group = "APC Products"
    item.stock_uom = "Nos"
    item.is_stock_item = 1

    if zoho_item_id:
        item.zoho_item_id = zoho_item_id

    item.insert(ignore_permissions=True)
    return item.name


def log_sync(sync_type, sync_status, zoho_id=None, apc_document_type=None,
             apc_document=None, request_data=None, error_message=None):
    """Log a sync attempt."""
    try:
        log = frappe.new_doc("Zoho Sync Log")
        log.sync_type = sync_type
        log.sync_status = sync_status
        log.sync_date = now()
        log.zoho_id = zoho_id
        log.apc_document_type = apc_document_type
        log.apc_document = apc_document

        if request_data:
            log.request_data = str(request_data)[:4000]
        if error_message:
            log.error_message = str(error_message)[:4000]

        log.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        pass


# =============================================================================
# Webhook Endpoints (for Zoho to call)
# =============================================================================

@frappe.whitelist()
def webhook_pfi_created():
    """
    Webhook endpoint for when PFI is created in Zoho Books.
    Zoho should POST to this endpoint when a new PFI is confirmed.
    """
    # This would be called by Zoho via webhook
    # For now, just acknowledge
    return {"success": True, "message": "Webhook received"}


@frappe.whitelist()
def webhook_pfi_updated():
    """Webhook endpoint for PFI updates in Zoho Books."""
    return {"success": True, "message": "Webhook received"}


@frappe.whitelist()
def webhook_delivery_confirmed():
    """Webhook endpoint for delivery confirmation from Zoho."""
    return {"success": True, "message": "Webhook received"}