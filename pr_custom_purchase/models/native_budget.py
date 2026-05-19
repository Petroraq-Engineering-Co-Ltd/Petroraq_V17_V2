from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CrossoveredBudget(models.Model):
    _inherit = "crossovered.budget"
    _rec_name = "budget_sequence"

    budget_sequence = fields.Char(string="Budget Code", readonly=True, default='New')
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
    can_pm_approve = fields.Boolean(compute="_compute_role_flags")
    can_accounts_approve = fields.Boolean(compute="_compute_role_flags")
    can_md_approve = fields.Boolean(compute="_compute_role_flags")
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id", readonly=True)
    budget_amount_total = fields.Monetary(
        string="Budget Amount",
        currency_field="currency_id",
        compute="_compute_po_budget_metrics",
    )
    po_spent_amount = fields.Monetary(
        string="Spent Amount",
        currency_field="currency_id",
        compute="_compute_po_budget_metrics",
        help="Amount consumed by Pending/Purchase/Done purchase orders through cost-center analytic distribution.",
    )
    budget_remaining_amount = fields.Monetary(
        string="Budget Remaining",
        currency_field="currency_id",
        compute="_compute_po_budget_metrics",
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
        "crossovered_budget_line.planned_amount",
        "crossovered_budget_line.analytic_account_id",
    )
    def _compute_po_budget_metrics(self):
        analytics = self.mapped("crossovered_budget_line.analytic_account_id").sudo()
        spent_by_analytic = analytics._get_po_budget_spent_map() if analytics else {}
        for rec in self:
            planned_amount = sum(rec.crossovered_budget_line.mapped("planned_amount"))
            budget_amount = planned_amount or rec.source_budget_limit or 0.0
            analytic_ids = rec.crossovered_budget_line.mapped("analytic_account_id").ids
            spent_amount = sum(spent_by_analytic.get(analytic_id, 0.0) for analytic_id in analytic_ids)
            rec.budget_amount_total = budget_amount
            rec.po_spent_amount = spent_amount
            rec.budget_remaining_amount = budget_amount - spent_amount

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

    def _get_orders_by_budget_analytics(self):
        analytic_ids = set(self.crossovered_budget_line.mapped("analytic_account_id").ids)
        orders = self.env["purchase.order"].sudo()
        if not analytic_ids:
            return orders

        candidate_orders = self.env["purchase.order"].sudo().search([
            ("order_line.analytic_distribution", "!=", False),
        ])
        for order in candidate_orders:
            for line in order.order_line:
                distribution = line.analytic_distribution or {}
                distribution_ids = {
                    int(key_part)
                    for key in distribution
                    for key_part in str(key).split(",")
                    if str(key_part).strip().isdigit()
                }
                if analytic_ids.intersection(distribution_ids):
                    orders |= order
                    break
        return orders

    @api.depends(
        "crossovered_budget_line.analytic_account_id",
    )
    def _compute_procurement_documents(self):
        CustomPR = self.env["custom.pr"].sudo()
        PurchaseRequisition = self.env["purchase.requisition"].sudo()
        PurchaseOrder = self.env["purchase.order"].sudo()

        for rec in self:
            custom_prs = CustomPR.search([("expense_bucket_id", "=", rec.id)])
            requisitions = PurchaseRequisition.search([("expense_bucket_id", "=", rec.id)])
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
            orders |= rec._get_orders_by_budget_analytics()

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
        for vals in vals_list:
            if not vals.get("budget_sequence") or vals.get("budget_sequence") in ("/", _("New"), "New"):
                vals["budget_sequence"] = self.env["ir.sequence"].next_by_code("crossovered.budget.custom") or _("New")
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
        string="PO Spent",
        currency_field="currency_id",
        compute="_compute_po_budget_line_metrics",
        help="Amount consumed by Pending/Purchase/Done purchase orders for this cost center.",
    )
    budget_remaining_amount = fields.Monetary(
        string="Budget Remaining",
        currency_field="currency_id",
        compute="_compute_po_budget_line_metrics",
    )

    @api.depends("planned_amount", "analytic_account_id")
    def _compute_po_budget_line_metrics(self):
        analytics = self.mapped("analytic_account_id").sudo()
        spent_by_analytic = analytics._get_po_budget_spent_map() if analytics else {}
        for line in self:
            spent = spent_by_analytic.get(line.analytic_account_id.id, 0.0) if line.analytic_account_id else 0.0
            line.po_spent_amount = spent
            line.budget_remaining_amount = (line.planned_amount or 0.0) - spent
