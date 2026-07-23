"""Shared status mapping for the APC console layer.

The four operational consoles (Transportation / Shipping / Security / QC)
need a single source of truth for translating internal DocType status
values into the human-friendly labels (and tones) shown in cards, modal
badges, and pending-count tiles.

All console APIs import from this module to avoid duplicating mapping
logic. UI label strings here intentionally match the labels listed in
``DESIGN_CONCEPT.md`` Sections 6, 7, 8, 9, and 11.
"""

from __future__ import annotations

from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Docs Status — Transport Schedule.transport_status -> Cleared / Uncleared
# ---------------------------------------------------------------------------

DOCS_STATUS_CLEARED = {"Delivered", "Completed"}

DOCS_STATUS_UNCLEARED = {
	"Draft",
	"Pending Assignment",
	"Scheduled",
	"Vehicle Assigned",
	"Driver Assigned",
	"Dispatched",
	"Picked Up",
	"Gate In",
	"In Transit",
}

DOCS_STATUS_HIDDEN = {"Cancelled"}


def docs_status_label(transport_status: str | None) -> str:
	if not transport_status:
		return "Uncleared"
	if transport_status in DOCS_STATUS_CLEARED:
		return "Cleared"
	if transport_status in DOCS_STATUS_HIDDEN:
		return "Hidden"
	return "Uncleared"


def docs_status_tone(label: str) -> str:
	return {"Cleared": "success", "Uncleared": "warn", "Hidden": "neutral"}.get(
		label, "neutral"
	)


# ---------------------------------------------------------------------------
# Vessel Status — Shipping Booking.vessel_status
# ---------------------------------------------------------------------------

VESSEL_STATUSES = {"In Transit", "Berthed", "Cleared"}


def vessel_status_label(value: str | None) -> str:
	return value or "In Transit"


def vessel_status_tone(value: str | None) -> str:
	return {
		"In Transit": "info",
		"Berthed": "warn",
		"Cleared": "success",
	}.get(value or "", "neutral")


# ---------------------------------------------------------------------------
# Transport Booked — Transport Schedule.transport_status -> bool
# ---------------------------------------------------------------------------

TRANSPORT_BOOKED_EXCLUDES = {"Draft", "Pending Assignment", "Cancelled"}


def is_transport_booked(transport_status: str | None) -> bool:
	if not transport_status:
		return False
	return transport_status not in TRANSPORT_BOOKED_EXCLUDES


# ---------------------------------------------------------------------------
# DO generation allowlist (Section 7.7 of DESIGN_CONCEPT.md — narrow list)
# ---------------------------------------------------------------------------

DO_GENERATION_ALLOWED_TRANSPORT_STATUSES = {
	"Vehicle Assigned",
	"Driver Assigned",
	"Scheduled",
	"Dispatched",
}


def can_generate_delivery_order(transport_status: str | None) -> bool:
	return (transport_status or "") in DO_GENERATION_ALLOWED_TRANSPORT_STATUSES


# ---------------------------------------------------------------------------
# SDDN security_status
# ---------------------------------------------------------------------------

SDDN_STATUSES = [
	"Draft",
	"Pending Review",
	"Approved",
	"Rejected",
	"Sent to Security",
	"Pending Verification",
	"Verified",
	"On Hold",
	"LDN Created",
	"Sent to QC",
	"Completed",
]

# Legacy values mapped to their replacements in the console UI.
SDDN_LEGACY_EQUIVALENTS = {
	"Approved": "Verified",
	"Pending Review": "Pending Verification",
}

SDDN_PENDING_STATUSES = {"Draft", "Pending Review", "Pending Verification", "Sent to Security"}
SDDN_VERIFIED_STATUSES = {"Verified", "Approved", "LDN Created", "Sent to QC", "Completed"}


def sddn_display_label(value: str | None) -> str:
	if not value:
		return "Draft"
	return SDDN_LEGACY_EQUIVALENTS.get(value, value)


def sddn_status_tone(value: str | None) -> str:
	canonical = sddn_display_label(value)
	return {
		"Draft": "neutral",
		"Sent to Security": "info",
		"Pending Verification": "warn",
		"Verified": "success",
		"On Hold": "warn",
		"Rejected": "danger",
		"LDN Created": "success",
		"Sent to QC": "info",
		"Completed": "success",
	}.get(canonical, "neutral")


def is_sddn_pending(value: str | None) -> bool:
	if not value:
		return True
	return value in SDDN_PENDING_STATUSES


def is_sddn_verified(value: str | None) -> bool:
	return (value or "") in SDDN_VERIFIED_STATUSES


# ---------------------------------------------------------------------------
# LDN delivery_note_status — map to design labels (Section 11)
# ---------------------------------------------------------------------------

# Design labels (UI):
LDN_UI_LABELS = [
	"Draft",
	"Created",
	"Sent to QC",
	"QC Pending",
	"QC Cleared",
	"QC Rejected",
	"COA Generated",
	"Dispatch Confirmed",
	"Completed",
]

