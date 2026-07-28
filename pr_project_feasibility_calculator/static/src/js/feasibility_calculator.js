/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

const DEFAULTS = {
    id: false,
    project_name: "New Project",
    investment_amount: 1000000,
    total_project_amount: 1500000,
    projected_total_profit: 500000,
    investor_ratio: 50,
    expected_monthly_rate: 5,
    duration_months: 6,
    notes: "",
};

export class ProjectFeasibilityCalculator extends Component {
    static template = "pr_project_feasibility_calculator.Calculator";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.state = useState({
            mode: "forward",
            busy: false,
            currency: { name: "SAR", symbol: "﷼", position: "after" },
            form: { ...DEFAULTS },
            records: [],
        });
        onWillStart(() => this.loadData());
    }

    async loadData() {
        const data = await this.orm.call(
            "project.feasibility.calculation",
            "get_calculator_data",
            [12]
        );
        this.state.currency = data.currency;
        this.state.records = data.records;
    }

    number(value) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : 0;
    }

    get result() {
        const investment = Math.max(this.number(this.state.form.investment_amount), 0);
        const totalProfit = Math.max(this.number(this.state.form.projected_total_profit), 0);
        const ratio = Math.max(Math.min(this.number(this.state.form.investor_ratio), 100), 0);
        const rate = Math.max(this.number(this.state.form.expected_monthly_rate), 0);
        const months = Math.max(this.number(this.state.form.duration_months), 0);
        const investorProfit = totalProfit * ratio / 100;
        const requiredProfit = investment * rate / 100 * months;
        const minimumRatio = totalProfit ? requiredProfit / totalProfit * 100 : 0;
        return {
            investorProfit,
            requiredProfit,
            variance: investorProfit - requiredProfit,
            monthlyProfit: months ? investorProfit / months : 0,
            roi: investment ? investorProfit / investment * 100 : 0,
            minimumRatio,
            requiredTotalProfit: ratio ? requiredProfit / (ratio / 100) : 0,
            feasible: investment > 0 && months > 0 && investorProfit >= requiredProfit,
            impossible: totalProfit > 0 && minimumRatio > 100,
            partnerRatio: 100 - ratio,
        };
    }

    get statusText() {
        if (this.result.impossible) {
            return "Not feasible at any profit split";
        }
        return this.result.feasible ? "Project is feasible" : "Project is not feasible";
    }

    updateNumber(field, event) {
        if (event.target.value === "") {
            this.state.form[field] = "";
            return;
        }
        let value = this.number(event.target.value);
        if (field === "investor_ratio") {
            value = Math.max(1, Math.min(value, 100));
        } else if (field === "duration_months") {
            value = Math.max(1, Math.min(Math.round(value), 120));
        } else if (field === "expected_monthly_rate") {
            value = Math.max(value, 0);
        }
        this.state.form[field] = value;
        event.target.value = value;
    }

    finalizeNumber(field, event) {
        if (event.target.value !== "") {
            this.updateNumber(field, event);
            return;
        }
        const minimums = {
            investor_ratio: 1,
            duration_months: 1,
            expected_monthly_rate: 0,
        };
        const value = minimums[field] ?? 0;
        this.state.form[field] = value;
        event.target.value = value;
    }

    updateAmount(field, event) {
        const rawValue = String(event.target.value || "").replace(/[^\d.-]/g, "");
        const value = this.number(rawValue);
        this.state.form[field] = value;
        event.target.value = this.formatInputAmount(value);
    }

    formatInputAmount(value) {
        return this.number(value).toLocaleString("en-US", {
            maximumFractionDigits: 2,
        });
    }

    updateText(field, event) {
        this.state.form[field] = event.target.value;
    }

    setMode(mode) {
        this.state.mode = mode;
    }

    formatMoney(value) {
        return new Intl.NumberFormat(undefined, {
            style: "currency",
            currency: this.state.currency.name || "SAR",
            maximumFractionDigits: 2,
        }).format(this.number(value));
    }

    formatPercent(value) {
        return `${this.number(value).toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        })}%`;
    }

    payload() {
        return {
            id: this.state.form.id || false,
            project_name: this.state.form.project_name || "New Project",
            investment_amount: this.number(this.state.form.investment_amount),
            total_project_amount: this.number(this.state.form.total_project_amount),
            projected_total_profit: this.number(this.state.form.projected_total_profit),
            investor_ratio: Math.max(
                1,
                Math.min(this.number(this.state.form.investor_ratio), 100)
            ),
            expected_monthly_rate: Math.max(
                this.number(this.state.form.expected_monthly_rate),
                0
            ),
            duration_months: Math.max(
                1,
                Math.min(Math.round(this.number(this.state.form.duration_months)), 120)
            ),
            notes: this.state.form.notes || "",
        };
    }

    async save() {
        this.state.busy = true;
        try {
            const saved = await this.orm.call(
                "project.feasibility.calculation",
                "save_calculation",
                [this.payload()]
            );
            Object.assign(this.state.form, saved);
            await this.loadData();
            this.notification.add(`${saved.name} saved successfully.`, {
                type: "success",
            });
            return saved;
        } finally {
            this.state.busy = false;
        }
    }

    async exportXlsx() {
        const saved = await this.save();
        window.open(`/project-feasibility/${saved.id}/xlsx`, "_blank", "noopener");
    }

    loadRecord(record) {
        Object.assign(this.state.form, record);
        window.scrollTo({ top: 0, behavior: "smooth" });
    }

    newCalculation() {
        this.state.form = { ...DEFAULTS };
        this.state.mode = "forward";
    }

    openRecord(record) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.feasibility.calculation",
            res_id: record.id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add(
    "pr_project_feasibility_calculator.main",
    ProjectFeasibilityCalculator
);
