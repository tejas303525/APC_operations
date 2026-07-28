# Security Inspection → QC Report Workflow

**App:** APC Operations  
**Last Updated:** 2026-05-05  
**Scope:** Security Inspection creation, checklist, QC linkage, Loading DN, and Receivables

---

## 1. Document Chain Overview

```
Transport Schedule (Scheduled / Vehicle Assigned / Driver Assigned)
    │
    │  auto-creates on_update
    ▼
Security Draft Delivery Note  (SDDN-YYYY-#####)
    │  status: Pending Review
    │
    │  Security user clicks "Open Inspection Checklist" button
    ▼
Security Inspection  (SEC-INS-YYYY-#####)
    │  status: Draft → Pending Checklist
    │
    │  Security officer ticks all Required checklist items
    │  status auto-advances to: Checklist Completed
    │
    │  Security officer clicks "Report to QC" button
    ▼
QC Report Request  (QC-REQ-YYYY-#####)
    │  qc_status: Pending QC
    │  Email sent to: Quality Manager, Quality User
    │
    │  QC officer opens QC Report Request
    │  Sets qc_status to: QC Cleared  OR  QC Rejected
    ▼
Security Inspection status updates automatically
    │  QC Cleared  → security_status: QC Cleared
    │  QC Rejected → security_status: QC Rejected
    │
    │  (if QC Cleared) Security officer clicks "Create Loading DN" button
    ▼
Loading Delivery Note  (LDN-YYYY-#####)
    │  delivery_note_status: QC Cleared
    │  receivables_status: Pending Receivables
    │
    │  Accounts team opens Loading DN
    │  Clicks "Report to Receivables" button
    ▼
Loading Delivery Note  → Reported to Receivables
Security Inspection   → Reported to Receivables
```

---

## 2. Document: Security Draft Delivery Note

**DocType:** `Security Draft Delivery Note`  
**Naming:** `SDDN-YYYY-#####`  
**Auto-created by:** `Transport Schedule.create_security_draft_delivery_note()`  
**Location:** `transportation/doctype/transport_schedule/transport_schedule.py`

### Key Fields

| Field | Type | Source |
|---|---|---|
| `transport_schedule` | Link → Transport Schedule | set on creation |
| `job_order` | Link → Job Order | copied from Transport Schedule.job_order |
| `customer` | Link → Customer | fetched from transport_schedule |
| `outward_type` | Select | fetched from transport_schedule |
| `vehicle`, `driver`, `transporter` | Links | fetched from transport_schedule |
| `security_status` | Select | Draft → Pending Review → Approved → Rejected |
| `gate_out_status` | Select | Pending Security Review → Approved for Gate Out → Gate Out Completed |

### Status Transitions

```
Draft
  ↓  (auto-set on creation)
Pending Review
  ↓  (security user clicks "Open Inspection Checklist")
Approved            ← Draft DN is now linked to an active Security Inspection
```

### "Open Inspection Checklist" Button (JS)

Defined in: `security/doctype/security_draft_delivery_note/security_draft_delivery_note.js`

**Logic:**
1. Checks if a `Security Inspection` already exists for `transportation_request = this.transport_schedule` and `docstatus != 2`
2. If yes → opens that existing inspection
3. If no → calls `create_security_inspection_from_draft_dn(draft_dn_name)` → creates new inspection → opens it

---

## 3. Document: Security Inspection

**DocType:** `Security Inspection`  
**Naming:** `SEC-INS-YYYY-#####`  
**Location:** `security/doctype/security_inspection/`

### Key Fields

| Field | Type | Notes |
|---|---|---|
| `job_order` | Link → Job Order | |
| `transportation_request` | Link → Transport Schedule | only set if TRN is not cancelled |
| `shipping_booking` | Link → Shipping Booking | |
| `customer` | Link → Customer | |
| `inspection_type` | Select | Container / ISO Tank / Tanker / Trailer / Local Delivery / Export Container |
| `inspection_date` | Date | |
| `security_status` | Select | see status list below |
| `qc_status` | Select | Not Sent / Pending QC / QC Cleared / QC Rejected |
| `checklist_items` | Table → Security Checklist | auto-seeded on `before_insert` |
| `qc_report_request` | Link → QC Report Request | set when Report to QC is clicked |
| `loading_delivery_note` | Link → Loading Delivery Note | set when Loading DN is created |

### Security Status Transitions

```
Draft
  ↓  checklist items exist
Pending Checklist
  ↓  all required checklist items ticked
Checklist Completed
  ↓  click "Report to QC" button
Reported to QC
  ↓  QC Report Request qc_status = QC Cleared (auto-synced)
QC Cleared
  ↓  click "Create Loading DN" button
Loading DN Created
  ↓  Loading DN "Report to Receivables" clicked (auto-synced)
Reported to Receivables
  ↓  (manual close)
Completed
```

### Checklist Auto-Seeding

On every new `Security Inspection`, `before_insert` seeds the following items automatically:

