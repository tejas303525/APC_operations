// Client Script for Shipping Booking DocType

frappe.ui.form.on('Shipping Booking', {
    refresh: function(frm) {
        if (frm.doc.docstatus === 1) {
            if (frm.doc.transport_status !== 'Completed' && frm.doc.linked_transport) {
                frm.add_custom_button(__('View Transport'), () => {
                    frappe.set_route('Form', 'Transport Schedule', frm.doc.linked_transport);
                }, __('Actions'));
            }

            if (!frm.doc.linked_transport && frm.doc.cro_number) {
                frm.add_custom_button(__('Generate Transport'), () => {
                    frappe.confirm(
                        __('Generate a Transport Schedule for this booking?'),
                        () => {
                            frappe.call({
                                method: 'apc_operations.shipping.doctype.shipping_booking.shipping_booking.create_transport_from_booking',
                                args: { booking_name: frm.doc.name },
                                callback: function(r) {
                                    if (r.message && r.message.success) {
                                        frappe.show_alert({ message: __('Transport Schedule created'), indicator: 'green' });
                                        frm.reload_doc();
                                    }
                                }
                            });
                        }
                    );
                }, __('Actions'));
            }

            if (frm.doc.linked_dispatch) {
                frm.add_custom_button(__('View Security Dispatch'), () => {
                    frappe.set_route('Form', 'Security Dispatch', frm.doc.linked_dispatch);
                }, __('Actions'));
            }

            frm.add_custom_button(__('Shipment Timeline'), () => {
                frm.trigger('show_timeline');
            }, __('Actions'));
        }

        frm.trigger('update_indicators');
    },

    show_timeline: function(frm) {
        frappe.call({
            method: 'apc_operations.shipping.api.get_shipment_timeline',
            args: { shipment_name: frm.doc.name },
            callback: function(r) {
                if (r.message) {
                    let html = '<div class="timeline">';
                    r.message.forEach(event => {
                        html += `
                            <div class="timeline-item" style="margin-bottom:12px">
                                <div class="timeline-dot ${event.status === 'Completed' ? 'bg-success' : 'bg-warning'}"></div>
                                <div class="timeline-content">
                                    <h6>${event.event}</h6>
                                    <p class="text-muted">${frappe.format(event.date, { fieldtype: 'Date' })}</p>
                                    <span class="badge badge-${event.status === 'Completed' ? 'success' : 'warning'}">${event.status}</span>
                                </div>
                            </div>
                        `;
                    });
                    html += '</div>';

                    frappe.msgprint({
                        title: __('Shipment Timeline'),
                        message: html,
                        indicator: 'blue'
                    });
                }
            }
        });
    },

    update_indicators: function(frm) {
        if (frm.doc.transport_status === 'Completed') {
            frm.dashboard.set_headline_alert(__('Transport Completed'), 'success');
        } else if (frm.doc.transport_status === 'In Progress') {
            frm.dashboard.set_headline_alert(__('Transport In Progress'), 'orange');
        } else if (frm.doc.cutoff_date) {
            const days_left = frappe.datetime.get_day_diff(frm.doc.cutoff_date, frappe.datetime.now_date());
            if (days_left <= 3 && days_left > 0) {
                frm.dashboard.set_headline_alert(
                    __(`Cutoff in ${days_left} day(s) — URGENT`),
                    'red'
                );
            } else if (days_left <= 7) {
                frm.dashboard.set_headline_alert(
                    __(`Cutoff in ${days_left} days`),
                    'orange'
                );
            }
        }
    },

    freight_rate: function(frm) {
        frm.trigger('calculate_totals');
    },

    container_count: function(frm) {
        frm.trigger('calculate_totals');
    },

    calculate_totals: function(frm) {
        frm.set_value('total_freight_charges', (frm.doc.freight_rate || 0) * (frm.doc.container_count || 0));
    },

    cutoff_date: function(frm) {
        if (frm.doc.cutoff_date) {
            frm.set_value('pull_out_date', frappe.datetime.add_days(frm.doc.cutoff_date, -3));
        }
        frm.trigger('update_indicators');
    },

    is_dangerous_goods: function(frm) {
        frm.toggle_display(['dg_class', 'un_number'], frm.doc.is_dangerous_goods);
    },

    cro_number: function(frm) {
        if (frm.doc.cro_number && !frm.doc.cro_date) {
            frm.set_value('cro_date', frappe.datetime.now_date());
        }
    },

    validate: function(frm) {
        if (frm.doc.cutoff_date && frm.doc.vessel_date) {
            if (frappe.datetime.get_day_diff(frm.doc.cutoff_date, frm.doc.vessel_date) > 0) {
                frappe.throw(__('Cutoff Date cannot be after Vessel Date'));
            }
        }
        if (frm.doc.pull_out_date && frm.doc.cutoff_date) {
            if (frappe.datetime.get_day_diff(frm.doc.pull_out_date, frm.doc.cutoff_date) > 0) {
                frappe.throw(__('Pull Out Date cannot be after Cutoff Date'));
            }
        }
    },

    after_save: function(frm) {
        frappe.show_alert({ message: __('Shipping Booking saved'), indicator: 'green' });
    }
});

frappe.listview_settings['Shipping Booking'] = {
    add_fields: ['job_order', 'customer', 'incoterm', 'port_of_loading', 'port_of_discharge', 'booking_status', 'cro_status', 'transport_status'],

    get_indicator: function(doc) {
        if (doc.transport_status === 'Completed') {
            return [__('Completed'), 'green', 'transport_status,=,Completed'];
        } else if (doc.transport_status === 'In Progress') {
            return [__('In Progress'), 'orange', 'transport_status,=,In Progress'];
        } else if (doc.cro_status === 'Pending') {
            return [__('CRO Pending'), 'yellow', 'cro_status,=,Pending'];
        } else if (doc.cro_status === 'Generated') {
            return [__('CRO Received'), 'blue', 'cro_status,=,Generated'];
        } else {
            return [__('Confirmed'), 'cyan', 'booking_status,=,Confirmed'];
        }
    }
};
