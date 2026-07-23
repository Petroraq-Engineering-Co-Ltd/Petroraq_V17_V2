import base64

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from .eos_calculation import MIN_EOS_SERVICE_YEARS, get_eosb_breakdown, get_service_duration

MD_GROUP = "pr_hr_recruitment_request.group_onboarding_md"


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
    service_period = fields.Char(
        string="Service Period",
        compute="_compute_service_duration",
        store=True,
    )
    years = fields.Integer(string="Years", compute="_compute_service_duration", store=True)
    months = fields.Integer(string="Months", compute="_compute_service_duration", store=True)
    days = fields.Integer(string="Days", compute="_compute_service_duration", store=True)
    completed_years = fields.Integer(
        string="Completed Years",
        compute="_compute_service_duration",
        store=True,
    )
    remaining_months = fields.Integer(
        string="Remaining Months",
        compute="_compute_service_duration",
        store=True,
    )
    remaining_days = fields.Integer(
        string="Remaining Days",
        compute="_compute_service_duration",
        store=True,
    )
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
    date_md_approval = fields.Date(string="MD Approval Date", readonly=True, copy=False)
    md_approved_by_id = fields.Many2one(
        "res.users",
        string="MD Approved By",
        readonly=True,
        copy=False,
    )
    date_accounting_approval = fields.Date(string="Accounting Approval Date", readonly=True, copy=False)
    date_payment = fields.Date(string="Payment Date", readonly=True, copy=False)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("hr_approval", "HR Approval"),
            ("md_approval", "MD Approval"),
            ("accounts_approval", "Accounts Approval"),
            ("employee_acceptance", "Employee Acceptance"),
            ("employee_rejected", "Employee Rejected"),
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
    eos_eligible = fields.Boolean(
        string="EOSB Eligible",
        compute="_compute_amounts",
        store=True,
    )
    eligibility_status = fields.Selection(
        [
            ("eligible", "Eligible"),
            ("not_eligible", "Not Eligible"),
        ],
        string="Eligibility Status",
        compute="_compute_amounts",
        store=True,
    )
    eligibility_message = fields.Char(
        string="Eligibility Message",
        compute="_compute_amounts",
        store=True,
    )
    eosb_formula_applied = fields.Text(
        string="EOSB Formula Applied",
        compute="_compute_amounts",
        store=True,
    )
    annual_leave_type_id = fields.Many2one(
        "hr.leave.type",
        string="Leave Type",
        compute="_compute_annual_leave",
        store=True,
        readonly=False,
    )
    annual_leave_days = fields.Float(
        string="Unused Annual Leave Days",
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
        string="Manual Addition",
        currency_field="currency_id",
        tracking=True,
    )
    deduction_amount = fields.Monetary(
        string="Manual Deductions",
        currency_field="currency_id",
        tracking=True,
    )
    adjustment_line_ids = fields.One2many(
        "pr.end.of.service.adjustment",
        "eos_id",
        string="Arrears / Deductions",
        copy=True,
    )
    adjustment_addition_amount = fields.Monetary(
        string="Arrears / Additions",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
    )
    adjustment_deduction_amount = fields.Monetary(
        string="Clearance Deductions",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
    )
    payroll_adjustment_synced_date = fields.Datetime(
        string="Recoveries Synced On",
        readonly=True,
        copy=False,
    )
    total_deserved_amount = fields.Monetary(
        string="Total Payable",
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
    net_settlement_amount = fields.Monetary(
        string="Net Settlement",
        compute="_compute_available_amount",
        store=True,
        currency_field="currency_id",
        help="Signed settlement after previous disbursements. Negative means the employee owes the company.",
    )
    available_amount = fields.Monetary(
        string="Available Amount",
        compute="_compute_available_amount",
        store=True,
        currency_field="currency_id",
    )
    employee_recovery_amount = fields.Monetary(
        string="Recoverable From Employee",
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
    employee_acceptance_state = fields.Selection(
        [
            ("not_sent", "Not Sent"),
            ("sent", "Sent"),
            ("accepted", "Accepted"),
            ("rejected", "Rejected"),
        ],
        string="Employee Acceptance",
        default="not_sent",
        readonly=True,
        copy=False,
        tracking=True,
    )
    employee_acceptance_date = fields.Datetime(
        string="Employee Acceptance Date",
        readonly=True,
        copy=False,
    )
    employee_acceptance_email = fields.Char(
        string="Settlement Sent To",
        readonly=True,
        copy=False,
        tracking=True,
    )
    employee_acceptance_email_sent_at = fields.Datetime(
        string="Settlement Email Sent On",
        readonly=True,
        copy=False,
        tracking=True,
    )
    employee_rejection_reason = fields.Text(
        string="Employee Rejection Reason",
        readonly=True,
        copy=False,
        tracking=True,
    )
    recovery_state = fields.Selection(
        [
            ("not_required", "Not Required"),
            ("pending", "Pending Recovery"),
            ("recovered", "Recovered"),
            ("waived", "Waived"),
        ],
        string="Recovery Status",
        default="not_required",
        readonly=True,
        copy=False,
        tracking=True,
    )
    recovery_date = fields.Date(string="Recovery Date", readonly=True, copy=False)
    recovery_note = fields.Text(string="Recovery / Waiver Notes", tracking=True)
    expense_bucket_id = fields.Many2one(
        "crossovered.budget",
        string="Budget",
        tracking=True,
        domain="[('state', 'in', ['validate', 'done']), ('pr_under_revision', '=', False)]",
    )
    cost_center_id = fields.Many2one(
        "account.analytic.account",
        string="Cost Center",
        tracking=True,
    )
    payment_request_id = fields.Many2one(
        "pr.employee.payment.request",
        string="Payment Request",
        readonly=True,
        copy=False,
        tracking=True,
    )
    cash_payment_id = fields.Many2one(
        "pr.account.cash.payment",
        string="Cash Payment",
        readonly=True,
        copy=False,
    )
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
        if self.employee_id:
            self.cost_center_id = self._get_default_cost_center()
            self.expense_bucket_id = self._get_default_budget(self.cost_center_id)

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
            rec.service_period = "0 years, 0 months, 0 days"
            rec.years = 0
            rec.months = 0
            rec.days = 0
            rec.completed_years = 0
            rec.remaining_months = 0
            rec.remaining_days = 0
            if not rec.joining_date or not rec.service_end_date or rec.service_end_date < rec.joining_date:
                continue
            duration = get_service_duration(rec.joining_date, rec.service_end_date)
            rec.years = duration["years"]
            rec.months = duration["months"]
            rec.days = duration["days"]
            rec.completed_years = duration["years"]
            rec.remaining_months = duration["months"]
            rec.remaining_days = duration["days"]
            rec.service_years = duration["service_years"]
            rec.service_period = duration["period_display"]

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
        minimum_years = max(self.reason_id.deserved_after or 0.0, MIN_EOS_SERVICE_YEARS)
        completed_years = int(self.completed_years or 0)
        if completed_years < minimum_years:
            return 0.0
        remaining_years = completed_years
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
        "completed_years",
        "annual_leave_days",
        "other_amount",
        "deduction_amount",
        "adjustment_line_ids.adjustment_type",
        "adjustment_line_ids.amount",
    )
    def _compute_amounts(self):
        for rec in self:
            monthly_base = rec._get_monthly_base_amount()
            eosb_breakdown = get_eosb_breakdown(monthly_base, rec.service_years, rec.completed_years)
            rec.monthly_base_amount = monthly_base
            rec.daily_base_amount = monthly_base / 30.0 if monthly_base else 0.0
            rec.eos_benefit_amount = rec._compute_rule_amount(monthly_base)
            rec.eos_eligible = eosb_breakdown["eligible"]
            rec.eligibility_status = eosb_breakdown["status"]
            rec.eligibility_message = eosb_breakdown["message"]
            rec.eosb_formula_applied = eosb_breakdown["formula"]
            rec.leave_settlement_amount = rec.annual_leave_days * rec.daily_base_amount
            rec.adjustment_addition_amount = sum(
                rec.adjustment_line_ids.filtered(
                    lambda line: line.adjustment_type == "addition"
                ).mapped("amount")
            )
            rec.adjustment_deduction_amount = sum(
                rec.adjustment_line_ids.filtered(
                    lambda line: line.adjustment_type == "deduction"
                ).mapped("amount")
            )
            rec.total_deserved_amount = (
                rec.eos_benefit_amount
                + rec.leave_settlement_amount
                + rec.other_amount
                + rec.adjustment_addition_amount
                - rec.deduction_amount
                - rec.adjustment_deduction_amount
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
            net_amount = rec.total_deserved_amount - rec.previously_disbursed_amount
            rec.net_settlement_amount = net_amount
            rec.available_amount = max(net_amount, 0.0)
            rec.employee_recovery_amount = abs(min(net_amount, 0.0))

    def _compute_bank_payment_count(self):
        for rec in self:
            rec.bank_payment_count = 1 if rec.bank_payment_id else 0

    def _needs_requested_amount_auto_sync(self):
        self.ensure_one()
        return not self.is_partial and self.state in ("draft", "hr_approval", "md_approval")

    def _sync_recovery_state_from_amount(self):
        for rec in self:
            if rec.employee_recovery_amount > 0.0 and rec.recovery_state == "not_required":
                rec.recovery_state = "pending"
            elif rec.employee_recovery_amount <= 0.0 and rec.recovery_state in ("not_required", "pending"):
                rec.recovery_state = "not_required"

    @api.onchange("reason_id", "settlement_type", "available_amount")
    def _onchange_requested_amount(self):
        for rec in self:
            if not rec.is_partial:
                rec.requested_amount = rec.available_amount

    def _get_payslip_net_amount(self, payslip):
        net_lines = payslip.line_ids.filtered(lambda line: (line.code or "").upper() == "NET")
        if net_lines:
            return sum(net_lines.mapped("total"))
        for field_name in ("net_wage", "net_amount", "amount_net"):
            if field_name in payslip._fields:
                return payslip[field_name] or 0.0
        return 0.0

    def _get_salary_attachment_remaining_amount(self, attachment):
        fields_to_try = (
            "remaining_amount",
            "amount_residual",
            "total_amount",
            "amount",
            "monthly_amount",
        )
        for field_name in fields_to_try:
            if field_name in attachment._fields and attachment[field_name]:
                amount = attachment[field_name]
                if field_name in ("total_amount", "amount") and "paid_amount" in attachment._fields:
                    amount -= attachment.paid_amount or 0.0
                return max(amount or 0.0, 0.0)
        return 0.0

    def _get_salary_attachment_employee_domain(self, Attachment):
        self.ensure_one()
        if "employee_id" in Attachment._fields:
            return [("employee_id", "=", self.employee_id.id)]
        if "employee_ids" in Attachment._fields:
            return [("employee_ids", "in", self.employee_id.ids)]
        return []

    def _get_salary_attachment_state_domain(self, Attachment):
        state_field = Attachment._fields.get("state")
        if not state_field:
            return []
        selection = state_field.selection
        available_states = []
        if isinstance(selection, (list, tuple)):
            available_states = [item[0] for item in selection]
        wanted_states = [
            state
            for state in ("draft", "open", "running", "active", "in_progress")
            if not available_states or state in available_states
        ]
        return [("state", "in", wanted_states or ["draft", "open"])]

    def _get_employee_partner(self):
        self.ensure_one()
        employee = self.employee_id.sudo()
        if "work_contact_id" in employee._fields and employee.work_contact_id:
            return employee.work_contact_id
        if "address_home_id" in employee._fields and employee.address_home_id:
            return employee.address_home_id
        return self.env["res.partner"]

    def _get_employee_account_recovery_amount(self):
        self.ensure_one()
        employee = self.employee_id.sudo()
        account = employee.employee_account_id if "employee_account_id" in employee._fields else False
        posted_domain = [("move_id.state", "=", "posted")]
        MoveLine = self.env["account.move.line"].sudo()
        recovery_lines = MoveLine
        if account:
            recovery_lines |= MoveLine.search(posted_domain + [("account_id", "=", account.id)])

        Account = self.env["account.account"].sudo()
        employee_advance_accounts = Account
        if "accounts_receivable_subcategory" in Account._fields:
            employee_advance_accounts = Account.search([
                ("accounts_receivable_subcategory", "=", "employee_advances"),
            ])
        else:
            employee_advance_accounts = Account.browse()

        if employee_advance_accounts:
            partner = self._get_employee_partner()
            if partner:
                recovery_lines |= MoveLine.search(
                    posted_domain
                    + [
                        ("partner_id", "=", partner.id),
                        ("account_id", "in", employee_advance_accounts.ids),
                    ]
                )
            employee_cost_center = (
                employee.employee_cost_center_id
                if "employee_cost_center_id" in employee._fields
                else False
            )
            if employee_cost_center and "cs_employee_id" in MoveLine._fields:
                recovery_lines |= MoveLine.search(
                    posted_domain
                    + [
                        ("cs_employee_id", "=", employee_cost_center.id),
                        ("account_id", "in", employee_advance_accounts.ids),
                    ]
                )

        balance = sum(recovery_lines.mapped("balance"))
        return max(balance, 0.0)

    def action_sync_payroll_adjustments(self):
        for rec in self:
            if rec.state not in ("draft", "hr_approval", "md_approval"):
                raise UserError(_("Recoveries can only be synced before accounts approval."))
            rec.sudo().adjustment_line_ids.filtered(
                lambda line: (line.source_ref or "").startswith(("payroll:", "accounts:"))
            ).unlink()
            line_commands = []
            Payslip = self.env["hr.payslip"].sudo()
            payslip_domain = [
                ("employee_id", "=", rec.employee_id.id),
                ("state", "not in", ["paid", "cancel"]),
            ]
            if "hold_salary" in Payslip._fields:
                payslip_domain.append(("hold_salary", "=", True))
            if rec.service_end_date:
                payslip_domain.append(("date_to", "<=", rec.service_end_date))
            for payslip in Payslip.search(payslip_domain):
                net_amount = rec._get_payslip_net_amount(payslip)
                if not net_amount:
                    continue
                payslip_label = payslip.name or getattr(payslip, "number", False) or payslip.display_name
                line_commands.append((0, 0, {
                    "name": _("Held salary arrears: %s") % payslip_label,
                    "category": "salary_arrears",
                    "adjustment_type": "addition" if net_amount > 0 else "deduction",
                    "amount": abs(net_amount),
                    "source_ref": "payroll:payslip:%s" % payslip.id,
                    "notes": _("Created from held/unpaid payslip during EOS payroll sync."),
                }))

            Attachment = self.env["hr.salary.attachment"].sudo()
            employee_domain = rec._get_salary_attachment_employee_domain(Attachment)
            if employee_domain:
                attachment_domain = employee_domain
                attachment_domain += rec._get_salary_attachment_state_domain(Attachment)
                if "payment_state" in Attachment._fields:
                    attachment_domain.append(("payment_state", "!=", "paid"))
                for attachment in Attachment.search(attachment_domain):
                    amount = rec._get_salary_attachment_remaining_amount(attachment)
                    if not amount:
                        continue
                    line_commands.append((0, 0, {
                        "name": _("Open salary attachment: %s") % attachment.display_name,
                        "category": "loan",
                        "adjustment_type": "deduction",
                        "amount": amount,
                        "source_ref": "payroll:salary_attachment:%s" % attachment.id,
                        "notes": _("Created from open salary attachment during EOS payroll sync."),
                    }))
            employee_account_recovery = rec._get_employee_account_recovery_amount()
            if employee_account_recovery:
                employee_account = (
                    rec.employee_id.sudo().employee_account_id
                    if "employee_account_id" in rec.employee_id._fields
                    else False
                )
                line_commands.append((0, 0, {
                    "name": _("Outstanding employee account balance%s") % (
                        ": %s" % employee_account.display_name if employee_account else ""
                    ),
                    "category": "account",
                    "adjustment_type": "deduction",
                    "amount": employee_account_recovery,
                    "source_ref": "accounts:employee_account:%s" % (employee_account.id if employee_account else rec.employee_id.id),
                    "notes": _("Created from posted Accounts balance during EOS recovery sync."),
                }))
            if line_commands:
                rec.sudo().write({
                    "adjustment_line_ids": line_commands,
                    "payroll_adjustment_synced_date": fields.Datetime.now(),
                })
            else:
                rec.sudo().payroll_adjustment_synced_date = fields.Datetime.now()
            rec.message_post(body=_("Payroll arrears and employee recovery deduction lines were synced."))
        return True

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
            if not rec.cost_center_id:
                rec.cost_center_id = rec._get_default_cost_center()
            if rec.cost_center_id and not rec.expense_bucket_id:
                rec.expense_bucket_id = rec._get_default_budget(rec.cost_center_id)
            rec._sync_recovery_state_from_amount()
        return records

    def write(self, vals):
        amount_fields = {
            "reason_id",
            "settlement_type",
            "available_amount",
            "annual_leave_days",
            "other_amount",
            "deduction_amount",
            "adjustment_line_ids",
        }
        sync_requested = (
            not self.env.context.get("skip_requested_amount_auto_sync")
            and "requested_amount" not in vals
            and bool(amount_fields.intersection(vals))
        )
        records_to_sync = (
            self.filtered(lambda rec: rec._needs_requested_amount_auto_sync())
            if sync_requested
            else self.env[self._name]
        )
        if records_to_sync:
            records_to_sync.with_context(skip_requested_amount_auto_sync=True).write({"requested_amount": 0.0})
        res = super().write(vals)
        if sync_requested:
            for rec in records_to_sync.exists().filtered(lambda item: item._needs_requested_amount_auto_sync()):
                rec.with_context(skip_requested_amount_auto_sync=True).requested_amount = rec.available_amount
        if bool(amount_fields.intersection(vals)):
            self._sync_recovery_state_from_amount()
        return res

    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                continue
            if not rec.contract_id:
                raise UserError(_("The employee must have an active contract."))
            if rec.requested_amount <= 0.0:
                if rec.available_amount > 0.0:
                    raise UserError(_("Requested amount must be greater than zero."))
            rec.state = "hr_approval"
            rec.message_post(body=_("End of service request submitted for HR approval."))

    def action_hr_approve(self):
        for rec in self:
            if rec.state != "hr_approval":
                continue
            rec.write({
                "state": "md_approval",
                "date_hr_approval": fields.Date.context_today(rec),
                "md_approved_by_id": False,
                "date_md_approval": False,
            })
            rec.message_post(body=_("HR approved the end of service request and sent it for MD approval."))

    def action_md_approve(self):
        if not (
            self.env.su
            or self.env.user.has_group(MD_GROUP)
            or self.env.user.has_group("base.group_system")
        ):
            raise UserError(_("Only MD can approve this end of service settlement."))
        for rec in self:
            if rec.state != "md_approval":
                continue
            rec.action_sync_payroll_adjustments()
            rec.write({
                "state": "accounts_approval",
                "md_approved_by_id": self.env.user.id,
                "date_md_approval": fields.Date.context_today(rec),
            })
            rec.message_post(body=_("MD approved the end of service request and sent it for Accounts approval."))

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

    def _get_default_cost_center(self):
        self.ensure_one()
        employee = self.employee_id.sudo()
        for field_name in (
            "employee_cost_center_id",
            "project_cost_center_id",
            "section_cost_center_id",
            "department_cost_center_id",
        ):
            if field_name in employee._fields and employee[field_name]:
                return employee[field_name]
        department = employee.department_id
        if (
            department
            and "department_cost_center_id" in department._fields
            and department.department_cost_center_id
        ):
            return department.department_cost_center_id
        return self.env["account.analytic.account"]

    def _get_default_budget(self, cost_center=False):
        self.ensure_one()
        cost_center = cost_center or self.cost_center_id
        if not cost_center:
            return self.env["crossovered.budget"]
        target_date = self.date_request or fields.Date.context_today(self)
        return self.env["crossovered.budget"].sudo().search([
            ("state", "in", ["validate", "done"]),
            ("date_from", "<=", target_date),
            ("date_to", ">=", target_date),
            ("crossovered_budget_line.analytic_account_id", "=", cost_center.id),
            ("pr_under_revision", "=", False),
        ], order="date_from desc, id desc", limit=1)

    def _check_payment_request_budget(self):
        self.ensure_one()
        if not self.cost_center_id:
            raise UserError(_("Please select the Cost Center before creating the payment request."))
        if not self.expense_bucket_id:
            raise UserError(_("Please select the approved Budget before creating the payment request."))
        self.expense_bucket_id._check_active_for_date(
            self.date_request or fields.Date.context_today(self)
        )
        remaining = self.expense_bucket_id._get_remaining_by_cost_center()
        if self.cost_center_id.id not in remaining:
            raise UserError(
                _("Cost Center %(cc)s is not included in Budget %(budget)s.")
                % {
                    "cc": self.cost_center_id.display_name,
                    "budget": self.expense_bucket_id.display_name,
                }
            )
        if self.requested_amount > remaining.get(self.cost_center_id.id, 0.0):
            raise UserError(
                _("Insufficient budget for %(cc)s. Remaining: %(remaining).2f, Required: %(amount).2f")
                % {
                    "cc": self.cost_center_id.display_name,
                    "remaining": remaining.get(self.cost_center_id.id, 0.0),
                    "amount": self.requested_amount,
                }
            )

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
            if rec.requested_amount <= 0.0:
                recovery_state = "pending" if rec.employee_recovery_amount > 0.0 else "not_required"
                rec.write({
                    "state": "done",
                    "date_accounting_approval": fields.Date.context_today(rec),
                    "date_payment": fields.Date.context_today(rec),
                    "employee_acceptance_state": "accepted",
                    "employee_acceptance_date": fields.Datetime.now(),
                    "recovery_state": recovery_state,
                })
                attachment = rec._generate_final_settlement_pdf_attachment()
                if not rec.is_partial:
                    rec.employee_id.with_context(pr_eos_service_end_date=rec.service_end_date).set_out_of_service()
                if rec.employee_recovery_amount > 0.0:
                    rec.message_post(body=_(
                        "Accounts approved a negative EOS settlement. No payment was created; %s is recoverable from the employee."
                    ) % rec.employee_recovery_amount, attachment_ids=attachment.ids if attachment else [])
                else:
                    rec.message_post(
                        body=_("Accounts approved a zero-payment EOS settlement. Employee was marked out of service. Final settlement PDF is attached."),
                        attachment_ids=attachment.ids if attachment else [],
                    )
                continue
            rec._check_payment_request_budget()
            rec.write({
                "state": "employee_acceptance",
                "date_accounting_approval": fields.Date.context_today(rec),
                "employee_acceptance_state": "sent",
                "employee_rejection_reason": False,
            })
            rec.action_send_employee_acceptance_email()

    def _create_payment_request_if_needed(self):
        self.ensure_one()
        if self.requested_amount <= 0.0 or self.payment_request_id:
            return self.payment_request_id
        if self.cash_payment_id or self.bank_payment_id:
            raise UserError(_("A payment voucher already exists for this EOS settlement."))
        self._check_payment_request_budget()
        expense_account = self._get_config_account(
            "pr_end_of_service.expense_account_id",
            _("EOS Expense Account"),
        )
        payment_request = self.env["pr.employee.payment.request"].sudo().create({
            "eos_id": self.id,
            "requested_user_id": self.env.user.id,
            "employee_id": self.employee_id.id,
            "company_id": self.company_id.id,
            "expense_bucket_id": self.expense_bucket_id.id,
            "cost_center_id": self.cost_center_id.id,
            "line_ids": [(0, 0, {
                "description": _("End of Service settlement for %s (%s)")
                % (self.employee_id.display_name, self.name),
                "amount": self.requested_amount,
                "expense_account_id": expense_account.id,
            })],
        })
        self.payment_request_id = payment_request.id
        payment_request._notify_accounts()
        self.message_post(
            body=_("Payment Request %s created for EOS settlement. Accounts can create its CPV/BPV.")
            % payment_request.name
        )
        return payment_request

    def _get_final_settlement_pdf_filename(self):
        self.ensure_one()
        return ("Final Settlement - %s.pdf" % (self.name or self.employee_id.display_name)).replace("/", "-")

    def _generate_final_settlement_pdf_attachment(self):
        self.ensure_one()
        existing = self.env["ir.attachment"].sudo().search([
            ("res_model", "=", self._name),
            ("res_id", "=", self.id),
            ("name", "=", self._get_final_settlement_pdf_filename()),
        ], limit=1)
        report = self.env.ref(
            "pr_end_of_service.action_report_pr_end_of_service",
            raise_if_not_found=False,
        )
        if not report:
            return self.env["ir.attachment"]
        pdf_content, _content_type = self.env["ir.actions.report"].sudo()._render_qweb_pdf(
            report.report_name,
            [self.id],
        )
        attachment_vals = {
            "name": self._get_final_settlement_pdf_filename(),
            "type": "binary",
            "datas": base64.b64encode(pdf_content),
            "res_model": self._name,
            "res_id": self.id,
            "mimetype": "application/pdf",
        }
        if existing:
            existing.write(attachment_vals)
            return existing
        return self.env["ir.attachment"].sudo().create(attachment_vals)

    def _get_employee_acceptance_email(self):
        self.ensure_one()
        employee = self.employee_id.sudo()
        candidates = [
            employee.work_email,
            employee.user_id.email if employee.user_id else False,
            employee.work_contact_id.email
            if "work_contact_id" in employee._fields and employee.work_contact_id
            else False,
            employee.private_email if "private_email" in employee._fields else False,
            employee.address_home_id.email
            if "address_home_id" in employee._fields and employee.address_home_id
            else False,
        ]
        return next((email.strip() for email in candidates if email and email.strip()), False)

    def action_send_employee_acceptance_email(self):
        for rec in self:
            if rec.state != "employee_acceptance":
                raise UserError(
                    _("The settlement can only be emailed while waiting for Employee Acceptance.")
                )
            email_to = rec._get_employee_acceptance_email()
            if not email_to:
                raise UserError(
                    _(
                        "Employee %s has no email address. Add a Work Email or Private Email before continuing."
                    )
                    % rec.employee_id.display_name
                )
            template = self.env.ref(
                "pr_end_of_service.mail_template_eos_employee_acceptance",
                raise_if_not_found=False,
            )
            if not template:
                raise UserError(_("The EOS employee acceptance email template is not configured."))
            attachment = rec._generate_final_settlement_pdf_attachment()
            if not attachment:
                raise UserError(_("The EOS settlement PDF could not be generated."))
            mail_id = template.sudo().send_mail(
                rec.id,
                force_send=True,
                email_values={
                    "email_to": email_to,
                    "attachment_ids": [(6, 0, attachment.ids)],
                },
            )
            if not mail_id:
                raise UserError(_("The EOS settlement email could not be created or sent."))
            sent_at = fields.Datetime.now()
            rec.write({
                "employee_acceptance_email": email_to,
                "employee_acceptance_email_sent_at": sent_at,
                "employee_acceptance_state": "sent",
            })
            rec.message_post(
                body=_("EOS settlement document emailed to %s for employee acceptance.") % email_to,
                attachment_ids=attachment.ids,
                message_type="notification",
            )
        return True

    def action_employee_accept(self):
        for rec in self:
            if rec.state != "employee_acceptance":
                continue
            if not rec.employee_acceptance_email_sent_at:
                raise UserError(
                    _("Send the EOS settlement document to the employee before recording acceptance.")
                )
            rec._create_payment_request_if_needed()
            rec.write({
                "state": "payment",
                "employee_acceptance_state": "accepted",
                "employee_acceptance_date": fields.Datetime.now(),
                "employee_rejection_reason": False,
            })
            rec.message_post(body=_("Employee accepted the EOS settlement."))

    def action_employee_reject(self):
        for rec in self:
            if rec.state != "employee_acceptance":
                continue
            rec.write({
                "state": "employee_rejected",
                "employee_acceptance_state": "rejected",
                "employee_acceptance_date": fields.Datetime.now(),
                "employee_rejection_reason": _("Rejected by employee. Revise the settlement and resend for approval."),
            })
            rec.message_post(body=_("Employee rejected the EOS settlement. Revise and reset to draft."))

    def _mark_done_from_payment(self, payment):
        for rec in self:
            if payment not in (rec.cash_payment_id, rec.bank_payment_id) or rec.state == "done":
                continue
            rec.write({
                "state": "done",
                "date_payment": fields.Date.context_today(rec),
            })
            attachment = rec._generate_final_settlement_pdf_attachment()
            if not rec.is_partial:
                rec.employee_id.with_context(pr_eos_service_end_date=rec.service_end_date).set_out_of_service()
            rec.message_post(
                body=_("End of service settlement completed from posted bank payment %s. Final settlement PDF is attached.") % payment.name,
                attachment_ids=attachment.ids if attachment else [],
            )

    def action_mark_done(self):
        for rec in self:
            if rec.state not in ("payment", "employee_acceptance"):
                continue
            if rec.requested_amount <= 0.0:
                recovery_state = "pending" if rec.employee_recovery_amount > 0.0 else "not_required"
                rec.write({
                    "state": "done",
                    "date_payment": fields.Date.context_today(rec),
                    "recovery_state": recovery_state,
                })
                attachment = rec._generate_final_settlement_pdf_attachment()
                if not rec.is_partial:
                    rec.employee_id.with_context(pr_eos_service_end_date=rec.service_end_date).set_out_of_service()
                if rec.employee_recovery_amount > 0.0:
                    rec.message_post(body=_(
                        "End of service settlement completed without payment. %s is recoverable from the employee."
                    ) % rec.employee_recovery_amount, attachment_ids=attachment.ids if attachment else [])
                else:
                    rec.message_post(
                        body=_("End of service settlement completed without payment. Final settlement PDF is attached."),
                        attachment_ids=attachment.ids if attachment else [],
                    )
                continue
            payment = rec.cash_payment_id or rec.bank_payment_id
            if not payment or payment.state != "posted":
                raise UserError(_("The CPV/BPV created from the related Payment Request must be posted first."))
            rec._mark_done_from_payment(payment)

    def action_mark_recovery_collected(self):
        for rec in self:
            if rec.employee_recovery_amount <= 0.0:
                raise UserError(_("There is no employee recovery amount on this settlement."))
            rec.write({
                "recovery_state": "recovered",
                "recovery_date": fields.Date.context_today(rec),
            })
            rec.message_post(body=_("Employee recovery amount %s was marked as collected.") % rec.employee_recovery_amount)
        return True

    def action_waive_recovery(self):
        for rec in self:
            if rec.employee_recovery_amount <= 0.0:
                raise UserError(_("There is no employee recovery amount on this settlement."))
            rec.write({
                "recovery_state": "waived",
                "recovery_date": fields.Date.context_today(rec),
            })
            rec.message_post(body=_("Employee recovery amount %s was waived.") % rec.employee_recovery_amount)
        return True

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
                "date_md_approval": False,
                "md_approved_by_id": False,
                "date_accounting_approval": False,
                "date_payment": False,
                "employee_acceptance_state": "not_sent",
                "employee_acceptance_date": False,
                "employee_acceptance_email": False,
                "employee_acceptance_email_sent_at": False,
                "employee_rejection_reason": False,
            })
            rec._sync_recovery_state_from_amount()

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

    def _get_final_settlement_report_data(self):
        self.ensure_one()
        employee = self.employee_id.sudo()
        contract = self.contract_id.sudo()
        offboarding = self.offboarding_request_id.sudo() if self.offboarding_request_id else False
        voucher = self.cash_payment_id or self.bank_payment_id

        salary_rules = contract.contract_salary_rule_ids if contract else self.env["hr.contract.salary.rule"]

        def rule_matches(line, keywords):
            text = "%s %s" % (
                (line.salary_rule_id.code or "").lower(),
                (line.salary_rule_id.name or "").lower(),
            )
            return any(keyword in text for keyword in keywords)

        housing_rules = salary_rules.filtered(
            lambda line: rule_matches(line, ("housing", "house", "hra"))
        )
        transport_rules = salary_rules.filtered(
            lambda line: rule_matches(line, ("transport", "travel", "conveyance"))
        )
        other_rules = salary_rules - housing_rules - transport_rules

        additions = self.adjustment_line_ids.filtered(
            lambda line: line.adjustment_type == "addition"
        )
        deductions = self.adjustment_line_ids.filtered(
            lambda line: line.adjustment_type == "deduction"
        )

        def adjustment_sum(lines, keywords=(), categories=()):
            matched = lines.filtered(
                lambda line: (
                    (categories and line.category in categories)
                    or (
                        keywords
                        and any(
                            keyword in ("%s %s" % (line.name or "", line.notes or "")).lower()
                            for keyword in keywords
                        )
                    )
                )
            )
            return sum(matched.mapped("amount")), matched

        overtime, overtime_lines = adjustment_sum(additions, keywords=("overtime",))
        commission, commission_lines = adjustment_sum(
            additions - overtime_lines,
            keywords=("commission", "incentive", "bonus"),
        )
        salary_payable, salary_lines = adjustment_sum(
            additions - overtime_lines - commission_lines,
            categories=("salary_arrears", "unpaid_salary"),
        )
        categorized_additions = salary_lines | overtime_lines | commission_lines
        other_payables = sum((additions - categorized_additions).mapped("amount"))

        advance_salary, advance_salary_lines = adjustment_sum(
            deductions, keywords=("advance salary", "salary advance")
        )
        advance_hra, advance_hra_lines = adjustment_sum(
            deductions - advance_salary_lines,
            keywords=("advance hra", "housing advance", "hra advance"),
        )
        loan_recovery, loan_lines = adjustment_sum(
            deductions - advance_salary_lines - advance_hra_lines,
            keywords=("loan",),
            categories=("loan",),
        )
        asset_damage, asset_lines = adjustment_sum(
            deductions - advance_salary_lines - advance_hra_lines - loan_lines,
            keywords=("damage", "asset"),
            categories=("asset",),
        )
        traffic_violations, traffic_lines = adjustment_sum(
            deductions - advance_salary_lines - advance_hra_lines - loan_lines - asset_lines,
            keywords=("traffic", "violation", "fine"),
        )
        personal_expenses, personal_lines = adjustment_sum(
            deductions
            - advance_salary_lines
            - advance_hra_lines
            - loan_lines
            - asset_lines
            - traffic_lines,
            keywords=("personal", "expense"),
        )
        categorized_deductions = (
            advance_salary_lines
            | advance_hra_lines
            | loan_lines
            | asset_lines
            | traffic_lines
            | personal_lines
        )
        other_recoveries = (
            sum((deductions - categorized_deductions).mapped("amount"))
            + self.deduction_amount
        )

        clearance_rows = []
        if offboarding:
            clearance_rows = [
                {
                    "name": line.name,
                    "status": (
                        _("Cleared")
                        if line.state == "done"
                        else dict(line._fields["state"].selection).get(line.state, line.state)
                    ),
                }
                for line in offboarding.clearance_line_ids.sorted(
                    lambda line: (line.sequence, line.id)
                )
            ]

        bank_account = (
            employee.bank_account_id
            if "bank_account_id" in employee._fields
            else self.env["res.partner.bank"]
        )
        employment_type = ""
        if contract and "contract_employment_type" in contract._fields:
            employment_type = dict(
                contract._fields["contract_employment_type"].selection
            ).get(contract.contract_employment_type, contract.contract_employment_type or "")

        employee_payables = (
            salary_payable
            + self.leave_settlement_amount
            + overtime
            + commission
            + self.other_amount
            + other_payables
        )
        total_deductions = (
            advance_salary
            + advance_hra
            + loan_recovery
            + asset_damage
            + traffic_violations
            + personal_expenses
            + other_recoveries
            + self.previously_disbursed_amount
        )
        gross_settlement = self.eos_benefit_amount + employee_payables

        return {
            "offboarding_ref": offboarding.name if offboarding else "",
            "settlement_date": self.date_payment or self.date_accounting_approval or self.date_request,
            "termination_reason": self.reason_id.display_name,
            "employee_code": employee.code if "code" in employee._fields else "",
            "employment_type": employment_type,
            "identification": employee.identification_id or employee.passport_id or "",
            "department": employee.department_id.display_name,
            "designation": employee.job_id.display_name,
            "basic_salary": contract.wage if contract else 0.0,
            "housing_allowance": sum(housing_rules.mapped("amount")),
            "transport_allowance": sum(transport_rules.mapped("amount")),
            "other_allowances": sum(other_rules.mapped("amount")),
            "gross_salary": (
                contract.gross_amount or contract.net_amount or contract.wage
                if contract
                else 0.0
            ),
            "salary_payable": salary_payable,
            "overtime": overtime,
            "commission": commission,
            "other_payables": other_payables,
            "employee_payables": employee_payables,
            "advance_salary": advance_salary,
            "advance_hra": advance_hra,
            "loan_recovery": loan_recovery,
            "asset_damage": asset_damage,
            "traffic_violations": traffic_violations,
            "personal_expenses": personal_expenses,
            "other_recoveries": other_recoveries,
            "total_deductions": total_deductions,
            "gross_settlement": gross_settlement,
            "net_settlement": employee_payables - total_deductions,
            "clearance_rows": clearance_rows,
            "payment_method": (
                "Cash"
                if voucher and voucher._name == "pr.account.cash.payment"
                else "Bank Transfer" if voucher else ""
            ),
            "bank": bank_account.bank_id.display_name if bank_account and bank_account.bank_id else "",
            "iban": bank_account.acc_number if bank_account else "",
            "voucher": voucher.display_name if voucher else "",
        }

    def action_view_payment_request(self):
        self.ensure_one()
        if not self.payment_request_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Payment Request"),
            "res_model": "pr.employee.payment.request",
            "view_mode": "form",
            "res_id": self.payment_request_id.id,
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


