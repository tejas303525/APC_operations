# Job Order: Import vs Export — Plan of Action

## Implementation status (codebase)

**Phases A–C (minimum shippable) and E1 (list indicator) are implemented** in the `apc_operations` app:

- **Job Order:** `commercial_movement` (Export / Import), `supplier`, `supplier_name`; Customer mandatory only for Export; `INCOTERM_RULES_IMPORT`; `get_incoterm_rule(incoterm, movement)`; primary `transport_schedule` is Outward (Export) or Inward (Import); transport creation / lookup / `create_inward_transport_schedule` aligned; Zoho PFI path sets Export.
- **Shipping Booking:** optional `supplier` / `supplier_name`; `validate_counterparty`; `generate_transportation()` creates **Inward** for Import Job Orders; `requires_transport_schedule_from_booking()` uses movement-aware incoterm rules.
- **Transportation API:** `_active_transport_for_job_order` filters by movement or explicit `transport_type`; inward import list restricted to **Import** Job Orders; export/local detail and SDDN helpers use the correct leg type.
- **Patch:** `backfill_job_order_commercial_movement_export` (guarded with `has_column`) sets legacy rows to Export.
- **Phase D (partial):** Inward Import console supports book transport + SDDN; `ensure_inward_follow_up_records` creates SDDN when vessel is Cleared and transport is booked; import Security Inspection can report to QC without Loading DN. E2–E3 (dashboards, permissions) remain deferred.

---

This document is the **master implementation plan**. It replaces the earlier exploratory analysis with **ordered work packages**, acceptance criteria, and file-level targets.

## 1. Goal

Support **two commercial modes** on the same Job Order DocType:

| Mode | APC role | Primary counterparty | Incoterm matrix |
|------|----------|----------------------|-----------------|
| **Export** (default, today) | Seller | Customer (buyer) | Existing seller-side rules |
| **Import** (new) | Buyer | Supplier (foreign seller) | New buyer-side rules |

**Non-goal for v1 (unless explicitly pulled in):** Full Zoho purchase-order sync, full inward security/QC parity with export, or finance in ERPNext.

---

## 2. What we will do (programme deliverables)

When this plan is executed end-to-end, the following will be true:

1. **Job Order form** — User selects **Export** or **Import** (default **Export**). Existing documents behave as Export after migration.
2. **Counterparty** — **Import** requires a **Supplier**; **Export** keeps **Customer** as today. Validation enforces the right party per mode.
3. **Incoterms** — `determine_booking_requirement()` applies **`INCOTERM_RULES`** for Export and a new **`INCOTERM_RULES_IMPORT`** for Import (not a naive string swap).
4. **Operational documents** — Auto-created **Transport Schedule** and **Shipping Booking** paths branch: Export → **Outward** / export patterns; Import → **Inward** (and shipping generation aligned) so import jobs do not silently spawn **Export Container** outward legs.
5. **Transportation console** — `_active_transport_for_job_order` (and related list logic) resolves the correct schedule when both types could exist (e.g. filter by `transport_type` per hub, not “latest modified” only).
6. **Tests** — Automated tests cover Import vs Export incoterm flags and at least one Import transport-creation path.
7. **Documentation** — This file stays the source of truth; `CLAUDE.md` or README updated only if you want ops-facing notes (optional).

**Note:** Core deliverables (1–6) are implemented in code; see **Implementation status** at the top of this file. Remaining items follow phases **D–E** below.

---

## 3. Phases and tasks

### Phase A — Data model and migration

| # | Task | Primary files | Done when |
|---|------|----------------|-----------|
| A1 | Add **`commercial_movement`** Select: `Export` \| `Import`, default **`Export`**, in list view / form early in `field_order`. | `job_order.json` | Field visible; new JOs default Export. |
| A2 | Add **`supplier`** Link → Supplier; **mandatory** if Import; **Customer** remains required for Export (or relax Customer on Import per product sign-off). | `job_order.json`, `job_order.py` `validate` | Save blocked if Import without supplier. |
| A3 | Patch: set **`commercial_movement = Export`** for all existing `tabJob Order` rows (idempotent). | `apc_operations/patches/…` | Migrate runs clean on production copy. |
| A4 | Optional: `supplier_name` read-only fetch from Supplier (mirror `customer_name`). | `job_order.json`, `job_order.py` | Display name on form/list. |

### Phase B — Import incoterm matrix and Job Order logic

| # | Task | Primary files | Done when |
|---|------|----------------|-----------|
| B1 | Add **`INCOTERM_RULES_IMPORT`** — same keys as supported incoterms today; values reflect **APC as buyer** and **supplier as seller** (freight, insurance, transport_arranged_by, shipping_arranged_by, flags, risk text, notes). Legal review optional but recommended for wording. | `job_order.py` | Each supported incoterm has an import row. |
| B2 | **`get_incoterm_rule(incoterm, movement)`** or **`get_incoterm_rules_for_doc(doc)`** — central selector used by Job Order and Shipping Booking. | `job_order.py` | Single source of truth. |
| B3 | **`determine_booking_requirement()`** — branch on `commercial_movement`; call `_apply_rule` with the correct dict. | `job_order.py` | Toggling movement + incoterm updates flags correctly. |
| B4 | **`validate_insurance_on_confirm()`** — still keyed off `insurance_required`; ensure import rules set flags consistently. | `job_order.py` | Import CIF/CIP etc. still enforce policy when required. |
| B5 | **Client script** — show/hide Customer vs Supplier section by movement; optional `frm.trigger` refresh on movement change. | `job_order.js` | Usable create flow without confusion. |

