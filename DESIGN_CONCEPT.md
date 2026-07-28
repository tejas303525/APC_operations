# Design Concept — Page-on-Page Console Redesign

**Scope:** Transportation, Shipping, Security, QC
**Date:** 2026-05-11
**Owner:** APC Operations
**Status:** Approved design — implementation pending

---

## 1. Why the redesign

The current dashboards (`shipping-dashboard`, `security-dashboard`, `Transportation-dashboard`) follow a single-page "everything visible at once" pattern — KPI strip + focus items + pipeline + milestones + recent CROs + recent JOs all stacked on one page. Operationally, users only need one slice at a time (the inward vs outward question, the pending-CRO question, the pending-DO question).

The redesign collapses each module into a **hub screen with 2–3 large buttons**. Clicking a button pushes a sub-screen onto an in-page stack with a back arrow. Clicking a row pushes a detail screen (or opens a small dialog for short forms like "Enter QC"). No URL changes, no full-page reloads — pure SPA inside one Frappe Page per module.

---

## 2. Module boundaries (corrected)

Each console lives in its own module so the codebase stays clean and ownership is obvious.

| Console | Module | Page folder |
|---|---|---|
| Transportation Console | Transportation | `apc_operations/transportation/page/transportation_console/` |
| Shipping Console | Shipping | `apc_operations/shipping/page/shipping_console/` |
| Security Console | Security | `apc_operations/security/page/security_console/` |
| QC Console | Quality *(new module)* | `apc_operations/quality/page/qc_console/` |

`modules.txt` gets one new line: `Quality`.

---

## 3. Shared SPA helper

New file: `apc_operations/public/js/console_router.js`

A tiny screen-stack router that every console reuses. A "screen" is just `{ title, render($root, router) }`. `router.push(screen)` shows it, `router.pop()` goes back, breadcrumb stays in sync.

Registered globally via `hooks.py`:

```python
app_include_js = [
    "/assets/apc_operations/js/console_router.js",
]
```

CSS for the consoles (cards, hub buttons, breadcrumb, badges) lives in `apc_operations/public/css/console.css`, also added to `hooks.py` via `app_include_css`.

---

## 4. Transportation Console

### Screen tree

```
transportation-console
└── Hub
    ├── [ A. Inward ]
    │     └── Inward Hub
    │           ├── [ Inward Import ] → List of inward-import Job Orders
    │           │     └── Row click → Detail screen:
    │           │           JO No, ETA, Docs Status (Cleared / Uncleared),
    │           │           Vessel Status (Berthed / In Transit / Cleared)
    │           └── [ Inward Land ]   → List of inward-land Job Orders
    │                 └── Row click → Detail screen:
    │                       JO details, Pull-out date, Status,
    │                       Origin → Destination
    │
    └── [ B. Outward Export ]
          └── Outward Hub
                (Sticky banner showing pending counts:
                 "X pending Transport Bookings", "Y pending Delivery Orders")
                ├── [ Local Deliveries ] → List
                │     └── Row click → Detail screen:
                │           JO, vehicle, driver, delivery location,
                │           scheduled date, status
                └── [ Export Containers ] → List
                      └── Row click → Detail screen:
                            JO → CRO number (fetched from Shipping Booking)
                            CRO date, Line, POL/POD, Vessel, SI cutoff,
                            Gate cutoff, Pull-out date
                            ▸ Transport booked? (Yes/No badge)
                            ▸ If booked → "Generate DO" button (manual)
                            ▸ DO Ready badge once generated
```

### Field sources

| Display field | Source |
|---|---|
| Docs Status (Cleared / Uncleared) | Derived from `Transport Schedule.transport_status` (see mapping in §11) |
| Vessel Status (Berthed / In Transit / Cleared) | **NEW field** `Shipping Booking.vessel_status` |
| ETA | `Transport Schedule.scheduled_delivery_date` |
| Pull-out date (export) | `Shipping Booking.pull_out_date` |
| CRO Number / Date | `Shipping Booking.cro_number`, `cro_date` |
| SI Cutoff / Gate Cutoff | `Shipping Booking.si_cutoff`, `gate_cutoff` |

### Backend APIs — new file `apc_operations/transportation/api.py`

```python
@frappe.whitelist()
def get_inward_import_list(): ...

@frappe.whitelist()
def get_inward_import_detail(job_order): ...

@frappe.whitelist()
def get_inward_land_list(): ...

@frappe.whitelist()
def get_inward_land_detail(job_order): ...

@frappe.whitelist()
def get_local_delivery_list(): ...

@frappe.whitelist()
def get_local_delivery_detail(job_order): ...

@frappe.whitelist()
def get_export_container_list(): ...

@frappe.whitelist()
def get_export_container_detail(job_order): ...

@frappe.whitelist()
def get_transportation_pending_counts():
    # { "pending_transport_bookings": int, "pending_delivery_orders": int }
```

