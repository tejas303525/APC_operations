# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt

import frappe


def _has_role(user, *roles):
    """Return True if user has any of the given roles."""
    user_roles = frappe.get_roles(user)
    return bool(set(roles) & set(user_roles))


def get_shipping_booking_permission(user):
    """Permission query for Shipping Booking"""
    if not user:
        user = frappe.session.user

    if _has_role(user, "System Manager", "Shipping Manager", "Administrator"):
        return ""

    if _has_role(user, "Shipping User"):
        return f"(`tabShipping Booking`.owner = {frappe.db.escape(user)})"

    if _has_role(user, "Transportation Manager"):
        return "(`tabShipping Booking`.transport_status != 'Cancelled')"

    return "1=0"


def get_transport_permission(user):
    """Permission query for Transport Schedule"""
    if not user:
        user = frappe.session.user

    if _has_role(user, "System Manager"):
        return ""

    if _has_role(user, "Transportation Manager", "Transportation User"):
        return ""

    if _has_role(user, "Shipping Manager"):
        return "(`tabTransport Schedule`.transport_status != 'Cancelled')"

    if _has_role(user, "Security Manager", "Security User"):
        return (
            "`tabTransport Schedule`.name IN ("
            "SELECT DISTINCT `tabSecurity Inspection`.transportation_request "
            "FROM `tabSecurity Inspection` "
            "WHERE IFNULL(`tabSecurity Inspection`.transportation_request, '') != '' "
            "AND IFNULL(`tabSecurity Inspection`.docstatus, 0) != 2)"
        )

    return "1=0"


def has_shipping_booking_permission(doc, user):
    """Check if user has permission on Shipping Booking"""
    if _has_role(user, "System Manager", "Shipping Manager"):
        return True

    if doc.owner == user and _has_role(user, "Shipping User"):
        return True

    return False


def has_transport_permission(doc, user):
    """Check if user has permission on Transport Schedule"""
    if _has_role(user, "System Manager", "Transportation Manager", "Transportation User", "Shipping Manager"):
        return True

    if _has_role(user, "Security Manager", "Security User") and doc and getattr(doc, "name", None):
        return bool(
            frappe.db.exists(
                "Security Inspection",
                {"transportation_request": doc.name, "docstatus": ["!=", 2]},
            )
        )

    return False
