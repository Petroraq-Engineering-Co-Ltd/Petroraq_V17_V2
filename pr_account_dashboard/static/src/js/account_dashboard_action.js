/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class AccountDashboardAction extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        const today = new Date();
        this.state = useState({
            data: {},
            loading: true,
            filters: {
                period: "year",
                date_from: this.toISODate(new Date(today.getFullYear(), 0, 1)),
                date_to: this.toISODate(today),
                company_id: false,
            },
        });

        onWillStart(async () => {
            await this.loadDashboardData();
        });
    }

    toISODate(value) {
        const year = value.getFullYear();
        const month = String(value.getMonth() + 1).padStart(2, "0");
        const day = String(value.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
    }

    async loadDashboardData() {
        this.state.loading = true;
        try {
            const options = {
                date_from: this.state.filters.date_from,
                date_to: this.state.filters.date_to,
                company_id: this.state.filters.company_id || false,
            };
            this.state.data = await this.orm.call(
                "pr.account.dashboard",
                "get_dashboard_data",
                [options]
            );
            const returnedFilters = this.state.data.filters || {};
            this.state.filters.company_id = returnedFilters.company_id || this.state.filters.company_id;
            this.state.filters.date_from = returnedFilters.date_from || this.state.filters.date_from;
            this.state.filters.date_to = returnedFilters.date_to || this.state.filters.date_to;
        } catch (error) {
            this.notification.add(
                error?.data?.message || error?.message || "Unable to load the accounting dashboard.",
                { type: "danger", title: "Accounting Dashboard" }
            );
        } finally {
            this.state.loading = false;
        }
    }

    async applyFilters() {
        this.state.filters.period = "custom";
        await this.loadDashboardData();
    }

    async setPeriod(event) {
        const period = event.currentTarget.dataset.period;
        const today = new Date();
        let start;
        if (period === "month") {
            start = new Date(today.getFullYear(), today.getMonth(), 1);
        } else if (period === "quarter") {
            start = new Date(today.getFullYear(), Math.floor(today.getMonth() / 3) * 3, 1);
        } else {
            start = new Date(today.getFullYear(), 0, 1);
        }
        this.state.filters.period = period;
        this.state.filters.date_from = this.toISODate(start);
        this.state.filters.date_to = this.toISODate(today);
        await this.loadDashboardData();
    }

    onDateFromChange(event) {
        this.state.filters.date_from = event.target.value;
    }

    onDateToChange(event) {
        this.state.filters.date_to = event.target.value;
    }

    onCompanyChange(event) {
        this.state.filters.company_id = Number(event.target.value);
    }

    openRecords(model, domain = [], name = "Records") {
        if (!model) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: model,
            views: [[false, "list"], [false, "form"]],
            domain: domain || [],
            target: "current",
        });
    }

    openRecord(model, id) {
        if (!model || !id) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openAction(actionXmlId) {
        if (actionXmlId) {
            this.action.doAction(actionXmlId);
        }
    }

    formatMoney(value) {
        const currency = this.state.data.currency || {};
        const amount = Number(value || 0);
        const digits = Math.abs(amount) >= 1000 ? 0 : Math.min(currency.digits ?? 2, 2);
        const formatted = new Intl.NumberFormat(undefined, {
            minimumFractionDigits: digits,
            maximumFractionDigits: digits,
        }).format(amount);
        const symbol = currency.symbol || "";
        return currency.position === "after"
            ? `${formatted} ${symbol}`.trim()
            : `${symbol}${formatted}`.trim();
    }

    formatNumber(value) {
        return new Intl.NumberFormat(undefined, {
            maximumFractionDigits: 2,
        }).format(Number(value || 0));
    }

    formatPercent(value) {
        return `${Math.round(Number(value || 0))}%`;
    }

    formatDate(value) {
        if (!value) {
            return "";
        }
        const date = new Date(`${value}T00:00:00`);
        return new Intl.DateTimeFormat(undefined, {
            day: "2-digit",
            month: "short",
            year: "numeric",
        }).format(date);
    }

    clampPercent(value) {
        return Math.max(0, Math.min(100, Number(value || 0)));
    }

    donutStyle(value, color = "#2563eb") {
        const percent = this.clampPercent(value);
        return `background: conic-gradient(${color} 0 ${percent}%, #e8edf4 ${percent}% 100%);`;
    }

    amountClass(value) {
        return Number(value || 0) < 0 ? "is-negative" : "is-positive";
    }

    severityClass(value = "") {
        const severity = String(value).toLowerCase();
        if (severity.includes("danger")) {
            return "is-danger";
        }
        if (severity.includes("warning")) {
            return "is-warning";
        }
        if (severity.includes("success")) {
            return "is-success";
        }
        return "is-neutral";
    }

    statusClass(value = "") {
        const status = String(value).toLowerCase();
        if (status.includes("posted") || status.includes("paid") || status.includes("finance approval")) {
            return "is-success";
        }
        if (status.includes("cancel") || status.includes("reject")) {
            return "is-danger";
        }
        if (status.includes("submit") || status.includes("approval") || status.includes("process")) {
            return "is-warning";
        }
        return "is-neutral";
    }
}

AccountDashboardAction.template = "pr_account_dashboard.AccountDashboardAction";

registry.category("actions").add(
    "pr_account_dashboard.account_dashboard",
    AccountDashboardAction
);