All return JSON-serialisable dicts. No DocType mutations.

---

## 5. Shipping Console — 3 buttons

### Screen tree

```
shipping-console
└── Hub (3 large buttons)
    ├── [ A. Pending Bookings ]
    │     → List of Shipping Bookings where vessel_name is not set
    │       Row click → Popup with JO/booking details
    │       Fields shown: JO, POL, POD, THC, TLUC, ED, Line, Vessel, ETD
    │
    ├── [ B. Pending CRO ]
    │     → List of Shipping Bookings where vessel_name is set
    │       AND cro_status NOT IN ('Generated', 'Issued')
    │       Row click → Same popup as above
    │
    └── [ C. Open CRO Schedule ]
          → List of Shipping Bookings where cro_status IN ('Generated', 'Issued')
            Fields shown: Line, SI Cutoff, Pull-out Date, Gate Cutoff,
                          Vessel, ETD, Container Count
```

### Backend APIs — extend `apc_operations/shipping/api.py`

```python
@frappe.whitelist()
def get_pending_bookings(): ...

@frappe.whitelist()
def get_pending_cros(): ...

@frappe.whitelist()
def get_open_cro_schedule(): ...

@frappe.whitelist()
def generate_delivery_order_for_export(job_order):
    """Server-side helper that backs the 'Generate DO' button
    in the Transportation Export Container detail screen."""
```

`generate_delivery_order_for_export`:
1. Resolves linked `Shipping Booking` and `Transport Schedule` from `job_order`.
2. Validates `Transport Schedule.transport_status` is in `{Vehicle Assigned, Driver Assigned, Scheduled, Dispatched}`.
3. Creates a `Delivery Order` populated from JO + booking (customer, addresses, ports, items).
4. Returns `{ "delivery_order": "<DO-name>" }`.

---

## 6. Security Console

### Screen tree

```
security-console
└── Hub
    ├── [ Pending Inspections ]
    │     → List of Security Inspections where security_status = "Pending Checklist"
    │       Row click → Detail screen with checklist items + Save
    │
    ├── [ Gate In / Gate Out ]
    │     → List of Gate Passes (Draft / Open) with quick gate-in / gate-out actions
    │
    └── [ Loading DN Queue ]
          → List of Loading Delivery Notes with status badges
            (QC status, COA verified, dispatch confirmed)
            Row click → Detail screen
```

### Backend APIs — new file `apc_operations/security/api.py`

```python
@frappe.whitelist()
def get_pending_inspections(): ...

@frappe.whitelist()
def get_gate_pass_queue(): ...

@frappe.whitelist()
def get_loading_dn_queue(): ...

@frappe.whitelist()
def get_inspection_detail(name): ...

@frappe.whitelist()
def get_loading_dn_detail(name): ...
```

---

## 7. QC Console — 2 buttons

### Screen tree

```
qc-console
└── Hub
    ├── [ A. New DO ]
    │     → List of Delivery Orders without a linked QC Report Request
    │       Row click → Dialog (frappe.ui.Dialog):
    │           - JO details (read-only)
    │           - Batch selector
    │           - QC parameters form
    │           - QC Status (Pending QC / QC Cleared / QC Rejected)
    │           - Remarks
    │           [ Save ]
    │           ↳ creates QC Report Request
    │           ↳ if QC Cleared → auto-create APC COA linked to batch
    │
    └── [ B. Pending DOs ]
          → List of Delivery Orders with existing QC Report Request
            grouped by qc_status (Pending QC / QC Cleared / QC Rejected)
```

### New module: `apc_operations/quality/`

```
apc_operations/quality/
├── __init__.py
├── api.py
└── page/
    └── qc_console/
        ├── __init__.py
        ├── qc_console.json
        ├── qc_console.js
        └── qc_console.css
```

### Backend APIs — `apc_operations/quality/api.py`

```python
@frappe.whitelist()
def get_new_dos_without_qc(): ...

@frappe.whitelist()
def get_pending_qc_dos(): ...

@frappe.whitelist()
def submit_qc_for_do(delivery_order, batch, qc_status, qc_remarks,
                    generate_coa=True):
    # 1. find or create QC Report Request linked to DO + batch
    # 2. write qc_status / qc_remarks / qc_checked_by / qc_checked_on
    # 3. if qc_status == "QC Cleared" and generate_coa:
    #       create APC COA via inventory.doctype.apc_coa.create_apc_coa_from_qc(...)
    #       link the COA back on the QC Report Request and the batch
```

