# ERPNext Merge Changes

## Scope

This document records the ERPNext merge work completed for APC Operations.

The merge keeps APC's custom outward movement workflow intact:

- Shipping Booking
- Transport Schedule
- Security Inspection
- Loading Delivery Note
- APC Dispatch Order
- APC Batch Allocation / FIFO reservation logic

ERPNext is used as the stable backbone for shared master data, batch identity, and quality inspection references.

## Installed App Context

The site now has these apps installed:

```text
frappe
erpnext
apc_operations
```

## 1. ERPNext Dependency

Updated `apc_operations/hooks.py` to make ERPNext an explicit dependency:

```python
required_apps = ["erpnext"]
```

Purpose:

- Prevent APC Operations from being installed without ERPNext.
- Ensure standard DocTypes such as `Item`, `Customer`, `Warehouse`, `UOM`, `Batch`, and `Quality Inspection` exist.

## 2. Master Data Merge

ERPNext is now the source for shared operational master data:

- `Item`
- `Customer`
- `Warehouse`
- `UOM`

APC Operations continues to use these master records through existing Link fields.

### Removed Duplicate APC UOM

Removed the custom APC `UOM` DocType files:

```text
apc_operations/shipping/doctype/uom/uom.json
apc_operations/shipping/doctype/uom/uom.py
apc_operations/shipping/doctype/uom/uom.js
apc_operations/shipping/doctype/uom/test_uom.py
```

Reason:

- ERPNext already provides `UOM`.
- Keeping a custom DocType with the same name risks migration and metadata conflicts.

After migration, `UOM` resolves from ERPNext module `Setup`.

### Added ERPNext Master Custom Fields

Created patch:

```text
apc_operations.patches.v0_1.merge_erpnext_master_data
```

The patch adds Zoho/APC tracking fields:

On `Customer`:

- `zoho_customer_id`

On `Item`:

- `zoho_item_id`
- `apc_grade`
- `apc_specification`
- `apc_packaging_type`

The patch also ensures an `APC Products` Item Group exists for Zoho-created stock items.

### Updated Zoho Master Sync

Updated:

```text
apc_operations/zoho/integration.py
```

Changes:

- `get_or_create_customer()` now creates/uses ERPNext `Customer`.
- `get_or_create_item()` now creates/uses ERPNext `Item`.
- Zoho IDs are stored on ERPNext master records.
- Zoho-created Items are created as stock items with batch tracking enabled.
- Default UOM uses ERPNext `UOM`.

## 3. APC Batch To ERPNext Batch Bridge

APC Batch remains the operational allocation wrapper.

ERPNext Batch is now the stable stock backbone batch identity.

### Added Field

Updated:

```text
apc_operations/inventory/doctype/apc_batch/apc_batch.json
```

Added field:

```text
erpnext_batch
```

Field details:

- Type: Link
- Options: `Batch`
- Read only
- Visible in list view and standard filters

### Updated APC Batch Controller

Updated:

```text
apc_operations/inventory/doctype/apc_batch/apc_batch.py
```

Added behavior:

- Validate linked ERPNext Batch belongs to the same Item.
- Automatically enable batch tracking on the linked ERPNext Item.
- Create ERPNext `Batch` when a new `APC Batch` is created.
- Sync manufacturing date, expiry date, APC reference, and description to ERPNext Batch.
- Include `erpnext_batch` in available batch API results.

### Updated APC Batch UI

Updated:

```text
apc_operations/inventory/doctype/apc_batch/apc_batch.js
```

Added button:

- `View ERPNext Batch`

### Added Backfill Patch

Created patch:

```text
apc_operations.patches.v0_1.backfill_apc_batch_erpnext_batch
```

Purpose:

- For existing `APC Batch` records, create or link matching ERPNext `Batch` records.

Current database note:

- At time of verification, there were `0` APC Batch records, so no existing batches needed backfill.

### Updated Batch Stock Ledger

Updated:

```text
apc_operations/inventory/report/batch_stock_ledger/batch_stock_ledger.py
```

Added `ERPNext Batch` column.

## 4. APC COA To ERPNext Quality Inspection Bridge

APC COA remains the outward-facing certificate layer.

ERPNext Quality Inspection is now the quality test/approval reference.

### Added Field

Updated:

```text
apc_operations/inventory/doctype/apc_coa/apc_coa.json
```

Added field:

```text
quality_inspection
```

Field details:

- Type: Link
- Options: `Quality Inspection`
- Visible in list view and standard filters

### Updated APC COA Controller

Updated:

```text
apc_operations/inventory/doctype/apc_coa/apc_coa.py
```

Added behavior:

