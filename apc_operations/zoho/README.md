# APC Operations — Zoho Books Integration API

This document describes the REST API endpoints available for integration between Zoho Books and APC Operations.

## Base URL

```
Production: https://your-domain.com/api/method/apc_operations.zoho.api
```

## Authentication

All API endpoints require an API key passed in the request header:

```
Header Name: X-APC-API-Key
Header Value: your-api-key
```

To get an API key:
1. Log in to APC Operations
2. Go to **APC Zoho Settings** (search in Awesomebar)
3. Generate or copy the API Key
4. Share this key with your Zoho developers

---

## Endpoints Overview

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `get_sales_orders` | Get list of Sales Demands |
| POST | `import_pfi` | Import PFI/Sales Order from Zoho |
| POST | `create_job_order_from_pfi` | Create Job Order from PFI |
| POST | `sync_delivery_note` | Sync dispatch/delivery to Zoho |
| GET | `get_inventory` | Get stock levels |
| GET | `get_batch_details` | Get batch information |
| GET | `get_job_orders` | Get Job Orders |
| POST | `update_job_order_status` | Update Job Order status |
| GET | `get_transport_schedule` | Get Transport Schedules |
| GET | `get_shipping_booking` | Get Shipping Bookings |

---

## Sales Order / PFI Endpoints

### Get Sales Orders

Fetch list of Sales Demands that need to be synced.

**Endpoint:** `GET /api/method/apc_operations.zoho.api.get_sales_orders`

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| status | string | No | Filter by status |
| from_date | date | No | Filter from date (YYYY-MM-DD) |
| to_date | date | No | Filter to date (YYYY-MM-DD) |
| limit | int | No | Max records (default 50) |

**Response:**
```json
{
  "success": true,
  "count": 2,
  "data": [
    {
      "name": "SD-2026-0001",
      "zoho_sales_order_id": "PFI-12345",
      "zoho_sales_order_number": "PFI-2026-001",
      "customer": "CUST-001",
      "customer_name": "ABC Company",
      "sales_order_date": "2026-05-01",
      "required_dispatch_date": "2026-05-15",
      "status": "Confirmed",
      "total_demand_quantity": 10000,
      "total_allocated_quantity": 5000,
      "total_dispatched_quantity": 0,
      "items": [
        {
          "name": "SDI-00001",
          "item": "ITEM-001",
          "item_name": "Premium Diesel",
          "grade": "Premium",
          "specification": "Euro V",
          "demand_quantity": 10000,
          "allocated_quantity": 5000,
          "uom": "LTR"
        }
      ]
    }
  ]
}
```

---

### Import PFI

Import a PFI (Provisional Fuel Invoice) / Sales Order from Zoho Books.

**Endpoint:** `POST /api/method/apc_operations.zoho.api.import_pfi`

**Headers:**
```
Content-Type: application/json
X-APC-API-Key: your-api-key
```

**Request Body:**
```json
{
  "zoho_pfi_id": "PFI-12345",
  "zoho_pfi_number": "PFI-2026-001",
  "customer_id": "CUST-001",
  "customer_name": "ABC Company",
  "pfi_date": "2026-05-01",
  "required_dispatch_date": "2026-05-15",
  "incoterms": "FOB",
  "port_of_loading": "Jebel Ali",
  "port_of_discharge": "Mundra",
  "mode_of_transport": "Sea",
  "items": [
    {
      "item_id": "ITEM-001",
      "item_name": "Premium Diesel",
      "grade": "Premium",
      "specification": "Euro V",
      "quantity": 10000,
      "uom": "LTR"
    }
  ]
}
```

**Response:**
```json
{
  "success": true,
  "message": "PFI imported successfully",
  "sales_demand": "SD-2026-0001",
  "sales_demand_url": "/app/apc-sales-demand/SD-2026-0001"
}
```

---

### Create Job Order from PFI

Create a Job Order from an imported PFI/Sales Demand.

**Endpoint:** `POST /api/method/apc_operations.zoho.api.create_job_order_from_pfi`

**Request Body:**
```json
{
  "pfi_id": "SD-2026-0001"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Job Order created successfully",
  "job_order": "JO-2026-0001",
  "job_order_url": "/app/job-order/JO-2026-0001"
}
```

---

## Delivery Note / Dispatch Endpoints

### Sync Delivery Note

Sync dispatch/delivery information back to Zoho Books.

**Endpoint:** `POST /api/method/apc_operations.zoho.api.sync_delivery_note`

**Request Body:**
```json
{
  "dispatch_order": "DISP-2026-0001",
  "zoho_delivery_note_id": "DN-12345",
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
```

**Response:**
```json
{
  "success": true,
  "message": "Delivery note synced",
  "dispatch_order": "DISP-2026-0001",
  "zoho_delivery_note_id": "DN-12345"
}
```

---

## Inventory / Stock Endpoints

### Get Inventory

Get current inventory/stock levels from APC.

**Endpoint:** `GET /api/method/apc_operations.zoho.api.get_inventory`

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| product | string | No | Filter by product/item code |
| warehouse | string | No | Filter by warehouse |
| as_of_date | date | No | Stock as of date |

