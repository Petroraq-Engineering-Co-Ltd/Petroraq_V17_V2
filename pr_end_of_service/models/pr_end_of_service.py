from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class PrEndOfService(models.Model):
    _name = "pr.end.of.service"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Petroraq End of Service"
    _order = "name desc"

    name = fields.Char(
        string="Number",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
        tracking=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        tracking=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        related="company_id.currency_id",
        store=True,
    )
    contract_id = fields.Many2one(
        "hr.contract",
        string="Contract",
        compute="_compute_contract_data",
        store=True,
        readonly=False,
    )
    joining_date = fields.Date(
        string="Joining Date",
        compute="_compute_contract_data",
        store=True,
        readonly=False,
    )
    service_end_date = fields.Date(
        string="Service End Date",
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    service_years = fields.Float(
        string="Service Years",
        compute="_compute_service_duration",
        store=True,
    )
    years = fields.Integer(string="Years", compute="_compute_service_duration", store=True)
    months = fields.Integer(string="Months", compute="_compute_service_duration", store=True)
    days = fields.Integer(string="Days", compute="_compute_service_duration", store=True)
    settlement_type = fields.Selection(
        [
            ("final", "Final Settlement"),
            ("partial", "Partial Settlement"),
        ],
        string="Settlement Type",
        default="final",
        required=True,
        tracking=True,
    )
    reason_id = fields.Many2one(
        "pr.end.service.reason",
        string="Reason",
        required=True,
        tracking=True,
    )
    date_request = fields.Date(
        string="Request Date",
        default=fields.Date.context_today,
        tracking=True,
    )
    date_hr_approval = fields.Date(string="HR Approval Date", readonly=True, copy=False)
    date_accounting_approval = fields.Date(string="Accounting Approval Date", readonly=True, copy=False)
    date_payment = fields.Date(string="Payment Date", readonly=True, copy=False)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("hr_approval", "HR Approval"),
            ("accounts_approval", "Accounts Approval"),
            ("payment", "Payment"),
            ("done", "Done"),
            ("cancel", "Cancelled"),
        ],
        string="Status",
        default="draft",
        tracking=True,
    )
    monthly_base_amount = fields.Monetary(
        string="Monthly Base",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
    )
    daily_base_amount = fields.Monetary(
        string="Daily Base",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
    )
    eos_benefit_amount = fields.Monetary(
        string="EOS Benefit",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
    )
    annual_leave_type_id = fields.Many2one(
        "hr.leave.type",
        string="Annual Leave Type",
        compute="_compute_annual_leave",
        store=True,
        readonly=False,
    )
    annual_leave_days = fields.Float(
        string="Annual Leave Days",
        compute="_compute_annual_leave",
        store=True,
        readonly=False,
    )
    leave_settlement_amount = fields.Monetary(
        string="Leave Settlement",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
    )
    other_amount = fields.Monetary(
        string="Other Additions",
        currency_field="currency_id",
        tracking=True,
    )
    deduction_amount = fields.Monetary(
        string="Deductions",
        currency_field="currency_id",
        tracking=True,
    )
    total_deserved_amount = fields.Monetary(
        string="Total Deserved",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
    )
    previously_disbursed_amount = fields.Monetary(
        string="Previously Disbursed",
        compute="_compute_previously_disbursed_amount",
        store=True,
        currency_field="currency_id",
    )
    available_amount = fields.Monetary(
        string="Available Amount",
        compute="_compute_available_amount",
        store=True,
        currency_field="currency_id",
    )
    requested_amount = fields.Monetary(
        string="Requested Amount",
        currency_field="currency_id",
        tracking=True,
    )
    is_partial = fields.Boolean(
        string="Partial",
        compute="_compute_is_partial",
        store=True,
    )
    notes = fields.Text(string="Notes")
    bank_payment_id = fields.Many2one(
        "pr.account.bank.payment",
        string="Bank Payment",
        readonly=True,
        copy=False,
    )
    bank_payment_count = fields.Integer(
        string="Bank Payments",
        compute="_compute_bank_payment_count",
    )
    journal_entry_id = fields.Many2one(
        "account.move",
        string="Journal Entry",
        related="bank_payment_id.journal_entry_id",
        readonly=True,
        store=True,
    )

    @api.onchange("employee_id")
    def _onchange_employee_last_working_day(self):
        if self.employee_id and self.employee_id.last_working_date:
            self.service_end_date = self.employee_id.last_working_date

    @api.depends("employee_id", "employee_id.contract_id", "employee_id.contract_id.joining_date", "employee_id.contract_id.date_start")
    def _compute_contract_data(self):
        for rec in self:
            contract = rec.employee_id.contract_id if rec.employee_id else False
            rec.contract_id = contract
            rec.joining_date = (contract.joining_date or contract.date_start) if contract else False

    @api.depends("joining_date", "service_end_date")
    def _compute_service_duration(self):
        for rec in self:
            rec.service_years = 0.0
            rec.years = 0
            rec.months = 0
            rec.days = 0
            if not rec.joining_date or not rec.service_end_date or rec.service_end_date < rec.joining_date:
                continue
            diff = relativedelta(rec.service_end_date, rec.joining_date)
            rec.years = diff.years
            rec.months = diff.months
            rec.days = diff.days
            rec.service_years = diff.years + (diff.months / 12.0) + (diff.days / 365.0)

    @api.depends("settlement_type", "reason_id", "reason_id.is_partial")
    def _compute_is_partial(self):
        for rec in self:
            rec.is_partial = rec.settlement_type == "partial" or bool(rec.reason_id.is_partial)

    def _get_annual_leave_type(self):
        leave_type = self.env["hr.leave.type"].search(
            [("leave_type", "=", "annual_leave")],
            limit=1,
        )
        if not leave_type:
            leave_type = self.env["hr.leave.type"].search(
                [("name", "ilike", "annual")],
                limit=1,
            )
        return leave_type

    def _get_remaining_leave_days(self, leave_type):
        self.ensure_one()
        if not self.employee_id or not leave_type:
            return 0.0
        employee = self.employee_id
        try:
            if hasattr(leave_type, "_pr_sync_due_accrual_allocations"):
                leave_type._pr_sync_due_accrual_allocations(employee)
            allocation_data = leave_type.get_allocation_data(employee, self.service_end_date).get(employee, [])
            leave_type_data = next(
                (
                    data
                    for _name, data, _requires_allocation, leave_type_id in allocation_data
                    if leave_type_id == leave_type.id
                ),
                {},
            )
            return max(
                float(
                    leave_type_data.get("virtual_remaining_leaves")
                    or leave_type_data.get("remaining_leaves")
                    or 0.0
                ),
                0.0,
            )
        except Exception:
            return 0.0

    @api.depends("employee_id", "service_end_date")
    def _compute_annual_leave(self):
        leave_type = self._get_annual_leave_type()
        for rec in self:
            rec.annual_leave_type_id = leave_type
            rec.annual_leave_days = rec._get_remaining_leave_days(leave_type)

    def _get_monthly_base_amount(self):
        self.ensure_one()
        contract = self.contract_id
        if not contract:
            return 0.0
        return contract.gross_amount or contract.net_amount or contract.wage or 0.0

    def _compute_rule_amount(self, monthly_base):
        self.ensure_one()
        if not self.reason_id:
            return 0.0
        if self.service_years < (self.reason_id.deserved_after or 0.0):
            return 0.0
        remaining_years = self.service_years
        amount = 0.0
        for line in self.reason_id.line_ids.sorted(lambda item: (item.sequence, item.id)):
            if remaining_years <= 0.0:
                break
            years_for_line = min(remaining_years, line.deserved_for_first or remaining_years)
            amount += years_for_line * (line.deserved_month_for_year or 0.0) * monthly_base
            remaining_years -= years_for_line
        return amount

    @api.depends(
        "contract_id",
        "contract_id.gross_amount",
        "contract_id.net_amount",
        "contract_id.wage",
        "reason_id",
        "reason_id.line_ids.deserved_for_first",
        "reason_id.line_ids.deserved_month_for_year",
        "service_years",
        "annual_leave_days",
        "other_amount",
        "deduction_amount",
    )
    def _compute_amounts(self):
        for rec in self:
            monthly_base = rec._get_monthly_base_amount()
            rec.monthly_base_amount = monthly_base
            rec.daily_base_amount = monthly_base / 30.0 if monthly_base else 0.0
            rec.eos_benefit_amount = rec._compute_rule_amount(monthly_base)
            rec.leave_settlement_amount = rec.annual_leave_days * rec.daily_base_amount
            rec.total_deserved_amount = (
                rec.eos_benefit_amount
                + rec.leave_settlement_amount
                + rec.other_amount
                - rec.deduction_amount
            )

    @api.depends("employee_id", "reason_id")
    def _compute_previously_disbursed_amount(self):
        for rec in self:
            rec.previously_disbursed_amount = 0.0
            if not rec.employee_id or not rec.reason_id:
                continue
            domain = [
                ("employee_id", "=", rec.employee_id.id),
                ("reason_id", "=", rec.reason_id.id),
                ("state", "=", "done"),
                ("is_partial", "=", True),
            ]
            origin_id = rec._origin.id if rec._origin else False
            if origin_id:
                domain.append(("id", "!=", origin_id))
            previous = self.search(domain)
            rec.previously_disbursed_amount = sum(previous.mapped("requested_amount"))

    @api.depends("total_deserved_amount", "previously_disbursed_amount")
    def _compute_available_amount(self):
        for rec in self:
            rec.available_amount = max(
                rec.total_deserved_amount - rec.previously_disbursed_amount,
                0.0,
            )

    def _compute_bank_payment_count(self):
        for rec in self:
            rec.bank_payment_count = 1 if rec.bank_payment_id else 0

    @api.onchange("reason_id", "settlement_type", "available_amount")
    def _onchange_requested_amount(self):
        for rec in self:
            if not rec.is_partial:
                rec.requested_amount = rec.available_amount

    @api.constrains("requested_amount", "available_amount")
    def _check_requested_amount(self):
        for rec in self:
            if rec.requested_amount < 0.0:
                raise ValidationError(_("Requested amount cannot be negative."))
            if rec.requested_amount > rec.available_amount:
                raise ValidationError(_("Requested amount cannot be greater than available amount."))

    @api.constrains("joining_date", "service_end_date")
    def _check_service_dates(self):
        for rec in self:
            if rec.joining_date and rec.service_end_date and rec.service_end_date < rec.joining_date:
                raise ValidationError(_("Service end date cannot be before the joining date."))

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []
        for incoming_vals in vals_list:
            vals = dict(incoming_vals)
            employee = self.env["hr.employee"].browse(vals.get("employee_id")).exists()
            if employee and employee.last_working_date and not vals.get("service_end_date"):
                vals["service_end_date"] = employee.last_working_date
            prepared_vals_list.append(vals)
        records = super().create(prepared_vals_list)
        for rec in records:
            if rec.name in (False, _("New"), "New"):
                rec.name = self.env["ir.sequence"].next_by_code("pr.end.of.service") or _("New")
            if not rec.is_partial and not rec.requested_amount:
                rec.requested_amount = rec.available_amount
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(field in vals for field in ("reason_id", "settlement_type", "available_amount")):
            for rec in self.filtered(lambda item: not item.is_partial and item.state == "draft"):
                rec.requested_amount = rec.available_amount
        return res

    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                continue
            if not rec.contract_id:
                raise UserError(_("The employee must have an active contract."))
            if rec.requested_amount <= 0.0:
                raise UserError(_("Requested amount must be greater than zero."))
            rec.state = "hr_approval"
            rec.message_post(body=_("End of service request submitted for HR approval."))

    def action_hr_approve(self):
        for rec in self:
            if rec.state != "hr_approval":
                continue
            rec.write({
                "state": "accounts_approval",
                "date_hr_approval": fields.Date.context_today(rec),
            })
            rec.message_post(body=_("HR approved the end of service request."))

    def _get_config_account(self, key, label):
        value = self.env["ir.config_parameter"].sudo().get_param(key)
        try:
            account_id = int(value or 0)
        except (TypeError, ValueError):
            account_id = 0
        account = self.env["account.account"].browse(account_id).exists()
        if not account:
            raise UserError(_("Please configure %s in Settings before creating the bank payment.") % label)
        return account

    def _employee_analytic_distribution(self):
        self.ensure_one()
        distribution = {}
        for field_name in (
            "department_cost_center_id",
            "section_cost_center_id",
            "project_cost_center_id",
            "employee_cost_center_id",
        ):
            if field_name in self.employee_id._fields:
                account = self.employee_id[field_name]
                if account:
                    distribution[str(account.id)] = 100.0
        return distribution

    def _prepare_bank_payment_vals(self):
        self.ensure_one()
        expense_account = self._get_config_account(
            "pr_end_of_service.expense_account_id",
            _("EOS Expense Account"),
        )
        payment_account = self._get_config_account(
            "pr_end_of_service.payment_account_id",
            _("EOS Payment Account"),
        )
        line_vals = {
            "account_id": expense_account.id,
            "description": _("End of Service settlement for %s (%s)") % (self.employee_id.display_name, self.name),
            "amount": self.requested_amount,
            "analytic_distribution": self._employee_analytic_distribution() or False,
            "reference_number": self.name,
        }
        if "employee_cost_center_id" in self.employee_id._fields and self.employee_id.employee_cost_center_id:
            line_vals["cs_employee_id"] = self.employee_id.employee_cost_center_id.id
        return {
            "account_id": payment_account.id,
            "description": _("End of Service settlement for %s (%s)") % (self.employee_id.display_name, self.name),
            "accounting_date": fields.Date.context_today(self),
            "eos_id": self.id,
            "bank_payment_line_ids": [(0, 0, line_vals)],
        }

    def action_accounting_approve(self):
        for rec in self:
            if rec.state != "accounts_approval":
                continue
            if not rec.bank_payment_id:
                payment = self.env["pr.account.bank.payment"].sudo().create(rec._prepare_bank_payment_vals())
                rec.bank_payment_id = payment.id
                rec.message_post(body=_("Bank Payment %s created for EOS settlement.") % payment.name)
            rec.write({
                "state": "payment",
                "date_accounting_approval": fields.Date.context_today(rec),
            })

    def _mark_done_from_payment(self, payment):
        for rec in self:
            if rec.bank_payment_id != payment or rec.state == "done":
                continue
            rec.write({
                "state": "done",
                "date_payment": fields.Date.context_today(rec),
            })
            if not rec.is_partial:
                rec.employee_id.with_context(pr_eos_service_end_date=rec.service_end_date).set_out_of_service()
            rec.message_post(body=_("End of service settlement completed from posted bank payment %s.") % payment.name)

    def action_mark_done(self):
        for rec in self:
            if rec.state != "payment":
                continue
            if not rec.bank_payment_id or rec.bank_payment_id.state != "posted":
                raise UserError(_("The related bank payment must be posted first."))
            rec._mark_done_from_payment(rec.bank_payment_id)

    def action_cancel(self):
        for rec in self:
            if rec.bank_payment_id and rec.bank_payment_id.state == "posted":
                raise UserError(_("You cannot cancel an EOS request with a posted bank payment."))
            rec.state = "cancel"

    def action_reset_to_draft(self):
        for rec in self:
            if rec.bank_payment_id and rec.bank_payment_id.state == "posted":
                raise UserError(_("You cannot reset an EOS request with a posted bank payment."))
            rec.write({
                "state": "draft",
                "date_hr_approval": False,
                "date_accounting_approval": False,
                "date_payment": False,
            })

    def action_view_bank_payment(self):
        self.ensure_one()
        if not self.bank_payment_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Bank Payment"),
            "res_model": "pr.account.bank.payment",
            "view_mode": "form",
            "res_id": self.bank_payment_id.id,
        }

    def action_view_journal_entry(self):
        self.ensure_one()
        if not self.journal_entry_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Journal Entry"),
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.journal_entry_id.id,
        }
