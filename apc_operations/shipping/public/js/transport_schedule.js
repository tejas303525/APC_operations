// Client Script for Transport Schedule DocType

frappe.ui.form.on('Transport Schedule', {
    setup(frm) {
        frm.set_query('assigned_vehicle', () => ({
            filters: { status: 'Active' }
        }));

        frm.set_query('assigned_driver', () => ({
            filters: { status: 'Active' }
        }));
    },

    refresh(frm) {
        if (!frm.is_new()) {
            frm.trigger('add_action_buttons');
            frm.trigger('add_link_buttons');
        }

        frm.trigger('update_indicators');
    },

    add_action_buttons(frm) {
        if (frm.doc.docstatus !== 0) {
            return;
        }

        if (['Scheduled', 'Vehicle Assigned', 'Driver Assigned'].includes(frm.doc.transport_status)) {
            frm.add_custom_button(__('Dispatch'), () => {
                frm.trigger('mark_dispatched');
            }, __('Actions'));
        }

        if (['Dispatched', 'Picked Up', 'In Transit'].includes(frm.doc.transport_status)) {
            frm.add_custom_button(__('Mark Delivered'), () => {
                frm.trigger('mark_delivered');
            }, __('Actions'));
        }

        if (frm.doc.assigned_driver) {
            frm.add_custom_button(__('Notify Driver'), () => {
                frm.trigger('notify_driver');
            }, __('Actions'));
        }
    },

    add_link_buttons(frm) {
        if (frm.doc.shipping_booking) {
            frm.add_custom_button(__('Shipping Booking'), () => {
                frappe.set_route('Form', 'Shipping Booking', frm.doc.shipping_booking);
            }, __('Linked Documents'));
        }

        if (frm.doc.job_order) {
            frm.add_custom_button(__('Job Order'), () => {
                frappe.set_route('Form', 'Job Order', frm.doc.job_order);
            }, __('Linked Documents'));
        }

        if (frm.doc.transport_po_request) {
            frm.add_custom_button(__('Transport PO Request'), () => {
                frappe.set_route('Form', 'Transport PO Request', frm.doc.transport_po_request);
            }, __('Linked Documents'));
        }

        if (frm.doc.security_draft_delivery_note) {
            frm.add_custom_button(__('Security Draft Delivery Note'), () => {
                frappe.set_route('Form', 'Security Draft Delivery Note', frm.doc.security_draft_delivery_note);
            }, __('Linked Documents'));
        }
    },

    mark_dispatched(frm) {
        frappe.call({
            method: 'apc_operations.transportation.doctype.transport_schedule.transport_schedule.update_transport_status',
            args: {
                transport_name: frm.doc.name,
                status: 'Dispatched'
            },
            callback(r) {
                if (r.message && r.message.success) {
                    frm.reload_doc();
                }
            }
        });
    },

    mark_delivered(frm) {
        frappe.call({
            method: 'apc_operations.transportation.doctype.transport_schedule.transport_schedule.update_transport_status',
            args: {
                transport_name: frm.doc.name,
                status: 'Delivered'
            },
            callback(r) {
                if (r.message && r.message.success) {
                    frm.reload_doc();
                }
            }
        });
    },

    notify_driver(frm) {
        frappe.call({
            method: 'apc_operations.shipping.notifications.notify_driver',
            args: {
                transport_name: frm.doc.name
            },
            callback() {
                frappe.show_alert({
                    message: __('Driver notified'),
                    indicator: 'green'
                });
            }
        });
    },

    shipping_booking(frm) {
        if (!frm.doc.shipping_booking) {
            return;
        }

        frappe.db.get_doc('Shipping Booking', frm.doc.shipping_booking).then(doc => {
            frm.set_value({
                source_document_type: 'Shipping Booking',
                job_order: doc.job_order,
                customer: doc.customer,
                shipping_line: doc.shipping_line,
                vessel_name: doc.vessel_name,
                vessel_date: doc.vessel_date,
                cro_number: doc.cro_number,
                cro_date: doc.cro_date,
                cutoff_date: doc.cutoff_date,
                gate_cutoff: doc.gate_cutoff,
                pull_out_date: doc.pull_out_date,
                gate_in_date: doc.gate_in_date,
                container_type: doc.container_type,
                container_count: doc.container_count,
                cargo_weight: doc.cargo_weight,
                material_description: doc.cargo_description,
                port_of_loading: doc.port_of_loading,
                port_of_discharge: doc.port_of_discharge,
                transport_type: 'Outward',
                outward_type: 'Export Container'
            });
        });
    },

    job_order(frm) {
        if (!frm.doc.job_order) {
            return;
        }

        frappe.db.get_doc('Job Order', frm.doc.job_order).then(doc => {
            frm.set_value({
                customer: doc.customer,
                incoterm: doc.terms_of_delivery,
                port_of_loading: doc.port_of_loading,
                port_of_discharge: doc.port_of_discharge
            });
        });
    },

    transport_charges(frm) {
        frm.trigger('calculate_totals');
    },

    fuel_cost(frm) {
        frm.trigger('calculate_totals');
    },

    additional_charges(frm) {
        frm.trigger('calculate_totals');
    },

    calculate_totals(frm) {
        const total =
            flt(frm.doc.transport_charges) +
            flt(frm.doc.fuel_cost) +
            flt(frm.doc.additional_charges);
        frm.set_value('total_cost', total);
    },

    update_indicators(frm) {
        if (frm.doc.scheduled_pickup_date && !['Completed', 'Cancelled'].includes(frm.doc.transport_status)) {
            const days_until = frappe.datetime.get_day_diff(frm.doc.scheduled_pickup_date, frappe.datetime.now_date());

            if (days_until < 0) {
                frm.dashboard.set_headline_alert(
                    __('Pickup is overdue by {0} day(s)', [Math.abs(days_until)]),
                    'red'
                );
            } else if (days_until <= 1) {
                frm.dashboard.set_headline_alert(__('Pickup is due soon'), 'orange');
            }
        }
    }
});

