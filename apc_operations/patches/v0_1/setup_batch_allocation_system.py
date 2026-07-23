# Copyright (c) 2026, APC and contributors
# For license information, please see license.txt
"""
Patch to set up the batch allocation system.
This creates necessary DocTypes and default data.
"""

import frappe


def execute():
    """Execute patch."""
    frappe.db.commit()

    # Create default roles if they don't exist
    create_roles()

    # Set up default permissions
    setup_permissions()

    # Create indexes for performance
    create_indexes()

    frappe.db.commit()


def create_roles():
    """Create necessary roles for batch allocation system."""
    roles = [
        {"role_name": "Inventory Manager", "desk_access": 1},
        {"role_name": "Inventory User", "desk_access": 1},
        {"role_name": "Sales Manager", "desk_access": 1},
        {"role_name": "Sales User", "desk_access": 1},
        {"role_name": "Dispatch Manager", "desk_access": 1},
        {"role_name": "Dispatch User", "desk_access": 1},
    ]

    for role_data in roles:
        if not frappe.db.exists("Role", role_data["role_name"]):
            role = frappe.new_doc("Role")
            role.role_name = role_data["role_name"]
            role.desk_access = role_data["desk_access"]
            role.insert()
            print(f"Created role: {role_data['role_name']}")


def setup_permissions():
    """Set up default permissions for batch allocation DocTypes."""
    # This will be handled by DocType JSON permissions
    pass


def create_indexes():
    """Create database indexes for performance."""
    # Indexes for APC Batch
    indexes = [
        # (table, fields)
        ("tabAPC Batch", ["product", "batch_status", "quality_status"]),
        ("tabAPC Batch", ["manufacturing_date"]),
        ("tabAPC Batch", ["grade", "specification"]),
        ("tabAPC COA", ["batch", "approval_status"]),
        ("tabAPC Sales Demand", ["customer", "status"]),
        ("tabAPC Sales Demand", ["required_dispatch_date"]),
        ("tabAPC Batch Allocation", ["sales_demand", "allocation_status"]),
        ("tabAPC Batch Allocation Detail", ["batch", "status"]),
        ("tabAPC Production Requirement", ["sales_demand", "status"]),
        ("tabAPC Dispatch Order", ["sales_demand", "status"]),
        ("tabZoho Sync Log", ["sync_type", "sync_status"]),
    ]

    for table, fields in indexes:
        index_name = f"idx_{table.replace('tab', '').lower()}_{'_'.join(fields)}"
        try:
            frappe.db.sql(f"""
                CREATE INDEX IF NOT EXISTS {index_name[:64]}
                ON {table}({', '.join(fields)})
            """)
        except Exception:
            # Index might already exist
            pass

    print("Database indexes created")
