from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta


class PrBudgetRequisition(models.Model):
    _name = "pr.budget.requisition"
    _description = "Department Budget Requisition"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(string="Request Number", default="New", readonly=True, copy=False, tracking=True)
    request_date = fields.Date(
        string="Request Date",
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    requested_by_id = fields.Many2one(
        "res.users",
        string="Requested By",
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
        readonly=True,
    )
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id", readonly=True)
    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        default=lambda self: self._default_department_id(),
        required=True,
        tracking=True,
    )
    department_manager_user_id = fields.Many2one(
        "res.users",
        string="Department Manager",
        related="department_id.manager_id.user_id",
        store=True,
        readonly=True,
    )
    budget_period_months = fields.Selection(
        [("3", "3 Months"), ("6", "6 Months"), ("12", "12 Months")],
        string="Budget Period",
        default="6",
        required=True,
        tracking=True,
    )
    period_date_from = fields.Date(
        string="Budget Start Date",
        default=lambda self: self._default_period_date_from(),
        required=True,
        tracking=True,
    )
    period_date_to = fields.Date(
        string="Budget End Date",
        default=lambda self: self._default_period_date_to(),
        required=True,
        tracking=True,
    )
    expense_type = fields.Selection(
        [("opex", "Opex"), ("capex", "Capex")],
        string="Expense Type",
        default="opex",
        required=True,
        tracking=True,
    )
    scope = fields.Selection(
        [("department", "Department")],
        string="Applies To",
        default="department",
        required=True,
        readonly=True,
    )
    reason = fields.Text(string="Justification", required=True, tracking=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("department_approval", "Pending Department Manager"),
            ("accounts_approval", "Pending Accounts"),
            ("md_approval", "Pending Managing Director"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="Status",
        default="draft",
        tracking=True,
        copy=False,
    )
    rejection_reason = fields.Text(string="Rejection Reason", readonly=True, tracking=True)
    line_ids = fields.One2many(
        "pr.budget.requisition.line",
        "requisition_id",
        string="Budget Lines",
        copy=True,
    )
    total_requested_amount = fields.Monetary(
        string="Total Requested",
        currency_field="currency_id",
        compute="_compute_total_requested_amount",
        store=True,
    )
    total_budget_amount = fields.Monetary(
        string="Current Budget",
        currency_field="currency_id",
        compute="_compute_budget_totals",
    )
    total_spent_amount = fields.Monetary(
        string="Spent Amount",
        currency_field="currency_id",
        compute="_compute_budget_totals",
    )
    total_remaining_amount = fields.Monetary(
        string="Budget Remaining",
        currency_field="currency_id",
        compute="_compute_budget_totals",
    )
    generated_budget_id = fields.Many2one(
        "crossovered.budget",
        string="Generated Budget",
        readonly=True,
        copy=False,
    )

    can_department_approve = fields.Boolean(compute="_compute_role_flags")
    can_accounts_approve = fields.Boolean(compute="_compute_role_flags")
    can_md_approve = fields.Boolean(compute="_compute_role_flags")
    can_reject = fields.Boolean(compute="_compute_role_flags")
    can_reset_to_draft = fields.Boolean(compute="_compute_role_flags")

    @api.model
    def _default_department_id(self):
        employee = self.env["hr.employee"].sudo().search([
            ("user_id", "=", self.env.uid),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        return employee.department_id.id if employee and employee.department_id else False

    @api.model
    def _default_period_date_from(self):
        today = fields.Date.context_today(self)
        return today.replace(day=1)

    @api.model
    def _default_period_date_to(self):
        return self._get_period_date_to(self._default_period_date_from(), "6")

    @api.model
    def _get_period_date_to(self, date_from, months):
        if not date_from or not months:
            return False
        return fields.Date.to_date(date_from) + relativedelta(months=int(months), days=-1)

    @api.onchange("period_date_from", "budget_period_months")
    def _onchange_budget_period(self):
        for rec in self:
            rec.period_date_to = rec._get_period_date_to(rec.period_date_from, rec.budget_period_months)

    @api.depends("line_ids.requested_amount")
    def _compute_total_requested_amount(self):
        for rec in self:
            rec.total_requested_amount = sum(rec.line_ids.mapped("requested_amount"))

    @api.depends(
        "line_ids.cost_center_id",
        "period_date_from",
        "period_date_to",
        "expense_type",
    )
    def _compute_budget_totals(self):
        for rec in self:
            cost_centers = rec.line_ids.mapped("cost_center_id")
            metrics = cost_centers.sudo()._get_budget_metrics_map(
                date_from=rec.period_date_from,
                date_to=rec.period_date_to,
                expense_type=rec.expense_type,
            ) if cost_centers else {}
            rec.total_budget_amount = sum(metric["allowance"] for metric in metrics.values())
            rec.total_spent_amount = sum(metric["spent"] for metric in metrics.values())
            rec.total_remaining_amount = sum(metric["remaining"] for metric in metrics.values())

    @api.depends_context("uid")
    @api.depends("state", "requested_by_id", "department_manager_user_id")
    def _compute_role_flags(self):
        user = self.env.user
        is_accounts = user.has_group("account.group_account_manager") or user.has_group("account.group_account_user")
        is_md = user.has_group("pr_custom_purchase.managing_director")
        is_admin = (
            user.has_group("pr_custom_purchase.procurement_admin")
            or user.has_group("purchase.group_purchase_manager")
        )
        for rec in self:
            is_requester = rec.requested_by_id == user
            is_department_manager = rec.department_manager_user_id == user
            rec.can_department_approve = rec.state == "department_approval" and is_department_manager
            rec.can_accounts_approve = rec.state == "accounts_approval" and is_accounts
            rec.can_md_approve = rec.state == "md_approval" and is_md
            rec.can_reject = (
                rec.state in ("draft", "department_approval", "accounts_approval", "md_approval")
                and (
                    (rec.state == "draft" and is_requester)
                    or (rec.state == "department_approval" and is_department_manager)
                    or (rec.state == "accounts_approval" and is_accounts)
                    or (rec.state == "md_approval" and is_md)
                    or is_admin
                )
            )
            rec.can_reset_to_draft = rec.state == "rejected" and (is_requester or is_admin)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("pr.budget.requisition") or "New"
            period_date_from = vals.get("period_date_from") or self._default_period_date_from()
            period_months = vals.get("budget_period_months") or "6"
            vals["period_date_to"] = self._get_period_date_to(period_date_from, period_months)
        return super().create(vals_list)

    def write(self, vals):
        protected_fields = {
            "department_id",
            "budget_period_months",
            "period_date_from",
            "period_date_to",
            "expense_type",
            "reason",
            "line_ids",
        }
        if protected_fields.intersection(vals):
            for rec in self:
                if rec.state != "draft":
                    raise UserError(_("Submitted budget requisitions cannot be edited. Reject and reset it first."))
        if len(self) == 1 and ("period_date_from" in vals or "budget_period_months" in vals):
            date_from = vals.get("period_date_from") or self.period_date_from
            months = vals.get("budget_period_months") or self.budget_period_months
            vals["period_date_to"] = self._get_period_date_to(date_from, months)
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state not in ("draft", "rejected"):
                raise UserError(_("Only draft or rejected budget requisitions can be deleted."))
            if rec.generated_budget_id:
                raise UserError(_("This requisition already generated a backend budget and cannot be deleted."))
        return super().unlink()

    @api.constrains("period_date_from", "period_date_to")
    def _check_period_dates(self):
        for rec in self:
            if rec.period_date_from and rec.period_date_to and rec.period_date_to < rec.period_date_from:
                raise ValidationError(_("Budget End Date cannot be before Budget Start Date."))

    def _check_ready_for_submission(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_("Add at least one budget item line."))
            if rec.total_requested_amount <= 0:
                raise UserError(_("Total requested amount must be greater than zero."))
            missing_item_lines = rec.line_ids.filtered(lambda line: not line.item_name)
            if missing_item_lines:
                raise UserError(_("Please enter an item description for every budget line."))
            invalid_amount_lines = rec.line_ids.filtered(lambda line: line.requested_amount <= 0.0)
            if invalid_amount_lines:
                raise UserError(_("Every budget item line must have a line total greater than zero."))
            if not rec.department_manager_user_id:
                raise UserError(
                    _("Please set a Department Manager user on the selected department before submitting.")
                )

    def _notify_users(self, users, summary, note):
        users = users.filtered(lambda user: user.active)
        activity_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        for rec in self:
            for user in users:
                if activity_type:
                    rec.activity_schedule(
                        activity_type_id=activity_type.id,
                        user_id=user.id,
                        summary=summary,
                        note=note,
                    )
            emails = ",".join(users.filtered(lambda user: user.email).mapped("email"))
            if emails:
                self.env["mail.mail"].sudo().create({
                    "email_from": "noreply@petroraq.com",
                    "email_to": emails,
                    "subject": summary,
                    "body_html": "<p>%s</p>" % note,
                }).send()

    def _notify_group(self, group_xml_ids, summary, note):
        users = self.env["res.users"]
        for xmlid in group_xml_ids:
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                users |= group.users
        self._notify_users(users, summary, note)

    def action_submit(self):
        self._check_ready_for_submission()
        for rec in self:
            if rec.state != "draft":
                continue
            rec.write({"state": "department_approval", "rejection_reason": False})
            rec._notify_users(
                rec.department_manager_user_id,
                _("Budget Requisition Approval Needed"),
                _("Budget requisition <b>%s</b> is waiting for Department Manager approval.") % rec.display_name,
            )
            rec.message_post(body=_("Budget requisition submitted for Department Manager approval."))

    def action_department_approve(self):
        for rec in self:
            if rec.state != "department_approval":
                continue
            if not rec.can_department_approve:
                raise UserError(_("Only the selected Department Manager can approve this stage."))
            rec.state = "accounts_approval"
            rec._notify_group(
                ["account.group_account_manager", "account.group_account_user"],
                _("Budget Requisition Approval Needed"),
                _("Budget requisition <b>%s</b> is waiting for Accounts approval.") % rec.display_name,
            )
            rec.message_post(body=_("Department Manager approved this budget requisition."))

    def action_accounts_approve(self):
        for rec in self:
            if rec.state != "accounts_approval":
                continue
            if not rec.can_accounts_approve:
                raise UserError(_("Only Accounts can approve this stage."))
            rec.state = "md_approval"
            rec._notify_group(
                ["pr_custom_purchase.managing_director"],
                _("Budget Requisition Approval Needed"),
                _("Budget requisition <b>%s</b> is waiting for Managing Director approval.") % rec.display_name,
            )
            rec.message_post(body=_("Accounts approved this budget requisition."))

    def action_md_approve(self):
        for rec in self:
            if rec.state != "md_approval":
                continue
            if not rec.can_md_approve:
                raise UserError(_("Only Managing Director can approve this stage."))
            budget = rec._create_or_validate_generated_budget()
            rec.write({
                "state": "approved",
                "generated_budget_id": budget.id,
            })
            rec.message_post(body=_("Managing Director approved this request and generated budget %s.") % budget.display_name)

    def action_reset_to_draft(self):
        for rec in self:
            if not rec.can_reset_to_draft:
                raise UserError(_("You cannot reset this requisition to draft."))
            rec.write({"state": "draft", "rejection_reason": False})
            rec.message_post(body=_("Budget requisition has been reset to draft."))

    def action_reject(self):
        self.ensure_one()
        if not self.can_reject:
            raise UserError(_("You cannot reject this requisition at the current stage."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Reject Budget Requisition"),
            "res_model": "pr.budget.requisition.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_requisition_id": self.id},
        }

    def _set_rejected(self, reason):
        for rec in self:
            if rec.state == "approved":
                raise UserError(_("Approved budget requisitions cannot be rejected."))
            rec.write({"state": "rejected", "rejection_reason": reason})
            rec.message_post(body=_("Budget requisition rejected: %s") % reason)

    def action_open_generated_budget(self):
        self.ensure_one()
        if not self.generated_budget_id:
            raise UserError(_("No backend budget has been generated yet."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Generated Budget"),
            "res_model": "crossovered.budget",
            "view_mode": "form",
            "res_id": self.generated_budget_id.id,
            "target": "current",
        }

    def _create_or_validate_generated_budget(self):
        self.ensure_one()
        self._check_ready_for_submission()

        Budget = self.env["crossovered.budget"].sudo()
        BudgetLine = self.env["crossovered.budget.lines"].sudo()
        budget = self.generated_budget_id.sudo()
        if not budget:
            budget = Budget.create({
                "name": _("%s - %s Budget") % (self.department_id.name, self.expense_type.upper()),
                "company_id": self.company_id.id,
                "user_id": self.requested_by_id.id,
                "date_from": self.period_date_from,
                "date_to": self.period_date_to,
                "budget_period_months": self.budget_period_months,
                "expense_type": self.expense_type,
                "scope": "department",
                "department_id": self.department_id.id,
                "source_budget_limit": self.total_requested_amount,
            })
            planned_by_cost_center = {}
            for line in self.line_ids:
                planned_by_cost_center[line.cost_center_id.id] = (
                    planned_by_cost_center.get(line.cost_center_id.id, 0.0) + line.requested_amount
                )

            for analytic_id, planned_amount in planned_by_cost_center.items():
                BudgetLine.create({
                    "crossovered_budget_id": budget.id,
                    "analytic_account_id": analytic_id,
                    "date_from": self.period_date_from,
                    "date_to": self.period_date_to,
                    "planned_amount": planned_amount,
                })
            budget.message_post(body=_("Generated from department budget requisition %s.") % self.display_name)

        for line in self.line_ids:
            if line.cost_center_id.budget_type != self.expense_type:
                line.cost_center_id.sudo().budget_type = self.expense_type

        if budget.state == "draft":
            budget.action_budget_confirm()
        if budget.state == "confirm":
            budget.approval_state = "md_approval"
            budget.action_budget_validate()
        if budget.state not in ("validate", "done"):
            raise UserError(_("Generated budget could not be validated. Current status: %s") % budget.state)
        return budget


class PrBudgetRequisitionLine(models.Model):
    _name = "pr.budget.requisition.line"
    _description = "Department Budget Requisition Line"
    _order = "id"

    def init(self):
        self.env.cr.execute(
            'ALTER TABLE pr_budget_requisition_line '
            'DROP CONSTRAINT IF EXISTS pr_budget_requisition_line_unique'
        )
        self.env.cr.execute(
            'ALTER TABLE pr_budget_requisition_line '
            'DROP CONSTRAINT IF EXISTS pr_budget_requisition_line_pr_budget_requisition_line_unique'
        )

    requisition_id = fields.Many2one("pr.budget.requisition", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="requisition_id.company_id", store=True, readonly=True)
    currency_id = fields.Many2one(related="requisition_id.currency_id", readonly=True)
    product_id = fields.Many2one(
        "product.product",
        string="Product/Item",
        help="Optional product reference. You can also type a custom item description.",
    )
    item_name = fields.Char(
        string="Item Description",
        required=True,
        help="Detailed item being requested, such as coffee, tea, stationery, or pantry supplies.",
    )
    cost_center_id = fields.Many2one(
        "account.analytic.account",
        string="Cost Center",
        required=True,
    )
    budget_code = fields.Char(string="Budget Code", related="cost_center_id.budget_code", readonly=True)
    current_budget = fields.Float(string="Current Budget", compute="_compute_period_budget_metrics")
    budget_spent = fields.Float(string="Spent Amount", compute="_compute_period_budget_metrics")
    budget_left = fields.Float(string="Budget Left", compute="_compute_period_budget_metrics")
    remaining_after_request = fields.Monetary(
        string="Remaining After Request",
        currency_field="currency_id",
        compute="_compute_remaining_after_request",
    )
    quantity = fields.Float(string="Quantity", default=1.0)
    unit = fields.Char(string="Unit", default="Unit")
    unit_price = fields.Monetary(string="Unit Price", currency_field="currency_id")
    requested_amount = fields.Monetary(string="Line Total", currency_field="currency_id", required=True)
    remarks = fields.Char(string="Remarks")

    _sql_constraints = [
        (
            "pr_budget_requisition_amount_positive",
            "CHECK(requested_amount > 0)",
            "Line total must be greater than zero.",
        ),
    ]

    @api.depends(
        "cost_center_id",
        "requisition_id.period_date_from",
        "requisition_id.period_date_to",
        "requisition_id.expense_type",
    )
    def _compute_period_budget_metrics(self):
        for line in self:
            if not line.cost_center_id:
                line.current_budget = 0.0
                line.budget_spent = 0.0
                line.budget_left = 0.0
                continue
            metrics = line.cost_center_id.sudo()._get_budget_metrics_map(
                date_from=line.requisition_id.period_date_from,
                date_to=line.requisition_id.period_date_to,
                expense_type=line.requisition_id.expense_type,
            )
            metric = metrics.get(line.cost_center_id.id, {})
            line.current_budget = metric.get("allowance", 0.0)
            line.budget_spent = metric.get("spent", 0.0)
            line.budget_left = metric.get("remaining", 0.0)

    @api.depends(
        "requested_amount",
        "cost_center_id",
        "budget_left",
        "requisition_id.line_ids.requested_amount",
        "requisition_id.line_ids.cost_center_id",
    )
    def _compute_remaining_after_request(self):
        for line in self:
            if not line.cost_center_id:
                line.remaining_after_request = 0.0
                continue
            requested_for_cost_center = sum(
                line.requisition_id.line_ids.filtered(
                    lambda req_line: req_line.cost_center_id == line.cost_center_id
                ).mapped("requested_amount")
            )
            line.remaining_after_request = (line.budget_left or 0.0) - requested_for_cost_center

    @api.onchange("product_id")
    def _onchange_product_id(self):
        for line in self:
            product = line.product_id
            if not product:
                continue
            line.item_name = line.item_name or product.display_name
            if product.uom_id and not line.unit:
                line.unit = product.uom_id.name
            if not line.unit_price:
                line.unit_price = product.lst_price or 0.0
            if line.quantity and line.unit_price:
                line.requested_amount = line.quantity * line.unit_price

    @api.onchange("quantity", "unit_price")
    def _onchange_line_amount(self):
        for line in self:
            if line.quantity and line.unit_price:
                line.requested_amount = line.quantity * line.unit_price

    def write(self, vals):
        if {
            "product_id",
            "item_name",
            "cost_center_id",
            "quantity",
            "unit",
            "unit_price",
            "requested_amount",
            "remarks",
        }.intersection(vals):
            for rec in self:
                if rec.requisition_id.state != "draft":
                    raise UserError(_("Submitted budget requisition lines cannot be edited."))
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            requisition = self.env["pr.budget.requisition"].browse(vals.get("requisition_id"))
            if requisition and requisition.state != "draft":
                raise UserError(_("Submitted budget requisition lines cannot be edited."))
        return super().create(vals_list)

    def unlink(self):
        for rec in self:
            if rec.requisition_id.state != "draft":
                raise UserError(_("Submitted budget requisition lines cannot be deleted."))
        return super().unlink()


class PrBudgetRequisitionRejectWizard(models.TransientModel):
    _name = "pr.budget.requisition.reject.wizard"
    _description = "Budget Requisition Reject Wizard"

    requisition_id = fields.Many2one("pr.budget.requisition", string="Budget Requisition", required=True)
    rejection_reason = fields.Text(string="Rejection Reason", required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        self.requisition_id._set_rejected(self.rejection_reason)
        return {"type": "ir.actions.act_window_close"}
