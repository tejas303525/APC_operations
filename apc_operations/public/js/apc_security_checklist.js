/* Shared security checklist grid for Security + QC consoles */

frappe.provide("frappe.apc");

frappe.apc.renderSecurityChecklist = function (items, editable) {
	if (!items || !items.length) {
		return `<div class="apc-empty-block">${frappe.utils.escape_html(
			__("No checklist items configured.")
		)}</div>`;
	}
	const safe = (v) =>
		v === null || v === undefined ? "" : frappe.utils.escape_html(String(v));
	const disabledAttr = editable ? "" : "disabled";
	const readonlyAttr = editable ? "" : "readonly";

	const rows = items
		.map((item, idx) => {
			const completed = item.completed ? "checked" : "";
			const requiredPill = item.required
				? `<span class="apc-checklist-required">${__("Required")}</span>`
				: "";
			return `
				<tr data-checklist-idx="${idx}"
				    data-checklist-name="${safe(item.name || "")}"
				    data-checklist-required="${item.required ? 1 : 0}"
				    data-checklist-item="${safe(item.checklist_item || "")}">
					<td class="apc-checklist-label">
						<div class="apc-checklist-item-text">${safe(item.checklist_item || "")}</div>
						${requiredPill}
					</td>
					<td class="apc-checklist-completed-cell">
						<input type="checkbox" class="apc-checklist-completed" ${completed} ${disabledAttr}>
					</td>
					<td class="apc-checklist-remarks-cell">
						<input type="text"
						       class="apc-checklist-remarks form-control input-xs"
						       value="${safe(item.remarks || "")}"
						       placeholder="${__("Remarks (optional)")}"
						       ${readonlyAttr}>
					</td>
				</tr>
			`;
		})
		.join("");

	return `
		<div class="apc-checklist-wrapper">
			<table class="apc-checklist-table">
				<thead>
					<tr>
						<th>${__("Checklist Item")}</th>
						<th class="apc-checklist-completed-cell">${__("Done")}</th>
						<th class="apc-checklist-remarks-cell">${__("Remarks")}</th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>
		</div>
	`;
};

frappe.apc.collectSecurityChecklist = function (dialog, fallback) {
	const $root = dialog.$wrapper.find(".apc-checklist-table tbody tr[data-checklist-idx]");
	if (!$root.length) {
		return Array.isArray(fallback) ? fallback : [];
	}
	const out = [];
	$root.each(function () {
		const $tr = $(this);
		const idx = parseInt($tr.attr("data-checklist-idx"), 10);
		const original = (fallback && fallback[idx]) || {};
		out.push({
			name: $tr.attr("data-checklist-name") || original.name || null,
			checklist_item: $tr.attr("data-checklist-item") || original.checklist_item || "",
			required: parseInt($tr.attr("data-checklist-required"), 10) || 0,
			completed: $tr.find(".apc-checklist-completed").is(":checked") ? 1 : 0,
			remarks: $tr.find(".apc-checklist-remarks").val() || "",
		});
	});
	return out;
};
