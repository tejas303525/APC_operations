app_name = "apc_operations"
app_title = "APC Operations"
app_publisher = "APC"
app_description = "APC Operations System for Shipping, Transportation, QC, Security, and Production"
app_email = "admin@apc.com"
app_license = "MIT"
app_version = "0.0.1"
required_apps = ["erpnext"]

# Feature flag for legacy operational dashboards.
# Set to True to keep the legacy *_dashboard pages visible to all roles.
# When False, the renamed *_dashboard_legacy pages are restricted to
# System Manager (the JSON role list does the actual hiding).
APC_LEGACY_DASHBOARDS_ENABLED = False

# Global asset injection — shared console router + CSS used by all four
# operational consoles (Transportation, Shipping, Security, QC).
app_include_js = [
	"/assets/apc_operations/js/qc_spec.js",
	"/assets/apc_operations/js/console_router.js",
	"/assets/apc_operations/js/console_delivery_helpers.js?v=20260530",
	"/assets/apc_operations/js/job_order_delete.js",
	"/assets/apc_operations/js/apc_security_checklist.js",
]

app_include_css = [
	"/assets/apc_operations/css/console.css",
]

# Inject delivery-date badge helpers into console page scripts (runs on each getpage).
page_js = {
	"security-console": "public/js/console_delivery_helpers.js",
	"qc-console": "public/js/console_delivery_helpers.js",
	"transportation-console": "public/js/console_delivery_helpers.js",
	"shipping-console": "public/js/console_delivery_helpers.js",
	"my-work-today": "public/js/console_delivery_helpers.js",
}

# Note: a single ``scheduler_events`` dict definition wins in Python; the
# previous file had two separate assignments which silently dropped the
# first one's reminder jobs. P5 collapses them into one dict and adds
# the Zoho invoice-status pull job.


# Doc Events
doc_events = {
    "Job Order": {
        "validate": "apc_operations.shipping.doctype.job_order.job_order.validate_job_order",
        "on_submit": "apc_operations.shipping.doctype.job_order.job_order.on_submit_job_order",
    },
    "Shipping Booking": {
        "on_update": "apc_operations.shipping.shipping_booking_events.on_booking_update",
        "on_submit": "apc_operations.shipping.shipping_booking_events.on_booking_submit",
    },
    "Transport Schedule": {
        "on_update": "apc_operations.shipping.transport_events.on_transport_update",
        "on_submit": "apc_operations.shipping.transport_events.on_transport_submit",
    },
    "Gate Pass": {
        "on_update": "apc_operations.shipping.gate_pass_events.on_gate_pass_update",
    },
    "Delivery Order": {
        "on_update": "apc_operations.shipping.delivery_order_events.on_delivery_order_update",
    },
    "Security Draft Delivery Note": {
        "on_update": [
            "apc_operations.shipping.security_events.on_security_draft_dn_update",
            "apc_operations.shipping.delivery_order_events.on_security_draft_dn_update",
        ],
    },
    "Security Inspection": {
        "on_update": "apc_operations.shipping.security_events.on_security_inspection_update",
    },
    "QC Report Request": {
        "on_update": [
            "apc_operations.shipping.security_events.on_qc_report_request_update",
            "apc_operations.shipping.delivery_order_events.on_qc_report_request_update_hook",
        ],
    },
    "Loading Delivery Note": {
        "after_insert": "apc_operations.shipping.delivery_order_events.on_loading_delivery_note_after_insert",
        "on_update": [
            "apc_operations.shipping.security_events.on_loading_delivery_note_update",
            "apc_operations.shipping.delivery_order_events.on_loading_delivery_note_update_hook",
        ],
    },
    "Pre-Check Clearance": {
        "on_update": "apc_operations.shipping.delivery_order_events.on_pre_check_clearance_update",
    },
    "Production Order": {
        "validate": "apc_operations.production.production_order_events.on_validate",
        "on_update": "apc_operations.production.production_order_events.on_update",
        "on_submit": "apc_operations.production.production_order_events.on_submit",
    },
    # Batch Allocation System Events
    "APC Sales Demand": {
        "on_update": "apc_operations.sales.doctype.apc_sales_demand.apc_sales_demand.on_update_sales_demand",
    },
    "APC Batch": {
        "on_update": "apc_operations.inventory.doctype.apc_batch.apc_batch.on_update_batch",
        "after_insert": "apc_operations.inventory.doctype.apc_batch.apc_batch.after_insert_batch",
    },
    "APC COA": {
        "on_update": "apc_operations.inventory.doctype.apc_coa.apc_coa.on_update_coa",
    },
    "Quality Inspection": {
        "on_update": "apc_operations.inventory.doctype.apc_coa.apc_coa.sync_apc_coa_from_quality_inspection",
        "on_submit": "apc_operations.inventory.doctype.apc_coa.apc_coa.sync_apc_coa_from_quality_inspection",
    },
    "APC Batch Allocation": {
        "on_submit": "apc_operations.sales.doctype.apc_batch_allocation.apc_batch_allocation.on_submit_allocation",
    },
    "APC Production Requirement": {
        "on_update": "apc_operations.production.doctype.apc_production_requirement.apc_production_requirement.on_update_production_requirement",
    },
    "APC Dispatch Order": {
        "on_submit": "apc_operations.dispatch.doctype.apc_dispatch_order.apc_dispatch_order.on_submit_dispatch",
    },
}

