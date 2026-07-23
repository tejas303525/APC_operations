import frappe


FALLBACK_NOTIFICATION_EMAIL = "tejas303525@gmail.com"


def first_valid_email(candidate):
    if not candidate:
        return None
    valid = frappe.utils.validate_email_address(candidate, throw=False)
    if isinstance(valid, (list, tuple)):
        return valid[0] if valid else None
    return valid if isinstance(valid, str) and valid else None


def resolve_user_email(user_id):
    if not user_id:
        return None
    email = frappe.db.get_value("User", user_id, "email")
    return first_valid_email(email) or first_valid_email(user_id)


def role_user_emails(roles, fallback_email=FALLBACK_NOTIFICATION_EMAIL):
    if isinstance(roles, str):
        roles = [roles]

    rows = frappe.get_all(
        "Has Role",
        filters={"parenttype": "User", "role": ["in", roles]},
        fields=["parent"],
        distinct=True,
    )

    emails = []
    for row in rows:
        email = resolve_user_email(row.parent)
        if email:
            emails.append(email)

    if not emails:
        fallback = first_valid_email(fallback_email)
        if fallback:
            emails.append(fallback)

    return list(dict.fromkeys(emails))