| Code | Item | Required |
|---|---|---|
| A-1 | Vehicle parked in designated area | Yes |
| A-2 | Vehicle type and purpose verified | Yes |
| A-3 | Quantity to load/offload confirmed | Yes |
| A-4 | Vehicle number recorded | Yes |
| A-5 | Driver name and details verified | Yes |
| A-6 | Driver EID collected and log book maintained | Yes |
| A-7 | Sending and receiving parties verified | Yes |
| A-8 | Material name matched with documents | Yes |
| A-9 | Gross/Tare/Net weight captured | No |
| B-1 | Vehicle exterior visually in good condition | Yes |
| B-2 | Vehicle interior in good condition | Yes |
| B-3 | Fire extinguishers available | Yes |
| B-4 | Spark arrestor available at exhaust | Yes |
| B-5 | Vehicle covered properly | Yes |
| B-6 | Hand brake applied and wheel chock used | Yes |
| B-7 | Vehicle engine switched off | Yes |
| B-8 | Driver wearing mandatory PPE | Yes |
| L-1 | Manholes opened | No |
| L-2 | Earthing done | No |
| L-3 | Hoses connected with camlock tie | No |
| L-4 | Pump rotation and flow checked | No |
| L-5 | Valves lined up | No |
| L-6 | Suitable PPE and harness available | No |
| L-7 | Watcher available for tanker overflow | No |
| L-8 | ST level confirmed to prevent overflow | No |
| L-9 | Tank number for load/offload verified | No |
| C-1 | Completion: Hose and earthing disconnected | No |
| C-2 | Completion: Manholes closed | No |
| C-3 | Completion: Vehicle safety lock points checked | No |
| C-4 | Completion: Final visual inspection completed | No |

> Items marked **Required = Yes** must be ticked before status can advance to `Checklist Completed`.

### Action Buttons (JS)

Defined in: `security/doctype/security_inspection/security_inspection.js`

| Button | Visible When | What It Does |
|---|---|---|
| **Report to QC** | status = `Checklist Completed`, no QC Request yet | Calls `report_to_qc()` → creates QC Report Request → advances status |
| **Create Loading DN** | `qc_status = QC Cleared`, no Loading DN yet | Calls `create_loading_delivery_note()` → creates Loading DN |
| **View QC Report** | QC Report Request exists | Opens linked QC Report Request |
| **View Loading DN** | Loading DN exists | Opens linked Loading Delivery Note |

---

## 4. Document: QC Report Request

**DocType:** `QC Report Request`  
**Naming:** `QC-REQ-YYYY-#####`  
**Location:** `shipping/doctype/qc_report_request/`  
**Created by:** `SecurityInspection.report_to_qc()`

### How the Link is Created

```python
# security_inspection.py → report_to_qc()

qc_request = frappe.new_doc("QC Report Request")
qc_request.security_inspection = self.name     # ← links back to parent inspection
qc_request.job_order            = self.job_order
qc_request.requested_by         = frappe.session.user
qc_request.requested_on         = now()
qc_request.qc_status            = "Pending QC"
qc_request.insert()

self.qc_report_request = qc_request.name       # ← inspection stores the QC ref
self.security_status   = "Reported to QC"
self.qc_status         = "Pending QC"
self.save()
```

### Key Fields

| Field | Type | Notes |
|---|---|---|
| `security_inspection` | Link → Security Inspection | required — the source |
| `job_order` | Link → Job Order | fetched from security_inspection |
| `loading_delivery_note` | Link → Loading Delivery Note | optional, can be linked later |
| `qc_status` | Select | Pending QC / QC Cleared / QC Rejected |
| `qc_checked_by` | Link → User | auto-set when cleared |
| `qc_checked_on` | Datetime | auto-set when cleared |
| `qc_remarks` | Text Editor | QC officer notes, especially on rejection |

### What Happens When QC Officer Updates qc_status

Handled by: `QCReportRequest.on_update()` → `update_security_inspection()`

**If QC Cleared:**
```
QC Report Request.qc_status = "QC Cleared"
    ↓  on_update fires
Security Inspection.qc_status        → QC Cleared
Security Inspection.security_status  → QC Cleared
Security Inspection.qc_checked_by    → current user
Security Inspection.qc_checked_on    → now()
    (if Loading DN already linked)
Loading Delivery Note.delivery_note_status → QC Cleared
    ↓  email sent to Security Manager, Security User
"QC Cleared for SEC-INS-YYYY-#####. You can now create Loading DN."
```

**If QC Rejected:**
```
QC Report Request.qc_status = "QC Rejected"
    ↓  on_update fires
Security Inspection.qc_status        → QC Rejected
Security Inspection.security_status  → QC Rejected
    (if Loading DN already linked)
Loading Delivery Note.delivery_note_status → Cancelled
    ↓  email sent to Security Manager, Security User
"QC REJECTED for SEC-INS-YYYY-#####. Action required."
```

---

## 5. Document: Loading Delivery Note

**DocType:** `Loading Delivery Note`  
**Naming:** `LDN-YYYY-#####`  
**Location:** `shipping/doctype/loading_delivery_note/`  
**Created by:** `SecurityInspection.create_loading_delivery_note()`

### Gate Condition

Loading DN **cannot be created** unless:
- `SecurityInspection.qc_status == "QC Cleared"`

