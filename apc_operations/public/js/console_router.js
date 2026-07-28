/* APC Operations — Shared Console Router
 *
 * A tiny page-on-page SPA router for the Transportation / Shipping /
 * Security / QC consoles. One Frappe Page wraps everything, screens are
 * stacked in memory, and a single Back button + breadcrumb is rendered
 * at the top of the page.
 *
 * Usage:
 *   const router = new APCConsoleRouter(page, { rootClass: "apc-console" });
 *   router.reset({
 *     title: __("Transportation"),
 *     render($root, router) { ... },
 *   });
 *
 * A screen is `{ title, render($root, router) }`. The renderer must
 * populate `$root` (a jQuery node). When the screen is shown again
 * after a pop, render() is called fresh, so screens should be
 * idempotent and re-fetch any server data they need.
 */

(function () {
	if (window.APCConsoleRouter) {
		return;
	}

	class APCConsoleRouter {
		constructor(page, options) {
			options = options || {};
			this.page = page;
			this.stack = [];
			this.rootClass = options.rootClass || "apc-console";

			this.$wrapper = $(page.main).empty();
			this.$wrapper.addClass(this.rootClass);

			this.$chrome = $(
				`<div class="apc-console-chrome">
					<button type="button" class="btn btn-default btn-xs apc-console-back" style="display:none;">
						<i class="fa fa-chevron-left"></i> ${frappe.utils.escape_html(__("Back"))}
					</button>
					<nav class="apc-console-breadcrumb" aria-label="breadcrumb"></nav>
				</div>`
			).appendTo(this.$wrapper);

			this.$body = $(`<div class="apc-console-body"></div>`).appendTo(this.$wrapper);

			this.$chrome.find(".apc-console-back").on("click", () => this.pop());
		}

		_currentScreen() {
			return this.stack.length ? this.stack[this.stack.length - 1] : null;
		}

		_renderCurrent() {
			const screen = this._currentScreen();
			if (!screen) {
				this.$body.empty();
				return;
			}

			if (screen.title) {
				this.page.set_title(screen.title);
			}

			this.$body.empty();
			const $root = $(`<div class="apc-console-screen"></div>`).appendTo(this.$body);

			this._renderBreadcrumb();
			this.$chrome.find(".apc-console-back").toggle(this.stack.length > 1);

			try {
				screen.render($root, this);
			} catch (e) {
				console.error("APCConsoleRouter render error", e);
				$root.html(
					`<div class="apc-console-empty apc-console-error">
						<strong>${frappe.utils.escape_html(__("Failed to render screen"))}</strong>
						<div class="text-muted">${frappe.utils.escape_html(String(e && e.message ? e.message : e))}</div>
					</div>`
				);
			}
		}

		_renderBreadcrumb() {
			const $bc = this.$chrome.find(".apc-console-breadcrumb").empty();
			const items = this.stack.map((s) => s.title || "");
			items.forEach((label, idx) => {
				const isLast = idx === items.length - 1;
				if (idx > 0) {
					$bc.append(`<span class="apc-console-breadcrumb-sep"> / </span>`);
				}
				if (isLast) {
					$bc.append(
						`<span class="apc-console-breadcrumb-current">${frappe.utils.escape_html(label)}</span>`
					);
				} else {
					const $link = $(
						`<a href="javascript:void(0)" class="apc-console-breadcrumb-link">${frappe.utils.escape_html(
							label
						)}</a>`
					);
					$link.on("click", () => this._popTo(idx));
					$bc.append($link);
				}
			});
		}

		push(screen) {
			if (!screen || typeof screen.render !== "function") {
				throw new Error("APCConsoleRouter.push requires { title, render }");
			}
			this.stack.push(screen);
			this._renderCurrent();
		}

		pop() {
			if (this.stack.length <= 1) {
				return;
			}
			this.stack.pop();
			this._renderCurrent();
		}

		replace(screen) {
			if (!screen || typeof screen.render !== "function") {
				throw new Error("APCConsoleRouter.replace requires { title, render }");
			}
			if (this.stack.length) {
				this.stack[this.stack.length - 1] = screen;
			} else {
				this.stack.push(screen);
			}
			this._renderCurrent();
		}

		reset(screen) {
			this.stack = [];
			if (screen) {
				this.stack.push(screen);
			}
			this._renderCurrent();
		}

		_popTo(index) {
			if (index < 0 || index >= this.stack.length) {
				return;
			}
			this.stack = this.stack.slice(0, index + 1);
			this._renderCurrent();
		}

		setTitle(title) {
			const current = this._currentScreen();
			if (current) {
				current.title = title;
			}
			if (title) {
				this.page.set_title(title);
			}
			this._renderBreadcrumb();
		}

		setBreadcrumb(items) {
			if (!Array.isArray(items)) {
				return;
			}
			this.stack.forEach((screen, idx) => {
				if (items[idx]) {
					screen.title = items[idx];
				}
			});
			this._renderBreadcrumb();
		}

		refresh() {
			this._renderCurrent();
		}
	}

	// Shared UI helpers used across all consoles.
	const APCConsoleUI = {
		statusBadge(label, tone) {
			const safeLabel = frappe.utils.escape_html(label || "");
			const safeTone = (tone || "neutral").replace(/[^a-z0-9_-]/gi, "");
			return `<span class="apc-status-badge apc-status-${safeTone}">${safeLabel}</span>`;
		},

		hubButtons($root, buttons) {
			const $grid = $(`<div class="apc-hub-grid"></div>`).appendTo($root);
			buttons.forEach((btn) => {
				const $btn = $(
					`<button type="button" class="apc-hub-btn">
						<span class="apc-hub-btn-title">${frappe.utils.escape_html(btn.label || "")}</span>
						${btn.subtitle ? `<span class="apc-hub-btn-subtitle">${frappe.utils.escape_html(btn.subtitle)}</span>` : ""}
					</button>`
				);
				$btn.on("click", () => btn.onClick && btn.onClick());
				$grid.append($btn);
			});
			return $grid;
		},

		searchRow($root, options) {
			options = options || {};
			const $row = $(`<div class="apc-console-search-row"></div>`).appendTo($root);
			const $input = $(
				`<input type="search" class="form-control apc-console-search" placeholder="${frappe.utils.escape_html(
					options.placeholder || __("Search...")
				)}">`
			).appendTo($row);
			let timer = null;
			$input.on("input", () => {
				if (timer) {
					clearTimeout(timer);
				}
				timer = setTimeout(() => {
					options.onChange && options.onChange(($input.val() || "").trim());
				}, 150);
			});
			return { $row, $input };
		},

		filterChips($root, chips, options) {
			options = options || {};
			const $bar = $(`<div class="apc-console-chip-row"></div>`).appendTo($root);
			let active = options.initial || (chips[0] && chips[0].id);
			const renderChips = () => {
				$bar.empty();
				chips.forEach((chip) => {
					const isActive = chip.id === active;
					const $chip = $(
						`<button type="button" class="apc-chip ${isActive ? "apc-chip-active" : ""}">${frappe.utils.escape_html(
							chip.label
						)}${typeof chip.count === "number" ? ` <span class="apc-chip-count">${chip.count}</span>` : ""}</button>`
					);
					$chip.on("click", () => {
						active = chip.id;
						renderChips();
						options.onChange && options.onChange(active);
					});
					$bar.append($chip);
				});
			};
			renderChips();
			return {
				$bar,
				get active() {
					return active;
				},
				setCounts(counts) {
					chips.forEach((c) => {
						if (counts && counts[c.id] !== undefined) {
							c.count = counts[c.id];
						}
					});
					renderChips();
				},
			};
		},

		cardList($root, items, onClick) {
			const $list = $(`<div class="apc-card-list"></div>`).appendTo($root);
			if (!items || !items.length) {
				$list.html(
					`<div class="apc-console-empty">${frappe.utils.escape_html(__("No items to display"))}</div>`
				);
				return $list;
			}
			items.forEach((item) => {
				const $card = $(
					`<button type="button" class="apc-card">
						<div class="apc-card-head">
							<span class="apc-card-title">${frappe.utils.escape_html(item.title || "")}</span>
							<span class="apc-card-subtitle">${frappe.utils.escape_html(item.subtitle || "")}</span>
						</div>
						<div class="apc-card-body">${item.body_html || ""}</div>
						<div class="apc-card-badges">${(item.badges || []).join(" ")}</div>
					</button>`
				);
				$card.on("click", () => onClick && onClick(item));
				$list.append($card);
			});
			return $list;
		},

		loading($root, label) {
			$root.html(
				`<div class="apc-console-loading">
					<i class="fa fa-spinner fa-spin"></i>
					<span>${frappe.utils.escape_html(label || __("Loading..."))}</span>
				</div>`
			);
		},

		empty($root, label) {
			$root.html(
				`<div class="apc-console-empty">${frappe.utils.escape_html(label || __("Nothing to show"))}</div>`
			);
		},

		errorBlock($root, err) {
			const msg =
				(err && (err.message || err._error_message || err.exc)) || __("Something went wrong");
			$root.html(
				`<div class="apc-console-empty apc-console-error">
					<strong>${frappe.utils.escape_html(__("Unable to load"))}</strong>
					<div class="text-muted">${frappe.utils.escape_html(String(msg))}</div>
				</div>`
			);
		},

		formatDate(value) {
			if (!value) {
				return "-";
			}
			try {
				return frappe.datetime.str_to_user(value);
			} catch (e) {
				return value;
			}
		},

		pendingBanner($root, counts, onClick) {
			const items = [
				{ id: "transport", label: __("Pending Transport Bookings"), count: counts.transport || 0 },
				{ id: "do", label: __("Pending Delivery Orders"), count: counts.do || 0 },
				{ id: "sddn", label: __("Pending SDDNs"), count: counts.sddn || 0 },
			];
			const $banner = $(`<div class="apc-pending-banner"></div>`).appendTo($root);
			items.forEach((it) => {
				const $tile = $(
					`<button type="button" class="apc-pending-tile">
						<span class="apc-pending-tile-count">${frappe.utils.escape_html(String(it.count))}</span>
						<span class="apc-pending-tile-label">${frappe.utils.escape_html(it.label)}</span>
					</button>`
				);
				$tile.on("click", () => onClick && onClick(it.id));
				$banner.append($tile);
			});
			return $banner;
		},

		callApi(method, args) {
			return new Promise((resolve, reject) => {
				frappe.call({
					method,
					args: args || {},
					callback: (r) => resolve(r && r.message),
					error: (err) => reject(err),
				});
			});
		},

		showApiError(err, fallback) {
			let message = fallback || __("Request failed");
			if (typeof err === "string") {
				message = err;
			} else if (err && err.message) {
				message = err.message;
			} else if (err && err._server_messages) {
				try {
					message = JSON.parse(JSON.parse(err._server_messages)[0]).message || message;
				} catch (e) {
					/* keep fallback */
				}
			} else if (err && err.exc) {
				const lines = String(err.exc).trim().split("\n");
				message = lines[lines.length - 1] || message;
			}
			frappe.msgprint({ title: __("Error"), message, indicator: "red" });
		},
	};

	window.APCConsoleRouter = APCConsoleRouter;
	window.APCConsoleUI = APCConsoleUI;
})();