# Scheduled Jobs (merged from previous two scheduler_events definitions
# in this file). Reminder + NAS retry + Zoho invoice-status pull.
scheduler_events = {
    "hourly": [
        "apc_operations.shipping.reminders.check_upcoming_cutoffs",
        "apc_operations.shipping.reminders.check_pending_pull_outs",
        "apc_operations.shipping.reminders.check_pending_cros",
        "apc_operations.shipping.reminders.check_pending_transport",
    ],
    "daily": [
        "apc_operations.shipping.reminders.send_daily_dashboard_summary",
        "apc_operations.shipping.reminders.check_transportation_daily_summary",
        "apc_operations.services.nas_service.retry_failed_nas_saves",
    ],
    "cron": {
        "0 8 * * *": [
            "apc_operations.shipping.reminders.send_morning_reminders",
        ],
        "0 16 * * *": [
            "apc_operations.shipping.reminders.send_evening_reminders",
        ],
        "0 */6 * * *": [
            "apc_operations.shipping.reminders.check_unassigned_transport_reminder",
            "apc_operations.shipping.reminders.check_unbooked_transport_over_24h",
        ],
        "*/15 * * * *": [
            "apc_operations.shipping.services.zoho_dispatch_sync_service.pull_zoho_invoice_status",
        ],
    },
}

# Notifications
notification_config = "apc_operations.shipping.notifications.get_notification_config"

# Fixtures
fixtures = [
    {
        "dt": "Role",
        "filters": [
            ["name", "in", [
                "Shipping Manager",
                "Shipping User",
                "Transportation Manager",
                "Transportation User",
                "Security Manager",
                "Security User",
                "Quality Manager",
                "Quality User",
                "Receivables Manager",
                "Receivables User",
                "Production Manager",
                "Production User",
            ]]
        ]
    },
    {
        "dt": "Workflow",
        "filters": [
            ["name", "in", [
                "Shipping Booking Workflow",
                "Transport Schedule Workflow",
                "Security Inspection Workflow",
            ]]
        ]
    },
    {
        "dt": "Custom HTML Block",
        "filters": [
            ["name", "in", [
                "Transportation Dashboard",
            ]]
        ]
    },
    {
        "dt": "Custom Field",
    },
    {
        "dt": "Property Setter",
    },
    {
        "dt": "Custom DocPerm",
        "filters": [
            ["parent", "in", ["Currency", "Vehicle", "Driver"]]
        ]
    }
]

# Permission Query Conditions
permission_query_conditions = {
    "Shipping Booking": "apc_operations.shipping.permissions.get_shipping_booking_permission",
    "Transport Schedule": "apc_operations.shipping.permissions.get_transport_permission",
}

# Has Permission
has_permission = {
    "Shipping Booking": "apc_operations.shipping.permissions.has_shipping_booking_permission",
    "Transport Schedule": "apc_operations.shipping.permissions.has_transport_permission",
}

# Before Tests
before_tests = "apc_operations.tests.test_utils.before_test"

