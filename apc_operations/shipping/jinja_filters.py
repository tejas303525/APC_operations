# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import getdate, today, date_diff


def get_cutoff_status(cutoff_date):
    """Get visual status for cutoff date"""
    if not cutoff_date:
        return "No Date"

    days = date_diff(getdate(cutoff_date), today())

    if days < 0:
        return "Overdue"
    elif days <= 2:
        return "Critical"
    elif days <= 7:
        return "Warning"
    else:
        return "OK"


def get_transport_status_color(status):
    """Get color for transport status"""
    colors = {
        "Pending": "gray",
        "Scheduled": "orange",
        "In Progress": "blue",
        "Completed": "green",
        "Cancelled": "red"
    }
    return colors.get(status, "gray")


def get_days_until(date_string):
    """Get days until a specific date"""
    if not date_string:
        return None
    return date_diff(getdate(date_string), today())


def format_currency(amount, currency="USD"):
    """Format amount as currency"""
    return f"{currency} {amount:,.2f}"
