# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class ProductionCapacityConfiguration(Document):
    def validate(self):
        self.validate_date_range()
        self.warn_overlapping_rules()

    def validate_date_range(self):
        if self.applies_to and self.applies_from:
            if getdate(self.applies_to) < getdate(self.applies_from):
                frappe.throw(_("Applies To must be on or after Applies From."))

    def warn_overlapping_rules(self):
        """Warn (do not block) if another active rule overlaps the same category window."""
        if not self.active or not self.production_category or not self.applies_from:
            return

        filters = {
            "production_category": self.production_category,
            "active": 1,
            "name": ["!=", self.name or ""],
        }

        candidates = frappe.get_all(
            "Production Capacity Configuration",
            filters=filters,
            fields=["name", "applies_from", "applies_to"],
        )

        my_from = getdate(self.applies_from)
        my_to = getdate(self.applies_to) if self.applies_to else None

        for row in candidates:
            other_from = getdate(row.applies_from) if row.applies_from else None
            other_to = getdate(row.applies_to) if row.applies_to else None

            if not other_from:
                continue

            overlap_start = max(my_from, other_from)
            overlap_end_candidates = [d for d in [my_to, other_to] if d]
            overlap_end = min(overlap_end_candidates) if overlap_end_candidates else None

            if overlap_end is None or overlap_start <= overlap_end:
                frappe.msgprint(
                    _(
                        "Rule {0} already covers an overlapping window for category {1}. "
                        "Both rules remain active; the most recent applies_from wins."
                    ).format(row.name, self.production_category),
                    indicator="orange",
                    alert=True,
                )


def get_active_capacity(category, on_date):
    """Return the most-specific active Production Capacity Configuration for the
    given category on the given date, or None if no rule applies.

    Selection rules:
      1. active = 1
      2. applies_from <= on_date
      3. applies_to is NULL/empty or applies_to >= on_date
      4. Pick the row with the latest applies_from (most recent rule wins).
    """
    if not category or not on_date:
        return None

    on_date = getdate(on_date)

    rows = frappe.db.sql(
        """
        SELECT name, production_category, max_quantity_per_day, uom, applies_from, applies_to
        FROM `tabProduction Capacity Configuration`
        WHERE active = 1
          AND production_category = %(category)s
          AND applies_from <= %(on_date)s
          AND (applies_to IS NULL OR applies_to = '' OR applies_to >= %(on_date)s)
        ORDER BY applies_from DESC, modified DESC
        LIMIT 1
        """,
        {"category": category, "on_date": on_date},
        as_dict=True,
    )

    return rows[0] if rows else None


def get_all_active_capacities(on_date):
    """Return the latest active rule per category on the given date.

    Used for dashboards / calendar to show "current limits" without N queries.
    """
    if not on_date:
        return {}

    on_date = getdate(on_date)

    rows = frappe.db.sql(
        """
        SELECT pcc.name, pcc.production_category, pcc.max_quantity_per_day, pcc.uom,
               pcc.applies_from, pcc.applies_to
        FROM `tabProduction Capacity Configuration` pcc
        INNER JOIN (
            SELECT production_category, MAX(applies_from) AS latest_from
            FROM `tabProduction Capacity Configuration`
            WHERE active = 1
              AND applies_from <= %(on_date)s
              AND (applies_to IS NULL OR applies_to = '' OR applies_to >= %(on_date)s)
            GROUP BY production_category
        ) latest
          ON latest.production_category = pcc.production_category
         AND latest.latest_from = pcc.applies_from
        WHERE pcc.active = 1
        """,
        {"on_date": on_date},
        as_dict=True,
    )

    by_category = {}
    for row in rows:
        existing = by_category.get(row.production_category)
        if not existing:
            by_category[row.production_category] = row
    return by_category