# Whitelisted Methods
whitelisted_methods = {
    # Shipping/Trasnport
    "get_todays_actions": "apc_operations.shipping.api.get_todays_actions",
    "get_dashboard_data": "apc_operations.shipping.api.get_dashboard_data",
    "get_shipping_dashboard_data": "apc_operations.shipping.api.get_shipping_dashboard_data",
    "create_transport_from_booking": "apc_operations.shipping.doctype.shipping_booking.shipping_booking.create_transport_from_booking",
    "update_transport_status": "apc_operations.transportation.doctype.transport_schedule.transport_schedule.update_transport_status",
    "assign_vehicle_and_driver": "apc_operations.transportation.doctype.transport_schedule.transport_schedule.assign_vehicle_and_driver",
    "get_overdue_assignments": "apc_operations.transportation.doctype.transport_schedule.transport_schedule.get_overdue_assignments",
    "create_security_inspection_from_job_order": "apc_operations.security.doctype.security_inspection.security_inspection.create_security_inspection_from_job_order",
    "create_security_inspection_from_draft_dn": "apc_operations.security.doctype.security_inspection.security_inspection.create_security_inspection_from_draft_dn",
    "get_pending_inspections": "apc_operations.security.doctype.security_inspection.security_inspection.get_pending_inspections",
    "get_qc_pending_inspections": "apc_operations.security.doctype.security_inspection.security_inspection.get_qc_pending_inspections",
    "get_pending_qc_requests": "apc_operations.shipping.doctype.qc_report_request.qc_report_request.get_pending_qc_requests",
    "get_pending_receivables": "apc_operations.shipping.doctype.loading_delivery_note.loading_delivery_note.get_pending_receivables",
    "get_security_dashboard_data": "apc_operations.shipping.api.get_security_dashboard_data",
    "get_production_dashboard_data": "apc_operations.production.api.get_production_dashboard_data",
    "get_production_calendar_data": "apc_operations.production.api.get_production_calendar_data",
    "evaluate_production_order": "apc_operations.production.api.evaluate_production_order",
    # QC Dashboard APIs
    "get_qc_dashboard_stats": "apc_operations.services.dashboard.get_qc_dashboard_stats",
    # Batch Allocation System APIs
    "get_available_batches": "apc_operations.inventory.doctype.apc_batch.apc_batch.get_available_batches",
    "calculate_free_stock": "apc_operations.inventory.doctype.apc_batch.apc_batch.calculate_free_stock",
    "allocate_batches_fifo": "apc_operations.services.batch_allocation.allocate_batches_fifo",
    "release_allocation": "apc_operations.sales.doctype.apc_batch_allocation.apc_batch_allocation.release_allocation",
    "calculate_production_requirement": "apc_operations.services.batch_allocation.calculate_production_requirement",
    "create_production_requirement_if_shortage": "apc_operations.services.batch_allocation.create_production_requirement_if_shortage",
    "validate_dispatch_batches": "apc_operations.services.batch_allocation.validate_dispatch_batches",
    "attach_batch_coas_to_dispatch": "apc_operations.services.batch_allocation.attach_batch_coas_to_dispatch",
    "create_dispatch_from_allocation": "apc_operations.dispatch.doctype.apc_dispatch_order.apc_dispatch_order.create_dispatch_from_allocation",
    "create_batch_allocation": "apc_operations.sales.doctype.apc_batch_allocation.apc_batch_allocation.create_batch_allocation",
    # Zoho Integration APIs
    "get_sales_orders": "apc_operations.zoho.api.get_sales_orders",
    "import_pfi": "apc_operations.zoho.api.import_pfi",
    "create_job_order_from_pfi": "apc_operations.zoho.api.create_job_order_from_pfi",
    "sync_delivery_note": "apc_operations.zoho.api.sync_delivery_note",
    "get_inventory": "apc_operations.zoho.api.get_inventory",
    "get_batch_details": "apc_operations.zoho.api.get_batch_details",
    "get_job_orders": "apc_operations.zoho.api.get_job_orders",
    "update_job_order_status": "apc_operations.zoho.api.update_job_order_status",
    "get_transport_schedule": "apc_operations.zoho.api.get_transport_schedule",
    "get_shipping_booking": "apc_operations.zoho.api.get_shipping_booking",
}

# Jinja Environment
jinja = {
    "methods": [
        "apc_operations.shipping.jinja_filters.get_cutoff_status",
        "apc_operations.shipping.jinja_filters.get_transport_status_color",
    ]
}

# User Data Protection
user_data_fields = [
    {
        "doctype": "Shipping Booking",
        "fields": ["owner", "modified_by"],
    },
    {
        "doctype": "Transport Schedule",
        "fields": ["owner", "modified_by"],
    },
]

# Boot Session
def set_bootinfo(bootinfo):
    bootinfo.apc_shipping_settings = {
        "cutoff_reminder_days": 3,
        "pullout_reminder_days": 2,
        "transport_reminder_days": 1,
    }
