from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class AccountAnalyticAccount(models.Model):
    _inherit = "account.analytic.account"

    expense_bucket_id = fields.Many2one(
        "pr.expense.bucket",
        string="Expense",
        help="Expense bucket (Capex/Opex for Department/Project) this cost center belongs to.",
    )

    budget_type = fields.Selection(
        [("opex", "Opex"), ("capex", "Capex")],
        string="Budget Type",
    )
    budget_code = fields.Char(string="Budget Code")
    budget_allowance = fields.Float(string="Budget Allowance")
    budget_spent = fields.Float(string="Budget Spent", compute="_compute_budget_metrics", store=False)
    budget_left = fields.Float(string="Budget Left", compute="_compute_budget_metrics", store=False)

    def _date_in_period(self, value, date_from=False, date_to=False):
        if not value:
            return True
        value_date = fields.Date.to_date(value)
        if date_from and value_date < fields.Date.to_date(date_from):
            return False
        if date_to and value_date > fields.Date.to_date(date_to):
            return False
        return True

    def _get_budget_allowance_map(self, date_from=False, date_to=False, active_on=False, expense_type=False):
        analytic_ids = set(self.ids)
        allowance_by_analytic = {analytic_id: 0.0 for analytic_id in analytic_ids}
        if not analytic_ids:
            return allowance_by_analytic

        BudgetLine = self.env["crossovered.budget.lines"].sudo()
        domain = [
            ("analytic_account_id", "in", list(analytic_ids)),
            ("crossovered_budget_id.state", "in", ["validate", "done"]),
        ]
        if expense_type:
            domain.append(("crossovered_budget_id.expense_type", "=", expense_type))
        if active_on:
            active_on = fields.Date.to_date(active_on)
            domain += [
                ("date_from", "<=", active_on),
                ("date_to", ">=", active_on),
            ]
        else:
            if date_from:
                domain.append(("date_to", ">=", fields.Date.to_date(date_from)))
            if date_to:
                domain.append(("date_from", "<=", fields.Date.to_date(date_to)))

        grouped = BudgetLine.read_group(
            domain=domain,
            fields=["analytic_account_id", "planned_amount:sum"],
            groupby=["analytic_account_id"],
            lazy=False,
        )
        for item in grouped:
            analytic = item.get("analytic_account_id")
            if analytic:
                allowance_by_analytic[analytic[0]] = item.get(
                    "planned_amount_sum",
                    item.get("planned_amount", 0.0),
                )
        return allowance_by_analytic

    def _get_po_budget_spent_map(self, date_from=False, date_to=False):
        """Return committed/spent budget by analytic account.

        Purchase Orders consume budget through PO lines. Cash PR vouchers
        consume budget through CPV/BPV lines once submitted into accounting
        approval. When a date range is supplied, only documents inside that
        budget period consume that budget.
        """
        analytic_ids = set(self.ids)
        spent_by_analytic = {analytic_id: 0.0 for analytic_id in analytic_ids}
        if not analytic_ids:
            return spent_by_analytic

        def add_distributed_amount(distribution, amount):
            if not distribution:
                return
            for analytic_key, percentage in distribution.items():
                try:
                    percentage = float(percentage or 0.0)
                except (TypeError, ValueError):
                    percentage = 0.0
                if not percentage:
                    continue
                for key_part in str(analytic_key).split(","):
                    if not key_part.strip().isdigit():
                        continue
                    analytic_id = int(key_part)
                    if analytic_id in spent_by_analytic:
                        spent_by_analytic[analytic_id] += amount * (percentage / 100.0)

        PurchaseOrderLine = self.env["purchase.order.line"].sudo()
        po_lines = PurchaseOrderLine.search([
            ("order_id.state", "in", ["pending", "purchase", "done"]),
            ("analytic_distribution", "!=", False),
        ])
        for line in po_lines:
            order = line.order_id
            order_date = order.date_order or order.date_approve or line.create_date
            if not self._date_in_period(order_date, date_from, date_to):
                continue
            distribution = line.analytic_distribution or {}
            if not distribution:
                continue

            amount = line.price_subtotal or 0.0
            line_currency = order.currency_id or line.company_id.currency_id
            company_currency = line.company_id.currency_id
            if line_currency and company_currency and line_currency != company_currency:
                amount = line_currency._convert(
                    amount,
                    company_currency,
                    line.company_id,
                    order.date_order or fields.Date.context_today(line),
                )

            add_distributed_amount(distribution, amount)

        voucher_sources = [
            ("pr.account.cash.payment.line", "cash_payment_id"),
            ("pr.account.bank.payment.line", "bank_payment_id"),
        ]
        for model_name, parent_field in voucher_sources:
            if model_name not in self.env:
                continue
            voucher_lines = self.env[model_name].sudo().search([
                ("%s.state" % parent_field, "in", ["submit", "finance_approve", "posted"]),
                ("analytic_distribution", "!=", False),
            ])
            for line in voucher_lines:
                parent = line[parent_field]
                voucher_date = (
                    getattr(parent, "accounting_date", False)
                    or getattr(parent, "date", False)
                    or parent.create_date
                )
                if not self._date_in_period(voucher_date, date_from, date_to):
                    continue
                add_distributed_amount(line.analytic_distribution or {}, line.amount or 0.0)

        return spent_by_analytic

    def _get_budget_metrics_map(self, date_from=False, date_to=False, active_on=False, expense_type=False):
        if active_on and not date_from and not date_to:
            active_on = fields.Date.to_date(active_on)
            BudgetLine = self.env["crossovered.budget.lines"].sudo()
            domain = [
                ("analytic_account_id", "in", self.ids),
                ("crossovered_budget_id.state", "in", ["validate", "done"]),
                ("date_from", "<=", active_on),
                ("date_to", ">=", active_on),
            ]
            if expense_type:
                domain.append(("crossovered_budget_id.expense_type", "=", expense_type))
            active_lines = BudgetLine.search(domain)
            metrics = {}
            for analytic in self:
                lines = active_lines.filtered(lambda line: line.analytic_account_id.id == analytic.id)
                allowance = sum(lines.mapped("planned_amount"))
                if allowance:
                    period_start = min(lines.mapped("date_from"))
                    period_end = max(lines.mapped("date_to"))
                    spent = analytic._get_po_budget_spent_map(
                        date_from=period_start,
                        date_to=period_end,
                    ).get(analytic.id, 0.0)
                else:
                    spent = 0.0
                metrics[analytic.id] = {
                    "allowance": allowance,
                    "spent": spent,
                    "remaining": allowance - spent,
                }
            return metrics

        allowance_by_analytic = self._get_budget_allowance_map(
            date_from=date_from,
            date_to=date_to,
            active_on=active_on,
            expense_type=expense_type,
        )
        spent_by_analytic = self._get_po_budget_spent_map(date_from=date_from, date_to=date_to)
        metrics = {}
        for analytic in self:
            allowance = allowance_by_analytic.get(analytic.id, 0.0)
            spent = spent_by_analytic.get(analytic.id, 0.0) if allowance else 0.0
            metrics[analytic.id] = {
                "allowance": allowance,
                "spent": spent,
                "remaining": allowance - spent,
            }
        return metrics

    @api.depends("budget_allowance", "budget_code", "budget_type")
    def _compute_budget_metrics(self):
        today = fields.Date.context_today(self)
        metrics = self.sudo()._get_budget_metrics_map(active_on=today)
        for rec in self:
            metric = metrics.get(rec.id, {})
            effective_allowance = metric.get("allowance", 0.0)
            spent = metric.get("spent", 0.0)
            rec.budget_spent = spent
            rec.budget_left = effective_allowance - spent

    @api.model
    def get_cost_center_budget(self, budget_type, budget_code):
        if not budget_type or not budget_code:
            return False

        return self.sudo().search([
            ("budget_type", "=", budget_type),
            ("budget_code", "=", budget_code),
        ], limit=1)

    @api.model
    def validate_budget_or_raise(self, budget_type, budget_code, required_amount=0.0):
        rec = self.get_cost_center_budget(budget_type, budget_code)
        if not rec:
            raise ValidationError(_("No cost center found for the selected budget type/code."))

        if rec.budget_left <= 0:
            raise ValidationError(_("No budget left for cost center %s.") % (rec.budget_code or rec.display_name))

        if required_amount and rec.budget_left < required_amount:
            raise ValidationError(
                _("Insufficient budget for cost center %s. Remaining: %s, Required: %s")
                % (rec.budget_code or rec.display_name, rec.budget_left, required_amount)
            )

        return rec

    @api.constrains("budget_allowance", "expense_bucket_id")
    def _check_budget_within_bucket(self):
        for rec in self:
            if not rec.expense_bucket_id:
                continue
            bucket = rec.expense_bucket_id
            total = sum(bucket.line_ids.mapped("budget_allowance"))
            if total > bucket.budget_amount:
                raise ValidationError(
                    _("Total cost center budget (%s) cannot exceed bucket budget (%s).")
                    % (total, bucket.budget_amount)
                )
