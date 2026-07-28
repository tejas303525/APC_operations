/* Delivery-date + daily-work helpers for operational consoles.
 * Loaded after console_router.js and again via page_js so browsers pick up
 * new APCConsoleUI methods even when console_router.js is cached.
 */
(function () {
	const UI = (window.APCConsoleUI = window.APCConsoleUI || {});

	function formatDeliveryDate(value) {
		if (typeof UI.formatDate === "function") {
			return UI.formatDate(value);
		}
		if (!value) {
			return "-";
		}
		try {
			return frappe.datetime.str_to_user(value);
		} catch (e) {
			return value;
		}
	}

	function statusBadge(label, tone) {
		if (typeof UI.statusBadge === "function") {
			return UI.statusBadge(label, tone);
		}
		const safeLabel = frappe.utils.escape_html(label || "");
		const safeTone = (tone || "neutral").replace(/[^a-z0-9_-]/gi, "");
		return `<span class="apc-status-badge apc-status-${safeTone}">${safeLabel}</span>`;
	}

	function deliveryUrgencyLabel(urgency) {
		const labels = {
			overdue: __("Overdue"),
			today: __("Due Today"),
			upcoming: __("Upcoming"),
		};
		return labels[urgency] || __("Delivery");
	}

	function deliveryUrgencyTone(urgency) {
		const tones = {
			overdue: "danger",
			today: "warn",
			upcoming: "neutral",
		};
		return tones[urgency] || "neutral";
	}

	function deliveryUrgencyBadge(item) {
		if (!item || (!item.delivery_due_date && !item.delivery_urgency)) {
			return "";
		}
		const label = deliveryUrgencyLabel(item.delivery_urgency);
		const datePart = item.delivery_due_date
			? ` · ${formatDeliveryDate(item.delivery_due_date)}`
			: "";
		return statusBadge(`${label}${datePart}`, deliveryUrgencyTone(item.delivery_urgency));
	}

	function deliveryDueKvHtml(item) {
		if (!item || !item.delivery_due_date) {
			return "";
		}
		return `
			<div class="apc-kv-label">${__("Delivery Date")}</div>
			<div>${frappe.utils.escape_html(formatDeliveryDate(item.delivery_due_date))}</div>`;
	}

	function consoleDeliveryBadges(item, extraBadges) {
		const badges = [];
		const dueBadge = deliveryUrgencyBadge(item);
		if (dueBadge) {
			badges.push(dueBadge);
		}
		return badges.concat(extraBadges || []);
	}

	function formatDailyWorkSubtitle(counts, fallback) {
		if (!counts) {
			return fallback || "";
		}
		const parts = [];
		if (counts.overdue) {
			parts.push(__("{0} overdue", [counts.overdue]));
		}
		if (counts.today) {
			parts.push(__("{0} due today", [counts.today]));
		}
		if (!parts.length && counts.this_week) {
			parts.push(__("{0} this week", [counts.this_week]));
		}
		return parts.join(" · ") || fallback || __("No urgent deliveries");
	}

	function aggregateQueueCounts(summary, queueKeys) {
		const out = {
			overdue: 0,
			today: 0,
			this_week: 0,
			upcoming: 0,
			unknown: 0,
			total: 0,
		};
		const queues = (summary && summary.queues) || {};
		(queueKeys || []).forEach((key) => {
			const row = queues[key] || {};
			out.overdue += row.overdue || 0;
			out.today += row.today || 0;
			out.this_week += row.this_week || 0;
			out.upcoming += row.upcoming || 0;
			out.unknown += row.unknown || 0;
			out.total += row.total || 0;
		});
		return out;
	}

	function filterByDeliveryUrgency(rows, filterId) {
		if (!filterId || filterId === "all") {
			return rows || [];
		}
		const todayStr = frappe.datetime.get_today();
		const weekEnd = frappe.datetime.add_days(todayStr, 7);
		return (rows || []).filter((row) => {
			const urgency = row.delivery_urgency;
			const due = row.delivery_due_date;
			if (filterId === "overdue") {
				return urgency === "overdue";
			}
			if (filterId === "today") {
				return urgency === "today";
			}
			if (filterId === "week") {
				if (urgency === "overdue" || urgency === "today") {
					return true;
				}
				if (!due) {
					return false;
				}
				return frappe.datetime.obj_to_str(frappe.datetime.str_to_obj(due)) <= weekEnd;
			}
			return true;
		});
	}

	function deliveryUrgencyFilterBar($root, onChange) {
		return UI.filterChips(
			$root,
			[
				{ id: "all", label: __("All") },
				{ id: "overdue", label: __("Overdue") },
				{ id: "today", label: __("Due Today") },
				{ id: "week", label: __("This Week") },
			],
			{ initial: "all", onChange }
		);
	}

	function renderCardScreen($root, options) {
		options = options || {};
		const deliveryFilter = options.deliveryFilter !== false;
		let urgencyFilter = "all";

		const { $input } = UI.searchRow($root, {
			placeholder: options.searchPlaceholder,
			onChange: () => render(),
		});

		if (deliveryFilter) {
			deliveryUrgencyFilterBar($root, (filterId) => {
				urgencyFilter = filterId;
				render();
			});
		}

		const $cards = $(`<div class="apc-console-screen-cards"></div>`).appendTo($root);
		let rows = [];

		const loadRows = () => {
			UI.loading($cards);
			return UI.callApi(options.listApi, options.listArgs || {})
				.then((data) => {
					rows = data || [];
					if (options.clientFilter) {
						rows = options.clientFilter(rows);
					}
					render();
				})
				.catch((err) => UI.errorBlock($cards, err));
		};

		function render() {
			const term = ($input.val() || "").trim().toLowerCase();
			let visible = rows;
			if (deliveryFilter) {
				visible = filterByDeliveryUrgency(visible, urgencyFilter);
			}
			if (term) {
				visible = visible.filter(
					(r) => JSON.stringify(r).toLowerCase().indexOf(term) !== -1
				);
			}
			const items = (visible || []).map(options.toCard);
			$cards.empty();
			UI.cardList($cards, items, (item) => options.onCardClick && options.onCardClick(item));
		}

		loadRows();
		return { reload: loadRows };
	}

	function hubButtonsWithDailyWork($root, hub, buttonDefs) {
		const renderButtons = (summary) => {
			const queues = (summary && summary.queues) || {};
			UI.hubButtons(
				$root,
				(buttonDefs || []).map((def) => {
					let counts = null;
					if (def.queueKey) {
						counts = queues[def.queueKey];
					} else if (def.queueKeys) {
						counts = aggregateQueueCounts(summary, def.queueKeys);
					}
					return {
						label: def.label,
						subtitle: formatDailyWorkSubtitle(counts, def.fallback),
						onClick: def.onClick,
					};
				})
			);
		};
		return UI.callApi("apc_operations.services.console_api.get_daily_work_summary", { hub })
			.then((summary) => renderButtons(summary))
			.catch(() =>
				UI.hubButtons(
					$root,
					(buttonDefs || []).map((def) => ({
						label: def.label,
						subtitle: def.fallback || "",
						onClick: def.onClick,
					}))
				)
			);
	}

	window.apcConsoleDeliveryBadges = consoleDeliveryBadges;
	window.apcConsoleDeliveryDueKvHtml = deliveryDueKvHtml;

	// Always patch — survives stale console_router.js cache.
	UI.deliveryUrgencyLabel = deliveryUrgencyLabel;
	UI.deliveryUrgencyTone = deliveryUrgencyTone;
	UI.deliveryUrgencyBadge = deliveryUrgencyBadge;
	UI.deliveryDueKvHtml = deliveryDueKvHtml;
	UI.consoleDeliveryBadges = consoleDeliveryBadges;
	UI.formatDailyWorkSubtitle = formatDailyWorkSubtitle;
	UI.aggregateQueueCounts = aggregateQueueCounts;
	UI.filterByDeliveryUrgency = filterByDeliveryUrgency;
	UI.deliveryUrgencyFilterBar = deliveryUrgencyFilterBar;
	UI.renderCardScreen = renderCardScreen;
	UI.hubButtonsWithDailyWork = hubButtonsWithDailyWork;
})();