### Phase C — Automation (Transport Schedule, Shipping Booking, API)

| # | Task | Primary files | Done when |
|---|------|----------------|-----------|
| C1 | **`create_or_link_transport_schedule()`** — if Import + rules need APC tracking: create **`transport_type = Inward`** (and appropriate subtype / fields); if Export: keep current Outward behaviour. Set `Job Order.transport_schedule` to the **primary** leg for that mode. | `job_order.py` | Confirmed Import sea job does not get default Export Container outward from this path alone. |
| C2 | **`get_existing_transport_schedule()`** — resolve ambiguity: filter by `transport_type` matching movement **or** use explicit link fields if product chooses dual links (see Phase F optional). | `job_order.py` | No random TS when two exist. |
| C3 | **`ShippingBooking.generate_transportation()`** — Import → **Inward** TS; Export → current Outward + Export Container. | `shipping_booking.py` | CRO path matches Job Order mode. |
| C4 | **`requires_export_transport()`** → rename/generalise to **`requires_job_order_transport_from_booking()`** (or similar); use **`get_incoterm_rule`** with Job Order’s movement. | `shipping_booking.py` | Naming matches behaviour. |
| C5 | **`_active_transport_for_job_order`** — accept optional `transport_type` or read Job Order movement and pick matching TS (latest within that type). Update **`get_inward_import_list`** / export container helpers as needed. | `transportation/api.py` | Inward Import hub shows Import JOs with Inward TS even if an old Outward row exists. |

### Phase D — Inward follow-ups (security / payables)

| # | Task | Primary files | Done when |
|---|------|----------------|-----------|
| D1 | Workshop with ops: which documents apply for **import** (gate-in, receipt, inspection). | — | Ongoing — code path implemented; ops sign-off still useful. |
| D2 | **`ensure_inward_follow_up_records()`** — auto SDDN when Inward TS booked + vessel Cleared (sea). | `transport_schedule.py` | Implemented. |
| D3 | **`create_security_draft_delivery_note()`** — Inward transport type; gate pass **In** for inward. | `transport_schedule.py`, SDDN JSON | Implemented. |
| D4 | Inward Import console: book transport, SDDN, security inspection link. | `transportation_console.js`, `api.py` | Implemented. |
| D5 | Import **`report_to_qc`** without mandatory Loading DN. | `security_inspection.py` | Implemented. |

### Phase E — UX, dashboards, permissions

| # | Task | Primary files | Done when |
|---|------|----------------|-----------|
| E1 | Job Order list indicator (Export / Import). | `job_order.js` listview_settings | At-a-glance in list. |
| E2 | Transportation / shipping dashboards — optional filter or KPI split by **`commercial_movement`** (if data on JO is joined). | `shipping/api.py`, console JS | Ops can slice import vs export. |
| E3 | Permissions — restrict Import JOs by role if required. | `permissions.py`, DocType permissions | Matches policy. |

### Phase F — Optional / later

| F1 | **Zoho** — `create_job_order_from_pfi` stays Export-only; new endpoint or flag for purchase import when integration exists. | `zoho/api.py` | Documented. |
| F2 | **Dual links** on Job Order: `export_transport_schedule` / `import_transport_schedule` instead of overloaded `transport_schedule`. | `job_order.json`, patches, all readers | Clearer if you routinely run both legs on one JO. |

---

## 4. Execution order (recommended)

```
A (model + migration) → B (rules + form) → C (automation + API) → tests for A–C
        ↓
   D (security) only after ops sign-off
        ↓
   E (polish) in parallel with D where safe
        ↓
   F when needed
```

**Minimum shippable import support:** **A + B + C1–C3 + C5** (so import jobs get correct flags and correct TS direction; console does not lie).

---

## 5. Acceptance checklist (sign-off)

- [ ] New Job Order: default Export; unchanged behaviour vs today.
- [ ] Switch to Import: Supplier required; incoterm fields populate from **import** matrix.
- [ ] Confirm Import (sea): no spurious **Outward / Export Container** auto-TS from Job Order / Shipping Booking paths covered in C.
- [ ] Transportation inward list: correct TS association per §C5.
- [ ] Tests green: `bench run-tests` for Job Order (+ Shipping Booking if touched).

---

## 6. Appendix — Current behaviour (reference only)

- **Job Order** has no movement field; **Customer** is always the counterparty; **`INCOTERM_RULES`** assume APC sells.
- **`create_or_link_transport_schedule`** always **Outward**; **`generate_transportation`** always **Outward** + **Export Container**.
- **`ensure_outward_follow_up_records`** / SDDN creation assume **export** gate-out flow.
- **`_active_transport_for_job_order`** uses latest **modified** TS without filtering by `transport_type`.

---

## 7. Document control

| Version | Change |
|---------|--------|
| 2.0 | Rewritten as plan of action with phases and deliverables. |
| 1.0 | Prior codebase analysis format. |

**Owner:** APC Operations / engineering lead assigns phase owners and dates.
