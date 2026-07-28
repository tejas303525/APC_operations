// Copyright (c) 2026, APC and contributors
// Shared cascade-delete confirmation for Job Order.

/**
 * Warn, then delete a Job Order and linked operational documents.
 *
 * @param {string} jobOrder - Job Order name (e.g. JO-2026-00001)
 * @param {Function} [onSuccess] - Called after successful delete
 */
function apcConfirmDeleteJobOrder(jobOrder, onSuccess) {
	if (!jobOrder) {
		return;
	}

	frappe.call({
		method: "apc_operations.shipping.api.get_job_order_delete_preview",
		args: { job_order: jobOrder },
		freeze: true,
		freeze_message: __("Checking linked documents..."),
		callback: (r) => {
			if (!r.message) {
				return;
			}
			const preview = r.message;
			const joLabel = preview.job_order_number || preview.job_order;
			const linked = preview.linked_documents || [];
			let message = __("This will permanently delete Job Order {0}.", [joLabel]);

			if (linked.length) {
				message +=
					"<br><br>" +
					__("The following {0} linked record(s) will also be deleted:", [linked.length]);
				message += "<ul>";
				linked.slice(0, 15).forEach((row) => {
					message += `<li>${frappe.utils.escape_html(row.label)}</li>`;
				});
				if (linked.length > 15) {
					message += `<li>${__("…and {0} more", [linked.length - 15])}</li>`;
				}
				message += "</ul>";
			}

			message += "<br>" + __("This action cannot be undone.");

			frappe.warn(
				__("Delete Job Order?"),
				message,
				() => {
					frappe.call({
						method: "apc_operations.shipping.api.delete_job_order_with_linked",
						args: { job_order: jobOrder },
						freeze: true,
						freeze_message: __("Deleting..."),
						callback: (res) => {
							const count = (res.message && res.message.deleted_count) || 0;
							frappe.show_alert({
								message: __("Deleted {0} record(s)", [count]),
								indicator: "green",
							});
							if (onSuccess) {
								onSuccess();
							}
						},
					});
				},
				__("Delete"),
				true
			);
		},
	});
}

/**
 * Add a destructive Delete action to a console dialog.
 */
function apcAddJobOrderDeleteAction(dialog, jobOrder, onSuccess) {
	if (!dialog || !jobOrder || typeof apcConfirmDeleteJobOrder !== "function") {
		return;
	}
	dialog.add_custom_action(__("Delete Job Order"), () => {
		dialog.hide();
		apcConfirmDeleteJobOrder(jobOrder, onSuccess);
	});
}
