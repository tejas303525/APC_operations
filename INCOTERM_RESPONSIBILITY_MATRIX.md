# APC Operations — Incoterm Responsibility Matrix

This document reflects the **implemented rules** in:

- `INCOTERM_RULES` — Export (APC = **seller**)
- `INCOTERM_RULES_IMPORT` — Import (APC = **buyer**)

Source: `apc_operations/shipping/doctype/job_order/job_order.py`

---

## Legend

| Term | Export | Import |
|------|--------|--------|
| **APC role** | Seller / exporter | Buyer / importer |
| **Counterparty** | Customer (buyer) | Supplier (foreign seller) |
| **“Customer” in Job Order fields** | Buyer | Supplier (same option label in the UI) |
| **Auto TS (JO)** | Transport Schedule created when Job Order is **Confirmed** and `transport_required = 1` |
| **Auto SB (JO, Sea)** | Shipping Booking when `shipping_required = 1` and **Mode of Transport = Sea** (not Road/Rail) |
| **Auto TS (SB/CRO)** | Transport Schedule when **CRO** is entered on Shipping Booking, only if `transport_arranged_by = APC` |

**Notes**

- **Auto TS (JO)** can still be created for coordination/security even when the counterparty arranges transport (e.g. Export EXW, Import FOB).
- **Auto TS (SB/CRO)** is blocked when inland transport is counterparty-arranged; you will see: *“Transport not auto-created… counterparty-arranged inland transport.”*
- **APC insurance policy on JO** = `insurance_required` forces policy fields when Job Order is Confirmed.
- DAP / DPU / DDP **Export**: insurance is APC’s commercial decision (`insurance_required = 0` on the form).

---

## Export (APC = seller)

| Incoterm | Counterparty | Main freight paid by | Marine insurance by | Inland transport to port arranged by | Vessel / sea booking arranged by | APC insurance policy on JO | Auto TS (JO) | Auto SB (JO, Sea) | Auto TS (SB/CRO) |
|----------|--------------|----------------------|---------------------|--------------------------------------|----------------------------------|----------------------------|--------------|-------------------|------------------|
| EXW | Customer (buyer) | Customer | Customer | Customer | N/A | No | Yes | No | No |
| FCA | Customer (buyer) | Customer | Customer | APC | Customer | No | Yes | No | Yes |
| FOB | Customer (buyer) | Customer | Customer | APC | Customer | No | Yes | Yes | Yes |
| CFR | Customer (buyer) | APC | Customer | APC | APC | No | Yes | Yes | Yes |
| CIF | Customer (buyer) | APC | APC | APC | APC | **Yes** | Yes | Yes | Yes |
| CPT | Customer (buyer) | APC | Customer | APC | APC | No | Yes | Yes | Yes |
| CIP | Customer (buyer) | APC | APC | APC | APC | **Yes** | Yes | Yes | Yes |
| DAP | Customer (buyer) | APC | APC* | APC | APC | No | Yes | Yes | Yes |
| DPU | Customer (buyer) | APC | APC* | APC | APC | No | Yes | Yes | Yes |
| DDP | Customer (buyer) | APC | APC* | APC | APC | No | Yes | Yes | Yes |

\*Insurance not forced on Job Order; APC may still arrange cover commercially.

### Export — risk transfer (summary)

| Incoterm | Risk transfers to buyer |
|----------|-------------------------|
| EXW | At seller's premises — goods made available |
| FCA | On delivery to buyer's nominated carrier at named place |
| FOB | On board vessel at port of loading |
| CFR | On board at POL (APC pays freight to POD) |
| CIF | On board at POL (APC pays freight + minimum insurance to POD) |
| CPT | On handover to first carrier (APC pays carriage to destination) |
| CIP | On handover to first carrier (APC pays carriage + all-risk insurance) |
| DAP | At named destination, ready for unloading |
| DPU | At named destination, after unloading |
| DDP | At named destination after import clearance |

---

## Import (APC = buyer)

| Incoterm | Counterparty | Main freight paid by | Marine insurance by | Pre-carriage / inland arranged by | Vessel / sea booking arranged by | APC insurance policy on JO | Auto TS (JO) | Auto SB (JO, Sea) | Auto TS (SB/CRO) |
|----------|--------------|----------------------|---------------------|-----------------------------------|----------------------------------|----------------------------|--------------|-------------------|------------------|
| EXW | Supplier | APC | APC | APC | N/A | No | Yes | No | Yes |
| FCA | Supplier | APC | APC | Supplier | APC | No | Yes | No | No |
| FOB | Supplier | APC | APC | Supplier | APC | No | Yes | Yes | No |
| CFR | Supplier | Supplier | APC | APC | Supplier | No | Yes | Yes | Yes |
| CIF | Supplier | Supplier | Supplier | APC | Supplier | No | Yes | Yes | Yes |
| CPT | Supplier | Supplier | APC | APC | Supplier | No | Yes | Yes | Yes |
| CIP | Supplier | Supplier | Supplier | APC | Supplier | No | Yes | Yes | Yes |
| DAP | Supplier | Supplier | Supplier | Supplier | Supplier | No | Yes | Yes | No |
| DPU | Supplier | Supplier | Supplier | Supplier | Supplier | No | Yes | Yes | No |
| DDP | Supplier | Supplier | Supplier | Supplier | Supplier | No | Yes | Yes | No |

### Import — risk transfer (summary)

| Incoterm | Risk transfers to APC (buyer) |
|----------|-------------------------------|
| EXW | At supplier's premises — goods made available |
| FCA | When supplier delivers to APC's nominated carrier |
| FOB | On board vessel at port of loading (supplier's country) |
| CFR | On board at POL; supplier pays freight to POD |
| CIF | On board at POL; supplier pays freight + minimum insurance to POD |
| CPT | On handover to first carrier; supplier pays carriage to destination |
| CIP | On handover to first carrier; supplier pays carriage + all-risk insurance |
| DAP | At named destination ready for unloading |
| DPU | At named destination after unloading |
| DDP | At named destination after import clearance |

---

## System automation quick reference

| Movement | Typical leg | `transport_type` | Created from |
|----------|-------------|------------------|--------------|
| Export | Outward to port / customer | Outward (+ Export Container for sea) | Job Order confirm; Shipping Booking CRO (if APC inland) |
| Import | Inward from port / supplier | Inward | Job Order confirm; Shipping Booking CRO (if APC inland) |

---

## Related documentation

- [JOB_ORDER_IMPORT_VS_EXPORT_ANALYSIS.md](./JOB_ORDER_IMPORT_VS_EXPORT_ANALYSIS.md) — import vs export implementation plan
- [CLAUDE.md](../CLAUDE.md) (repo root) — outward movement and incoterm business direction

---

## Document control

| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2026-05-15 | Initial matrix from `INCOTERM_RULES` / `INCOTERM_RULES_IMPORT` |