A new helper goes into `apc_operations/inventory/doctype/apc_coa/apc_coa.py`:

```python
def create_apc_coa_from_qc(qc_report_request_name):
    """Create an APC COA from a cleared QC Report Request.
    Idempotent: returns existing COA if one already exists for the batch."""
```

The existing `hooks.py` mapping for `Quality Inspection -> sync_apc_coa_from_quality_inspection` stays untouched. This new helper is the DO-driven path.

---

## 8. DocType change — single, additive

**File:** `apc_operations/shipping/doctype/shipping_booking/shipping_booking.json`

Add to `field_order` (inside `vessel_details_section`):

```text
vessel_name
vessel_date
vessel_status        ← new
```

Add to `fields[]`:

```json
{
  "fieldname": "vessel_status",
  "fieldtype": "Select",
  "label": "Vessel Status",
  "options": "\nIn Transit\nBerthed\nCleared",
  "default": "In Transit",
  "in_list_view": 1
}
```

### Patch — new file `apc_operations/patches/v0_2/backfill_vessel_status.py`

```python
import frappe

def execute():
    frappe.db.sql("""
        UPDATE `tabShipping Booking`
        SET vessel_status = 'In Transit'
        WHERE IFNULL(vessel_status, '') = ''
    """)
```

Add to `patches.txt`:

```text
apc_operations.patches.v0_2.backfill_vessel_status
```

Then `bench --site apc.local migrate`.

---

## 9. Feature flag for the legacy dashboards

To keep rollback safe, the three existing dashboards stay in the codebase but are hidden:

**Renames:**
- `shipping/page/shipping_dashboard/` → `shipping_dashboard_legacy/` (also rename `page_name` and `name` in the `.json` to `shipping-dashboard-legacy`).
- `shipping/page/security_dashboard/` → `security_dashboard_legacy/`.
- `shipping/page/job_dashboard/` → `job_dashboard_legacy/`.

**Role gating:** restrict each legacy page to `System Manager` only.

**Flag in `hooks.py`:**

```python
APC_LEGACY_DASHBOARDS_ENABLED = False
```

**Workspace shortcuts** pointing to the old pages get removed; new workspace shortcuts point at:
- `/app/transportation-console`
- `/app/shipping-console`
- `/app/security-console`
- `/app/qc-console`

---

## 10. `hooks.py` changes (summary)

| Change | Location |
|---|---|
| `app_include_js` — `console_router.js` | new key |
| `app_include_css` — `console.css` | new key |
| `whitelisted_methods` — add all new APIs from §4 / §5 / §6 / §7 | extend existing dict around line 162 |
| `permission_query_conditions` | extend if Security / QC consoles need row-level filters |
| `doc_events` | unchanged |
| `scheduler_events` | unchanged |

---

## 11. Status mapping rules

### Inward Import "Docs Status" (from `Transport Schedule.transport_status`)

| `transport_status` | Docs Status |
|---|---|
| Delivered, Completed | Cleared |
| Draft, Pending Assignment, Scheduled | Uncleared |
| Vehicle Assigned, Driver Assigned, Dispatched, Picked Up, Gate In, In Transit | Uncleared |
| Cancelled | (hidden from list) |

### Inward Import "Vessel Status"

Driven directly by the new `Shipping Booking.vessel_status` field. No derivation.

### Export "Transport booked"

True when a linked `Transport Schedule` exists AND its `transport_status` is NOT in `{Draft, Pending Assignment, Cancelled}`.

### Export "DO ready"

True when a `Delivery Order` linked to the same Job Order exists with `docstatus != 2`.

---

## 12. File deliverables (complete list)

### New files

