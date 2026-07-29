// Copyright (c) 2026, APC and contributors
// For license information, please see license.txt

// Job Order Item is istable:1, so Frappe never loads this file — child-table
// client scripts have to live in the parent doctype's own .js to run
// (frappe/desk/form/meta.py FormMeta.load_assets skips add_code() for
// istable doctypes). All Job Order Item row logic lives in
// ../job_order/job_order.js instead. Keep this file empty rather than
// carrying dead code that looks like it runs but never does.
