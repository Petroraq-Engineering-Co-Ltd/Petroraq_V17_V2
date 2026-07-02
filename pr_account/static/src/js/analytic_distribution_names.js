/** @odoo-module **/

import {
    AnalyticDistribution,
} from "@analytic/components/analytic_distribution/analytic_distribution";
import { patch } from "@web/core/utils/patch";

const ACCOUNTING_ANALYTIC_MODELS = new Set([
    "account.move.line",
    "pr.account.bank.payment",
    "pr.account.bank.payment.line",
    "pr.account.bank.receipt",
    "pr.account.bank.receipt.line",
    "pr.account.cash.payment",
    "pr.account.cash.payment.line",
    "pr.account.cash.receipt",
    "pr.account.cash.receipt.line",
    "pr.payment.receipt",
    "pr.transaction.payment",
]);

patch(AnalyticDistribution.prototype, {
    get showPrAnalyticAccountName() {
        return ACCOUNTING_ANALYTIC_MODELS.has(this.props.record.resModel);
    },

    get prAnalyticAccountContext() {
        return this.showPrAnalyticAccountName
            ? "{'show_analytic_name': True}"
            : "{}";
    },

    async fetchAnalyticAccounts(domain) {
        if (!this.showPrAnalyticAccountName) {
            return super.fetchAnalyticAccounts(domain);
        }

        const fields = ["id", "display_name", "root_plan_id", "color"];
        const records = await this.batchedOrm.read(
            "account.analytic.account",
            domain[0][2],
            fields,
            { context: { show_analytic_name: true } }
        );
        return Object.assign(
            {},
            ...records.map(({ id, ...values }) => ({ [id]: values }))
        );
    },
});