Any attempt before this throws:
> `QC clearance is required before creating Loading Delivery Note`

### Data Copied from Security Inspection

| Loading DN Field | Source |
|---|---|
| `security_inspection` | inspection.name |
| `job_order` | inspection.job_order |
| `transportation_request` | inspection.transportation_request |
| `customer` | inspection.customer |
| `vehicle`, `driver` | inspection.vehicle / driver |
| `container_number`, `seal_number` | inspection.container_number / seal_number |
| `material_description`, `quantity`, `uom` | inspection.material/quantity/uom |
| `loading_date` | today() |
| `delivery_note_status` | "QC Cleared" |
| `receivables_status` | "Pending Receivables" |

### Status Transitions

```
QC Cleared
  ↓  accounts team clicks "Report to Receivables"
Reported to Receivables  → email sent to Accounts Manager / Accounts User
  ↓  (manual)
Completed
```

---

## 6. Status Synchronisation Map

Shows which document updates which, and via what mechanism:

```
Security Inspection  ──on_update──►  QC Report Request
    (sync_to_qc_report)                 .qc_status = inspection.qc_status

QC Report Request    ──on_update──►  Security Inspection
    (update_security_inspection)         .qc_status / .security_status / .qc_checked_by / .qc_checked_on

QC Report Request    ──on_update──►  Loading Delivery Note  (if linked)
    (update_security_inspection)         .delivery_note_status → QC Cleared or Cancelled

Loading Delivery Note──on_update──►  Security Inspection
    (on_loading_delivery_note_update)    .receivables_status
                                         .security_status → Reported to Receivables
```

---

## 7. Dashboard KPI Counters

| Box | DocType Queried | Filter |
|---|---|---|
| Vehicles at Gate | Security Inspection | gate_in_time set, gate_out_time not set, not cancelled/completed, docstatus != 2 |
| Pending Container Checklists | Security Inspection | security_status = Pending Checklist, docstatus != 2 |
| ISO Checks Pending | Security Inspection | inspection_type in ISO Tank/Tanker, not cancelled, docstatus != 2 |
| Weightment Slips Pending | Security Inspection | no weighment_slip, status in Pending Checklist/Checklist Completed/Reported to QC, docstatus != 2 |
| QC Reports Pending | QC Report Request | qc_status = Pending QC |
| Loading DNs To Issue | Loading Delivery Note | delivery_note_status not in Completed/Cancelled |
| Draft DNs from Transportation | Security Draft Delivery Note | security_status = Pending Review |
| Receivables Notifications Pending | Loading Delivery Note | receivables_status = Pending Receivables, delivery_note_status in QC Cleared/Ready for Receivables |

> **Note:** All Security Inspection queries use `docstatus != 2` to exclude cancelled documents.

---

## 8. Roles and Access

| Role | Can Do |
|---|---|
| Security Manager | Full access to Security Inspection, Draft DN, Checklist, read QC |
| Security User | Create/edit Security Inspection, Draft DN; read QC |
| Quality Manager | Full access to QC Report Request; read Security Inspection |
| Quality User | Create/edit QC Report Request; read Security Inspection |
| Accounts Manager | Read/write Loading DN; trigger Report to Receivables |
| Transportation Manager | Read-only on Security Inspection, Draft DN |

---

## 9. Known Gaps / Pending Work

| Gap | Description | Priority |
|---|---|---|
| **Print Format — Loading DN** | No custom print format exists; Frappe uses generic layout. The actual delivery note (with company header, buyer/consignee block, item table, signature area) needs a Jinja HTML print format. | High |
| **Print Format — Security Checklist** | No printable checklist format matching the APC paper form (Sections A, B, Loading, Completion, signatures). | High |
| **Print Format — Draft DN** | No custom print format. | Medium |
| **Loading DN — items child table** | Current Loading DN has only flat fields (material_description, quantity, uom). Multiple items/batches cannot be captured. Needs a child table. | Medium |
| **QC Report — batch/COA linkage** | QC Report Request does not link to APC Batch or APC COA. Batch-level QC traceability is incomplete. | Medium |
| **Weightment Slip** | Weighment Slip DocType exists but is not auto-created from Security Inspection. Gate section has a `weighment_slip` link but it is manually set. | Low |

---

## 10. File Reference

| Purpose | File |
|---|---|
| Security Inspection controller | `security/doctype/security_inspection/security_inspection.py` |
| Security Inspection form buttons | `security/doctype/security_inspection/security_inspection.js` |
| Security Checklist schema | `security/doctype/security_checklist/security_checklist.json` |
| Draft DN form button | `security/doctype/security_draft_delivery_note/security_draft_delivery_note.js` |
| QC Report Request controller | `shipping/doctype/qc_report_request/qc_report_request.py` |
| Loading Delivery Note controller | `shipping/doctype/loading_delivery_note/loading_delivery_note.py` |
| Cross-document status sync hooks | `shipping/security_events.py` |
| Dashboard API (KPI counts + queue) | `shipping/api.py → get_security_dashboard_data()` |
| Security Dashboard JS | `shipping/page/security_dashboard/security_dashboard.js` |
| Doc event registrations | `hooks.py` |
