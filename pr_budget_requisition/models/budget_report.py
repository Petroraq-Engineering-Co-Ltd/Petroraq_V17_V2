from collections import OrderedDict

from odoo import _, api, fields, models


class PrBudgetReportWizard(models.TransientModel):
    _name = "pr.budget.report.wizard"
    _description = "Budget Analysis Report Wizard"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
    )
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id", readonly=True)
    date_from = fields.Date(
        string="Budget From",
        default=lambda self: fields.Date.context_today(self).replace(month=1, day=1),
        required=True,
    )
    date_to = fields.Date(
        string="Budget To",
        default=lambda self: fields.Date.context_today(self).replace(month=12, day=31),
        required=True,
    )
    department_ids = fields.Many2many("hr.department", string="Departments")
    expense_type = fields.Selection(
        [("opex", "Opex"), ("capex", "Capex")],
        string="Expense Type",
    )
    scope = fields.Selection(
        [("department", "Department"), ("project", "Project"), ("trading", "Trading")],
        string="Applies To",
        default="department",
    )
    budget_state = fields.Selection(
        [("approved", "Approved / Active"), ("all", "All Budgets")],
        string="Budget Status",
        default="approved",
        required=True,
    )
    line_ids = fields.One2many("pr.budget.report.line", "wizard_id", string="Report Lines")

    def _selection_label(self, record, field_name):
        field = record._fields.get(field_name)
        if not field:
            return record[field_name] or ""
        selection = field.selection
        if callable(selection):
            selection = selection(record)
        return dict(selection).get(record[field_name], record[field_name] or "")

    def _budget_domain(self):
        self.ensure_one()
        domain = [("company_id", "=", self.company_id.id)]
        if self.budget_state == "approved":
            domain.append(("state", "in", ["validate", "done"]))
        if self.date_from:
            domain.append(("date_to", ">=", self.date_from))
        if self.date_to:
            domain.append(("date_from", "<=", self.date_to))
        if self.department_ids:
            domain.append(("department_id", "in", self.department_ids.ids))
        if self.expense_type:
            domain.append(("expense_type", "=", self.expense_type))
        if self.scope:
            domain.append(("scope", "=", self.scope))
        return domain

    def _date_in_period(self, value, date_from=False, date_to=False):
        if not value:
            return True
        value_date = fields.Date.to_date(value)
        if date_from and value_date < fields.Date.to_date(date_from):
            return False
        if date_to and value_date > fields.Date.to_date(date_to):
            return False
        return True

    def _amount_for_analytic_distribution(self, distribution, analytic_id, amount):
        if not distribution or not analytic_id:
            return 0.0
        total = 0.0
        for analytic_key, percentage in distribution.items():
            try:
                percentage = float(percentage or 0.0)
            except (TypeError, ValueError):
                percentage = 0.0
            if not percentage:
                continue
            analytic_ids = [
                int(key_part)
                for key_part in str(analytic_key).split(",")
                if key_part.strip().isdigit()
            ]
            if analytic_id in analytic_ids:
                total += (amount or 0.0) * (percentage / 100.0)
        return total

    def _get_spend_breakdown(self, analytic, date_from, date_to):
        self.ensure_one()
        po_spent = 0.0
        cash_spent = 0.0
        bank_spent = 0.0
        po_ids = set()
        cash_ids = set()
        bank_ids = set()

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

            line_spent = self._amount_for_analytic_distribution(
                line.analytic_distribution or {},
                analytic.id,
                amount,
            )
            if line_spent:
                po_spent += line_spent
                po_ids.add(order.id)

        voucher_sources = [
            ("pr.account.cash.payment.line", "cash_payment_id", cash_ids, "cash"),
            ("pr.account.bank.payment.line", "bank_payment_id", bank_ids, "bank"),
        ]
        for model_name, parent_field, ids_set, spend_type in voucher_sources:
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

                spent = self._amount_for_analytic_distribution(
                    line.analytic_distribution or {},
                    analytic.id,
                    line.amount or 0.0,
                )
                if not spent:
                    continue
                ids_set.add(parent.id)
                if spend_type == "cash":
                    cash_spent += spent
                else:
                    bank_spent += spent

        return {
            "po_spent": po_spent,
            "cash_spent": cash_spent,
            "bank_spent": bank_spent,
            "po_count": len(po_ids),
            "cash_voucher_count": len(cash_ids),
            "bank_voucher_count": len(bank_ids),
        }

    def _refresh_report_lines(self):
        self.ensure_one()
        self.line_ids.unlink()

        Budget = self.env["crossovered.budget"].sudo()
        Requisition = self.env["pr.budget.requisition"].sudo()
        budgets = Budget.search(self._budget_domain(), order="date_from desc, id desc")
        requisitions = Requisition.search([
            ("generated_budget_id", "in", budgets.ids),
            ("state", "=", "approved"),
        ], order="id desc")
        requisition_by_budget = {}
        for requisition in requisitions:
            if requisition.generated_budget_id:
                requisition_by_budget.setdefault(requisition.generated_budget_id.id, requisition)

        vals_list = []
        for budget in budgets:
            source_requisition = requisition_by_budget.get(budget.id)
            for budget_line in budget.crossovered_budget_line.filtered("analytic_account_id"):
                line_date_from = budget_line.date_from or budget.date_from
                line_date_to = budget_line.date_to or budget.date_to
                if self.date_from and line_date_to and line_date_to < self.date_from:
                    continue
                if self.date_to and line_date_from and line_date_from > self.date_to:
                    continue

                analytic = budget_line.analytic_account_id.sudo()
                breakdown = self._get_spend_breakdown(analytic, line_date_from, line_date_to)
                spent_amount = (
                    breakdown["po_spent"]
                    + breakdown["cash_spent"]
                    + breakdown["bank_spent"]
                )
                planned_amount = budget_line.planned_amount or 0.0
                remaining_amount = planned_amount - spent_amount
                utilization_rate = (spent_amount / planned_amount * 100.0) if planned_amount else 0.0

                vals_list.append({
                    "wizard_id": self.id,
                    "company_id": budget.company_id.id,
                    "currency_id": budget.company_id.currency_id.id,
                    "budget_id": budget.id,
                    "budget_line_id": budget_line.id,
                    "source_requisition_id": source_requisition.id if source_requisition else False,
                    "department_id": budget.department_id.id if budget.department_id else False,
                    "department_manager_user_id": budget.department_manager_user_id.id if budget.department_manager_user_id else False,
                    "cost_center_id": analytic.id,
                    "expense_type": budget.expense_type,
                    "scope": budget.scope,
                    "budget_period_months": getattr(budget, "budget_period_months", False),
                    "date_from": line_date_from,
                    "date_to": line_date_to,
                    "budget_state": budget.state,
                    "approval_state": getattr(budget, "approval_state", False),
                    "planned_amount": planned_amount,
                    "requested_amount": source_requisition.total_requested_amount if source_requisition else 0.0,
                    "spent_amount": spent_amount,
                    "po_spent_amount": breakdown["po_spent"],
                    "cash_spent_amount": breakdown["cash_spent"],
                    "bank_spent_amount": breakdown["bank_spent"],
                    "remaining_amount": remaining_amount,
                    "utilization_rate": utilization_rate,
                    "po_count": breakdown["po_count"],
                    "cash_voucher_count": breakdown["cash_voucher_count"],
                    "bank_voucher_count": breakdown["bank_voucher_count"],
                })

        if vals_list:
            self.env["pr.budget.report.line"].create(vals_list)
        return self.line_ids

    def action_generate_report(self):
        self.ensure_one()
        self._refresh_report_lines()

        return {
            "type": "ir.actions.act_window",
            "name": _("Budget Analysis Report"),
            "res_model": "pr.budget.report.line",
            "view_mode": "tree,pivot,graph",
            "domain": [("wizard_id", "=", self.id)],
            "context": {
                "search_default_group_department": 1,
                "search_default_group_budget": 1,
            },
            "target": "current",
        }

    def action_print_pdf(self):
        self.ensure_one()
        self._refresh_report_lines()
        return self.env.ref("pr_budget_requisition.action_report_pr_budget_analysis_pdf").report_action(self)

    def action_print_xlsx(self):
        self.ensure_one()
        self._refresh_report_lines()
        return self.env.ref("pr_budget_requisition.action_report_pr_budget_analysis_xlsx").report_action(self)

    def _report_lines(self):
        self.ensure_one()
        if not self.line_ids:
            self._refresh_report_lines()
        return self.line_ids.sorted(
            key=lambda line: (
                line.department_id.display_name or "",
                line.budget_id.display_name or "",
                line.cost_center_id.display_name or "",
                line.id,
            )
        )

    def _get_report_filters(self):
        self.ensure_one()
        return {
            "company": self.company_id.display_name or "",
            "date_from": self.date_from,
            "date_to": self.date_to,
            "budget_state": self._selection_label(self, "budget_state"),
            "scope": self._selection_label(self, "scope") if self.scope else _("All"),
            "expense_type": self._selection_label(self, "expense_type") if self.expense_type else _("All"),
            "departments": ", ".join(self.department_ids.mapped("display_name")) if self.department_ids else _("All"),
            "currency": self.currency_id.name or "",
            "generated_on": fields.Date.context_today(self),
        }

    def _get_report_summary(self):
        self.ensure_one()
        lines = self._report_lines()
        planned = sum(lines.mapped("planned_amount"))
        requested = sum(lines.mapped("requested_amount"))
        spent = sum(lines.mapped("spent_amount"))
        po_spent = sum(lines.mapped("po_spent_amount"))
        cash_spent = sum(lines.mapped("cash_spent_amount"))
        bank_spent = sum(lines.mapped("bank_spent_amount"))
        remaining = sum(lines.mapped("remaining_amount"))
        return {
            "budget_count": len(set(lines.mapped("budget_id").ids)),
            "requisition_count": len(set(lines.mapped("source_requisition_id").ids)),
            "department_count": len(set(lines.mapped("department_id").ids)),
            "cost_center_count": len(set(lines.mapped("cost_center_id").ids)),
            "planned_amount": planned,
            "requested_amount": requested,
            "spent_amount": spent,
            "po_spent_amount": po_spent,
            "cash_spent_amount": cash_spent,
            "bank_spent_amount": bank_spent,
            "remaining_amount": remaining,
            "utilization_rate": (spent / planned * 100.0) if planned else 0.0,
            "po_count": sum(lines.mapped("po_count")),
            "cash_voucher_count": sum(lines.mapped("cash_voucher_count")),
            "bank_voucher_count": sum(lines.mapped("bank_voucher_count")),
        }

    def _spend_documents_for_line(self, report_line):
        self.ensure_one()
        analytic = report_line.cost_center_id.sudo()
        if not analytic:
            return []

        documents = []
        PurchaseOrderLine = self.env["purchase.order.line"].sudo()
        po_lines = PurchaseOrderLine.search([
            ("order_id.state", "in", ["pending", "purchase", "done"]),
            ("analytic_distribution", "!=", False),
        ])
        for po_line in po_lines:
            order = po_line.order_id
            order_date = order.date_order or order.date_approve or po_line.create_date
            if not self._date_in_period(order_date, report_line.date_from, report_line.date_to):
                continue

            amount = po_line.price_subtotal or 0.0
            line_currency = order.currency_id or po_line.company_id.currency_id
            company_currency = po_line.company_id.currency_id
            if line_currency and company_currency and line_currency != company_currency:
                amount = line_currency._convert(
                    amount,
                    company_currency,
                    po_line.company_id,
                    order.date_order or fields.Date.context_today(po_line),
                )

            spent = self._amount_for_analytic_distribution(po_line.analytic_distribution or {}, analytic.id, amount)
            if not spent:
                continue
            documents.append({
                "source": _("Purchase Order"),
                "document": order.name or "",
                "date": fields.Date.to_date(order_date),
                "state": self._selection_label(order, "state"),
                "partner": order.partner_id.display_name or "",
                "description": po_line.product_id.display_name or po_line.name or "",
                "amount": spent,
                "cost_center": analytic.display_name or "",
                "budget": report_line.budget_id.display_name or "",
                "requisition": report_line.source_requisition_id.display_name or "",
            })

        voucher_sources = [
            ("pr.account.cash.payment.line", "cash_payment_id", _("Cash Payment Voucher")),
            ("pr.account.bank.payment.line", "bank_payment_id", _("Bank Payment Voucher")),
        ]
        for model_name, parent_field, source_label in voucher_sources:
            if model_name not in self.env:
                continue
            voucher_lines = self.env[model_name].sudo().search([
                ("%s.state" % parent_field, "in", ["submit", "finance_approve", "posted"]),
                ("analytic_distribution", "!=", False),
            ])
            for voucher_line in voucher_lines:
                parent = voucher_line[parent_field]
                voucher_date = (
                    getattr(parent, "accounting_date", False)
                    or getattr(parent, "date", False)
                    or parent.create_date
                )
                if not self._date_in_period(voucher_date, report_line.date_from, report_line.date_to):
                    continue
                spent = self._amount_for_analytic_distribution(
                    voucher_line.analytic_distribution or {},
                    analytic.id,
                    voucher_line.amount or 0.0,
                )
                if not spent:
                    continue
                parent_partner = getattr(parent, "partner_id", False)
                documents.append({
                    "source": source_label,
                    "document": parent.name or "",
                    "date": fields.Date.to_date(voucher_date),
                    "state": self._selection_label(parent, "state") if "state" in parent._fields else "",
                    "partner": voucher_line.partner_id.display_name or (parent_partner.display_name if parent_partner else ""),
                    "description": voucher_line.description or voucher_line.account_id.display_name or "",
                    "amount": spent,
                    "cost_center": analytic.display_name or "",
                    "budget": report_line.budget_id.display_name or "",
                    "requisition": report_line.source_requisition_id.display_name or "",
                })

        return documents

    def _get_budget_report_groups(self, include_spend_documents=False):
        self.ensure_one()
        grouped = OrderedDict()
        for line in self._report_lines():
            key = line.budget_id.id or line.id
            grouped.setdefault(key, {
                "budget": line.budget_id,
                "budget_name": line.budget_id.display_name or _("No Budget"),
                "source_requisition": line.source_requisition_id,
                "source_requisition_name": line.source_requisition_id.display_name or "",
                "department": line.department_id,
                "department_name": line.department_id.display_name or "",
                "manager_name": line.department_manager_user_id.display_name or "",
                "expense_type_label": self._selection_label(line, "expense_type") if line.expense_type else "",
                "scope_label": self._selection_label(line, "scope") if line.scope else "",
                "period_label": self._selection_label(line, "budget_period_months") if line.budget_period_months else "",
                "budget_state_label": self._selection_label(line, "budget_state") if line.budget_state else "",
                "approval_state_label": self._selection_label(line, "approval_state") if line.approval_state else "",
                "date_from": line.date_from,
                "date_to": line.date_to,
                "lines": self.env["pr.budget.report.line"],
                "items": line.source_requisition_id.line_ids if line.source_requisition_id else self.env["pr.budget.requisition.line"],
                "planned_amount": 0.0,
                "requested_amount": 0.0,
                "spent_amount": 0.0,
                "po_spent_amount": 0.0,
                "cash_spent_amount": 0.0,
                "bank_spent_amount": 0.0,
                "remaining_amount": 0.0,
                "po_count": 0,
                "cash_voucher_count": 0,
                "bank_voucher_count": 0,
                "spend_documents": [],
            })
            group = grouped[key]
            group["lines"] |= line
            group["planned_amount"] += line.planned_amount or 0.0
            group["requested_amount"] = max(group["requested_amount"], line.requested_amount or 0.0)
            group["spent_amount"] += line.spent_amount or 0.0
            group["po_spent_amount"] += line.po_spent_amount or 0.0
            group["cash_spent_amount"] += line.cash_spent_amount or 0.0
            group["bank_spent_amount"] += line.bank_spent_amount or 0.0
            group["remaining_amount"] += line.remaining_amount or 0.0
            group["po_count"] += line.po_count or 0
            group["cash_voucher_count"] += line.cash_voucher_count or 0
            group["bank_voucher_count"] += line.bank_voucher_count or 0
            if include_spend_documents:
                group["spend_documents"].extend(self._spend_documents_for_line(line))

        for group in grouped.values():
            planned = group["planned_amount"]
            group["utilization_rate"] = (group["spent_amount"] / planned * 100.0) if planned else 0.0
        return list(grouped.values())


