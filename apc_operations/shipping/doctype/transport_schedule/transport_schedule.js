// Copyright (c) 2026, APC and contributors
// For license information, please see license.txt

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
        if (frm.is_new()) {
            return;
        }

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

        if (frm.doc.docstatus === 0 && ['Scheduled', 'Vehicle Assigned', 'Driver Assigned'].includes(frm.doc.transport_status)) {
            frm.add_custom_button(__('Dispatch'), () => {
                frappe.call({
                    method: 'apc_operations.shipping.doctype.transport_schedule.transport_schedule.update_transport_status',
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
            }, __('Actions'));
        }
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
    }
});

frappe.listview_settings['Transport Schedule'] = {
    // Make Job Order the primary business identifier in list view.
    // Frappe may still keep the internal name column depending on version.
    hide_name_column: true,
    add_fields: ['job_order', 'customer', 'incoterm', 'pickup_location', 'delivery_location', 'transport_status'],

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
};
