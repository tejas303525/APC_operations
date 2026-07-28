// Shipping Dashboard Client Scripts
// Handles dashboard interactions, action buttons, and real-time updates

frappe.provide('apc.shipping');

apc.shipping.Dashboard = class ShippingDashboard {
    constructor() {
        this.refresh_interval = null;
        this.init();
    }

    init() {
        this.setup_event_listeners();
        this.refresh_dashboard_data();
        this.start_auto_refresh();
    }

    setup_event_listeners() {
        // Action button handlers
        $(document).on('click', '.btn-book-vessel', () => {
            this.open_book_vessel_dialog();
        });

        $(document).on('click', '.btn-enter-cro', () => {
            frappe.set_route('List', 'Shipping Booking', {
                cro_status: 'Pending'
            });
        });

        $(document).on('click', '.btn-generate-transport', () => {
            this.open_generate_transport_dialog();
        });

        $(document).on('click', '.btn-view-timeline', () => {
            this.open_shipment_timeline_dialog();
        });

        $(document).on('click', '.btn-notify-payables', () => {
            this.notify_payables_team();
        });
    }

    start_auto_refresh() {
        // Refresh every 5 minutes
        this.refresh_interval = setInterval(() => {
            this.refresh_dashboard_data();
        }, 300000);
    }

    refresh_dashboard_data() {
        frappe.call({
            method: 'apc_operations.shipping.api.get_dashboard_data',
            callback: (r) => {
                if (r.message) {
                    this.update_dashboard_ui(r.message);
                }
            }
        });
    }

    update_dashboard_ui(data) {
        // Update counts
        if (data.counts) {
            this.update_count_cards(data.counts);
        }

        // Update lists
        if (data.upcoming_vessels) {
            this.render_upcoming_vessels(data.upcoming_vessels);
        }
    }

    update_count_cards(counts) {
        // This will be handled by frappe's built-in number cards
        // Just trigger a refresh
        frappe.app.trigger('number_card_refresh');
    }

    render_upcoming_vessels(vessels) {
        // Render upcoming vessels in a table if container exists
        const container = $('.upcoming-vessels-container');
        if (!container.length) return;

        let html = `
            <table class="table table-bordered">
                <thead>
                    <tr>
                        <th>Vessel</th>
                        <th>Cutoff</th>
                        <th>Days Left</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
        `;

        vessels.forEach(vessel => {
            const status_class = vessel.days_until_cutoff <= 2 ? 'text-danger' : 'text-warning';
            html += `
                <tr>
                    <td><a href="/app/vessel-booking/${vessel.name}">${vessel.vessel_name}</a></td>
                    <td>${frappe.format_date(vessel.cutoff_date)}</td>
                    <td class="${status_class}">${vessel.days_until_cutoff}</td>
                    <td>${vessel.transport_status}</td>
                </tr>
            `;
        });

        html += '</tbody></table>';
        container.html(html);
    }

    open_book_vessel_dialog() {
        const dialog = new frappe.ui.Dialog({
            title: __('Book Vessel'),
            fields: [
                {
                    fieldname: 'shipping_line',
                    label: __('Shipping Line'),
                    fieldtype: 'Link',
                    options: 'Shipping Line',
                    reqd: 1
                },
                {
                    fieldname: 'vessel_name',
                    label: __('Vessel Name'),
                    fieldtype: 'Data',
                    reqd: 1
                },
                {
                    fieldname: 'container_type',
                    label: __('Container Type'),
                    fieldtype: 'Select',
                    options: '20FT Standard\n40FT Standard\n40FT High Cube\n20FT Reefer\n40FT Reefer',
                    reqd: 1
                },
                {
                    fieldname: 'container_number',
                    label: __('Container Number'),
                    fieldtype: 'Data',
                    description: __('Physical container ID (e.g. MSCU1234567)')
                },
                {
                    fieldname: 'container_count',
                    label: __('Container Count'),
                    fieldtype: 'Int',
                    default: 1,
                    reqd: 1
                },
                {
                    fieldname: 'port_of_loading',
                    label: __('Port of Loading'),
                    fieldtype: 'Link',
                    options: 'Port',
                    reqd: 1
                },
                {
                    fieldname: 'port_of_discharge',
                    label: __('Port of Discharge'),
                    fieldtype: 'Link',
                    options: 'Port',
                    reqd: 1
                },
                {
                    fieldname: 'cargo_description',
                    label: __('Cargo Description'),
                    fieldtype: 'Small Text',
                    reqd: 1
                },
                {
                    fieldname: 'cargo_weight',
                    label: __('Cargo Weight (MT)'),
                    fieldtype: 'Float',
                    reqd: 1
                },
                {
                    fieldname: 'is_dangerous_goods',
                    label: __('Dangerous Goods'),
                    fieldtype: 'Check'
                },
                {
                    fieldname: 'vessel_date',
                    label: __('Vessel Date (ETD)'),
                    fieldtype: 'Date',
                    reqd: 1
                },
                {
                    fieldname: 'cutoff_date',
                    label: __('Cutoff Date'),
                    fieldtype: 'Date',
                    reqd: 1
                },
                {
                    fieldname: 'pull_out_date',
                    label: __('Pull Out Date'),
                    fieldtype: 'Date',
                    reqd: 1
                },
                {
                    fieldname: 'freight_rate',
                    label: __('Freight Rate'),
                    fieldtype: 'Currency',
                    reqd: 1
                },
                {
                    fieldname: 'currency',
                    label: __('Currency'),
                    fieldtype: 'Link',
                    options: 'Currency',
                    default: 'USD'
                }
            ],
            primary_action_label: __('Create Shipping Booking'),
            primary_action: (values) => {
                frappe.call({
                    method: 'apc_operations.shipping.api.quick_create_vessel_booking',
                    args: {
                        data: values
                    },
                    callback: (r) => {
                        if (r.message && r.message.success) {
                            frappe.show_alert({
                                message: __('Shipping Booking {0} created', [r.message.name]),
                                indicator: 'green'
                            });
                            dialog.hide();
                            frappe.set_route('Form', 'Shipping Booking', r.message.name);
                        }
                    }
                });
            }
        });

        dialog.show();
    }

    open_generate_transport_dialog() {
        // Get Shipping Bookings with CRO details and no linked transport.
        frappe.call({
            method: 'frappe.client.get_list',
            args: {
                doctype: 'Shipping Booking',
                filters: {
                    cro_status: 'Generated',
                    linked_transport: ['in', ['', null]]
                },
                fields: ['name', 'cro_number', 'vessel_name', 'cutoff_date', 'container_count'],
                limit_page_length: 50
            },
            callback: (r) => {
                const cros = r.message || [];

                if (!cros.length) {
                    frappe.msgprint(__('No Shipping Bookings pending transport generation'));
                    return;
                }

                const dialog = new frappe.ui.Dialog({
                    title: __('Generate Transport Schedules'),
                    fields: [
                        {
                            fieldname: 'cros',
                            label: __('Select Shipping Bookings'),
                            fieldtype: 'Table',
                            cannot_add_rows: true,
                            in_place_edit: true,
                            data: cros.map(cro => ({
                                name: cro.name,
                                cro_number: cro.cro_number,
                                vessel_name: cro.vessel_name,
                                cutoff_date: cro.cutoff_date,
                                container_count: cro.container_count,
                                selected: 0
                            })),
                            fields: [
                                {
                                    fieldname: 'selected',
                                    label: __('Select'),
                                    fieldtype: 'Check',
                                    in_list_view: 1
                                },
                                {
                                    fieldname: 'cro_number',
                                    label: __('CRO Number'),
                                    fieldtype: 'Data',
                                    in_list_view: 1,
                                    read_only: 1
                                },
                                {
                                    fieldname: 'vessel_name',
                                    label: __('Vessel'),
                                    fieldtype: 'Data',
                                    in_list_view: 1,
                                    read_only: 1
                                },
                                {
                                    fieldname: 'cutoff_date',
                                    label: __('Cutoff'),
                                    fieldtype: 'Date',
                                    in_list_view: 1,
                                    read_only: 1
                                }
                            ]
                        }
                    ],
                    primary_action_label: __('Generate Transport'),
                    primary_action: (values) => {
                        const selected = values.cros
                            .filter(row => row.selected)
                            .map(row => row.name);

                        if (!selected.length) {
                            frappe.msgprint(__('Please select at least one Shipping Booking'));
                            return;
                        }

                        frappe.call({
                            method: 'apc_operations.shipping.api.bulk_generate_transport',
                            args: {
                                cro_list: JSON.stringify(selected)
                            },
                            callback: (r) => {
                                const results = r.message || [];
                                const success = results.filter(res => res.status === 'success').length;
                                const failed = results.filter(res => res.status === 'error').length;

                                frappe.show_alert({
                                    message: __(`Transport generated: ${success} success, ${failed} failed`),
                                    indicator: failed ? 'orange' : 'green'
                                });

                                dialog.hide();
                                this.refresh_dashboard_data();
                            }
                        });
                    }
                });

                dialog.show();
            }
        });
    }

    open_shipment_timeline_dialog() {
        const dialog = new frappe.ui.Dialog({
            title: __('View Shipment Timeline'),
            fields: [
                {
                    fieldname: 'shipment',
                    label: __('Select Shipment'),
                    fieldtype: 'Link',
                    options: 'Shipping Booking',
                    reqd: 1,
                    get_query: () => ({
                        filters: {
                            docstatus: 1
                        }
                    })
                }
            ],
            primary_action_label: __('View Timeline'),
            primary_action: (values) => {
                dialog.hide();
                this.show_timeline_view(values.shipment);
            }
        });

        dialog.show();
    }

    show_timeline_view(shipment_name) {
        frappe.call({
            method: 'apc_operations.shipping.api.get_shipment_timeline',
            args: {
                shipment_name: shipment_name
            },
            callback: (r) => {
                const timeline = r.message || [];

                let html = '<div class="shipment-timeline">';
                timeline.forEach(event => {
                    html += `
                        <div class="timeline-item">
                            <div class="timeline-date">${frappe.format_date(event.date)}</div>
                            <div class="timeline-event">
                                <span class="timeline-badge ${event.status === 'Completed' ? 'bg-success' : 'bg-warning'}">
                                    ${event.status}
                                </span>
                                <span class="timeline-text">${event.event}</span>
                            </div>
                        </div>
                    `;
                });
                html += '</div>';

                const dialog = new frappe.ui.Dialog({
                    title: __('Shipment Timeline'),
                    fields: [
                        {
                            fieldname: 'timeline_html',
                            fieldtype: 'HTML',
                            options: html
                        }
                    ]
                });

                dialog.show();
            }
        });
    }

    notify_payables_team() {
        frappe.confirm(
            __('Send notification to payables team for all pending shipment charges?'),
            () => {
                frappe.call({
                    method: 'apc_operations.shipping.notifications.notify_payables_bulk',
                    callback: (r) => {
                        frappe.show_alert({
                            message: __('Notifications sent to payables team'),
                            indicator: 'green'
                        });
                    }
                });
            }
        );
    }
};

// Initialize dashboard on page load
$(document).ready(() => {
    if (frappe.get_route_str() === 'workspace/shipping') {
        apc.shipping.dashboard = new apc.shipping.Dashboard();
    }
});
