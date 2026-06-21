from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


BUDGET_SEQUENCE_START = 1001


class CrossoveredBudget(models.Model):
    _inherit = "crossovered.budget"
    _rec_name = "budget_sequence"

    budget_sequence = fields.Char(string="Budget Code", readonly=True, default='New')
    budget_period_months = fields.Selection(
        [("3", "3 Months"), ("6", "6 Months"), ("12", "12 Months")],
        string="Budget Period",
    )
    expense_type = fields.Selection(
        [("opex", "Opex"), ("capex", "Capex")],
        string="Expense Type",
        required=True,
    )
    scope = fields.Selection(
        [("department", "Department"), ("project", "Project"), ("trading", "Trading")],
        string="Applies To",
    )
    department_id = fields.Many2one("hr.department", string="Department")
    department_manager_user_id = fields.Many2one(
        "res.users",
        string="Department Manager",
        related="department_id.manager_id.user_id",
        readonly=True,
    )
    source_budget_limit = fields.Float(string="Source Budget Limit")
    po_reference = fields.Char(string="PO Reference")
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
        default="draft",
        tracking=True,
    )
    pr_under_revision = fields.Boolean(
        string="Under Revision",
        compute="_compute_pr_under_revision",
        search="_search_pr_under_revision",
        help="Enabled while the Budget Requisition linked to this budget is being revised.",
    )
    can_pm_approve = fields.Boolean(compute="_compute_role_flags")
    can_accounts_approve = fields.Boolean(compute="_compute_role_flags")
    can_md_approve = fields.Boolean(compute="_compute_role_flags")
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id", readonly=True)
    budget_amount_total = fields.Monetary(
        string="Total Amount",
        currency_field="currency_id",
        compute="_compute_po_budget_metrics",
    )
    po_spent_amount = fields.Monetary(
        string="Spent Amount",
        currency_field="currency_id",
        compute="_compute_po_budget_metrics",
        help="Amount consumed by PRs, purchase orders, and submitted/approved payment vouchers linked to this exact budget.",
    )
    budget_remaining_amount = fields.Monetary(
        string="Remaining Amount",
        currency_field="currency_id",
        compute="_compute_po_budget_metrics",
    )
    expensed_amount = fields.Monetary(
        string="Expensed Amount",
        currency_field="currency_id",
        compute="_compute_po_budget_metrics",
        help="Actual posted analytic/accounting items represented by the budget lines' practical amount.",
    )
    custom_pr_ids = fields.Many2many(
        "custom.pr",
        string="Custom PRs",
        compute="_compute_procurement_documents",
    )
    purchase_requisition_ids = fields.Many2many(
        "purchase.requisition",
        string="Purchase Requisitions",
        compute="_compute_procurement_documents",
    )
    budget_rfq_ids = fields.Many2many(
        "purchase.order",
        "crossovered_budget_rfq_rel",
        "budget_id",
        "purchase_order_id",
        string="RFQs",
        compute="_compute_procurement_documents",
    )
    budget_purchase_order_ids = fields.Many2many(
        "purchase.order",
        "crossovered_budget_po_rel",
        "budget_id",
        "purchase_order_id",
        string="Purchase Orders",
        compute="_compute_procurement_documents",
    )
    custom_pr_count = fields.Integer(compute="_compute_procurement_documents")
    purchase_requisition_count = fields.Integer(compute="_compute_procurement_documents")
    rfq_count = fields.Integer(compute="_compute_procurement_documents")
    purchase_order_count = fields.Integer(compute="_compute_procurement_documents")

    def name_get(self):
        result = []
        for rec in self:
            if rec.budget_sequence and rec.name:
                display_name = f"{rec.budget_sequence} - {rec.name}"
            else:
                display_name = rec.budget_sequence or rec.name or _("New Budget")
            result.append((rec.id, display_name))
        return result

    @api.model
    def _pr_budget_revision_lock_states(self):
        return ("draft", "department_approval", "accounts_approval", "md_approval")

    @api.model
    def _get_pr_under_revision_budget_ids(self):
        if "pr.budget.requisition" not in self.env:
            return []
        requisitions = self.env["pr.budget.requisition"].sudo().search([
            ("generated_budget_id", "!=", False),
            ("revision_number", ">", 0),
            ("state", "in", self._pr_budget_revision_lock_states()),
        ])
        return requisitions.mapped("generated_budget_id").ids

    def _compute_pr_under_revision(self):
        locked_budget_ids = set(self._get_pr_under_revision_budget_ids())
        for rec in self:
            rec.pr_under_revision = rec.id in locked_budget_ids

    @api.model
    def _search_pr_under_revision(self, operator, value):
        if operator not in ("=", "!="):
            raise UserError(_("Unsupported search operator for Under Revision."))
        locked_budget_ids = self._get_pr_under_revision_budget_ids()
        search_true = (operator == "=" and bool(value)) or (operator == "!=" and not bool(value))
        return [("id", "in" if search_true else "not in", locked_budget_ids)]

    @api.model
    def _split_yearly_budget_code(self, code):
        if not code or "-" not in code:
            return False, False
        year, number = code.split("-", 1)
        if len(year) != 4 or not year.isdigit() or not number.isdigit():
            return False, False
        return int(year), int(number)

    @api.model
    def _format_yearly_budget_code(self, year, number):
        return "%s-%04d" % (year, number)

    @api.model
    def _budget_code_year(self, value=False):
        value = value or self.env.context.get("pr_budget_code_date") or fields.Date.context_today(self)
        return fields.Date.to_date(value).year

    @api.model
    def _last_budget_number(self):
        last_number = BUDGET_SEQUENCE_START - 1
        budgets = self.with_context(active_test=False).sudo().search([("budget_sequence", "!=", False)])
        for budget in budgets:
            _year, number = self._split_yearly_budget_code(budget.budget_sequence)
            if number:
                last_number = max(last_number, number)
        return last_number

    @api.constrains("budget_sequence")
    def _check_budget_sequence(self):
        if self.env.context.get("skip_budget_sequence_check"):
            return
        for rec in self:
            if not rec.budget_sequence or rec.budget_sequence in ("/", _("New"), "New"):
                raise ValidationError(_("Budget Code is required."))
            duplicate = self.sudo().search([
                ("budget_sequence", "=", rec.budget_sequence),
                ("id", "!=", rec.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    _("Budget Code %(code)s already exists on %(budget)s.")
                    % {"code": rec.budget_sequence, "budget": duplicate.display_name}
                )

    @api.model
    def action_resequence_budget_codes(self):
        records = self.with_context(active_test=False).sudo().search([], order="date_from, create_date, id")
        counter = BUDGET_SEQUENCE_START - 1
        for rec in records:
            code_date = rec.date_from or rec.create_date or fields.Date.context_today(self)
            year = rec._budget_code_year(code_date)
            counter += 1
            rec.with_context(skip_budget_sequence_check=True).write({
                "budget_sequence": rec._format_yearly_budget_code(year, counter),
            })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Budget Codes Resequenced"),
                "message": _("%s budgets were resequenced continuously across all years.") % len(records),
                "type": "success",
                "sticky": False,
            },
        }

    @api.depends_context("uid")
    def _compute_role_flags(self):
        user = self.env.user
        is_pm = user.has_group("pr_custom_purchase.project_manager")
        is_accounts = user.has_group("account.group_account_manager") or user.has_group("account.group_account_user")
        is_md = user.has_group("pr_custom_purchase.managing_director")
        for rec in self:
            is_department_manager = bool(
                rec.department_id
                and rec.department_manager_user_id
                and rec.department_manager_user_id == user
            )
            rec.can_pm_approve = is_department_manager or is_pm
            rec.can_accounts_approve = is_accounts
            rec.can_md_approve = is_md

    @api.depends(
        "source_budget_limit",
        "date_from",
        "date_to",
        "crossovered_budget_line.planned_amount",
        "crossovered_budget_line.analytic_account_id",
        "crossovered_budget_line.date_from",
        "crossovered_budget_line.date_to",
        "crossovered_budget_line.practical_amount",
    )
    def _compute_po_budget_metrics(self):
        analytics = self.mapped("crossovered_budget_line.analytic_account_id").sudo()
        for rec in self:
            rec_analytics = rec.crossovered_budget_line.mapped("analytic_account_id").sudo()
            spent_by_analytic = (
                rec_analytics._get_po_budget_spent_map(
                    date_from=rec.date_from,
                    date_to=rec.date_to,
                    budget=rec,
                )
                if rec_analytics
                else {}
            )
            planned_amount = sum(rec.crossovered_budget_line.mapped("planned_amount"))
            budget_amount = planned_amount or rec.source_budget_limit or 0.0
            analytic_ids = rec.crossovered_budget_line.mapped("analytic_account_id").ids
            spent_amount = sum(spent_by_analytic.get(analytic_id, 0.0) for analytic_id in analytic_ids)
            rec.budget_amount_total = budget_amount
            rec.po_spent_amount = spent_amount
            rec.budget_remaining_amount = budget_amount - spent_amount
            rec.expensed_amount = sum(rec.crossovered_budget_line.mapped("practical_amount"))

    def _is_active_for_date(self, target_date=False):
        self.ensure_one()
        target_date = fields.Date.to_date(target_date or fields.Date.context_today(self))
        return (
            self.state in ("validate", "done")
            and (not self.date_from or self.date_from <= target_date)
            and (not self.date_to or self.date_to >= target_date)
        )

    def _check_active_for_date(self, target_date=False):
        self.ensure_one()
        target_date = fields.Date.to_date(target_date or fields.Date.context_today(self))
        if self.pr_under_revision:
            raise UserError(
                _("Budget %(budget)s is under revision and cannot be used in Purchase Requisitions until the revision is approved or rejected.")
                % {"budget": self.display_name}
            )
        if not self._is_active_for_date(target_date):
            raise UserError(
                _("Budget %(budget)s is not active on %(date)s. Create/select a new budget for this period.")
                % {
                    "budget": self.display_name,
                    "date": fields.Date.to_string(target_date),
                }
            )

    def _get_remaining_by_cost_center(self):
        self.ensure_one()
        lines = self.crossovered_budget_line.filtered("analytic_account_id")
        planned_by_analytic = {}
        for line in lines:
            analytic_id = line.analytic_account_id.id
            planned_by_analytic[analytic_id] = planned_by_analytic.get(analytic_id, 0.0) + (line.planned_amount or 0.0)

        analytics = lines.mapped("analytic_account_id").sudo()
        spent_by_analytic = (
            analytics._get_po_budget_spent_map(
                date_from=self.date_from,
                date_to=self.date_to,
                budget=self,
            )
            if analytics
            else {}
        )
        return {
            analytic_id: planned_amount - spent_by_analytic.get(analytic_id, 0.0)
            for analytic_id, planned_amount in planned_by_analytic.items()
        }

    def _budget_order_is_rfq(self, order):
        name = (order.name or "").upper()
        if "RFQ" in name:
            return True
        if "PO" in name:
            return False
        return order.state in ("draft", "sent")

    def _budget_order_is_po(self, order):
        name = (order.name or "").upper()
        if "PO" in name:
            return True
        if "RFQ" in name:
            return False
        return order.state in ("pending", "purchase", "done")

    @api.depends(
        "crossovered_budget_line.analytic_account_id",
    )
    def _compute_procurement_documents(self):
        CustomPR = self.env["custom.pr"].sudo()
        PurchaseRequisition = self.env["purchase.requisition"].sudo()
        PurchaseOrder = self.env["purchase.order"].sudo()

        for rec in self:
            custom_prs = CustomPR.search([
                ("expense_bucket_id", "=", rec.id),
                ("purchase_requisition_id", "=", False),
            ])
            requisitions = PurchaseRequisition.search([("expense_bucket_id", "=", rec.id)])
            linked_custom_prs = CustomPR.search([
                ("expense_bucket_id", "=", rec.id),
                ("purchase_requisition_id", "!=", False),
            ])
            requisitions |= linked_custom_prs.mapped("purchase_requisition_id")
            pr_names = set(custom_prs.mapped("name") + requisitions.mapped("name"))
            if pr_names:
                requisitions |= PurchaseRequisition.search([("name", "in", list(pr_names))])
                pr_names.update(requisitions.mapped("name"))

            orders = PurchaseOrder
            if requisitions:
                orders |= PurchaseOrder.search([("requisition_id", "in", requisitions.ids)])
            if pr_names:
                orders |= PurchaseOrder.search([
                    "|",
                    ("pr_name", "in", list(pr_names)),
                    ("origin", "in", list(pr_names)),
                ])
            rfqs = orders.filtered(rec._budget_order_is_rfq)
            purchase_orders = orders.filtered(rec._budget_order_is_po)

            rec.custom_pr_ids = custom_prs
            rec.purchase_requisition_ids = requisitions
            rec.budget_rfq_ids = rfqs
            rec.budget_purchase_order_ids = purchase_orders
            rec.custom_pr_count = len(custom_prs)
            rec.purchase_requisition_count = len(requisitions)
            rec.rfq_count = len(rfqs)
            rec.purchase_order_count = len(purchase_orders)

    def _budget_action_for_records(self, name, model, records, view_mode="tree,form"):
        self.ensure_one()
        action = {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": model,
            "view_mode": view_mode,
            "domain": [("id", "in", records.ids)],
            "target": "current",
        }
        if len(records) == 1:
            action.update({"view_mode": "form", "res_id": records.id})
        return action

    def action_view_budget_custom_prs(self):
        self.ensure_one()
        return self._budget_action_for_records(_("Custom PRs"), "custom.pr", self.custom_pr_ids)

    def action_view_budget_purchase_requisitions(self):
        self.ensure_one()
        return self._budget_action_for_records(
            _("Purchase Requisitions"),
            "purchase.requisition",
            self.purchase_requisition_ids,
        )

    def action_view_budget_rfqs(self):
        self.ensure_one()
        return self._budget_action_for_records(_("RFQs"), "purchase.order", self.budget_rfq_ids)

    def action_view_budget_purchase_orders(self):
        self.ensure_one()
        return self._budget_action_for_records(
            _("Purchase Orders"),
            "purchase.order",
            self.budget_purchase_order_ids,
        )

    @api.model_create_multi
    def create(self, vals_list):
        needs_code = any(
            not vals.get("budget_sequence")
            or vals.get("budget_sequence") in ("/", _("New"), "New")
            for vals in vals_list
        )
        if needs_code:
            # Keep the global suffix unique even when users create budgets at
            # the same time in different years.
            self.env.cr.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                ["pr.crossovered.budget.global.code"],
            )
        next_number = self._last_budget_number() if needs_code else False
        for vals in vals_list:
            if not vals.get("budget_sequence") or vals.get("budget_sequence") in ("/", _("New"), "New"):
                year = self._budget_code_year(vals.get("date_from"))
                next_number += 1
                vals["budget_sequence"] = self._format_yearly_budget_code(year, next_number)
            if vals.get("department_id") and not vals.get("scope"):
                vals["scope"] = "department"
        return super().create(vals_list)

    def action_budget_confirm(self):
        for rec in self:
            if rec.department_id and not rec.department_manager_user_id:
                raise UserError(
                    _("Please set a Department Manager user for the selected department before submitting."))
        res = super().action_budget_confirm()
        for rec in self:
            if rec.state == "confirm" and rec.approval_state == "draft":
                rec.approval_state = "pm_approval"
        return res

    def action_pm_approve(self):
        for rec in self:
            if rec.state != "confirm" or rec.approval_state != "pm_approval":
                continue
            if not rec.can_pm_approve:
                raise UserError(_("Only Department Manager or Project Manager can approve at this stage."))
            rec.approval_state = "accounts_approval"

    def action_accounts_approve(self):
        for rec in self:
            if rec.state != "confirm" or rec.approval_state != "accounts_approval":
                continue
            if not rec.can_accounts_approve:
                raise UserError(_("Only Accounts can approve at this stage."))
            rec.approval_state = "md_approval"

    def action_budget_validate(self):
        for rec in self:
            if rec.state == "confirm" and rec.approval_state != "md_approval":
                raise UserError(_("Budget requires PM, Accounts, and MD approvals before validation."))
        res = super().action_budget_validate()
        for rec in self:
            if rec.state in ("validate", "done"):
                rec.approval_state = "approved"
                rec._sync_cost_center_budget_allowance()
        return res

    def action_budget_done(self):
        res = super().action_budget_done()
        for rec in self:
            if rec.state == "done":
                rec.approval_state = "approved"
                rec._sync_cost_center_budget_allowance()
        return res

    def _sync_cost_center_budget_allowance(self):
        """Reflect approved budget lines into Cost Center budget allowances."""
        BudgetLine = self.env["crossovered.budget.lines"].sudo()
        AnalyticAccount = self.env["account.analytic.account"].sudo()

        for rec in self:
            analytics = rec.crossovered_budget_line.mapped("analytic_account_id").filtered(lambda a: a)
            if not analytics:
                continue

            grouped = BudgetLine.read_group(
                domain=[
                    ("analytic_account_id", "in", analytics.ids),
                    ("crossovered_budget_id.state", "in", ["validate", "done"]),
                    ("date_from", "<=", fields.Date.context_today(self)),
                    ("date_to", ">=", fields.Date.context_today(self)),
                ],
                fields=["analytic_account_id", "planned_amount:sum"],
                groupby=["analytic_account_id"],
                lazy=False,
            )
            totals = {
                item["analytic_account_id"][0]: item.get("planned_amount_sum", item.get("planned_amount", 0.0))
                for item in grouped
                if item.get("analytic_account_id")
            }

            for analytic in AnalyticAccount.browse(analytics.ids):
                analytic.budget_allowance = totals.get(analytic.id, 0.0)

    def write(self, vals):
        if vals.get("state") == "draft" and "approval_state" not in vals:
            vals["approval_state"] = "draft"
        return super().write(vals)


class CrossoveredBudgetLines(models.Model):
    _inherit = "crossovered.budget.lines"

    po_spent_amount = fields.Monetary(
        string="Spent Amount",
        currency_field="currency_id",
        compute="_compute_po_budget_line_metrics",
        help="Amount consumed by PRs, purchase orders, and submitted/approved payment vouchers linked to this exact budget.",
    )
    budget_remaining_amount = fields.Monetary(
        string="Remaining Amount",
        currency_field="currency_id",
        compute="_compute_po_budget_line_metrics",
    )

    @api.depends("planned_amount", "analytic_account_id", "date_from", "date_to", "crossovered_budget_id")
    def _compute_po_budget_line_metrics(self):
        for line in self:
            spent = (
                line.analytic_account_id.sudo()._get_po_budget_spent_map(
                    date_from=line.date_from,
                    date_to=line.date_to,
                    budget=line.crossovered_budget_id,
                ).get(line.analytic_account_id.id, 0.0)
                if line.analytic_account_id and line.crossovered_budget_id
                else 0.0
            )
            line.po_spent_amount = spent
            line.budget_remaining_amount = (line.planned_amount or 0.0) - spent