class PrEndOfServiceAdjustment(models.Model):
    _name = "pr.end.of.service.adjustment"
    _description = "End of Service Arrears / Deduction Line"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    eos_id = fields.Many2one(
        "pr.end.of.service",
        string="End of Service",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company",
        related="eos_id.company_id",
        store=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="eos_id.currency_id",
        readonly=True,
    )
    name = fields.Char(string="Description", required=True)
    category = fields.Selection(
        [
            ("salary_arrears", "Salary Arrears"),
            ("unpaid_salary", "Unpaid Salary"),
            ("asset", "Asset / Handover"),
            ("loan", "Loan / Advance"),
            ("insurance", "Insurance"),
            ("account", "Accounts"),
            ("gosi", "GOSI"),
            ("clearance", "Clearance"),
            ("other", "Other"),
        ],
        string="Category",
        default="other",
        required=True,
    )
    adjustment_type = fields.Selection(
        [
            ("addition", "Addition / Arrears"),
            ("deduction", "Deduction"),
        ],
        string="Type",
        default="deduction",
        required=True,
    )
    amount = fields.Monetary(
        string="Amount",
        required=True,
        currency_field="currency_id",
    )
    source_ref = fields.Char(string="Source Reference", readonly=True, copy=False)
    notes = fields.Text(string="Notes")

    @api.constrains("amount")
    def _check_amount(self):
        for line in self:
            if line.amount < 0.0:
                raise ValidationError(_("Adjustment amount cannot be negative."))