# DB-status -> UI label. Anything outside this map shows the raw value.
LDN_DB_TO_UI = {
	"Draft": "Draft",
	"Pending QC": "QC Pending",
	"Batch Allocation Pending": "QC Pending",
	"Batch Allocated": "QC Pending",
	"QC Cleared": "QC Cleared",
	"QC Rejected": "QC Rejected",
	"COA Attached": "COA Generated",
	"Ready for Receivables": "COA Generated",
	"Reported to Receivables": "Completed",
	"Loading Completed": "Completed",
	"Dispatch Confirmed": "Dispatch Confirmed",
	"Completed": "Completed",
	"Cancelled": "Cancelled",
}


def ldn_display_label(value: str | None) -> str:
	if not value:
		return "Draft"
	return LDN_DB_TO_UI.get(value, value)


def ldn_status_tone(value: str | None) -> str:
	label = ldn_display_label(value)
	return {
		"Draft": "neutral",
		"Created": "info",
		"Sent to QC": "info",
		"QC Pending": "warn",
		"QC Cleared": "success",
		"QC Rejected": "danger",
		"COA Generated": "success",
		"Dispatch Confirmed": "success",
		"Completed": "success",
		"Cancelled": "neutral",
	}.get(label, "neutral")


# ---------------------------------------------------------------------------
# QC status — QC Report Request.qc_status
# ---------------------------------------------------------------------------

QC_STATUSES = ["Pending QC", "QC Cleared", "QC Rejected"]


def qc_status_label(value: str | None) -> str:
	if not value:
		return "Pending QC"
	return value


def qc_status_tone(value: str | None) -> str:
	return {
		"Pending QC": "warn",
		"QC Cleared": "success",
		"QC Rejected": "danger",
	}.get(value or "", "neutral")


# ---------------------------------------------------------------------------
# COA status (display-only — derived from APC COA.status / approval_status)
# ---------------------------------------------------------------------------

COA_DISPLAY_PENDING = "Pending"
COA_DISPLAY_GENERATED = "Generated"
COA_DISPLAY_UPLOADED = "Uploaded"


def coa_display_label(coa_doc: dict | None) -> str:
	"""Map an APC COA doc to one of: Pending / Generated / Uploaded."""
	if not coa_doc:
		return COA_DISPLAY_PENDING
	status = (coa_doc.get("status") or "").strip()
	approval = (coa_doc.get("approval_status") or "").strip()
	has_pdf = bool(coa_doc.get("coa_pdf"))
	if status in {"Approved", "Passed"} or approval == "Approved":
		return COA_DISPLAY_UPLOADED if has_pdf else COA_DISPLAY_GENERATED
	if status in {"Draft", "Pending Testing", ""} and not has_pdf:
		return COA_DISPLAY_PENDING
	if has_pdf:
		return COA_DISPLAY_UPLOADED
	return COA_DISPLAY_GENERATED


def coa_status_tone(label: str) -> str:
	return {
		COA_DISPLAY_PENDING: "warn",
		COA_DISPLAY_GENERATED: "info",
		COA_DISPLAY_UPLOADED: "success",
	}.get(label, "neutral")


# ---------------------------------------------------------------------------
# DO display
# ---------------------------------------------------------------------------


def do_display_label(do_doc: dict | None) -> str:
	if not do_doc:
		return "Pending"
	status = (do_doc.get("status") or "").strip()
	docstatus = do_doc.get("docstatus", 0)
	if docstatus == 2:
		return "Cancelled"
	if status in {"Submitted", "In Transit"}:
		return "Generated"
	if status == "Delivered":
		return "Completed"
	return "Pending"


def do_status_tone(label: str) -> str:
	return {
		"Pending": "neutral",
		"Generated": "info",
		"Completed": "success",
		"Cancelled": "danger",
	}.get(label, "neutral")


# ---------------------------------------------------------------------------
# Transport booking display (Pending / Booked)
# ---------------------------------------------------------------------------


def transport_booking_label(transport_status: str | None) -> str:
	return "Booked" if is_transport_booked(transport_status) else "Pending"


def transport_booking_tone(transport_status: str | None) -> str:
	return "success" if is_transport_booked(transport_status) else "warn"


# ---------------------------------------------------------------------------
# Common badge helper for API responses
# ---------------------------------------------------------------------------


def badge(label: str, tone: str = "neutral") -> dict[str, str]:
	return {"label": label, "tone": tone}


def badges_for_transport(transport_status: str | None) -> list[dict[str, str]]:
	docs = docs_status_label(transport_status)
	return [
		badge(transport_booking_label(transport_status), transport_booking_tone(transport_status)),
		badge(docs, docs_status_tone(docs)),
	]


def filter_visible_transport_statuses(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
	"""Drop rows whose transport_status is in DOCS_STATUS_HIDDEN."""
	return [r for r in rows if (r.get("transport_status") or "") not in DOCS_STATUS_HIDDEN]
