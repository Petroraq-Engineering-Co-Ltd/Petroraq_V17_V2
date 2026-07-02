from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare
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
    department_approved = fields.Boolean(copy=False, readonly=True)
    department_approved_by_id = fields.Many2one(
        "res.users",
        string="Department Approved By",
        copy=False,
        readonly=True,
    )
    accounts_approved = fields.Boolean(copy=False, readonly=True)
    accounts_approved_by_id = fields.Many2one(
        "res.users",
        string="Accounts Approved By",
        copy=False,
        readonly=True,
    )
    md_approved = fields.Boolean(copy=False, readonly=True)
    md_approved_by_id = fields.Many2one(
        "res.users",
        string="MD Approved By",
        copy=False,
        readonly=True,
    )
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
        string="Remaining Amount",
        currency_field="currency_id",
        compute="_compute_budget_totals",
    )
    generated_budget_id = fields.Many2one(
        "crossovered.budget",
        string="Generated Budget",
        readonly=True,
        copy=False,
    )
    generated_budget_code = fields.Char(
        string="Budget Code",
        related="generated_budget_id.budget_sequence",
        readonly=True,
    )
    revision_of_id = fields.Many2one(
        "pr.budget.requisition",
        string="Revision Of",
        readonly=True,
        copy=False,
        tracking=True,
    )
    revision_ids = fields.One2many(
        "pr.budget.requisition",
        "revision_of_id",
        string="Revisions",
        readonly=True,
    )
    revision_count = fields.Integer(string="Revisions", compute="_compute_revision_count")
    revision_number = fields.Integer(string="Revision No.", readonly=True, copy=False)
    is_revision = fields.Boolean(string="Revision", compute="_compute_is_revision", store=True)
    budget_version_label = fields.Char(string="Budget Version", compute="_compute_budget_version_label")

    can_department_approve = fields.Boolean(compute="_compute_role_flags")
    can_accounts_approve = fields.Boolean(compute="_compute_role_flags")
    can_md_approve = fields.Boolean(compute="_compute_role_flags")
    can_reject = fields.Boolean(compute="_compute_role_flags")
    can_reset_to_draft = fields.Boolean(compute="_compute_role_flags")
    can_request_revision = fields.Boolean(compute="_compute_role_flags")

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

    @api.depends("revision_ids")
    def _compute_revision_count(self):
        for rec in self:
            rec.revision_count = len(rec.revision_ids)

    @api.depends("revision_of_id", "revision_number")
    def _compute_is_revision(self):
        for rec in self:
            rec.is_revision = bool(rec.revision_of_id or rec.revision_number)

    @api.depends("revision_of_id", "revision_number", "revision_count")
    def _compute_budget_version_label(self):
        for rec in self:
            if rec.revision_number:
                rec.budget_version_label = _("Revised Budget R%s") % (rec.revision_number or 1)
            elif rec.revision_of_id:
                rec.budget_version_label = _("Revised Budget")
            elif rec.revision_count:
                rec.budget_version_label = _("Original - Revised")
            else:
                rec.budget_version_label = _("Original")

    @api.depends(
        "line_ids.cost_center_id",
        "period_date_from",
        "period_date_to",
        "expense_type",
        "generated_budget_id",
        "generated_budget_id.crossovered_budget_line.planned_amount",
        "generated_budget_id.crossovered_budget_line.analytic_account_id",
    )
    def _compute_budget_totals(self):
        for rec in self:
            cost_centers = rec.line_ids.mapped("cost_center_id")
            budget = rec.generated_budget_id.sudo()
            if budget and cost_centers:
                budget_lines = budget.crossovered_budget_line.filtered(
                    lambda line: line.analytic_account_id in cost_centers
                )
                planned_by_cost_center = {}
                for budget_line in budget_lines:
                    analytic_id = budget_line.analytic_account_id.id
                    planned_by_cost_center[analytic_id] = (
                        planned_by_cost_center.get(analytic_id, 0.0)
                        + (budget_line.planned_amount or 0.0)
                    )
                spent_by_cost_center = cost_centers.sudo()._get_po_budget_spent_map(
                    date_from=rec.period_date_from,
                    date_to=rec.period_date_to,
                    budget=budget,
                )
                rec.total_budget_amount = sum(planned_by_cost_center.values())
                rec.total_spent_amount = sum(
                    spent_by_cost_center.get(analytic_id, 0.0)
                    for analytic_id in planned_by_cost_center
                )
                rec.total_remaining_amount = rec.total_budget_amount - rec.total_spent_amount
                continue

            metrics = cost_centers.sudo()._get_budget_metrics_map(
                date_from=rec.period_date_from,
                date_to=rec.period_date_to,
                expense_type=rec.expense_type,
            ) if cost_centers else {}
            rec.total_budget_amount = sum(metric["allowance"] for metric in metrics.values())
            rec.total_spent_amount = sum(metric["spent"] for metric in metrics.values())
            rec.total_remaining_amount = sum(metric["remaining"] for metric in metrics.values())

    @api.depends_context("uid")
    @api.depends("state", "requested_by_id", "department_manager_user_id", "generated_budget_id")
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
            rec.can_request_revision = rec._can_user_request_revision(user)

    def _can_user_request_revision(self, user):
        self.ensure_one()
        is_admin = (
            user.has_group("pr_custom_purchase.procurement_admin")
            or user.has_group("purchase.group_purchase_manager")
        )
        return (
            self.state == "approved"
            and bool(self.generated_budget_id)
            and (
                self.requested_by_id == user
                or self.department_manager_user_id == user
                or is_admin
            )
        )

    @api.model
    def _next_requisition_name(self, sequence_date=False):
        sequence = self.env["ir.sequence"].sudo().search([
            ("code", "=", "pr.budget.requisition"),
            ("company_id", "=", False),
        ], limit=1)
        if not sequence:
            return "New"

        # Lock and synchronize the sequence with every suffix already used.
        # This also repairs databases where yearly date ranges were enabled.
        self.env.cr.execute(
            "SELECT id FROM ir_sequence WHERE id = %s FOR UPDATE",
            [sequence.id],
        )
        used_numbers = []
        for name in self.with_context(active_test=False).sudo().search([]).mapped("name"):
            suffix = (name or "").rsplit("-", 1)[-1]
            if suffix.isdigit():
                used_numbers.append(int(suffix))
        range_next_numbers = sequence.date_range_ids.mapped("number_next_actual")
        required_next = max(
            [max(used_numbers, default=0) + 1, sequence.number_next_actual]
            + range_next_numbers
        )

        if sequence.use_date_range:
            sequence.write({"use_date_range": False})
            sequence.invalidate_recordset(["number_next_actual"])
        if sequence.number_next_actual < required_next:
            sequence.number_next_actual = required_next

        sequence_date = fields.Date.to_date(sequence_date) if sequence_date else fields.Date.context_today(self)
        return sequence.with_context(ir_sequence_date=sequence_date).next_by_id() or "New"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self._next_requisition_name(vals.get("period_date_from"))
            period_date_from = vals.get("period_date_from") or self._default_period_date_from()
            period_months = vals.get("budget_period_months") or "6"
            vals["period_date_to"] = self._get_period_date_to(period_date_from, period_months)
        return super().create(vals_list)

    def write(self, vals):
        revision_identity_fields = {
            "department_id",
            "budget_period_months",
            "period_date_from",
            "period_date_to",
            "expense_type",
            "scope",
        }
        if revision_identity_fields.intersection(vals):
            for rec in self:
                if rec.generated_budget_id:
                    raise UserError(
                        _("Budget revisions keep the original department, period, and Opex/Capex type. "
                          "Edit the budget lines only, or create a new budget for a different period/type.")
                    )
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

    def _planned_amounts_by_cost_center(self):
        self.ensure_one()
        planned_by_cost_center = {}
        for line in self.line_ids:
            if not line.cost_center_id:
                continue
            planned_by_cost_center[line.cost_center_id.id] = (
                planned_by_cost_center.get(line.cost_center_id.id, 0.0) + line.requested_amount
            )
        return planned_by_cost_center

    def _get_spend_scope_budget(self):
        """Return the backend budget whose consumption belongs to this request."""
        self.ensure_one()
        if self.generated_budget_id:
            return self.generated_budget_id.sudo()
        if self.revision_of_id:
            return self._get_revision_backend_budget()
        return self.env["crossovered.budget"]

    def _check_requested_amounts_not_below_spent(self):
        self.ensure_one()
        planned_by_cost_center = self._planned_amounts_by_cost_center()
        if not planned_by_cost_center:
            return
        analytics = self.env["account.analytic.account"].sudo().browse(list(planned_by_cost_center))
        budget = self._get_spend_scope_budget()
        spent_by_analytic = (
            analytics._get_po_budget_spent_map(
                date_from=self.period_date_from,
                date_to=self.period_date_to,
                budget=budget,
            )
            if budget
            else {analytic.id: 0.0 for analytic in analytics}
        )
        precision = self.currency_id.rounding or 0.01
        for analytic in analytics:
            planned_amount = planned_by_cost_center.get(analytic.id, 0.0)
            spent_amount = spent_by_analytic.get(analytic.id, 0.0)
            if float_compare(planned_amount, spent_amount, precision_rounding=precision) < 0:
                raise UserError(
                    _(
                        "Budget for cost center %(cost_center)s cannot be %(planned).2f because "
                        "%(spent).2f is already spent/committed in this period."
                    )
                    % {
                        "cost_center": analytic.display_name,
                        "planned": planned_amount,
                        "spent": spent_amount,
                    }
                )

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
            rec._check_requested_amounts_not_below_spent()

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

    def _reset_role_approvals(self):
        self.write({
            "department_approved": False,
            "department_approved_by_id": False,
            "accounts_approved": False,
            "accounts_approved_by_id": False,
            "md_approved": False,
            "md_approved_by_id": False,
        })

    def _backfill_completed_stages(self):
        """Keep requisitions already in progress compatible after this upgrade."""
        for rec in self:
            vals = {}
            if rec.state in ("accounts_approval", "md_approval", "approved"):
                vals["department_approved"] = True
            if rec.state in ("md_approval", "approved"):
                vals["accounts_approved"] = True
            if rec.state == "approved":
                vals["md_approved"] = True
            if vals:
                rec.write(vals)

    def _record_current_user_roles(self):
        """One approval click covers every approval role held by the user."""
        self.ensure_one()
        user = self.env.user
        vals = {}
        roles = []
        if not self.department_approved and self.department_manager_user_id == user:
            vals.update({
                "department_approved": True,
                "department_approved_by_id": user.id,
            })
            roles.append(_("Department Manager"))
        if (
            not self.accounts_approved
            and (
                user.has_group("account.group_account_manager")
                or user.has_group("account.group_account_user")
            )
        ):
            vals.update({
                "accounts_approved": True,
                "accounts_approved_by_id": user.id,
            })
            roles.append(_("Accounts"))
        if not self.md_approved and user.has_group("pr_custom_purchase.managing_director"):
            vals.update({
                "md_approved": True,
                "md_approved_by_id": user.id,
            })
            roles.append(_("Managing Director"))
        if vals:
            self.write(vals)
        return roles

    def _complete_approval(self):
        self.ensure_one()
        budget = self._create_or_validate_generated_budget()
        self.write({
            "state": "approved",
            "generated_budget_id": budget.id,
        })
        if self.revision_of_id or self.revision_number:
            message = _("All required roles approved this revision and updated budget %s.")
        else:
            message = _("All required roles approved this request and generated budget %s.")
        self.message_post(body=message % budget.display_name)

    def _advance_to_next_unapproved_role(self):
        self.ensure_one()
        if not self.department_approved:
            self.state = "department_approval"
            self._notify_users(
                self.department_manager_user_id,
                _("Budget Requisition Approval Needed"),
                _("Budget requisition <b>%s</b> is waiting for Department Manager approval.")
                % self.display_name,
            )
        elif not self.accounts_approved:
            self.state = "accounts_approval"
            self._notify_group(
                ["account.group_account_manager", "account.group_account_user"],
                _("Budget Requisition Approval Needed"),
                _("Budget requisition <b>%s</b> is waiting for Accounts approval.") % self.display_name,
            )
        elif not self.md_approved:
            self.state = "md_approval"
            self._notify_group(
                ["pr_custom_purchase.managing_director"],
                _("Budget Requisition Approval Needed"),
                _("Budget requisition <b>%s</b> is waiting for Managing Director approval.")
                % self.display_name,
            )
        else:
            self._complete_approval()

    def _approve_current_stage(self):
        self.ensure_one()
        self._backfill_completed_stages()
        roles = self._record_current_user_roles()
        if not roles:
            raise UserError(_("Your approval role has already been recorded for this requisition."))
        self.message_post(
            body=_("%(user)s approved this budget requisition for: %(roles)s.")
            % {
                "user": self.env.user.display_name,
                "roles": ", ".join(roles),
            }
        )
        self._advance_to_next_unapproved_role()

    def action_submit(self):
        self._check_ready_for_submission()
        for rec in self:
            if rec.state != "draft":
                continue
            rec._reset_role_approvals()
            rec.write({"rejection_reason": False})
            rec._advance_to_next_unapproved_role()
            rec.message_post(body=_("Budget requisition submitted for Department Manager approval."))

    def action_department_approve(self):
        for rec in self:
            if rec.state != "department_approval":
                continue
            if not rec.can_department_approve:
                raise UserError(_("Only the selected Department Manager can approve this stage."))
            rec._approve_current_stage()

    def action_accounts_approve(self):
        for rec in self:
            if rec.state != "accounts_approval":
                continue
            if not rec.can_accounts_approve:
                raise UserError(_("Only Accounts can approve this stage."))
            rec._approve_current_stage()

    def action_md_approve(self):
        for rec in self:
            if rec.state != "md_approval":
                continue
            if not rec.can_md_approve:
                raise UserError(_("Only Managing Director can approve this stage."))
            rec._approve_current_stage()

    def action_reset_to_draft(self):
        for rec in self:
            if not rec.can_reset_to_draft:
                raise UserError(_("You cannot reset this requisition to draft."))
            rec.write({"state": "draft", "rejection_reason": False})
            rec._reset_role_approvals()
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

    def _get_revision_root(self):
        self.ensure_one()
        root = self
        while root.revision_of_id:
            root = root.revision_of_id
        return root

    def _get_latest_revision_source(self):
        self.ensure_one()
        root = self._get_revision_root()
        latest_revision = self.sudo().search([
            ("revision_of_id", "=", root.id),
            ("state", "=", "approved"),
            ("generated_budget_id", "!=", False),
        ], order="revision_number desc, id desc", limit=1)
        return latest_revision or root

    def _get_revision_backend_budget(self):
        self.ensure_one()
        source = self._get_latest_revision_source()
        budget = source.generated_budget_id or source._get_revision_root().generated_budget_id
        if not budget:
            raise UserError(_("The original requisition does not have an approved backend budget to revise."))
        return budget.sudo()

    def _get_pending_revision(self):
        self.ensure_one()
        root = self._get_revision_root()
        return self.sudo().search([
            ("revision_of_id", "=", root.id),
            ("state", "not in", ["approved", "rejected"]),
        ], order="id desc", limit=1)

    def _open_requisition_action(self, requisition, name=False):
        return {
            "type": "ir.actions.act_window",
            "name": name or _("Budget Requisition"),
            "res_model": "pr.budget.requisition",
            "view_mode": "form",
            "res_id": requisition.id,
            "target": "current",
        }

    def action_open_revisions(self):
        self.ensure_one()
        root = self._get_revision_root()
        revisions = self.sudo().search([("revision_of_id", "=", root.id)], order="revision_number desc, id desc")
        return {
            "type": "ir.actions.act_window",
            "name": _("Budget Revisions"),
            "res_model": "pr.budget.requisition",
            "view_mode": "tree,form",
            "domain": [("id", "in", revisions.ids)],
            "target": "current",
        }

    def action_request_revision(self):
        self.ensure_one()
        if not self._can_user_request_revision(self.env.user):
            raise UserError(_("You cannot request a revision for this budget."))
        if not self.generated_budget_id:
            raise UserError(_("No approved backend budget is available to revise."))
        if self.state != "approved":
            return self._open_requisition_action(self, _("Budget Revision"))

        revision_number = (self.revision_number or 0) + 1
        self.write({
            "state": "draft",
            "revision_number": revision_number,
            "rejection_reason": False,
        })
        self._reset_role_approvals()
        self.message_post(
            body=_("Budget revision R%s started. Edit the existing lines, then submit for approval again.")
            % revision_number
        )
        return self._open_requisition_action(self, _("Budget Revision"))

    def _apply_planned_amounts_to_budget(self, budget, planned_by_cost_center):
        self.ensure_one()
        BudgetLine = self.env["crossovered.budget.lines"].sudo()
        budget = budget.sudo()
        analytic_ids = set(planned_by_cost_center)
        existing_lines = budget.crossovered_budget_line.filtered("analytic_account_id")
        analytic_ids.update(existing_lines.mapped("analytic_account_id").ids)
        analytics = self.env["account.analytic.account"].sudo().browse(list(analytic_ids))
        spent_by_analytic = analytics._get_po_budget_spent_map(
            date_from=self.period_date_from,
            date_to=self.period_date_to,
            budget=budget,
        )
        precision = self.currency_id.rounding or 0.01
        for analytic in analytics:
            planned_amount = planned_by_cost_center.get(analytic.id, 0.0)
            spent_amount = spent_by_analytic.get(analytic.id, 0.0)
            if float_compare(planned_amount, spent_amount, precision_rounding=precision) < 0:
                raise UserError(
                    _(
                        "Cannot revise budget line %(cost_center)s below already spent/committed amount. "
                        "Proposed: %(planned).2f, spent: %(spent).2f."
                    )
                    % {
                        "cost_center": analytic.display_name,
                        "planned": planned_amount,
                        "spent": spent_amount,
                    }
                )

        existing_by_analytic = {}
        duplicate_lines = self.env["crossovered.budget.lines"].sudo()
        for budget_line in existing_lines:
            analytic_id = budget_line.analytic_account_id.id
            if analytic_id in existing_by_analytic:
                duplicate_lines |= budget_line
            else:
                existing_by_analytic[analytic_id] = budget_line

        for analytic_id, planned_amount in planned_by_cost_center.items():
            budget_line = existing_by_analytic.get(analytic_id)
            vals = {
                "crossovered_budget_id": budget.id,
                "analytic_account_id": analytic_id,
                "date_from": self.period_date_from,
                "date_to": self.period_date_to,
                "planned_amount": planned_amount,
            }
            if budget_line:
                budget_line.write(vals)
            else:
                BudgetLine.create(vals)

        obsolete_lines = (
            existing_lines.filtered(lambda line: line.analytic_account_id.id not in planned_by_cost_center)
            | duplicate_lines
        )
        if obsolete_lines:
            obsolete_lines.unlink()

    def _create_or_validate_generated_budget(self):
        self.ensure_one()
        self._check_ready_for_submission()

        Budget = self.env["crossovered.budget"].sudo()
        budget = self.generated_budget_id.sudo()
        planned_by_cost_center = self._planned_amounts_by_cost_center()
        if self.revision_of_id:
            budget = self._get_revision_backend_budget()

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
            budget.message_post(body=_("Generated from department budget requisition %s.") % self.display_name)
        else:
            budget.write({
                "date_from": self.period_date_from,
                "date_to": self.period_date_to,
                "budget_period_months": self.budget_period_months,
                "expense_type": self.expense_type,
                "scope": "department",
                "department_id": self.department_id.id,
                "source_budget_limit": self.total_requested_amount,
            })
            if self.revision_of_id:
                budget.message_post(body=_("Revised from department budget requisition %s.") % self.display_name)

        self._apply_planned_amounts_to_budget(budget, planned_by_cost_center)

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
        budget._sync_cost_center_budget_allowance()
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
        string="Remaining After Approval",
        currency_field="currency_id",
        compute="_compute_remaining_after_request",
    )
    quantity = fields.Float(string="Quantity", default=1.0)
    unit = fields.Char(string="Unit", default="Unit")
    unit_price = fields.Monetary(string="Unit Price", currency_field="currency_id")
    requested_amount = fields.Monetary(string="Total Amount", currency_field="currency_id", required=True)
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
        "requisition_id.generated_budget_id",
        "requisition_id.generated_budget_id.crossovered_budget_line.planned_amount",
        "requisition_id.generated_budget_id.crossovered_budget_line.analytic_account_id",
    )
    def _compute_period_budget_metrics(self):
        for line in self:
            if not line.cost_center_id:
                line.current_budget = 0.0
                line.budget_spent = 0.0
                line.budget_left = 0.0
                continue
            budget = line.requisition_id.generated_budget_id.sudo()
            if budget:
                budget_lines = budget.crossovered_budget_line.filtered(
                    lambda budget_line: budget_line.analytic_account_id == line.cost_center_id
                )
                allowance = sum(budget_lines.mapped("planned_amount"))
                spent = line.cost_center_id.sudo()._get_po_budget_spent_map(
                    date_from=line.requisition_id.period_date_from,
                    date_to=line.requisition_id.period_date_to,
                    budget=budget,
                ).get(line.cost_center_id.id, 0.0)
                line.current_budget = allowance
                line.budget_spent = spent
                line.budget_left = allowance - spent
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
            line.remaining_after_request = requested_for_cost_center - (line.budget_spent or 0.0)

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