**Response:**
```json
{
  "success": true,
  "count": 2,
  "data": [
    {
      "product": "Premium Diesel",
      "grade": "Premium",
      "specification": "Euro V",
      "total_available": 50000,
      "total_allocated": 10000,
      "total_batch_quantity": 60000,
      "batches": [
        {
          "batch_number": "BATCH-001",
          "available_quantity": 30000,
          "allocated_quantity": 5000,
          "manufacturing_date": "2026-04-01",
          "warehouse": "Main Warehouse"
        }
      ]
    }
  ]
}
```

---

### Get Batch Details

Get details of a specific batch.

**Endpoint:** `GET /api/method/apc_operations.zoho.api.get_batch_details`

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| batch_number | string | Yes | Batch number to lookup |

**Response:**
```json
{
  "success": true,
  "data": {
    "name": "BATCH-001",
    "batch_number": "BATCH-001",
    "product": "Premium Diesel",
    "grade": "Premium",
    "specification": "Euro V",
    "batch_quantity": 30000,
    "available_quantity": 30000,
    "allocated_quantity": 0,
    "manufacturing_date": "2026-04-01",
    "expiry_date": "2028-04-01",
    "warehouse": "Main Warehouse",
    "quality_status": "Approved",
    "batch_status": "Active",
    "linked_coa": "COA-001"
  }
}
```

---

## Job Order Endpoints

### Get Job Orders

Get list of Job Orders.

**Endpoint:** `GET /api/method/apc_operations.zoho.api.get_job_orders`

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| status | string | No | Filter by status |
| from_date | date | No | Filter from date |
| to_date | date | No | Filter to date |
| limit | int | No | Max records |

**Response:**
```json
{
  "success": true,
  "count": 1,
  "data": [
    {
      "name": "JO-2026-0001",
      "job_order_number": "JO-2026-0001",
      "customer": "CUST-001",
      "customer_name": "ABC Company",
      "date": "2026-05-01",
      "status": "Confirmed",
      "terms_of_delivery": "FOB",
      "mode_of_transport": "Sea",
      "port_of_loading": "Jebel Ali",
      "port_of_discharge": "Mundra",
      "transport_status": "Scheduled",
      "shipping_status": "In Progress",
      "transport_schedule": "TRN-2026-0001",
      "shipping_booking": "SB-2026-0001"
    }
  ]
}
```

---

### Update Job Order Status

Update Job Order status from Zoho.

**Endpoint:** `POST /api/method/apc_operations.zoho.api.update_job_order_status`

**Request Body:**
```json
{
  "job_order": "JO-2026-0001",
  "status": "In Progress",
  "notes": "Status update from Zoho"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Job Order status updated",
  "job_order": "JO-2026-0001",
  "status": "In Progress"
}
```

---

## Transport & Shipping Endpoints

### Get Transport Schedule

**Endpoint:** `GET /api/method/apc_operations.zoho.api.get_transport_schedule`

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| job_order | string | No | Filter by Job Order |
| status | string | No | Filter by transport status |
| limit | int | No | Max records |

---

### Get Shipping Booking

**Endpoint:** `GET /api/method/apc_operations.zoho.api.get_shipping_booking`

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| job_order | string | No | Filter by Job Order |
| status | string | No | Filter by booking status |
| limit | int | No | Max records |

---

## Error Responses

All endpoints return errors in this format:

```json
{
  "success": false,
  "error": "Error description here"
}
```

Common error codes:
- `Missing API key` — Add `X-APC-API-Key` header
- `Invalid API key` — Check your API key in APC Zoho Settings
- `Sales Demand not found` — The PFI ID doesn't exist
- `Job Order already exists` — Already linked

---

## Testing

Test the API using curl:

```bash
# Get sales orders
curl -X GET "https://your-domain.com/api/method/apc_operations.zoho.api.get_sales_orders" \
  -H "X-APC-API-Key: your-api-key"

# Import PFI
curl -X POST "https://your-domain.com/api/method/apc_operations.zoho.api.import_pfi" \
  -H "Content-Type: application/json" \
  -H "X-APC-API-Key: your-api-key" \
  -d '{"zoho_pfi_id":"PFI-123","customer_name":"Test","items":[{"item_id":"ITEM-1","item_name":"Test"}]}'
```

---

## Flow Diagram

```
Zoho Books                    APC Operations
    |                              |
    |-- PFI Created (Webhook) -->  |
    |                              |-- import_pfi()
    |                              |-- APC Sales Demand Created
    |                              |
    |-- Get Sales Orders -->       |
    |                              |-- Returns Sales Demand list
    |                              |
    |-- Create Job Order -->       |
    |                              |-- create_job_order_from_pfi()
    |                              |-- Job Order Created
    |                              |
    |                     (Internal APC Flow)
    |                              |
    |                              |-- Transport Schedule
    |                              |-- Security Inspection
    |                              |-- QC Report
    |                              |-- Loading DN
    |                              |
    |-- Sync Delivery Note -->    |
    |                              |-- sync_delivery_note()
    |                              |-- Delivery Note synced to Zoho
    |                              |
    |-- Get Inventory -->         |
    |                              |-- Returns stock levels
```

---

## Support

For API issues or questions:
- Check **Zoho Sync Log** in APC Operations for sync history
- Review server logs at `/logs/frappe.log`
- Contact APC IT team