- Validate linked Quality Inspection exists.
- Validate Quality Inspection item matches the COA product.
- Validate Quality Inspection batch matches the ERPNext Batch linked from APC Batch, when available.
- Sync ERPNext Quality Inspection status into APC COA:
  - `Accepted` -> `Approved`
  - `Rejected` -> `Rejected`
- Continue syncing APC COA approval/rejection into APC Batch quality status.

### Added ERPNext Quality Inspection Hook

Updated:

```text
apc_operations/hooks.py
```

Added doc events for `Quality Inspection`:

- `on_update`
- `on_submit`

Both call:

```text
apc_operations.inventory.doctype.apc_coa.apc_coa.sync_apc_coa_from_quality_inspection
```

Purpose:

- If an ERPNext Quality Inspection changes status, linked APC COAs are updated automatically.

### Updated APC COA UI

Updated:

```text
apc_operations/inventory/doctype/apc_coa/apc_coa.js
```

Added buttons:

- `View Quality Inspection`
- `Sync Quality Inspection`

Added client-side status mapping:

- Quality Inspection `Accepted` sets COA status to `Approved`.
- Quality Inspection `Rejected` sets COA status to `Rejected`.

### Added Backfill Patch

Created patch:

```text
apc_operations.patches.v0_1.backfill_apc_coa_quality_inspection
```

Purpose:

- For existing APC COAs already linked to Quality Inspections, pull current inspection status into APC COA.

Current database note:

- At time of verification, there were `0` APC COA records, so no existing COAs needed backfill.

## 5. Patch List Updates

Updated:

```text
apc_operations/patches.txt
```

Added patches:

```text
apc_operations.patches.v0_1.merge_erpnext_master_data
apc_operations.patches.v0_1.backfill_apc_batch_erpnext_batch
apc_operations.patches.v0_1.backfill_apc_coa_quality_inspection
```

## 6. Migrations And Builds Run

The following commands were run successfully during the merge:

```bash
env/bin/bench --site apc.local migrate
env/bin/bench --site apc.local clear-cache
env/bin/bench build --app apc_operations
```

## 7. Verification Performed

### Master Data

Verified:

- `UOM` resolves from ERPNext module `Setup`.
- `Item-zoho_item_id` custom field exists.
- `Customer-zoho_customer_id` custom field exists.
- Mock Zoho import created an `APC Sales Demand`.

Created by smoke test:

```text
DEMAND-2026-00030
```

### Batch Bridge

Verified:

- `APC Batch.erpnext_batch` exists.
- Field links to ERPNext `Batch`.
- ERPNext `Batch` belongs to module `Stock`.
- Migration patch executed successfully.

### Quality Bridge

Verified:

- `APC COA.quality_inspection` exists.
- Field links to ERPNext `Quality Inspection`.
- ERPNext `Quality Inspection` belongs to module `Stock`.
- Migration patch executed successfully.

### Static Checks

Python syntax checks passed for changed Python files.

No linter errors were reported for changed files.

## 8. What Was Intentionally Not Replaced

The following APC workflows were not replaced by ERPNext:

- Shipping coordination
- Transport scheduling
- Security inspection
- Loading delivery note workflow
- Dispatch order workflow
- FIFO batch allocation/reservation workflow
- Zoho Books finance integration boundary

These remain APC-specific operational workflows.

## 9. Current Architecture After Merge

```text
Zoho Books Sales Order
 -> APC Sales Demand
 -> APC Batch Allocation / Production Requirement
 -> APC Batch
      -> ERPNext Batch
 -> ERPNext Quality Inspection
      -> APC COA
 -> APC Transport / Shipping / Security
 -> APC Dispatch Order
 -> Zoho Books update / integration point
```

## 10. Recommended Next Steps

### Next Step 1: Production Bridge

Bridge:

```text
APC Production Requirement -> ERPNext Work Order
```

Keep `APC Production Requirement` as the shortage/demand signal.

Use ERPNext `Work Order` for production execution.

### Next Step 2: Stock Posting Bridge

Decide whether dispatch completion should create:

- ERPNext `Delivery Note`, or
- ERPNext `Stock Entry`

Recommendation:

- Use `Delivery Note` if ERPNext should record customer delivery.
- Use `Stock Entry` if APC only needs operational stock movement and Zoho remains the commercial system.

### Next Step 3: Reports

Gradually update stock dashboards/reports to show:

- APC reserved quantity from `APC Batch Allocation`
- ERPNext physical batch/stock quantity from `Batch` / stock ledger

## 11. Important Notes

- Finance remains in Zoho Books.
- ERPNext Accounting should not become the source of truth unless explicitly decided later.
- APC Batch Allocation remains necessary because ERPNext does not directly provide APC's required sales-demand FIFO reservation workflow.
- APC COA remains necessary as APC's customer-facing certificate layer, even though ERPNext Quality Inspection stores quality test approval.