frappe.listview_settings['Transport Schedule'] = {
    hide_name_column: true,
    add_fields: ['job_order', 'job_order_number', 'customer', 'incoterm', 'pickup_location', 'delivery_location', 'transport_status'],

    get_indicator(doc) {
        if (doc.transport_status === 'Completed') {
            return [__('Completed'), 'green', 'transport_status,=,Completed'];
        }
        if (['Dispatched', 'Picked Up', 'Gate In', 'In Transit'].includes(doc.transport_status)) {
            return [__('In Transit'), 'blue', 'transport_status,in,Dispatched,Picked Up,Gate In,In Transit'];
        }
        if (['Scheduled', 'Vehicle Assigned', 'Driver Assigned'].includes(doc.transport_status)) {
            return [__('Scheduled'), 'orange', 'transport_status,in,Scheduled,Vehicle Assigned,Driver Assigned'];
        }
        return [__('Pending'), 'gray', 'transport_status,in,Draft,Pending Assignment'];
    },

    formatters: {
        job_order_number(value, _df, doc) {
            if (!value) return '';
            const jobOrder = encodeURIComponent(doc.job_order || '');
            return jobOrder
                ? `<a href="/app/job-order/${jobOrder}">${value}</a>`
                : value;
        },
        job_order(value) {
            if (!value) return '';
            return `<a href="/app/job-order/${encodeURIComponent(value)}">${value}</a>`;
        }
    },

    onload(listview) {
        listview.page.add_inner_button(__('Pending Pickups'), () => {
            listview.filter_area.add([['Transport Schedule', 'transport_status', 'in', ['Draft', 'Pending Assignment', 'Scheduled']]]);
            listview.filter_area.add([['Transport Schedule', 'scheduled_pickup_date', '<=', frappe.datetime.add_days(frappe.datetime.now_date(), 3)]]);
            listview.refresh();
        });
    }
};