```
apc_operations/public/js/console_router.js
apc_operations/public/css/console.css

apc_operations/transportation/api.py
apc_operations/transportation/page/__init__.py
apc_operations/transportation/page/transportation_console/__init__.py
apc_operations/transportation/page/transportation_console/transportation_console.json
apc_operations/transportation/page/transportation_console/transportation_console.js
apc_operations/transportation/page/transportation_console/transportation_console.css

apc_operations/shipping/page/shipping_console/__init__.py
apc_operations/shipping/page/shipping_console/shipping_console.json
apc_operations/shipping/page/shipping_console/shipping_console.js
apc_operations/shipping/page/shipping_console/shipping_console.css

apc_operations/security/api.py
apc_operations/security/page/__init__.py
apc_operations/security/page/security_console/__init__.py
apc_operations/security/page/security_console/security_console.json
apc_operations/security/page/security_console/security_console.js
apc_operations/security/page/security_console/security_console.css

apc_operations/quality/__init__.py
apc_operations/quality/api.py
apc_operations/quality/page/__init__.py
apc_operations/quality/page/qc_console/__init__.py
apc_operations/quality/page/qc_console/qc_console.json
apc_operations/quality/page/qc_console/qc_console.js
apc_operations/quality/page/qc_console/qc_console.css

apc_operations/patches/v0_2/backfill_vessel_status.py
```

### Modified files

```
apc_operations/modules.txt                                  # +Quality
apc_operations/hooks.py                                     # app_include_*, whitelisted_methods
apc_operations/patches.txt                                  # +backfill_vessel_status
apc_operations/shipping/api.py                              # +3 endpoints + generate_delivery_order_for_export
apc_operations/shipping/doctype/shipping_booking/shipping_booking.json  # +vessel_status
apc_operations/inventory/doctype/apc_coa/apc_coa.py         # +create_apc_coa_from_qc helper
```

### Renamed (legacy → archived behind flag)

```
apc_operations/shipping/page/shipping_dashboard/   → shipping_dashboard_legacy/
apc_operations/shipping/page/security_dashboard/   → security_dashboard_legacy/
apc_operations/shipping/page/job_dashboard/        → job_dashboard_legacy/
```

---

## 13. Implementation order (reviewable in small steps)

1. **Shared SPA helper** — `console_router.js` + `console.css` + `hooks.py` `app_include_*`.
2. **DocType change + patch** — `Shipping Booking.vessel_status` field + `v0_2/backfill_vessel_status.py` + migrate.
3. **Quality module bootstrap** — create `quality/` folder + `__init__.py` + add `Quality` to `modules.txt`.
4. **Transportation Console** — `transportation/api.py` + page (hub → 4 sub-screens → popups).
5. **Shipping Console** — page + 3 new shipping APIs.
6. **QC Console** — page + `quality/api.py` + `create_apc_coa_from_qc` helper.
7. **Security Console** — page + `security/api.py`.
8. **Legacy retirement** — rename legacy page folders, role-gate to System Manager, remove workspace shortcuts, run `bench --site apc.local clear-cache && bench build`.

---

## 14. Roles & permissions

Each console page's `.json` `roles[]` block:

| Console | Roles |
|---|---|
| `transportation-console` | Transportation Manager, Transportation User, System Manager |
| `shipping-console` | Shipping Manager, Shipping User, System Manager |
| `security-console` | Security Manager, Security User, System Manager |
| `qc-console` | Quality Manager, Quality User, System Manager |

All roles already exist in the fixtures block in `hooks.py` (lines 106–125).

---

## 15. UX rules of thumb

- **List → detail = screen push** (back arrow, no modal).
- **Short forms (Enter QC, Generate DO confirm) = `frappe.ui.Dialog`**.
- **Sticky pending-counts banner** only on Outward Export hub and the legacy `Today's Actions` strip is gone everywhere else.
- **No KPI strips, no pipeline graphs, no focus items** on the new consoles — the user said "not all infos clustered in a single page". Stats are accessible by clicking a button that lists the underlying rows, not by stacking KPI cards.
- **Auto-refresh interval**: 5 minutes (same as today's `_start_auto_refresh` in `shipping_dashboard.js`).

---

## 16. Testing

New tests under `apc_operations/tests/`:

- `test_transportation_api.py` — covers all 9 transportation endpoints + the docs-status / vessel-status / transport-booked mappings.
- `test_shipping_console_api.py` — covers pending bookings / pending CROs / open CRO schedule / `generate_delivery_order_for_export` happy path + guard rails (raises when transport not yet booked).
- `test_qc_console_api.py` — covers `submit_qc_for_do` happy path and the auto-COA branch (asserts an APC COA was created and linked to the batch).
- `test_security_console_api.py` — covers all security endpoints.

Frappe test runner:

```bash
bench --site apc.local run-tests --app apc_operations
```

---

## 17. Open items (not in this design)

- Localization / i18n strings for the new consoles — use `__(...)` from the start.
- Mobile breakpoint — hub buttons go full-width below 720px; list rows collapse to a 2-line card.
- Audit-log of "Generate DO" clicks — recommend writing a `Comment` on the Job Order on each invocation.
- Zoho Books integration points are unaffected by this redesign.
