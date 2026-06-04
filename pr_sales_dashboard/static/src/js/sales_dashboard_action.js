/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class SalesDashboardAction extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            data: {},
            loading: true,
        });

        onWillStart(async () => {
            await this.loadDashboardData();
        });
    }

    async loadDashboardData() {
        this.state.loading = true;
        this.state.data = await this.orm.call("pr.sales.dashboard", "get_dashboard_data", []);
        this.state.loading = false;
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
            domain,
            target: "current",
        });
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
        return currency.position === "after" ? `${formatted} ${symbol}`.trim() : `${symbol}${formatted}`.trim();
    }

    formatNumber(value) {
        return new Intl.NumberFormat(undefined, {
            maximumFractionDigits: 2,
        }).format(Number(value || 0));
    }

    formatPercent(value) {
        return `${Math.round(Number(value || 0))}%`;
    }

    clampPercent(value) {
        return Math.max(0, Math.min(100, Number(value || 0)));
    }

    donutStyle(value, color = "#2f95ed") {
        const percent = this.clampPercent(value);
        return `background: conic-gradient(${color} 0 ${percent}%, #e7edf4 ${percent}% 100%);`;
    }

    gaugeStyle(value, color = "#2f95ed") {
        const percent = this.clampPercent(value);
        return `--gauge-value:${percent / 2}%; --gauge-color:${color};`;
    }

    linePoints(monthly = []) {
        const width = 520;
        const height = 150;
        const pad = 10;
        const values = monthly.map((item) => Number(item.revenue || 0));
        const max = Math.max(...values, 0);
        if (!monthly.length) {
            return "";
        }
        if (!max) {
            return monthly.map((item, index) => {
                const x = pad + (index * (width - pad * 2)) / Math.max(monthly.length - 1, 1);
                return `${x},${height / 2}`;
            }).join(" ");
        }
        return monthly.map((item, index) => {
            const x = pad + (index * (width - pad * 2)) / Math.max(monthly.length - 1, 1);
            const y = height - pad - ((Number(item.revenue || 0) / max) * (height - pad * 2));
            return `${x},${y}`;
        }).join(" ");
    }

    lineAreaPoints(monthly = []) {
        const points = this.linePoints(monthly);
        if (!points) {
            return "";
        }
        return `10,150 ${points} 510,150`;
    }

    sparklinePoints(monthly = []) {
        const width = 150;
        const height = 58;
        const values = monthly.map((item) => Number(item.revenue || 0));
        const max = Math.max(...values, 0);
        if (!monthly.length) {
            return "";
        }
        return monthly.map((item, index) => {
            const x = (index * width) / Math.max(monthly.length - 1, 1);
            const y = max ? height - ((Number(item.revenue || 0) / max) * height) : height / 2;
            return `${x},${y}`;
        }).join(" ");
    }
}

SalesDashboardAction.template = "pr_sales_dashboard.SalesDashboardAction";

registry.category("actions").add("pr_sales_dashboard.sales_dashboard", SalesDashboardAction);
