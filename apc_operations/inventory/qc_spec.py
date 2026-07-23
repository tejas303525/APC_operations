# Copyright (c) 2026, APC and contributors
"""Helpers for optional min/max specification limits on QC test rows."""

from __future__ import annotations

from frappe.utils import flt


def optional_spec_float(value) -> float | None:
	"""Return None when a spec limit is unset; preserve 0 as a valid limit."""
	if value is None or value == "":
		return None
	return flt(value)


def has_spec_limit(value) -> bool:
	return optional_spec_float(value) is not None