class PrBudgetReportLine(models.TransientModel):
    _name = "pr.budget.report.line"
    _description = "Budget Analysis Report Line"
    _order = "date_from desc, department_id, budget_id, cost_center_id"

    wizard_id = fields.Many2one("pr.budget.report.wizard", required=True, ondelete="cascade")
    company_id = fields.Many2one("res.company", string="Company", readonly=True)
    currency_id = fields.Many2one("res.currency", string="Currency", readonly=True)
    budget_id = fields.Many2one("crossovered.budget", string="Budget", readonly=True)
    budget_line_id = fields.Many2one("crossovered.budget.lines", string="Budget Line", readonly=True)
    source_requisition_id = fields.Many2one("pr.budget.requisition", string="Source Requisition", readonly=True)
    department_id = fields.Many2one("hr.department", string="Department", readonly=True)
    department_manager_user_id = fields.Many2one("res.users", string="Department Manager", readonly=True)
    cost_center_id = fields.Many2one("account.analytic.account", string="Cost Center", readonly=True)
    expense_type = fields.Selection(
        [("opex", "Opex"), ("capex", "Capex")],
        string="Expense Type",
        readonly=True,
    )
    scope = fields.Selection(
        [("department", "Department"), ("project", "Project"), ("trading", "Trading")],
        string="Applies To",
        readonly=True,
    )
    budget_period_months = fields.Selection(
        [("3", "3 Months"), ("6", "6 Months"), ("12", "12 Months")],
        string="Budget Period",
        readonly=True,
    )
    date_from = fields.Date(string="Start Date", readonly=True)
    date_to = fields.Date(string="End Date", readonly=True)
    budget_state = fields.Selection(
        [
            ("draft", "Draft"),
            ("cancel", "Cancelled"),
            ("confirm", "Confirmed"),
            ("validate", "Validated"),
            ("done", "Done"),
        ],
        string="Budget Status",
        readonly=True,
    )
    approval_state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pm_approval", "Pending Department/Project Manager"),
            ("accounts_approval", "Pending Accounts"),
            ("md_approval", "Pending Managing Director"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="Approval Stage",
        readonly=True,
    )
    planned_amount = fields.Monetary(string="Budget Created", currency_field="currency_id", readonly=True)
    requested_amount = fields.Monetary(string="Requested Amount", currency_field="currency_id", readonly=True)
    spent_amount = fields.Monetary(string="Total Spent", currency_field="currency_id", readonly=True)
    po_spent_amount = fields.Monetary(string="PO Spend", currency_field="currency_id", readonly=True)
    cash_spent_amount = fields.Monetary(string="CPV Spend", currency_field="currency_id", readonly=True)
    bank_spent_amount = fields.Monetary(string="BPV Spend", currency_field="currency_id", readonly=True)
    remaining_amount = fields.Monetary(string="Budget Remaining", currency_field="currency_id", readonly=True)
    utilization_rate = fields.Float(string="Utilization %", readonly=True)
    po_count = fields.Integer(string="PO Count", readonly=True)
    cash_voucher_count = fields.Integer(string="CPV Count", readonly=True)
    bank_voucher_count = fields.Integer(string="BPV Count", readonly=True)
