from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta


IQAMA_REQUEST_TYPES = ("iqama_new", "iqama_renewal")
MEDICAL_INSURANCE_REQUEST_TYPES = ("medical_insurance_new", "medical_insurance_renewal")
HR_COMPLIANCE_REQUEST_TYPES = IQAMA_REQUEST_TYPES + MEDICAL_INSURANCE_REQUEST_TYPES
NEW_COMPLIANCE_REQUEST_TYPES = ("iqama_new", "medical_insurance_new")
COMPLIANCE_RENEWAL_REQUEST_TYPES = ("iqama_renewal", "medical_insurance_renewal")
SERVICE_PERIOD_REQUEST_TYPES = IQAMA_REQUEST_TYPES + MEDICAL_INSURANCE_REQUEST_TYPES
TICKET_REIMBURSEMENT_TYPE = "ticket"
SELF_COMPANY_REQUEST_TYPES = ("exit_reentry",) + COMPLIANCE_RENEWAL_REQUEST_TYPES
SAUDI_RESTRICTED_REQUEST_TYPES = ("exit_reentry",) + IQAMA_REQUEST_TYPES
SELF_PAYMENT_RESPONSIBILITY = "self"
COMPANY_PAYMENT_RESPONSIBILITY = "company"
EXIT_REENTRY_SINGLE_ENTRY = "single"
EXIT_REENTRY_MULTIPLE_ENTRY = "multiple"
ACCOUNTING_GROUP_XML_IDS = (
    "base.group_system",
    "account.group_account_invoice",
    "account.group_account_user",
    "account.group_account_manager",
    "pr_account.custom_group_accounting_manager",
    "pr_account.custom_group_account_supervisor",
)
ACCOUNTING_EPR_RULE_BYPASS_MODES = ("read", "write")


def _open_attachment_preview_action(record, attachments, title=None):
    attachments = attachments.exists()
    if not attachments:
        raise UserError(_("No attachments found to preview."))
    if len(attachments) == 1:
        return attachments.action_preview_inline()

    tree_view = record.env.ref(
        "prt_report_attachment_preview.view_attachment_preview_tree",
        raise_if_not_found=False,
    )
    form_view = record.env.ref(
        "prt_report_attachment_preview.view_attachment_preview_form",
        raise_if_not_found=False,
    )
    views = []
    if tree_view:
        views.append((tree_view.id, "tree"))
    if form_view:
        views.append((form_view.id, "form"))
    action = {
        "type": "ir.actions.act_window",
        "name": title or _("Attachments"),
        "res_model": "ir.attachment",
        "view_mode": "tree,form",
        "domain": [("id", "in", attachments.ids)],
        "target": "current",
        "context": {
            "create": False,
            "delete": False,
        },
    }
    if views:
        action["views"] = views
    return action


class PrEmployeeServiceRequest(models.Model):
    _name = "pr.employee.service.request"
    _description = "Employee Service Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(string="Request Number", default="New", readonly=True, copy=False, tracking=True)
    request_type = fields.Selection(
        [
            ("reimbursement", "Reimbursement"),
            ("exit_reentry", "Exit/Re-entry"),
            ("iqama_new", "New Iqama & Work Permit"),
            ("iqama_renewal", "Iqama & Work Permit Renewal"),
            ("medical_insurance_new", "New Medical Insurance"),
            ("medical_insurance_renewal", "Medical Insurance Renewal"),
        ],
        string="Request Type",
        required=True,
        default="reimbursement",
        tracking=True,
    )
    requested_by_id = fields.Many2one(
        "res.users",
        string="Requested By",
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        default=lambda self: self._default_employee_id(),
        required=True,
        tracking=True,
    )
    department_id = fields.Many2one("hr.department", related="employee_id.department_id", store=True, readonly=True)
    employee_manager_user_id = fields.Many2one(
        "res.users",
        string="Employee Manager",
        compute="_compute_employee_manager_user_id",
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
        tracking=True,
    )
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id", readonly=True)
    request_date = fields.Date(
        string="Request Date",
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    payment_responsibility = fields.Selection(
        [
            (COMPANY_PAYMENT_RESPONSIBILITY, "By Company"),
            (SELF_PAYMENT_RESPONSIBILITY, "Self"),
        ],
        string="Payment Responsibility",
        default=SELF_PAYMENT_RESPONSIBILITY,
        required=True,
        tracking=True,
        help="Self-paid requests do not create employee payment requests or accounting vouchers.",
    )
    exit_reentry_entry_type = fields.Selection(
        [
            (EXIT_REENTRY_SINGLE_ENTRY, "Single Entry"),
            (EXIT_REENTRY_MULTIPLE_ENTRY, "Multiple Entry"),
        ],
        string="Exit/Re-entry Type",
        default=EXIT_REENTRY_SINGLE_ENTRY,
        required=True,
        tracking=True,
        help="Multiple-entry Exit/Re-entry visas are always self-paid.",
    )
    exit_reentry_historical_company_paid = fields.Boolean(
        string="Already Taken on Company Expense",
        copy=False,
        tracking=True,
        help=(
            "Use this for old company-paid Exit/Re-entry visas that were already "
            "approved and paid outside this workflow. It creates a record only and "
            "still consumes the company-paid entitlement."
        ),
    )
    contract_id = fields.Many2one(
        "hr.contract",
        string="Contract",
        readonly=True,
        copy=False,
        tracking=True,
    )
    contract_exit_reentry_benefit_type = fields.Selection(
        related="contract_id.exit_reentry_benefit_type",
        string="Contract Category",
        readonly=True,
    )
    exit_reentry_company_eligible = fields.Boolean(
        string="Company Exit/Re-entry Eligible",
        compute="_compute_exit_reentry_eligibility",
    )
    exit_reentry_eligibility_message = fields.Char(
        string="Eligibility Note",
        compute="_compute_exit_reentry_eligibility",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("hr_supervisor_approval", "HR Supervisor"),
            ("employee_manager_approval", "Dept. Manager"),
            ("hr_manager_approval", "HR Manager"),
            ("accounts_approval", "Accounts"),
            ("md_approval", "Managing Director"),
            ("finance_approval", "Finance"),
            ("payment_approval", "Voucher Approval"),
            ("paid", "Paid"),
            ("issued", "Issued"),
            ("rejected", "Rejected"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        tracking=True,
        copy=False,
    )

    reimbursement_type = fields.Selection(
        [
            ("fuel", "Fuel"),
            ("food", "Food"),
            ("business_trip", "Business Trip"),
            ("petty_cash", "Petty Cash"),
            ("ticket", "Ticket"),
            ("travel", "Travel"),
            ("medical", "Medical"),
            ("mobile", "Mobile/Internet"),
            ("office", "Office Expense"),
            ("government", "Government Fee"),
            ("other", "Other"),
        ],
        string="Reimbursement Category",
        default="fuel",
        tracking=True,
    )
    expense_date = fields.Date(string="Expense Date", tracking=True)
    requested_amount = fields.Monetary(
        string="Requested Amount",
        currency_field="currency_id",
        tracking=True,
    )
    approved_amount = fields.Monetary(
        string="Approved / Payable Amount",
        currency_field="currency_id",
        tracking=True,
    )
    payment_method = fields.Selection(
        [("bank", "Bank Transfer"), ("cash", "Cash")],
        string="Payment Method",
        default="bank",
        tracking=True,
    )
    payment_account_id = fields.Many2one(
        "account.account",
        string="Pay From Account",
        tracking=True,
        domain="[('account_type', 'in', ['asset_cash', 'asset_current'])]",
    )
    expense_bucket_id = fields.Many2one(
        "crossovered.budget",
        string="Budget",
        tracking=True,
        domain="[('state', 'in', ['validate', 'done']), ('pr_under_revision', '=', False)]",
        help="Approved backend budget to consume for this HR request.",
    )
    cost_center_id = fields.Many2one(
        "account.analytic.account",
        string="Cost Center",
        tracking=True,
        help="Cost center that will receive the BPV/CPV analytic distribution.",
    )
    expense_account_id = fields.Many2one(
        "account.account",
        string="Employee / Expense Account",
        tracking=True,
        domain="[('account_type', 'in', ['expense', 'expense_direct_cost', 'expense_depreciation', 'asset_current', 'liability_payable'])]",
    )
    payment_reference = fields.Char(string="Payment Reference", tracking=True)
    paid_date = fields.Date(string="Paid Date", tracking=True)
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "pr_employee_service_request_attachment_rel",
        "request_id",
        "attachment_id",
        string="Receipts / Attachments",
    )
    attachment_count = fields.Integer(string="Attachments", compute="_compute_attachment_count")
    cash_payment_id = fields.Many2one(
        "pr.account.cash.payment",
        string="CPV",
        readonly=True,
        copy=False,
        tracking=True,
    )
    bank_payment_id = fields.Many2one(
        "pr.account.bank.payment",
        string="BPV",
        readonly=True,
        copy=False,
        tracking=True,
    )
    payment_request_id = fields.Many2one(
        "pr.employee.payment.request",
        string="Payment Request",
        readonly=True,
        copy=False,
        tracking=True,
    )
    payment_request_state = fields.Selection(
        [
            ("requested", "Requested"),
            ("voucher_created", "Voucher Created"),
            ("cancelled", "Cancelled"),
        ],
        string="Payment Request Status",
        compute="_compute_payment_request_state",
    )
    payment_voucher_state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submit", "Submitted"),
            ("finance_approve", "Accounts Approval"),
            ("posted", "Posted"),
            ("cancel", "Cancelled"),
        ],
        string="Voucher Status",
        compute="_compute_payment_voucher_state",
    )

    destination_country_id = fields.Many2one("res.country", string="Destination Country", tracking=True)
    travel_date = fields.Date(string="Travel Date", tracking=True)
    return_date = fields.Date(string="Return Date", tracking=True)
    duration_days = fields.Integer(string="Duration (Days)", compute="_compute_duration_days", store=True)
    passport_no = fields.Char(string="Passport No.", tracking=True)
    iqama_no = fields.Char(string="Iqama No.", tracking=True)
    visa_number = fields.Char(string="Exit/Re-entry Visa No.", tracking=True)
    issue_date = fields.Date(string="Issue Date", tracking=True)
    visa_expiry_date = fields.Date(string="Visa Expiry Date", tracking=True)
    visa_fee = fields.Monetary(string="Visa Fee", currency_field="currency_id", tracking=True)
    service_from_date = fields.Date(string="From Date", tracking=True)
    service_to_date = fields.Date(string="To Date", tracking=True)
    service_expiry_date = fields.Date(string="Expiry Date", tracking=True)
    work_permit_expiry_date = fields.Date(string="Work Permit Expiry Date", tracking=True)
    place_of_issue = fields.Char(string="Place of Issue", tracking=True)
    insurance_company = fields.Char(string="Insurance Company", tracking=True)
    insurance_category = fields.Char(string="Insurance Category", tracking=True)
    iqama_profession = fields.Char(string="Iqama / Work Permit Profession", tracking=True)
    moi_fee_amount = fields.Monetary(
        string="MOI Fee",
        currency_field="currency_id",
        tracking=True,
        help="Ministry of Interior fee for the Iqama.",
    )
    mol_fee_amount = fields.Monetary(
        string="MOL Fee",
        currency_field="currency_id",
        tracking=True,
        help="Ministry of Labor fee for the work permit.",
    )
    iqama_id = fields.Many2one("hr.employee.iqama", string="Iqama", readonly=True, copy=False, tracking=True)
    iqama_line_id = fields.Many2one("hr.employee.iqama.line", string="Iqama Renewal Line", readonly=True, copy=False, tracking=True)
    insurance_id = fields.Many2one(
        "hr.employee.medical.insurance",
        string="Medical Insurance",
        readonly=True,
        copy=False,
        tracking=True,
    )
    insurance_line_id = fields.Many2one(
        "hr.employee.medical.insurance.line",
        string="Medical Insurance Line",
        readonly=True,
        copy=False,
        tracking=True,
    )
    work_permit_id = fields.Many2one("hr.work.permit", string="Work Permit", readonly=True, copy=False, tracking=True)

    reason = fields.Text(string="Reason / Notes", required=True, tracking=True)
    rejection_reason = fields.Text(string="Rejection Reason", readonly=True, tracking=True)

    hr_supervisor_approved_by_id = fields.Many2one("res.users", string="HR Supervisor Approved By", readonly=True, copy=False)
    hr_supervisor_approved_date = fields.Datetime(string="HR Supervisor Approved On", readonly=True, copy=False)
    employee_manager_approved_by_id = fields.Many2one("res.users", string="Manager Approved By", readonly=True, copy=False)
    employee_manager_approved_date = fields.Datetime(string="Manager Approved On", readonly=True, copy=False)
    hr_manager_approved_by_id = fields.Many2one("res.users", string="HR Manager Approved By", readonly=True, copy=False)
    hr_manager_approved_date = fields.Datetime(string="HR Manager Approved On", readonly=True, copy=False)
    accounts_approved_by_id = fields.Many2one("res.users", string="Accounts Approved By", readonly=True, copy=False)
    accounts_approved_date = fields.Datetime(string="Accounts Approved On", readonly=True, copy=False)
    md_approved_by_id = fields.Many2one("res.users", string="MD Approved By", readonly=True, copy=False)
    md_approved_date = fields.Datetime(string="MD Approved On", readonly=True, copy=False)
    finance_approved_by_id = fields.Many2one("res.users", string="Finance Approved By", readonly=True, copy=False)
    finance_approved_date = fields.Datetime(string="Finance Approved On", readonly=True, copy=False)

    can_hr_supervisor_approve = fields.Boolean(compute="_compute_action_flags")
    can_employee_manager_approve = fields.Boolean(compute="_compute_action_flags")
    can_hr_manager_approve = fields.Boolean(compute="_compute_action_flags")
    can_accounts_approve = fields.Boolean(compute="_compute_action_flags")
    can_md_approve = fields.Boolean(compute="_compute_action_flags")
    can_finance_approve = fields.Boolean(compute="_compute_action_flags")
    can_create_payment_request = fields.Boolean(compute="_compute_action_flags")
    can_issue = fields.Boolean(compute="_compute_action_flags")
    can_reject = fields.Boolean(compute="_compute_action_flags")
    can_reset_to_draft = fields.Boolean(compute="_compute_action_flags")
    can_cancel = fields.Boolean(compute="_compute_action_flags")

    @api.model
    def _default_employee_id(self):
        employee = self.env["hr.employee"].sudo().search([
            ("user_id", "=", self.env.uid),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        return employee.id if employee else False

    @api.depends("employee_id", "employee_id.parent_id", "employee_id.department_id.manager_id")
    def _compute_employee_manager_user_id(self):
        for rec in self:
            manager = rec.employee_id.parent_id
            if not manager and rec.employee_id.department_id:
                manager = rec.employee_id.department_id.manager_id
            if manager == rec.employee_id:
                manager = rec.employee_id.department_id.parent_id.manager_id if rec.employee_id.department_id.parent_id else False
            rec.employee_manager_user_id = manager.user_id if manager and manager.user_id else False

    @api.depends("attachment_ids")
    def _compute_attachment_count(self):
        for rec in self:
            rec.attachment_count = len(rec._get_supporting_attachments())

    def _get_supporting_attachments(self):
        self.ensure_one()
        chatter_attachments = self.env["ir.attachment"].sudo().search([
            ("res_model", "=", self._name),
            ("res_id", "=", self.id),
        ])
        return self.attachment_ids.sudo() | chatter_attachments

    def action_view_attachments(self):
        self.ensure_one()
        return _open_attachment_preview_action(
            self,
            self._get_supporting_attachments(),
            _("Attachments - %s") % self.display_name,
        )

    @api.depends("cash_payment_id.state", "bank_payment_id.state")
    def _compute_payment_voucher_state(self):
        for rec in self:
            voucher = rec.cash_payment_id or rec.bank_payment_id
            rec.payment_voucher_state = voucher.state if voucher else False

    @api.depends("payment_request_id.state")
    def _compute_payment_request_state(self):
        for rec in self:
            rec.payment_request_state = rec.payment_request_id.state if rec.payment_request_id else False

    @api.depends("travel_date", "return_date")
    def _compute_duration_days(self):
        for rec in self:
            if rec.travel_date and rec.return_date and rec.return_date >= rec.travel_date:
                rec.duration_days = (rec.return_date - rec.travel_date).days + 1
            else:
                rec.duration_days = 0

    @api.depends(
        "employee_id",
        "request_type",
        "request_date",
        "travel_date",
        "contract_id",
        "exit_reentry_entry_type",
        "exit_reentry_historical_company_paid",
    )
    def _compute_exit_reentry_eligibility(self):
        for rec in self:
            if rec.request_type != "exit_reentry" or not rec.employee_id:
                rec.exit_reentry_company_eligible = False
                rec.exit_reentry_eligibility_message = False
                continue
            if rec._is_saudi_restricted_request():
                rec.exit_reentry_company_eligible = False
                rec.exit_reentry_eligibility_message = _(
                    "Saudi employees do not require Exit/Re-entry requests."
                )
                continue
            if rec.exit_reentry_entry_type == EXIT_REENTRY_MULTIPLE_ENTRY:
                rec.exit_reentry_company_eligible = False
                rec.exit_reentry_eligibility_message = _(
                    "Multiple-entry Exit/Re-entry visas must be Self-paid."
                )
                continue
            if rec.exit_reentry_historical_company_paid:
                rec.exit_reentry_company_eligible = False
                rec.exit_reentry_eligibility_message = _(
                    "This record is for already availed exit re-entry service provided by company in current contract period."
                )
                continue
            eligible, message, _contract = rec._get_exit_reentry_company_eligibility()
            rec.exit_reentry_company_eligible = eligible
            rec.exit_reentry_eligibility_message = message

    @api.depends_context("uid")
    @api.depends(
        "state",
        "request_type",
        "payment_responsibility",
        "requested_by_id",
        "employee_manager_user_id",
        "payment_request_id",
        "payment_request_id.state",
        "cash_payment_id",
        "cash_payment_id.state",
        "bank_payment_id",
        "bank_payment_id.state",
        "cash_payment_id.accounting_manager_state",
        "bank_payment_id.accounting_manager_state",
    )
    def _compute_action_flags(self):
        user = self.env.user
        is_hr_supervisor = (
            user.has_group("pr_hr_recruitment_request.group_onboarding_supervisor")
            or user.has_group("de_hr_workspace.group_hr_employee_approvals")
        )
        is_hr_manager = (
            user.has_group("hr.group_hr_manager")
            or user.has_group("pr_hr_recruitment_request.group_onboarding_manager")
        )
        is_md = (
            user.has_group("pr_custom_purchase.managing_director")
            or user.has_group("pr_hr_recruitment_request.group_onboarding_md")
        )
        is_accounts = any(user.has_group(xmlid) for xmlid in ACCOUNTING_GROUP_XML_IDS)
        is_finance = (
            user.has_group("pr_account.custom_group_accounting_manager")
            or user.has_group("account.group_account_manager")
        )
        is_admin = user.has_group("base.group_system")
        for rec in self:
            is_owner = rec.requested_by_id == user or rec.employee_id.user_id == user
            is_employee_manager = rec.employee_manager_user_id == user
            rec.can_hr_supervisor_approve = rec.state == "hr_supervisor_approval" and (is_hr_supervisor or is_admin)
            rec.can_employee_manager_approve = rec.state == "employee_manager_approval" and (is_employee_manager or is_admin)
            rec.can_hr_manager_approve = rec.state == "hr_manager_approval" and (is_hr_manager or is_admin)
            rec.can_accounts_approve = rec.state == "accounts_approval" and (is_accounts or is_admin)
            rec.can_md_approve = rec.state == "md_approval" and (is_md or is_admin)
            rec.can_finance_approve = rec.state == "finance_approval" and (is_finance or is_admin)
            rec.can_create_payment_request = (
                rec.state == "payment_approval"
                and not rec.payment_request_id
                and not rec.cash_payment_id
                and not rec.bank_payment_id
                and not rec._is_self_paid_request()
                and not rec._is_historical_company_paid_exit_reentry()
            )
            rec.can_issue = (
                rec.request_type in ("exit_reentry",) + HR_COMPLIANCE_REQUEST_TYPES
                and rec.state == "paid"
                and (is_hr_manager or is_hr_supervisor or is_admin)
            )
            rec.can_reject = (
                rec.state in (
                    "hr_supervisor_approval",
                    "employee_manager_approval",
                    "hr_manager_approval",
                    "accounts_approval",
                    "md_approval",
                    "finance_approval",
                )
                and (
                    (rec.state == "hr_supervisor_approval" and is_hr_supervisor)
                    or (rec.state == "employee_manager_approval" and is_employee_manager)
                    or (rec.state == "hr_manager_approval" and is_hr_manager)
                    or (rec.state == "accounts_approval" and is_accounts)
                    or (rec.state == "md_approval" and is_md)
                    or (rec.state == "finance_approval" and is_finance)
                    or is_admin
                )
            )
            can_manage_own_non_final = is_owner or is_hr_manager or is_admin
            payment_is_final = rec._has_posted_payment_artifacts()
            rec.can_reset_to_draft = (
                rec.state in (
                    "hr_supervisor_approval",
                    "employee_manager_approval",
                    "hr_manager_approval",
                    "accounts_approval",
                    "md_approval",
                    "finance_approval",
                    "payment_approval",
                    "rejected",
                    "cancelled",
                )
                and can_manage_own_non_final
                and not payment_is_final
            )
            rec.can_cancel = (
                rec.state
                in (
                    "draft",
                    "hr_supervisor_approval",
                    "employee_manager_approval",
                    "hr_manager_approval",
                    "accounts_approval",
                    "md_approval",
                    "finance_approval",
                    "payment_approval",
                    "rejected",
                )
                and can_manage_own_non_final
                and not payment_is_final
            )

    @api.onchange("employee_id", "payment_method", "cost_center_id")
    def _onchange_employee_or_payment_method(self):
        for rec in self:
            if rec.employee_id:
                rec.company_id = rec.employee_id.company_id or self.env.company
                rec.passport_no = rec.employee_id.passport_id or rec.passport_no
                rec.iqama_no = rec.employee_id.identification_id or rec.iqama_no
                current_contract = rec._get_current_contract()
                if current_contract:
                    rec.contract_id = current_contract.id
                if not rec.cost_center_id:
                    rec.cost_center_id = rec._get_default_hr_cost_center()
                if rec.cost_center_id and not rec.expense_bucket_id:
                    rec.expense_bucket_id = rec._get_default_hr_budget(rec.cost_center_id)
                employee_account = rec._get_employee_account()
                if employee_account and not rec.expense_account_id:
                    rec.expense_account_id = employee_account
            if not rec.payment_account_id:
                rec.payment_account_id = rec._get_default_payment_account()

    @api.onchange(
        "request_type",
        "payment_responsibility",
        "employee_id",
        "travel_date",
        "request_date",
        "exit_reentry_entry_type",
        "exit_reentry_historical_company_paid",
    )
    def _onchange_payment_responsibility_eligibility(self):
        for rec in self:
            if rec.request_type not in SELF_COMPANY_REQUEST_TYPES:
                rec.payment_responsibility = COMPANY_PAYMENT_RESPONSIBILITY
                rec.exit_reentry_historical_company_paid = False
                continue
            current_contract = rec._get_current_contract()
            if current_contract:
                rec.contract_id = current_contract.id
            if rec.request_type != "exit_reentry":
                rec.exit_reentry_historical_company_paid = False
                continue
            if rec.exit_reentry_entry_type == EXIT_REENTRY_MULTIPLE_ENTRY:
                rec.payment_responsibility = SELF_PAYMENT_RESPONSIBILITY
                rec.exit_reentry_historical_company_paid = False
                rec.approved_amount = 0.0
                return {
                    "warning": {
                        "title": _("Multiple-entry is Self-paid"),
                        "message": _("Multiple-entry Exit/Re-entry visas cannot be charged to the company."),
                    }
                }
            if rec.exit_reentry_historical_company_paid:
                rec.exit_reentry_entry_type = EXIT_REENTRY_SINGLE_ENTRY
                rec.payment_responsibility = COMPANY_PAYMENT_RESPONSIBILITY
                rec.approved_amount = 0.0
                continue
            if rec.payment_responsibility != COMPANY_PAYMENT_RESPONSIBILITY:
                continue
            eligible, message, _contract = rec._get_exit_reentry_company_eligibility()
            if not eligible:
                rec.payment_responsibility = SELF_PAYMENT_RESPONSIBILITY
                return {
                    "warning": {
                        "title": _("Company-paid Exit/Re-entry is not eligible"),
                        "message": message,
                    }
                }

    @api.onchange(
        "requested_amount",
        "visa_fee",
        "moi_fee_amount",
        "mol_fee_amount",
        "request_type",
        "payment_responsibility",
        "exit_reentry_historical_company_paid",
    )
    def _onchange_amounts(self):
        for rec in self:
            if rec._is_self_paid_request() or rec._is_historical_company_paid_exit_reentry():
                rec.approved_amount = 0.0
                if rec.request_type == "iqama_renewal":
                    rec.requested_amount = rec.moi_fee_amount + rec.mol_fee_amount
                continue
            if rec.request_type == "iqama_renewal":
                rec.requested_amount = rec.moi_fee_amount + rec.mol_fee_amount
                rec.approved_amount = rec.requested_amount
            elif not rec.approved_amount:
                rec.approved_amount = rec._get_payment_amount()

    @api.onchange("request_type", "employee_id")
    def _onchange_compliance_request_defaults(self):
        for rec in self:
            if not rec.employee_id:
                continue
            if rec._is_saudi_restricted_request():
                return {
                    "warning": {
                        "title": _("Not required for Saudi employees"),
                        "message": _(
                            "Saudi employees do not require Iqama/Work Permit or Exit/Re-entry requests."
                        ),
                    }
                }
            if rec.request_type not in SELF_COMPANY_REQUEST_TYPES:
                rec.payment_responsibility = COMPANY_PAYMENT_RESPONSIBILITY
            if rec.request_type != "exit_reentry":
                rec.exit_reentry_historical_company_paid = False
                rec.exit_reentry_entry_type = EXIT_REENTRY_SINGLE_ENTRY
            elif not rec.exit_reentry_entry_type:
                rec.exit_reentry_entry_type = EXIT_REENTRY_SINGLE_ENTRY
            rec.passport_no = rec.employee_id.passport_id or rec.passport_no
            rec.iqama_no = rec.employee_id.identification_id or rec.iqama_no
            if rec.request_type in IQAMA_REQUEST_TYPES:
                rec.iqama_id = False
                rec.iqama_line_id = False
                rec.work_permit_id = False
            if rec.request_type in MEDICAL_INSURANCE_REQUEST_TYPES:
                rec.insurance_id = False
                rec.insurance_line_id = False

            if rec.request_type == "iqama_renewal":
                iqama = rec._find_employee_iqama()
                if iqama:
                    rec.iqama_id = iqama.id
                    rec.iqama_no = iqama.identification_id or rec.iqama_no
                    rec.place_of_issue = iqama.place_of_issue or rec.place_of_issue
                    rec.service_from_date = rec._next_service_from_date(iqama.iqama_line_ids)
                    rec.service_expiry_date = iqama.expiry_date or rec.service_expiry_date
                work_permit = rec._find_employee_work_permit()
                if work_permit:
                    rec.work_permit_id = work_permit.id
                    rec.visa_number = work_permit.visa_number or rec.visa_number
                    rec.iqama_profession = work_permit.iqama_profession or rec.iqama_profession
                    rec.work_permit_expiry_date = (
                        work_permit.work_permit_expiry_date
                        or rec.work_permit_expiry_date
                    )
                rec.issue_date = rec.service_from_date or rec.issue_date
                rec.iqama_profession = rec.iqama_profession or rec.employee_id.job_id.name
            elif rec.request_type == "iqama_new":
                rec.iqama_profession = rec.iqama_profession or rec.employee_id.job_id.name
            elif rec.request_type == "medical_insurance_renewal":
                insurance = rec._find_employee_insurance()
                if insurance:
                    rec.insurance_id = insurance.id
                    rec.iqama_no = insurance.identification_id or rec.iqama_no
                    rec.insurance_company = insurance.insurance_company or rec.insurance_company
                    rec.insurance_category = insurance.insurance_category or rec.insurance_category
                    rec.service_from_date = rec._next_service_from_date(insurance.insurance_line_ids)
                    rec.service_expiry_date = insurance.expiry_date or rec.service_expiry_date

    @api.onchange("service_to_date")
    def _onchange_service_to_date(self):
        for rec in self:
            if rec.service_to_date:
                rec.service_expiry_date = rec.service_to_date

    @api.constrains(
        "request_type",
        "employee_id",
        "requested_amount",
        "payment_responsibility",
        "exit_reentry_entry_type",
        "exit_reentry_historical_company_paid",
        "moi_fee_amount",
        "mol_fee_amount",
        "travel_date",
        "return_date",
        "service_from_date",
        "service_to_date",
    )
    def _check_request_values(self):
        for rec in self:
            if rec._is_saudi_restricted_request():
                raise ValidationError(_(
                    "Saudi employees do not require Iqama/Work Permit or Exit/Re-entry requests."
                ))
            if rec.request_type == "reimbursement" and rec.requested_amount <= 0.0:
                raise ValidationError(_("Requested Amount must be greater than zero for reimbursement requests."))
            if rec.request_type == "iqama_renewal" and (
                rec.moi_fee_amount < 0.0 or rec.mol_fee_amount < 0.0
            ):
                raise ValidationError(_("MOI and MOL fees cannot be negative."))
            if (
                rec._get_requested_compliance_amount() <= 0.0
                and rec.request_type in COMPLIANCE_RENEWAL_REQUEST_TYPES
                and not rec._is_self_paid_request()
            ):
                raise ValidationError(_("Requested Amount must be greater than zero for renewal requests."))
            if rec.request_type == "exit_reentry":
                if rec.exit_reentry_entry_type == EXIT_REENTRY_MULTIPLE_ENTRY:
                    if rec.payment_responsibility != SELF_PAYMENT_RESPONSIBILITY:
                        raise ValidationError(_("Multiple-entry Exit/Re-entry visas must be Self-paid."))
                    if rec.exit_reentry_historical_company_paid:
                        raise ValidationError(_("Historical company-paid Exit/Re-entry records must be single-entry."))
                if rec.exit_reentry_historical_company_paid:
                    if rec.payment_responsibility != COMPANY_PAYMENT_RESPONSIBILITY:
                        raise ValidationError(_("Historical Exit/Re-entry records are only for company-paid visas."))
                    if rec.exit_reentry_entry_type != EXIT_REENTRY_SINGLE_ENTRY:
                        raise ValidationError(_("Historical company-paid Exit/Re-entry records must be single-entry."))
            if rec.request_type == "exit_reentry" and rec.travel_date and rec.return_date:
                if rec.return_date < rec.travel_date:
                    raise ValidationError(_("Return Date cannot be before Travel Date."))
            if rec.request_type in SERVICE_PERIOD_REQUEST_TYPES and rec.service_from_date and rec.service_to_date:
                if rec.service_to_date < rec.service_from_date:
                    raise ValidationError(_("To Date cannot be before From Date."))

    @api.model
    def _normalize_exit_reentry_create_vals(self, vals):
        vals = dict(vals)
        request_type = vals.get("request_type")
        if request_type == "exit_reentry":
            entry_type = vals.get("exit_reentry_entry_type") or EXIT_REENTRY_SINGLE_ENTRY
            if entry_type == EXIT_REENTRY_MULTIPLE_ENTRY:
                vals["payment_responsibility"] = SELF_PAYMENT_RESPONSIBILITY
                vals["exit_reentry_historical_company_paid"] = False
                vals["approved_amount"] = 0.0
            elif vals.get("exit_reentry_historical_company_paid"):
                vals["exit_reentry_entry_type"] = EXIT_REENTRY_SINGLE_ENTRY
                vals["payment_responsibility"] = COMPANY_PAYMENT_RESPONSIBILITY
                vals["approved_amount"] = 0.0
        elif request_type:
            vals["exit_reentry_historical_company_paid"] = False
        return vals

    def _normalize_exit_reentry_write_vals(self, vals):
        self.ensure_one()
        vals = dict(vals)
        request_type = vals.get("request_type", self.request_type)
        if request_type != "exit_reentry":
            if "request_type" in vals:
                vals["exit_reentry_historical_company_paid"] = False
            return vals

        entry_type = vals.get(
            "exit_reentry_entry_type",
            self.exit_reentry_entry_type or EXIT_REENTRY_SINGLE_ENTRY,
        )
        historical = vals.get(
            "exit_reentry_historical_company_paid",
            self.exit_reentry_historical_company_paid,
        )
        if entry_type == EXIT_REENTRY_MULTIPLE_ENTRY:
            vals["payment_responsibility"] = SELF_PAYMENT_RESPONSIBILITY
            vals["exit_reentry_historical_company_paid"] = False
            vals["approved_amount"] = 0.0
        elif historical:
            vals["exit_reentry_entry_type"] = EXIT_REENTRY_SINGLE_ENTRY
            vals["payment_responsibility"] = COMPANY_PAYMENT_RESPONSIBILITY
            vals["approved_amount"] = 0.0
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._normalize_exit_reentry_create_vals(vals) for vals in vals_list]
        for vals in vals_list:
            if vals.get("request_type") == "iqama_renewal":
                vals["requested_amount"] = (
                    vals.get("moi_fee_amount", 0.0)
                    + vals.get("mol_fee_amount", 0.0)
                )
        records = super().create(vals_list)
        for rec in records:
            if rec.name in (False, "New", _("New")):
                rec.name = self.env["ir.sequence"].next_by_code("pr.employee.service.request") or _("New")
            if not rec.passport_no:
                rec.passport_no = rec.employee_id.passport_id or False
            if not rec.iqama_no:
                rec.iqama_no = rec.employee_id.identification_id or False
            updates = {}
            current_contract = rec._get_current_contract()
            if current_contract and not rec.contract_id:
                updates["contract_id"] = current_contract.id
            if not rec.cost_center_id:
                cost_center = rec._get_default_hr_cost_center()
                if cost_center:
                    updates["cost_center_id"] = cost_center.id
            if not rec.expense_bucket_id:
                cost_center = rec.cost_center_id or self.env["account.analytic.account"].browse(updates.get("cost_center_id"))
                budget = rec._get_default_hr_budget(cost_center)
                if budget:
                    updates["expense_bucket_id"] = budget.id
            if not rec.expense_account_id:
                employee_account = rec._get_employee_account()
                if employee_account:
                    updates["expense_account_id"] = employee_account.id
            if not rec.payment_account_id:
                payment_account = rec._get_default_payment_account()
                if payment_account:
                    updates["payment_account_id"] = payment_account.id
            if updates:
                rec.write(updates)
        records._apply_exit_reentry_company_eligibility(auto_message=False)
        return records

    def write(self, vals):
        if self.env.context.get("skip_employee_service_request_lock"):
            return super().write(vals)
        if {
            "request_type",
            "payment_responsibility",
            "exit_reentry_entry_type",
            "exit_reentry_historical_company_paid",
        }.intersection(vals):
            if len(self) > 1:
                for rec in self:
                    rec.write(rec._normalize_exit_reentry_write_vals(vals))
                return True
            vals = self._normalize_exit_reentry_write_vals(vals)
        protected = {
            "request_type",
            "employee_id",
            "reimbursement_type",
            "expense_date",
            "requested_amount",
            "payment_method",
            "payment_responsibility",
            "exit_reentry_entry_type",
            "exit_reentry_historical_company_paid",
            "attachment_ids",
            "destination_country_id",
            "travel_date",
            "return_date",
            "passport_no",
            "iqama_no",
            "service_from_date",
            "service_to_date",
            "service_expiry_date",
            "work_permit_expiry_date",
            "place_of_issue",
            "insurance_company",
            "insurance_category",
            "iqama_profession",
            "moi_fee_amount",
            "mol_fee_amount",
            "reason",
        }
        if protected.intersection(vals):
            for rec in self:
                if rec.state != "draft":
                    raise UserError(_("Submitted requests cannot be edited. Reject and reset to draft first."))
        budget_fields = {"expense_bucket_id", "cost_center_id"}
        if budget_fields.intersection(vals):
            can_edit_budget = (
                self.env.user.has_group("pr_hr_recruitment_request.group_onboarding_supervisor")
                or self.env.user.has_group("hr.group_hr_manager")
                or self.env.user.has_group("pr_hr_recruitment_request.group_onboarding_manager")
                or self.env.user.has_group("pr_custom_purchase.managing_director")
                or self.env.user.has_group("pr_hr_recruitment_request.group_onboarding_md")
                or any(self.env.user.has_group(xmlid) for xmlid in ACCOUNTING_GROUP_XML_IDS)
                or self.env.user.has_group("base.group_system")
            )
            for rec in self:
                if rec.state == "draft":
                    continue
                if rec.state in ("payment_approval", "paid", "issued", "rejected", "cancelled") or rec.payment_request_id:
                    raise UserError(_("Budget and Cost Center cannot be changed after the payment request is created."))
                if not can_edit_budget:
                    raise UserError(_("Only HR/MD approvers can edit Budget and Cost Center after submission."))
        approval_fields = {"approved_amount", "payment_account_id", "expense_account_id", "visa_fee"}
        if approval_fields.intersection(vals):
            can_edit_approval = (
                self.env.user.has_group("pr_hr_recruitment_request.group_onboarding_supervisor")
                or self.env.user.has_group("hr.group_hr_manager")
                or self.env.user.has_group("pr_hr_recruitment_request.group_onboarding_manager")
                or self.env.user.has_group("pr_custom_purchase.managing_director")
                or self.env.user.has_group("pr_hr_recruitment_request.group_onboarding_md")
                or any(self.env.user.has_group(xmlid) for xmlid in ACCOUNTING_GROUP_XML_IDS)
                or self.env.user.has_group("base.group_system")
            )
            for rec in self:
                if rec.state != "draft" and not can_edit_approval:
                    raise UserError(_("Only HR/MD approvers can edit approval and voucher accounting fields."))
        res = super().write(vals)
        if {
            "request_type",
            "employee_id",
            "payment_responsibility",
            "exit_reentry_entry_type",
            "exit_reentry_historical_company_paid",
            "travel_date",
            "request_date",
        }.intersection(vals):
            self._apply_exit_reentry_company_eligibility(auto_message=True)
        return res

    def unlink(self):
        for rec in self:
            if rec.state not in ("draft", "cancelled", "rejected"):
                raise UserError(_("Only draft, cancelled, or rejected requests can be deleted."))
            if rec.cash_payment_id or rec.bank_payment_id:
                raise UserError(_("This request already created a payment voucher and cannot be deleted."))
        return super().unlink()

    def _check_before_submit(self):
        for rec in self:
            if not rec.employee_id:
                raise UserError(_("Please select an employee."))
            if rec._is_saudi_restricted_request():
                raise UserError(_(
                    "Saudi employees do not require Iqama/Work Permit or Exit/Re-entry requests."
                ))
            if rec._is_department_manager_flow() and not rec.employee_manager_user_id:
                raise UserError(_("Please set a manager user on the employee before submitting."))
            if rec.request_type == "reimbursement":
                if rec.requested_amount <= 0.0:
                    raise UserError(_("Please enter a reimbursement amount greater than zero."))
                if not rec.reimbursement_type:
                    raise UserError(_("Please select the reimbursement category."))
                if not rec.expense_date:
                    raise UserError(_("Please enter the expense date."))
            if rec.request_type == "exit_reentry":
                if not rec.destination_country_id:
                    raise UserError(_("Please select the destination country."))
                if not rec.travel_date or not rec.return_date:
                    raise UserError(_("Please enter travel and return dates."))
                if rec.return_date < rec.travel_date:
                    raise UserError(_("Return Date cannot be before Travel Date."))
            if rec.request_type in COMPLIANCE_RENEWAL_REQUEST_TYPES:
                if not rec._is_self_paid_request():
                    if rec._get_requested_compliance_amount() <= 0.0:
                        raise UserError(_("Please enter the expected fee amount greater than zero."))
                    if not rec.expense_bucket_id:
                        raise UserError(_("Please select the approved Budget for this renewal."))
                    if not rec.cost_center_id:
                        raise UserError(_("Please select the Cost Center for this renewal."))
                    if not rec.expense_account_id:
                        raise UserError(_("Please select the Employee / Expense Account for this renewal."))
                    if not rec.attachment_ids:
                        raise UserError(_("Please attach the renewal supporting document(s)."))
            if rec.request_type in HR_COMPLIANCE_REQUEST_TYPES:
                if not rec.iqama_no:
                    raise UserError(_("Please enter the Iqama No."))
            if rec.request_type in SERVICE_PERIOD_REQUEST_TYPES:
                if not rec.service_from_date or not rec.service_to_date:
                    raise UserError(_("Please enter From Date and To Date."))
                if rec.service_to_date < rec.service_from_date:
                    raise UserError(_("To Date cannot be before From Date."))
                if not rec.service_expiry_date:
                    raise UserError(_("Please enter the expiry date."))
            if rec.request_type in IQAMA_REQUEST_TYPES:
                if not rec.iqama_profession:
                    raise UserError(_("Please enter the Iqama / Work Permit Profession."))
                if not rec.issue_date:
                    raise UserError(_("Please enter the Iqama / Work Permit issuance date."))
                if not rec.work_permit_expiry_date:
                    raise UserError(_("Please enter the Work Permit expiry date."))
            if rec.request_type in MEDICAL_INSURANCE_REQUEST_TYPES:
                if not rec.insurance_company or not rec.insurance_category:
                    raise UserError(_("Please enter insurance company and category."))
            rec._check_new_or_renewal_target()

    def _is_ticket_reimbursement(self):
        self.ensure_one()
        return self.request_type == "reimbursement" and self.reimbursement_type == TICKET_REIMBURSEMENT_TYPE

    def _is_department_manager_flow(self):
        self.ensure_one()
        return self.request_type == "reimbursement" and not self._is_ticket_reimbursement()

    def _is_new_compliance_request(self):
        self.ensure_one()
        return self.request_type in NEW_COMPLIANCE_REQUEST_TYPES

    def _is_compliance_renewal(self):
        self.ensure_one()
        return self.request_type in COMPLIANCE_RENEWAL_REQUEST_TYPES

    def _is_hr_flow(self):
        self.ensure_one()
        return (
            self._is_ticket_reimbursement()
            or self.request_type == "exit_reentry"
            or self.request_type in HR_COMPLIANCE_REQUEST_TYPES
        )

    @staticmethod
    def _is_saudi_country(country):
        return bool(
            country
            and (
                (country.code or "").upper() == "SA"
                or ("is_homeland" in country._fields and country.is_homeland)
                or (country.name or "").strip().casefold()
                in ("saudi", "saudi arabia", "kingdom of saudi arabia")
            )
        )

    def _is_saudi_employee(self):
        self.ensure_one()
        return self._is_saudi_country(self.employee_id.country_id)

    def _is_saudi_restricted_request(self):
        self.ensure_one()
        return self.request_type in SAUDI_RESTRICTED_REQUEST_TYPES and self._is_saudi_employee()

    def _is_self_paid_request(self):
        self.ensure_one()
        return (
            self.request_type in SELF_COMPANY_REQUEST_TYPES
            and self.payment_responsibility == SELF_PAYMENT_RESPONSIBILITY
        )

    def _is_historical_company_paid_exit_reentry(self):
        self.ensure_one()
        return (
            self.request_type == "exit_reentry"
            and self.exit_reentry_historical_company_paid
            and self.payment_responsibility == COMPANY_PAYMENT_RESPONSIBILITY
        )

    def _is_company_paid_exit_reentry_consumption(self):
        self.ensure_one()
        return (
            self.request_type == "exit_reentry"
            and self.exit_reentry_entry_type in (False, EXIT_REENTRY_SINGLE_ENTRY)
            and self.payment_responsibility == COMPANY_PAYMENT_RESPONSIBILITY
            and self.state not in ("cancelled", "rejected")
        )

    def _get_current_contract(self):
        self.ensure_one()
        employee = self.employee_id
        if not employee:
            return self.env["hr.contract"]
        contract = employee.contract_id if "contract_id" in employee._fields else self.env["hr.contract"]
        if contract and contract.state == "open":
            return contract.sudo()
        return self.env["hr.contract"].sudo().search([
            ("employee_id", "=", employee.id),
            ("state", "=", "open"),
        ], order="date_start desc, id desc", limit=1)

    def _get_exit_reentry_eligibility_date(self):
        self.ensure_one()
        return self.travel_date or self.request_date or fields.Date.context_today(self)

    def _get_exit_reentry_company_schedule(self, contract):
        benefit_type = contract.exit_reentry_benefit_type or "non_executive"
        if benefit_type == "executive":
            return 11, 12
        return 23, 24

    def _get_exit_reentry_company_window(self, contract, target_date):
        self.ensure_one()
        if not contract or not contract.date_start:
            return False, False
        first_offset_months, interval_months = self._get_exit_reentry_company_schedule(contract)
        window_start = contract.date_start + relativedelta(months=first_offset_months)
        if target_date < window_start:
            return window_start, False
        while window_start + relativedelta(months=interval_months) <= target_date:
            window_start += relativedelta(months=interval_months)
        window_end = window_start + relativedelta(months=interval_months) - relativedelta(days=1)
        return window_start, window_end

    def _consumes_exit_reentry_company_window(self, contract, window_start, window_end):
        self.ensure_one()
        if not self._is_company_paid_exit_reentry_consumption():
            return False
        consumed_date = self._get_exit_reentry_eligibility_date()
        if not consumed_date or consumed_date < contract.date_start or consumed_date > window_end:
            return False
        if window_start <= consumed_date <= window_end:
            return True
        first_offset_months, _interval_months = self._get_exit_reentry_company_schedule(contract)
        first_window_start = contract.date_start + relativedelta(months=first_offset_months)
        return window_start == first_window_start and consumed_date < window_start

    def _get_exit_reentry_company_eligibility(self):
        self.ensure_one()
        if self.request_type != "exit_reentry":
            return False, False, self.env["hr.contract"]
        if self.exit_reentry_entry_type == EXIT_REENTRY_MULTIPLE_ENTRY:
            return (
                False,
                _("Multiple-entry Exit/Re-entry visas must be Self-paid."),
                self.env["hr.contract"],
            )
        if self._is_saudi_employee():
            return (
                False,
                _("Saudi employees do not require Exit/Re-entry requests."),
                self.env["hr.contract"],
            )
        contract = self.contract_id or self._get_current_contract()
        if not contract:
            return (
                False,
                _("No running contract was found. The request will be handled as Self-paid."),
                contract,
            )
        if not contract.date_start:
            return (
                False,
                _("The current contract has no start date. The request will be handled as Self-paid."),
                contract,
            )
        target_date = self._get_exit_reentry_eligibility_date()
        window_start, window_end = self._get_exit_reentry_company_window(contract, target_date)
        benefit_label = dict(contract._fields["exit_reentry_benefit_type"].selection).get(
            contract.exit_reentry_benefit_type or "non_executive",
            _("Non Executive"),
        )
        if not window_end:
            return (
                False,
                _("This Employee will be Eligible for company-paid Exit/Re-entry from %(date)s.")
                % {"category": benefit_label, "date": window_start},
                contract,
            )

        candidate_requests = self.sudo().search([
            ("id", "!=", self.id or 0),
            ("employee_id", "=", self.employee_id.id),
            ("request_type", "=", "exit_reentry"),
            ("payment_responsibility", "=", COMPANY_PAYMENT_RESPONSIBILITY),
            ("state", "not in", ["cancelled", "rejected"]),
        ])
        used_request = candidate_requests.filtered(
            lambda request: request._consumes_exit_reentry_company_window(
                contract,
                window_start,
                window_end,
            )
        )[:1]
        if used_request:
            return (
                False,
                _("Company-paid Exit/Re-entry was already used in this entitlement period by %s.")
                % used_request.display_name,
                contract,
            )
        return (
            True,
            _("%(category)s company-paid entitlement is available for %(start)s to %(end)s.")
            % {"category": benefit_label, "start": window_start, "end": window_end},
            contract,
        )

    def _apply_exit_reentry_company_eligibility(self, auto_message=True):
        for rec in self.filtered(lambda request: request.request_type == "exit_reentry"):
            contract = rec._get_current_contract()
            if contract and rec.contract_id != contract:
                rec.with_context(skip_employee_service_request_lock=True).write({"contract_id": contract.id})
            if rec.exit_reentry_entry_type == EXIT_REENTRY_MULTIPLE_ENTRY:
                needs_update = (
                    rec.payment_responsibility != SELF_PAYMENT_RESPONSIBILITY
                    or rec.exit_reentry_historical_company_paid
                    or rec.approved_amount
                )
                if needs_update:
                    rec.with_context(skip_employee_service_request_lock=True).write({
                        "payment_responsibility": SELF_PAYMENT_RESPONSIBILITY,
                        "exit_reentry_historical_company_paid": False,
                        "approved_amount": 0.0,
                    })
                if auto_message and needs_update:
                    rec.message_post(body=_("Multiple-entry Exit/Re-entry switched to Self-paid."))
                continue
            if rec._is_historical_company_paid_exit_reentry():
                if rec.approved_amount:
                    rec.with_context(skip_employee_service_request_lock=True).write({"approved_amount": 0.0})
                continue
            if rec.payment_responsibility != COMPANY_PAYMENT_RESPONSIBILITY:
                continue
            eligible, message, _contract = rec._get_exit_reentry_company_eligibility()
            if eligible:
                continue
            rec.with_context(skip_employee_service_request_lock=True).write({
                "payment_responsibility": SELF_PAYMENT_RESPONSIBILITY,
                "approved_amount": 0.0,
            })
            if auto_message:
                rec.message_post(body=_("Payment responsibility switched to Self: %s") % message)

    def _check_new_or_renewal_target(self):
        self.ensure_one()
        if self.request_type == "iqama_new" and self._find_employee_iqama():
            raise UserError(_("An existing Iqama is already recorded for this employee. Please use Iqama Renewal."))
        if self.request_type == "iqama_renewal" and not (self.iqama_id or self._find_employee_iqama()):
            raise UserError(_("No existing Iqama was found for this employee. Please use New Iqama."))
        if self.request_type == "medical_insurance_new" and self._find_employee_insurance():
            raise UserError(
                _("An existing Medical Insurance record is already recorded for this employee. Please use Medical Insurance Renewal.")
            )
        if self.request_type == "medical_insurance_renewal" and not (self.insurance_id or self._find_employee_insurance()):
            raise UserError(_("No existing Medical Insurance record was found for this employee. Please use New Medical Insurance."))

    def _check_before_md_approval(self):
        for rec in self:
            if rec._is_self_paid_request() or rec._is_historical_company_paid_exit_reentry():
                continue
            amount = rec._get_payment_amount()
            if amount <= 0.0:
                if rec.request_type == "exit_reentry":
                    raise UserError(_("Please enter the visa fee or approved payable amount before MD approval."))
                raise UserError(_("Please enter an approved amount greater than zero before MD approval."))
            if not rec.expense_bucket_id:
                raise UserError(_("Please select the approved Budget before MD approval."))
            if not rec.cost_center_id:
                raise UserError(_("Please select the Cost Center before MD approval."))
            rec._check_selected_budget_or_raise(amount)

    def _check_before_accounts_approval(self):
        for rec in self:
            if rec._is_self_paid_request() or rec._is_historical_company_paid_exit_reentry():
                continue
            amount = rec._get_payment_amount()
            if amount <= 0.0:
                if rec.request_type == "exit_reentry":
                    raise UserError(_("Please enter the visa fee or approved payable amount before Accounts approval."))
                raise UserError(_("Please enter an approved amount greater than zero before Accounts approval."))
            if not rec.expense_bucket_id:
                raise UserError(_("Please select the approved Budget before Accounts approval."))
            if not rec.cost_center_id:
                raise UserError(_("Please select the Cost Center before Accounts approval."))
            if not rec.expense_account_id:
                raise UserError(_("Please select the Employee / Expense Account before Accounts approval."))
            rec._check_selected_budget_or_raise(amount)

    def _notify_group(self, group_xml_ids, summary, note):
        users = self.env["res.users"]
        for xmlid in group_xml_ids:
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                users |= group.users
        self._notify_users(users, summary, note)

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

    def action_submit(self):
        self._apply_exit_reentry_company_eligibility(auto_message=True)
        self._check_before_submit()
        for rec in self:
            if rec.state != "draft":
                continue
            vals = {"rejection_reason": False, "approved_amount": False}
            if rec._is_self_paid_request():
                vals["approved_amount"] = 0.0
            if rec.request_type == "iqama_renewal":
                vals["requested_amount"] = rec._get_requested_compliance_amount()
            if rec._is_historical_company_paid_exit_reentry():
                vals.update({
                    "state": "issued",
                    "approved_amount": 0.0,
                    "issue_date": rec.issue_date or fields.Date.context_today(rec),
                })
                rec.write(vals)
                rec.message_post(
                    body=_(
                        "Historical company-paid Exit/Re-entry recorded as already approved/paid. "
                        "No payment request or voucher was created."
                    )
                )
                continue
            if rec._is_new_compliance_request():
                rec.write(vals)
                if rec.request_type == "iqama_new":
                    rec._issue_iqama_request()
                else:
                    rec._issue_medical_insurance()
                continue
            if rec._is_compliance_renewal():
                vals["state"] = "hr_manager_approval"
                rec.write(vals)
                rec._notify_group(
                    ["hr.group_hr_manager", "pr_hr_recruitment_request.group_onboarding_manager"],
                    _("Employee Renewal Approval Needed"),
                    _("%s <b>%s</b> is waiting for HR Manager approval.")
                    % (rec._get_type_label(), rec.display_name),
                )
                rec.message_post(body=_("Renewal submitted for HR Manager approval."))
            elif rec._is_department_manager_flow():
                vals["state"] = "employee_manager_approval"
                rec.write(vals)
                rec._notify_users(
                    rec.employee_manager_user_id,
                    _("Employee Request Approval Needed"),
                    _("%s <b>%s</b> is waiting for Department Manager approval.")
                    % (rec._get_type_label(), rec.display_name),
                )
                rec.message_post(body=_("Request submitted for Department Manager approval."))
            elif rec._is_ticket_reimbursement() or rec.request_type == "exit_reentry":
                vals["state"] = "hr_manager_approval"
                rec.write(vals)
                rec._notify_group(
                    ["hr.group_hr_manager", "pr_hr_recruitment_request.group_onboarding_manager"],
                    _("Employee Request Approval Needed"),
                    _("%s <b>%s</b> is waiting for HR Manager approval.") % (rec._get_type_label(), rec.display_name),
                )
                rec.message_post(body=_("Request submitted for HR Manager approval."))
            else:
                vals["state"] = "hr_supervisor_approval"
                rec.write(vals)
                rec._notify_group(
                    ["pr_hr_recruitment_request.group_onboarding_supervisor", "de_hr_workspace.group_hr_employee_approvals"],
                    _("Employee Request Approval Needed"),
                    _("%s <b>%s</b> is waiting for HR Supervisor approval.") % (rec._get_type_label(), rec.display_name),
                )
                rec.message_post(body=_("Request submitted for HR Supervisor approval."))

    def action_hr_supervisor_approve(self):
        for rec in self:
            if not rec.can_hr_supervisor_approve:
                raise UserError(_("Only HR Supervisor can approve this stage."))
            next_state = "hr_manager_approval" if rec._is_hr_flow() else "employee_manager_approval"
            rec.write({
                "state": next_state,
                "hr_supervisor_approved_by_id": self.env.user.id,
                "hr_supervisor_approved_date": fields.Datetime.now(),
            })
            if next_state == "hr_manager_approval":
                rec._notify_group(
                    ["hr.group_hr_manager", "pr_hr_recruitment_request.group_onboarding_manager"],
                    _("Employee Request Approval Needed"),
                    _("%s <b>%s</b> is waiting for HR Manager approval.") % (rec._get_type_label(), rec.display_name),
                )
            else:
                rec._notify_users(
                    rec.employee_manager_user_id,
                    _("Employee Request Approval Needed"),
                    _("%s <b>%s</b> is waiting for Employee Manager approval.") % (rec._get_type_label(), rec.display_name),
                )
            rec.message_post(body=_("HR Supervisor approved this request."))

    def action_employee_manager_approve(self):
        for rec in self:
            if not rec.can_employee_manager_approve:
                raise UserError(_("Only the employee's manager can approve this stage."))
            if rec._is_department_manager_flow():
                payment_request = rec._create_payment_request()
                rec.write({
                    "state": "payment_approval",
                    "employee_manager_approved_by_id": self.env.user.id,
                    "employee_manager_approved_date": fields.Datetime.now(),
                })
                rec.message_post(
                    body=_("Department Manager approved this request and created payment request %s for Accounts.")
                    % payment_request.display_name
                )
                continue
            rec.write({
                "state": "hr_manager_approval",
                "employee_manager_approved_by_id": self.env.user.id,
                "employee_manager_approved_date": fields.Datetime.now(),
            })
            rec._notify_group(
                ["hr.group_hr_manager", "pr_hr_recruitment_request.group_onboarding_manager"],
                _("Employee Request Approval Needed"),
                _("%s <b>%s</b> is waiting for HR Manager approval.") % (rec._get_type_label(), rec.display_name),
            )
            rec.message_post(body=_("Employee Manager approved this request."))

    def action_hr_manager_approve(self):
        for rec in self:
            if not rec.can_hr_manager_approve:
                raise UserError(_("Only HR Manager can approve this stage."))
            approval_vals = {
                "approved_amount": 0.0 if rec._is_self_paid_request() else rec._get_payment_amount(),
                "hr_manager_approved_by_id": self.env.user.id,
                "hr_manager_approved_date": fields.Datetime.now(),
            }
            if rec._is_self_paid_request():
                if rec.request_type == "exit_reentry":
                    approval_vals["state"] = "paid"
                    rec.write(approval_vals)
                    rec.message_post(body=_("Self-paid Exit/Re-entry approved. No accounting entry will be created; HR can issue the visa."))
                    continue
                rec.write(approval_vals)
                if rec.request_type in IQAMA_REQUEST_TYPES:
                    rec._issue_iqama_request()
                elif rec.request_type in MEDICAL_INSURANCE_REQUEST_TYPES:
                    rec._issue_medical_insurance()
                rec.message_post(body=_("Self-paid renewal approved and issued without accounting entries."))
                continue
            rec.write({
                "state": "md_approval",
                "approved_amount": rec._get_payment_amount(),
                "hr_manager_approved_by_id": self.env.user.id,
                "hr_manager_approved_date": fields.Datetime.now(),
            })
            rec._notify_group(
                ["pr_custom_purchase.managing_director", "pr_hr_recruitment_request.group_onboarding_md"],
                _("Employee Request Approval Needed"),
                _("%s <b>%s</b> is waiting for MD approval.") % (rec._get_type_label(), rec.display_name),
            )
            rec.message_post(body=_("HR Manager approved this request."))

    def action_accounts_approve(self):
        for rec in self:
            if not rec.can_accounts_approve:
                raise UserError(_("Only Accounts can approve this stage."))
            if rec._is_department_manager_flow():
                payment_request = rec._create_payment_request()
                rec.write({
                    "state": "payment_approval",
                    "approved_amount": rec._get_payment_amount(),
                    "accounts_approved_by_id": self.env.user.id,
                    "accounts_approved_date": fields.Datetime.now(),
                })
                rec.message_post(
                    body=_("Accounts approved this request and created payment request %s.")
                    % payment_request.display_name
                )
                continue
            rec._check_before_md_approval()
            rec.write({
                "state": "md_approval",
                "approved_amount": rec._get_payment_amount(),
                "accounts_approved_by_id": self.env.user.id,
                "accounts_approved_date": fields.Datetime.now(),
            })
            rec._notify_group(
                ["pr_custom_purchase.managing_director", "pr_hr_recruitment_request.group_onboarding_md"],
                _("Employee Request Approval Needed"),
                _("%s <b>%s</b> is waiting for MD approval.") % (rec._get_type_label(), rec.display_name),
            )
            rec.message_post(body=_("Accounts approved this request."))

    def action_md_approve(self):
        for rec in self:
            if not rec.can_md_approve:
                raise UserError(_("Only MD can approve this stage."))
            rec._check_before_md_approval()
            if rec._is_self_paid_request():
                rec.write({
                    "approved_amount": 0.0,
                    "md_approved_by_id": self.env.user.id,
                    "md_approved_date": fields.Datetime.now(),
                })
                if rec.request_type == "exit_reentry":
                    rec.write({"state": "paid"})
                    rec.message_post(body=_("Self-paid Exit/Re-entry approved. No accounting entry will be created; HR can issue the visa."))
                elif rec.request_type in IQAMA_REQUEST_TYPES:
                    rec._issue_iqama_request()
                elif rec.request_type in MEDICAL_INSURANCE_REQUEST_TYPES:
                    rec._issue_medical_insurance()
                continue
            if rec._is_compliance_renewal():
                rec.write({
                    "state": "payment_approval",
                    "approved_amount": rec._get_payment_amount(),
                    "md_approved_by_id": self.env.user.id,
                    "md_approved_date": fields.Datetime.now(),
                })
                rec._notify_group(
                    list(ACCOUNTING_GROUP_XML_IDS),
                    _("Employee Payment Request Needed"),
                    _("%s <b>%s</b> is MD approved. Please create the payment request and choose CPV/BPV.")
                    % (rec._get_type_label(), rec.display_name),
                )
                rec.message_post(
                    body=_("MD approved this renewal. Accounts can now create the payment request and choose the transfer type.")
                )
                continue
            payment_request = rec._create_payment_request()
            rec.write({
                "state": "payment_approval",
                "approved_amount": rec._get_payment_amount(),
                "md_approved_by_id": self.env.user.id,
                "md_approved_date": fields.Datetime.now(),
            })
            rec.message_post(
                body=_("MD approved this request and created payment request %s for Accounts.")
                % payment_request.display_name
            )

    def action_finance_approve(self):
        for rec in self:
            if not rec.can_finance_approve:
                raise UserError(_("Only Finance can approve this stage."))
            rec._check_before_accounts_approval()
            if rec._is_self_paid_request():
                rec.write({
                    "state": "paid" if rec.request_type == "exit_reentry" else rec.state,
                    "approved_amount": 0.0,
                    "finance_approved_by_id": self.env.user.id,
                    "finance_approved_date": fields.Datetime.now(),
                })
                if rec.request_type in IQAMA_REQUEST_TYPES:
                    rec._issue_iqama_request()
                elif rec.request_type in MEDICAL_INSURANCE_REQUEST_TYPES:
                    rec._issue_medical_insurance()
                rec.message_post(body=_("Self-paid request approved without accounting entries."))
                continue
            payment_request = rec._create_payment_request()
            rec.write({
                "state": "payment_approval",
                "approved_amount": rec._get_payment_amount(),
                "finance_approved_by_id": self.env.user.id,
                "finance_approved_date": fields.Datetime.now(),
            })
            rec.message_post(
                body=_("Finance approved this request and created payment request %s for Accounts.")
                % payment_request.display_name
            )

    def action_create_payment_request(self):
        for rec in self:
            if not rec.can_create_payment_request:
                raise UserError(_("A payment request can only be created after final approval and before any payment request or voucher exists."))
            payment_request = rec._create_payment_request(notify_accounts=False)
            rec.message_post(
                body=_("Payment request %s created for Accounts to select transfer type and create CPV/BPV.")
                % payment_request.display_name
            )
        return self[:1].action_open_payment_request() if len(self) == 1 else True

    def action_issue(self):
        for rec in self:
            if not rec.can_issue:
                raise UserError(_("Only HR can issue paid employee service requests."))
            if rec.request_type == "exit_reentry":
                if not rec.visa_number:
                    raise UserError(_("Please enter the Exit/Re-entry Visa No. before issuing."))
                rec.write({"state": "issued", "issue_date": rec.issue_date or fields.Date.context_today(rec)})
                rec.message_post(body=_("Exit/Re-entry request has been issued."))
            elif rec.request_type in IQAMA_REQUEST_TYPES:
                rec._issue_iqama_request()
            elif rec.request_type in MEDICAL_INSURANCE_REQUEST_TYPES:
                rec._issue_medical_insurance()

    def _iter_payment_artifacts(self):
        self.ensure_one()
        vouchers = []
        for voucher in (self.cash_payment_id, self.bank_payment_id):
            if voucher:
                vouchers.append(voucher)
        if self.payment_request_id:
            for voucher in (self.payment_request_id.cash_payment_id, self.payment_request_id.bank_payment_id):
                if voucher and voucher not in vouchers:
                    vouchers.append(voucher)
        return vouchers

    def _has_posted_payment_artifacts(self):
        self.ensure_one()
        for voucher in self._iter_payment_artifacts():
            voucher = voucher.sudo()
            if (
                voucher.state == "posted"
                or voucher.accounting_manager_state == "posted"
                or (voucher.journal_entry_id and voucher.journal_entry_id.state == "posted")
            ):
                return True
        return False

    def _cleanup_payment_artifacts(self):
        for rec in self:
            if rec._has_posted_payment_artifacts() or rec.state in ("paid", "issued"):
                raise UserError(_("This request already has posted accounting/payment activity and cannot be reset or cancelled."))
            payment_request = rec.payment_request_id
            for voucher in rec._iter_payment_artifacts():
                voucher = voucher.sudo()
                if voucher.journal_entry_id:
                    raise UserError(_("Voucher %s already has an accounting entry and cannot be removed by reset/cancel.") % voucher.display_name)
                if voucher.state != "draft":
                    voucher.sudo().action_draft()
                voucher.sudo().unlink()
            if payment_request:
                payment_request.sudo().unlink()
            rec.with_context(skip_employee_service_request_lock=True).write({
                "payment_request_id": False,
                "cash_payment_id": False,
                "bank_payment_id": False,
                "payment_reference": False,
                "paid_date": False,
            })

    def _reset_approval_tracking_vals(self):
        return {
            "approved_amount": 0.0,
            "rejection_reason": False,
            "payment_reference": False,
            "paid_date": False,
            "hr_supervisor_approved_by_id": False,
            "hr_supervisor_approved_date": False,
            "employee_manager_approved_by_id": False,
            "employee_manager_approved_date": False,
            "hr_manager_approved_by_id": False,
            "hr_manager_approved_date": False,
            "accounts_approved_by_id": False,
            "accounts_approved_date": False,
            "md_approved_by_id": False,
            "md_approved_date": False,
            "finance_approved_by_id": False,
            "finance_approved_date": False,
        }

    def action_cancel(self):
        for rec in self:
            if not rec.can_cancel:
                raise UserError(_("You can only cancel non-final requests that do not have posted accounting."))
            rec._cleanup_payment_artifacts()
            vals = rec._reset_approval_tracking_vals()
            vals["state"] = "cancelled"
            rec.with_context(skip_employee_service_request_lock=True).write(vals)
            rec.message_post(body=_("Request cancelled by employee."))

    def action_reset_to_draft(self):
        for rec in self:
            if not rec.can_reset_to_draft:
                raise UserError(_("You cannot reset this request to draft."))
            rec._cleanup_payment_artifacts()
            vals = rec._reset_approval_tracking_vals()
            vals["state"] = "draft"
            rec.with_context(skip_employee_service_request_lock=True).write(vals)
            rec.message_post(body=_("Request reset to draft."))

    def action_reject(self):
        self.ensure_one()
        if not self.can_reject:
            raise UserError(_("You cannot reject this request at the current stage."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Reject Request"),
            "res_model": "pr.employee.service.request.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_request_id": self.id},
        }

    def _set_rejected(self, reason):
        for rec in self:
            rec.write({"state": "rejected", "rejection_reason": reason})
            rec.message_post(body=_("Request rejected: %s") % reason)

    def action_open_payment_voucher(self):
        self.ensure_one()
        voucher = self.cash_payment_id or self.bank_payment_id
        if not voucher:
            raise UserError(_("No payment voucher has been created yet."))
        self._copy_attachments_to(voucher)
        return {
            "type": "ir.actions.act_window",
            "name": _("Payment Voucher"),
            "res_model": voucher._name,
            "view_mode": "form",
            "res_id": voucher.id,
            "target": "current",
        }

    def action_open_payment_request(self):
        self.ensure_one()
        if not self.payment_request_id:
            raise UserError(_("No payment request has been created yet."))
        self._copy_attachments_to(self.payment_request_id)
        return {
            "type": "ir.actions.act_window",
            "name": _("Payment Request"),
            "res_model": "pr.employee.payment.request",
            "view_mode": "form",
            "res_id": self.payment_request_id.id,
            "target": "current",
        }

    def _prepare_payment_request_lines(self):
        self.ensure_one()
        expense_account_id = self.expense_account_id.id if self.expense_account_id else False
        if self.request_type == "iqama_renewal":
            return [
                (0, 0, {
                    "description": description,
                    "amount": line_amount,
                    "expense_account_id": expense_account_id,
                })
                for description, line_amount in (
                    (_("MOI fee - Iqama renewal - %s") % self.employee_id.name, self.moi_fee_amount),
                    (_("MOL fee - Work Permit renewal - %s") % self.employee_id.name, self.mol_fee_amount),
                )
                if line_amount > 0.0
            ]
        return [(0, 0, {
            "description": self._get_payment_description(),
            "amount": self._get_payment_amount(),
            "expense_account_id": expense_account_id,
        })]

    def _create_payment_request(self, notify_accounts=True):
        self.ensure_one()
        if self._is_self_paid_request() or self._is_historical_company_paid_exit_reentry():
            raise UserError(_("Self-paid and historical requests do not create payment requests or accounting vouchers."))
        if self.payment_request_id:
            if self.payment_request_id.state == "cancelled":
                self.payment_request_id.state = "requested"
            self._copy_attachments_to(self.payment_request_id)
            return self.payment_request_id
        if self.cash_payment_id or self.bank_payment_id:
            raise UserError(_("A payment voucher already exists for this request."))
        amount = self._get_payment_amount()
        self._check_selected_budget_or_raise(amount)
        payment_request = self.env["pr.employee.payment.request"].sudo().create({
            "service_request_id": self.id,
            "requested_user_id": self.requested_by_id.id or self.env.user.id,
            "employee_id": self.employee_id.id,
            "company_id": self.company_id.id,
            "expense_bucket_id": self.expense_bucket_id.id,
            "cost_center_id": self.cost_center_id.id,
            "line_ids": self._prepare_payment_request_lines(),
        })
        self.payment_request_id = payment_request.id
        self._copy_attachments_to(payment_request)
        if notify_accounts:
            payment_request._notify_accounts()
        return payment_request

    def _create_renewal_bpv(self):
        """Create and submit the renewal BPV immediately after MD approval."""
        self.ensure_one()
        if self._is_self_paid_request():
            raise UserError(_("Self-paid renewals do not create BPVs."))
        if not self._is_compliance_renewal():
            raise UserError(_("Automatic BPV creation is only available for compliance renewals."))
        if self.bank_payment_id:
            return self.bank_payment_id

        payment_request = self._create_payment_request(notify_accounts=False)
        pay_from_account = self.payment_account_id or payment_request._get_default_payment_account("bank")
        if not pay_from_account:
            raise UserError(_("Please configure or select the bank account used for renewal BPVs."))
        payment_request.sudo().write({
            "transfer_type": "bank",
            "pay_from_account_id": pay_from_account.id,
        })
        payment_request.sudo().action_create_payment_voucher()
        voucher = payment_request.bank_payment_id
        if not voucher:
            raise UserError(_("The renewal BPV could not be created."))
        self.bank_payment_id = voucher.id
        self._copy_attachments_to(voucher)
        if voucher.state == "draft":
            voucher.sudo().action_submit()
        payment_request.sudo()._notify_accounts()
        return voucher

    def _copy_attachments_to(self, target):
        self.ensure_one()
        source_attachments = self._get_supporting_attachments()
        if not target or not source_attachments:
            return self.env["ir.attachment"]
        Attachment = self.env["ir.attachment"].sudo()
        existing = Attachment.search([
            ("res_model", "=", target._name),
            ("res_id", "=", target.id),
        ])
        existing_keys = {
            (attachment.name, attachment.checksum)
            for attachment in existing
        }
        linked_attachments = self.env["ir.attachment"]
        for attachment in source_attachments:
            key = (attachment.name, attachment.checksum)
            if key in existing_keys:
                linked_attachments |= existing.filtered(
                    lambda existing_attachment: (
                        existing_attachment.name,
                        existing_attachment.checksum,
                    ) == key
                )[:1]
                continue
            copied_attachment = attachment.copy({
                "res_model": target._name,
                "res_id": target.id,
                "res_field": False,
            })
            linked_attachments |= copied_attachment
            existing_keys.add(key)
        if linked_attachments and "attachment_ids" in target._fields:
            target.sudo().write({
                "attachment_ids": [(4, attachment.id) for attachment in linked_attachments],
            })
        return linked_attachments

    def _create_payment_voucher(self):
        self.ensure_one()
        if self._is_self_paid_request() or self._is_historical_company_paid_exit_reentry():
            raise UserError(_("Self-paid and historical requests do not create payment vouchers."))
        existing_voucher = self.cash_payment_id or self.bank_payment_id
        if existing_voucher:
            return existing_voucher

        amount = self._get_payment_amount()
        line_vals = {
            "account_id": self.expense_account_id.id,
            "description": self._get_payment_description(),
            "reference_number": self.name,
            "amount": amount,
        }
        partner = self._get_employee_partner()
        if partner:
            line_vals["partner_id"] = partner.id
        analytic_distribution = self._get_employee_analytic_distribution()
        if analytic_distribution:
            line_vals["analytic_distribution"] = analytic_distribution
        employee_cost_center = self._get_employee_cost_center()
        if employee_cost_center and self.payment_method == "cash":
            line_vals["cs_employee_id"] = employee_cost_center.id
        if employee_cost_center and self.payment_method == "bank":
            line_vals["cs_employee_id"] = employee_cost_center.id

        payment_vals = {
            "account_id": self.payment_account_id.id,
            "company_id": self.company_id.id,
            "description": self._get_payment_description(),
            "accounting_date": fields.Date.context_today(self),
            "employee_service_request_id": self.id,
        }
        if self.payment_method == "cash":
            line_vals = {key: value for key, value in line_vals.items() if key in self.env["pr.account.cash.payment.line"]._fields}
            payment_vals["cash_payment_line_ids"] = [(0, 0, line_vals)]
            voucher = self.env["pr.account.cash.payment"].sudo().create(payment_vals)
            self.cash_payment_id = voucher.id
        else:
            line_vals = {key: value for key, value in line_vals.items() if key in self.env["pr.account.bank.payment.line"]._fields}
            payment_vals["bank_payment_line_ids"] = [(0, 0, line_vals)]
            voucher = self.env["pr.account.bank.payment"].sudo().create(payment_vals)
            self.bank_payment_id = voucher.id

        voucher.sudo().action_submit()
        self._copy_attachments_to(voucher)
        self.write({"payment_reference": voucher.name})
        return voucher

    def _mark_paid_from_voucher(self, voucher):
        for rec in self:
            if rec.state in ("paid", "issued"):
                continue
            rec.sudo().write({
                "state": "paid",
                "paid_date": fields.Date.context_today(rec),
                "payment_reference": voucher.name,
            })
            rec.message_post(body=_("Payment voucher %s was fully approved. Request marked as paid.") % voucher.display_name)

    def _issue_iqama_request(self):
        self.ensure_one()
        self._check_new_or_renewal_target()
        iqama = self.iqama_id or (self._find_employee_iqama() if self.request_type == "iqama_renewal" else False)
        if not iqama:
            iqama = self.env["hr.employee.iqama"].sudo().create({
                "name": self._get_type_label(),
                "employee_id": self.employee_id.id,
                "identification_id": self.iqama_no,
                "place_of_issue": self.place_of_issue or False,
                "expiry_date": self.service_expiry_date,
                "state": "approve",
            })
        else:
            iqama.sudo().write({
                "identification_id": self.iqama_no,
                "place_of_issue": self.place_of_issue or False,
                "expiry_date": self.service_expiry_date,
                "state": "approve",
            })
        if self.iqama_line_id:
            self.iqama_line_id.sudo().state = "issued"
        else:
            self_relation = self._get_self_relation()
            iqama_line = self.env["hr.employee.iqama.line"].sudo().create({
                "name": self.name,
                "iqama_id": iqama.id,
                "employee_id": self.employee_id.id,
                "relation_id": self_relation.id,
                "identification_id": self.iqama_no,
                "place_of_issue": self.place_of_issue or False,
                "from_date": self.service_from_date,
                "to_date": self.service_to_date,
                "expiry_date": self.service_expiry_date,
                "country_id": self.employee_id.country_id.id if self.employee_id.country_id else False,
                "amount": self._get_payment_amount(),
                "state": "issued",
            })
            self.iqama_line_id = iqama_line.id
        self.iqama_id = iqama.id
        self._copy_attachments_to(iqama)
        work_permit = self._create_or_update_combined_work_permit()
        self.with_context(skip_employee_service_request_lock=True).write({
            "state": "issued",
            "issue_date": self.issue_date or fields.Date.context_today(self),
            "work_permit_id": work_permit.id,
        })
        message = (
            _("New Iqama and Work Permit records have been created.")
            if self.request_type == "iqama_new"
            else _("Iqama and Work Permit renewal has been issued.")
        )
        self.message_post(body=message)

    def _issue_medical_insurance(self):
        self.ensure_one()
        self._check_new_or_renewal_target()
        insurance = self.insurance_id or (
            self._find_employee_insurance() if self.request_type == "medical_insurance_renewal" else False
        )
        if not insurance:
            insurance = self.env["hr.employee.medical.insurance"].sudo().create({
                "name": self._get_type_label(),
                "employee_id": self.employee_id.id,
                "identification_id": self.iqama_no,
                "insurance_company": self.insurance_company,
                "insurance_category": self.insurance_category,
                "expiry_date": self.service_expiry_date,
                "state": "approve",
            })
        else:
            insurance.sudo().write({
                "identification_id": self.iqama_no,
                "insurance_company": self.insurance_company,
                "insurance_category": self.insurance_category,
                "expiry_date": self.service_expiry_date,
                "state": "approve",
            })
        if self.insurance_line_id:
            self.insurance_line_id.sudo().state = "issued"
        else:
            self_relation = self._get_self_relation()
            insurance_line = self.env["hr.employee.medical.insurance.line"].sudo().create({
                "name": self.name,
                "insurance_id": insurance.id,
                "employee_id": self.employee_id.id,
                "relation_id": self_relation.id,
                "identification_id": self.iqama_no,
                "insurance_company": self.insurance_company,
                "insurance_category": self.insurance_category,
                "from_date": self.service_from_date,
                "to_date": self.service_to_date,
                "expiry_date": self.service_expiry_date,
                "country_id": self.employee_id.country_id.id if self.employee_id.country_id else False,
                "amount": self._get_payment_amount(),
                "state": "issued",
            })
            self.insurance_line_id = insurance_line.id
        self.insurance_id = insurance.id
        self._copy_attachments_to(insurance)
        self.with_context(skip_employee_service_request_lock=True).write({
            "state": "issued",
            "issue_date": self.issue_date or fields.Date.context_today(self),
        })
        message = (
            _("New medical insurance record has been created.")
            if self.request_type == "medical_insurance_new"
            else _("Medical insurance renewal has been issued.")
        )
        self.message_post(body=message)

    def _create_or_update_combined_work_permit(self):
        self.ensure_one()
        work_permit = self.work_permit_id or self._find_employee_work_permit()
        if not self.issue_date:
            raise UserError(_("Please enter the Iqama / Work Permit issuance date."))
        visa_number = self.visa_number or self.iqama_no or self.passport_no or self.name
        vals = {
            "name": self.name,
            "employee_id": self.employee_id.id,
            "visa_number": visa_number,
            "iqama_profession": self.iqama_profession or self.employee_id.job_id.name or _("To Be Confirmed"),
            "work_permit_fees": self._get_payment_amount(),
            "iqama_issuance_date": self.issue_date,
            "iqama_expiry_date": self.service_expiry_date,
            "work_permit_expiry_date": self.work_permit_expiry_date,
            "state": "issued",
            "payment_state": "draft" if self.request_type == "iqama_new" else "paid",
        }
        if work_permit:
            work_permit.sudo().write(vals)
        else:
            work_permit = self.env["hr.work.permit"].sudo().create(vals)
        if self.bank_payment_id and "bank_payment_id" in work_permit._fields:
            work_permit.sudo().bank_payment_id = self.bank_payment_id.id
        self._copy_attachments_to(work_permit)
        if self.visa_number != visa_number:
            self.with_context(skip_employee_service_request_lock=True).visa_number = visa_number
        return work_permit

    def _get_self_relation(self):
        relation = self.env.ref("pr_hr.employee_dependent_relationship_self", raise_if_not_found=False)
        if not relation:
            relation = self.env["hr.employee.dependent.relation"].sudo().search([("name", "=ilike", "Self")], limit=1)
        if not relation:
            raise UserError(_("Please configure the Self dependent relation before issuing this request."))
        return relation

    def _find_employee_iqama(self):
        self.ensure_one()
        domain = [("employee_id", "=", self.employee_id.id)]
        if self.iqama_no:
            exact = self.env["hr.employee.iqama"].sudo().search(domain + [("identification_id", "=", self.iqama_no)], limit=1)
            if exact:
                return exact
        return self.env["hr.employee.iqama"].sudo().search(domain, order="id desc", limit=1)

    def _find_employee_insurance(self):
        self.ensure_one()
        domain = [("employee_id", "=", self.employee_id.id)]
        if self.iqama_no:
            exact = self.env["hr.employee.medical.insurance"].sudo().search(
                domain + [("identification_id", "=", self.iqama_no)],
                limit=1,
            )
            if exact:
                return exact
        return self.env["hr.employee.medical.insurance"].sudo().search(domain, order="id desc", limit=1)

    def _find_employee_work_permit(self):
        self.ensure_one()
        domain = [("employee_id", "=", self.employee_id.id)]
        if self.visa_number:
            exact = self.env["hr.work.permit"].sudo().search(domain + [("visa_number", "=", self.visa_number)], limit=1)
            if exact:
                return exact
        return self.env["hr.work.permit"].sudo().search(domain, order="id desc", limit=1)

    @staticmethod
    def _next_service_from_date(lines):
        if not lines:
            return False
        to_dates = lines.filtered("to_date").mapped("to_date")
        return max(to_dates) + relativedelta(days=1) if to_dates else False

    def _get_payment_amount(self):
        self.ensure_one()
        if self._is_self_paid_request() or self._is_historical_company_paid_exit_reentry():
            return 0.0
        if self.request_type == "iqama_renewal":
            return self._get_requested_compliance_amount()
        if self.approved_amount:
            return self.approved_amount
        if self.request_type == "exit_reentry":
            return self.visa_fee
        return self.requested_amount

    def _get_requested_compliance_amount(self):
        self.ensure_one()
        if self.request_type == "iqama_renewal":
            return (self.moi_fee_amount or 0.0) + (self.mol_fee_amount or 0.0)
        return self.requested_amount

    def _get_payment_description(self):
        self.ensure_one()
        if self.request_type == "iqama_renewal":
            return _("%(request)s - Iqama & Work Permit renewal - %(employee)s (MOI %(moi).2f + MOL %(mol).2f)") % {
                "request": self.name,
                "employee": self.employee_id.name,
                "moi": self.moi_fee_amount,
                "mol": self.mol_fee_amount,
            }
        return _("%s - %s - %s") % (self.name, self._get_type_label(), self.employee_id.name)

    def _get_type_label(self):
        self.ensure_one()
        return dict(self._fields["request_type"].selection).get(self.request_type, _("Request"))

    def _get_employee_account(self):
        self.ensure_one()
        if "employee_account_id" in self.employee_id._fields and self.employee_id.employee_account_id:
            return self.employee_id.employee_account_id
        return self.env["account.account"]

    def _get_employee_cost_center(self):
        self.ensure_one()
        if self.cost_center_id:
            return self.cost_center_id
        if "employee_cost_center_id" in self.employee_id._fields and self.employee_id.employee_cost_center_id:
            return self.employee_id.employee_cost_center_id
        return self.env["account.analytic.account"]

    def _get_employee_analytic_distribution(self):
        self.ensure_one()
        employee_cost_center = self._get_employee_cost_center()
        if not employee_cost_center:
            return False
        if employee_cost_center == self.cost_center_id:
            return {str(employee_cost_center.id): 100.0}
        analytic_distribution = {}
        for field_name in ("project_id", "section_id", "department_id"):
            account = getattr(employee_cost_center, field_name, False)
            if account:
                analytic_distribution[str(account.id)] = 100.0
        analytic_distribution[str(employee_cost_center.id)] = 100.0
        return analytic_distribution

    def _get_employee_partner(self):
        self.ensure_one()
        if "work_contact_id" in self.employee_id._fields and self.employee_id.work_contact_id:
            return self.employee_id.work_contact_id
        if "address_home_id" in self.employee_id._fields and self.employee_id.address_home_id:
            return self.employee_id.address_home_id
        return self.env["res.partner"]

    def _get_default_payment_account(self):
        self.ensure_one()
        config_key = "pr_employee_service_requests.%s_account_id" % (self.payment_method or "bank")
        try:
            account_id = int(self.env["ir.config_parameter"].sudo().get_param(config_key, "0") or 0)
        except ValueError:
            account_id = 0
        if account_id:
            account = self.env["account.account"].sudo().browse(account_id).exists()
            if account:
                return account

        codes = ["1001.02.00.07"] if self.payment_method == "bank" else ["1001.01.00.01", "1001.01.00.02"]
        account = self.env["account.account"].sudo().search([("code", "in", codes)], limit=1)
        if account:
            return account

        code_prefix = "1001.02" if self.payment_method == "bank" else "1001.01"
        account = self.env["account.account"].sudo().search([("code", "=like", code_prefix + "%")], order="code", limit=1)
        if account:
            return account

        return self.env["account.account"].sudo().search([("account_type", "=", "asset_cash")], order="code", limit=1)

    def _get_default_hr_cost_center(self):
        self.ensure_one()
        employee = self.employee_id
        for field_name in (
            "employee_cost_center_id",
            "project_cost_center_id",
            "section_cost_center_id",
            "department_cost_center_id",
        ):
            if field_name in employee._fields:
                cost_center = employee[field_name]
                if cost_center:
                    return cost_center
        department = employee.department_id
        if department and "department_cost_center_id" in department._fields and department.department_cost_center_id:
            return department.department_cost_center_id
        return self.env["account.analytic.account"]

    def _get_default_hr_budget(self, cost_center=False):
        self.ensure_one()
        cost_center = cost_center or self.cost_center_id
        if not cost_center:
            return self.env["crossovered.budget"]
        target_date = self._get_budget_check_date()
        return self.env["crossovered.budget"].sudo().search([
            ("state", "in", ["validate", "done"]),
            ("date_from", "<=", target_date),
            ("date_to", ">=", target_date),
            ("crossovered_budget_line.analytic_account_id", "=", cost_center.id),
            ("pr_under_revision", "=", False),
        ], order="date_from desc, id desc", limit=1)

    def _check_selected_budget_or_raise(self, amount=False):
        self.ensure_one()
        if not self.expense_bucket_id:
            raise UserError(_("Please select the approved Budget."))
        if not self.cost_center_id:
            raise UserError(_("Please select the Cost Center."))
        self.expense_bucket_id._check_active_for_date(self._get_budget_check_date())
        remaining_by_cost_center = self.expense_bucket_id._get_remaining_by_cost_center()
        if self.cost_center_id.id not in remaining_by_cost_center:
            raise UserError(
                _("Cost Center %(cc)s is not included in Budget %(budget)s.")
                % {"cc": self.cost_center_id.display_name, "budget": self.expense_bucket_id.display_name}
            )
        amount = amount if amount is not False else self._get_payment_amount()
        remaining = remaining_by_cost_center.get(self.cost_center_id.id, 0.0)
        if amount > remaining:
            raise UserError(
                _("Insufficient budget for %(cc)s. Remaining: %(remaining).2f, Required: %(amount).2f")
                % {"cc": self.cost_center_id.display_name, "remaining": remaining, "amount": amount}
            )

    def _get_budget_check_date(self):
        self.ensure_one()
        return (
            self.expense_date
            or self.travel_date
            or self.service_from_date
            or self.issue_date
            or self.request_date
            or fields.Date.context_today(self)
        )


class PrEmployeeServiceRequestRejectWizard(models.TransientModel):
    _name = "pr.employee.service.request.reject.wizard"
    _description = "Employee Service Request Reject Wizard"

    request_id = fields.Many2one("pr.employee.service.request", string="Request", required=True)
    rejection_reason = fields.Text(string="Rejection Reason", required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        self.request_id._set_rejected(self.rejection_reason)
        return {"type": "ir.actions.act_window_close"}


class PrEmployeePaymentRequest(models.Model):
    _name = "pr.employee.payment.request"
    _description = "Employee Payment Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(string="Request Number", default="New", readonly=True, copy=False, tracking=True)
    service_request_id = fields.Many2one(
        "pr.employee.service.request",
        string="Employee Service Request",
        readonly=True,
        copy=False,
        tracking=True,
    )
    iqama_line_id = fields.Many2one(
        "hr.employee.iqama.line",
        string="Iqama Request",
        readonly=True,
        copy=False,
        tracking=True,
    )
    insurance_line_id = fields.Many2one(
        "hr.employee.medical.insurance.line",
        string="Medical Insurance Request",
        readonly=True,
        copy=False,
        tracking=True,
    )
    requested_user_id = fields.Many2one(
        "res.users",
        string="Requested By",
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True,
    )
    request_date = fields.Date(
        string="Request Date",
        default=fields.Date.context_today,
        readonly=True,
        tracking=True,
    )
    employee_id = fields.Many2one("hr.employee", string="Employee", required=True, readonly=True, tracking=True)
    department_id = fields.Many2one("hr.department", related="employee_id.department_id", store=True, readonly=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
        readonly=True,
    )
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id", readonly=True)
    expense_bucket_id = fields.Many2one(
        "crossovered.budget",
        string="Budget",
        required=True,
        readonly=True,
        tracking=True,
    )
    cost_center_id = fields.Many2one(
        "account.analytic.account",
        string="Cost Center",
        required=True,
        readonly=True,
        tracking=True,
    )
    transfer_type = fields.Selection(
        [("cash", "Cash"), ("bank", "Bank Transfer")],
        string="Transfer Type",
        tracking=True,
        copy=False,
    )
    pay_from_account_id = fields.Many2one(
        "account.account",
        string="Pay From Account",
        tracking=True,
        copy=False,
        help="Cash or bank account credited by the generated CPV/BPV.",
    )
    line_ids = fields.One2many(
        "pr.employee.payment.request.line",
        "payment_request_id",
        string="Payment Lines",
        copy=True,
    )
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "pr_employee_payment_request_attachment_rel",
        "payment_request_id",
        "attachment_id",
        string="Attachments",
        copy=False,
        help="Supporting documents copied from the employee service request and then copied to the generated CPV/BPV.",
    )
    total_amount = fields.Monetary(
        string="Total Amount",
        currency_field="currency_id",
        compute="_compute_total_amount",
        store=True,
    )
    state = fields.Selection(
        [
            ("requested", "Requested"),
            ("voucher_created", "Voucher Created"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="requested",
        tracking=True,
        copy=False,
    )
    cash_payment_id = fields.Many2one(
        "pr.account.cash.payment",
        string="CPV",
        readonly=True,
        copy=False,
        tracking=True,
    )
    bank_payment_id = fields.Many2one(
        "pr.account.bank.payment",
        string="BPV",
        readonly=True,
        copy=False,
        tracking=True,
    )
    attachment_count = fields.Integer(string="Attachments", compute="_compute_attachment_count")

    _sql_constraints = [
        (
            "pr_employee_payment_request_service_unique",
            "unique(service_request_id)",
            "A payment request already exists for this employee service request.",
        ),
        (
            "pr_employee_payment_request_iqama_unique",
            "unique(iqama_line_id)",
            "A payment request already exists for this Iqama request.",
        ),
        (
            "pr_employee_payment_request_insurance_unique",
            "unique(insurance_line_id)",
            "A payment request already exists for this medical insurance request.",
        ),
    ]

    def _is_accounting_epr_user(self):
        return any(self.env.user.has_group(xmlid) for xmlid in ACCOUNTING_GROUP_XML_IDS)

    def _apply_ir_rules(self, query, mode="read"):
        if mode in ACCOUNTING_EPR_RULE_BYPASS_MODES and self._is_accounting_epr_user():
            return
        return super()._apply_ir_rules(query, mode=mode)

    def check_access_rule(self, operation):
        if operation in ACCOUNTING_EPR_RULE_BYPASS_MODES and self._is_accounting_epr_user():
            return True
        return super().check_access_rule(operation)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("pr.employee.payment.request") or "New"
        records = super().create(vals_list)
        for record in records:
            if record.service_request_id:
                record.service_request_id.payment_request_id = record.id
            if record.iqama_line_id and "payment_request_id" in record.iqama_line_id._fields:
                record.iqama_line_id.payment_request_id = record.id
            if record.insurance_line_id and "payment_request_id" in record.insurance_line_id._fields:
                record.insurance_line_id.payment_request_id = record.id
        return records

    @api.depends("line_ids.amount")
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(rec.line_ids.mapped("amount"))

    @api.depends("attachment_ids", "service_request_id", "service_request_id.attachment_ids")
    def _compute_attachment_count(self):
        for rec in self:
            rec.attachment_count = len(rec._get_supporting_attachments())

    def _get_supporting_attachments(self):
        self.ensure_one()
        Attachment = self.env["ir.attachment"]
        own_attachments = self.attachment_ids.sudo() | Attachment.sudo().search([
            ("res_model", "=", self._name),
            ("res_id", "=", self.id),
        ])
        source_attachments = Attachment
        if self.service_request_id:
            source_attachments |= self.service_request_id._get_supporting_attachments()
        if self.iqama_line_id:
            source_attachments |= Attachment.sudo().search([
                ("res_model", "=", self.iqama_line_id._name),
                ("res_id", "=", self.iqama_line_id.id),
            ])
            if self.iqama_line_id.iqama_id:
                source_attachments |= Attachment.sudo().search([
                    ("res_model", "=", self.iqama_line_id.iqama_id._name),
                    ("res_id", "=", self.iqama_line_id.iqama_id.id),
                ])
        if self.insurance_line_id:
            source_attachments |= Attachment.sudo().search([
                ("res_model", "=", self.insurance_line_id._name),
                ("res_id", "=", self.insurance_line_id.id),
            ])
            if self.insurance_line_id.insurance_id:
                source_attachments |= Attachment.sudo().search([
                    ("res_model", "=", self.insurance_line_id.insurance_id._name),
                    ("res_id", "=", self.insurance_line_id.insurance_id.id),
                ])

        unique_ids = []
        seen_keys = set()
        for attachment in own_attachments | source_attachments:
            key = (
                attachment.name,
                attachment.checksum or attachment.url or attachment.store_fname or attachment.id,
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            unique_ids.append(attachment.id)
        return Attachment.browse(unique_ids)

    def action_view_attachments(self):
        self.ensure_one()
        return _open_attachment_preview_action(
            self,
            self._get_supporting_attachments(),
            _("Attachments - %s") % self.display_name,
        )

    def _copy_attachments_to(self, target):
        self.ensure_one()
        source_attachments = self._get_supporting_attachments()
        if not target or not source_attachments:
            return self.env["ir.attachment"]
        Attachment = self.env["ir.attachment"].sudo()
        existing = Attachment.search([
            ("res_model", "=", target._name),
            ("res_id", "=", target.id),
        ])
        existing_keys = {
            (attachment.name, attachment.checksum)
            for attachment in existing
        }
        linked_attachments = self.env["ir.attachment"]
        for attachment in source_attachments:
            key = (attachment.name, attachment.checksum)
            if key in existing_keys:
                linked_attachments |= existing.filtered(
                    lambda existing_attachment: (
                        existing_attachment.name,
                        existing_attachment.checksum,
                    ) == key
                )[:1]
                continue
            copied_attachment = attachment.copy({
                "res_model": target._name,
                "res_id": target.id,
                "res_field": False,
            })
            linked_attachments |= copied_attachment
            existing_keys.add(key)
        if linked_attachments and "attachment_ids" in target._fields:
            target.sudo().write({
                "attachment_ids": [(4, attachment.id) for attachment in linked_attachments],
            })
        return linked_attachments

    @api.onchange("transfer_type")
    def _onchange_transfer_type(self):
        for rec in self:
            rec.pay_from_account_id = rec._get_default_payment_account(rec.transfer_type)

    def _get_default_payment_account(self, transfer_type=False):
        transfer_type = transfer_type or self.transfer_type or "bank"
        codes = ["1001.02.00.07"] if transfer_type == "bank" else ["1001.01.00.01", "1001.01.00.02"]
        account = self.env["account.account"].sudo().search([("code", "in", codes)], limit=1)
        if account:
            return account
        code_prefix = "1001.02" if transfer_type == "bank" else "1001.01"
        account = self.env["account.account"].sudo().search([("code", "=like", code_prefix + "%")], order="code", limit=1)
        if account:
            return account
        return self.env["account.account"].sudo().search([("account_type", "=", "asset_cash")], order="code", limit=1)

    def _check_account_user(self):
        user = self.env.user
        if not any(user.has_group(xmlid) for xmlid in ACCOUNTING_GROUP_XML_IDS):
            raise UserError(_("Only Accounts users can create payment vouchers."))

    def _notify_accounts(self):
        users = self.env["res.users"]
        for xmlid in ACCOUNTING_GROUP_XML_IDS:
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                users |= group.users
        users = users.filtered(lambda user: user.active)
        activity_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        for rec in self:
            for user in users:
                if activity_type:
                    rec.activity_schedule(
                        activity_type_id=activity_type.id,
                        user_id=user.id,
                        summary=_("Employee Payment Request"),
                        note=_("Please review payment request %s and create the CPV/BPV.") % rec.display_name,
                    )

    def _check_ready_for_voucher(self):
        for rec in self:
            if rec.state == "cancelled":
                raise UserError(_("Cancelled payment requests cannot create vouchers."))
            if rec.cash_payment_id or rec.bank_payment_id:
                raise UserError(_("A payment voucher already exists for payment request %s.") % rec.name)
            if rec.service_request_id and (rec.service_request_id.cash_payment_id or rec.service_request_id.bank_payment_id):
                raise UserError(_("A payment voucher already exists for employee request %s.") % rec.service_request_id.name)
            if not rec.transfer_type:
                raise UserError(_("Please select Transfer Type: Cash or Bank Transfer."))
            if not rec.pay_from_account_id:
                raise UserError(_("Please select the Pay From Account."))
            if not rec.expense_bucket_id:
                raise UserError(_("Please select the approved Budget."))
            if not rec.cost_center_id:
                raise UserError(_("Please select the Cost Center."))
            if not rec.line_ids:
                raise UserError(_("This payment request has no lines."))
            missing_accounts = rec.line_ids.filtered(lambda line: not line.expense_account_id)
            if missing_accounts:
                raise UserError(_("Please select an Expense Account on every payment request line."))
            invalid_lines = rec.line_ids.filtered(lambda line: line.amount <= 0.0)
            if invalid_lines:
                raise UserError(_("Payment request lines must have a positive amount."))
            rec._check_selected_budget_or_raise()

    def _check_selected_budget_or_raise(self, amount=False):
        for rec in self:
            rec.expense_bucket_id._check_active_for_date(rec.request_date)
            remaining_by_cost_center = rec.expense_bucket_id._get_remaining_by_cost_center()
            if rec.cost_center_id.id not in remaining_by_cost_center:
                raise UserError(
                    _("Cost Center %(cc)s is not included in Budget %(budget)s.")
                    % {"cc": rec.cost_center_id.display_name, "budget": rec.expense_bucket_id.display_name}
                )
            amount_to_check = amount if amount is not False else rec.total_amount
            remaining = remaining_by_cost_center.get(rec.cost_center_id.id, 0.0)
            if amount_to_check > remaining:
                raise UserError(
                    _("Insufficient budget for %(cc)s. Remaining: %(remaining).2f, Required: %(amount).2f")
                    % {
                        "cc": rec.cost_center_id.display_name,
                        "remaining": remaining,
                        "amount": amount_to_check,
                    }
                )

    def _get_employee_partner(self):
        self.ensure_one()
        employee = self.employee_id
        if "work_contact_id" in employee._fields and employee.work_contact_id:
            return employee.work_contact_id
        if "address_home_id" in employee._fields and employee.address_home_id:
            return employee.address_home_id
        return self.env["res.partner"]

    def _prepare_voucher_line_vals(self):
        self.ensure_one()
        line_vals = []
        partner = self._get_employee_partner()
        cost_center_is_project = getattr(self.cost_center_id, "analytic_plan_type", False) == "project"
        cost_center_is_employee = getattr(self.cost_center_id, "analytic_plan_type", False) == "employee"
        for line in self.line_ids:
            amount = line.amount or 0.0
            if amount <= 0.0:
                continue
            line_vals.append({
                "account_id": line.expense_account_id.id,
                "description": line.description or self.name,
                "reference_number": self.name,
                "partner_id": partner.id if partner else False,
                "amount": amount,
                "cs_project_id": self.cost_center_id.id if cost_center_is_project else False,
                "cs_employee_id": self.cost_center_id.id if cost_center_is_employee else False,
                "analytic_distribution": {str(self.cost_center_id.id): 100.0},
            })
        if not line_vals:
            raise UserError(_("Payment request has no positive amount lines to create a voucher."))
        return line_vals

    def _filter_model_vals(self, model_name, vals):
        model_fields = self.env[model_name]._fields
        return {key: value for key, value in vals.items() if key in model_fields}

    def action_create_payment_voucher(self):
        self._check_account_user()
        voucher = False
        voucher_model = False
        for rec in self:
            rec._check_ready_for_voucher()
            line_vals = rec._prepare_voucher_line_vals()
            common_vals = {
                "account_id": rec.pay_from_account_id.id,
                "company_id": rec.company_id.id,
                "description": _("Generated from Employee payment request %s") % rec.name,
                "accounting_date": fields.Date.context_today(rec),
                "employee_payment_request_id": rec.id,
            }
            if rec.service_request_id:
                common_vals["employee_service_request_id"] = rec.service_request_id.id
            if rec.iqama_line_id:
                common_vals["iqama_line_id"] = rec.iqama_line_id.id
            if rec.insurance_line_id:
                common_vals["insurance_line_id"] = rec.insurance_line_id.id

            if rec.transfer_type == "cash":
                voucher_model = "pr.account.cash.payment"
                voucher_vals = rec._filter_model_vals(voucher_model, common_vals)
                line_model = "pr.account.cash.payment.line"
                voucher = self.env[voucher_model].sudo().create({
                    **voucher_vals,
                    "cash_payment_line_ids": [
                        (0, 0, rec._filter_model_vals(line_model, vals)) for vals in line_vals
                    ],
                })
                rec.cash_payment_id = voucher.id
                if rec.service_request_id:
                    rec.service_request_id.cash_payment_id = voucher.id
            else:
                voucher_model = "pr.account.bank.payment"
                voucher_vals = rec._filter_model_vals(voucher_model, common_vals)
                line_model = "pr.account.bank.payment.line"
                voucher = self.env[voucher_model].sudo().create({
                    **voucher_vals,
                    "bank_payment_line_ids": [
                        (0, 0, rec._filter_model_vals(line_model, vals)) for vals in line_vals
                    ],
                })
                rec.bank_payment_id = voucher.id
                if rec.service_request_id:
                    rec.service_request_id.bank_payment_id = voucher.id
                if rec.iqama_line_id and "bank_payment_id" in rec.iqama_line_id._fields:
                    rec.iqama_line_id.bank_payment_id = voucher.id
                if rec.insurance_line_id and "bank_payment_id" in rec.insurance_line_id._fields:
                    rec.insurance_line_id.bank_payment_id = voucher.id

            rec.state = "voucher_created"
            rec._copy_attachments_to(voucher)
            if rec.service_request_id:
                rec.service_request_id.payment_reference = voucher.name
            rec.message_post(
                body=_("%s %s created in Draft.")
                % ("CPV" if rec.transfer_type == "cash" else "BPV", voucher.name),
                message_type="notification",
            )

        return {
            "type": "ir.actions.act_window",
            "name": _("Payment Voucher"),
            "res_model": voucher_model,
            "res_id": voucher.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_payment_voucher(self):
        self.ensure_one()
        voucher = self.cash_payment_id or self.bank_payment_id
        if not voucher:
            raise UserError(_("No payment voucher has been created yet."))
        self._copy_attachments_to(voucher)
        return {
            "type": "ir.actions.act_window",
            "name": _("Payment Voucher"),
            "res_model": voucher._name,
            "res_id": voucher.id,
            "view_mode": "form",
            "target": "current",
        }

    def _mark_source_paid_from_voucher(self, voucher):
        for rec in self:
            if rec.service_request_id:
                rec.service_request_id._mark_paid_from_voucher(voucher)
            if rec.iqama_line_id:
                vals = {"state": "issued"}
                if voucher._name == "pr.account.bank.payment" and "bank_payment_id" in rec.iqama_line_id._fields:
                    vals["bank_payment_id"] = voucher.id
                rec.iqama_line_id.sudo().write(vals)
            if rec.insurance_line_id:
                vals = {"state": "issued"}
                if voucher._name == "pr.account.bank.payment" and "bank_payment_id" in rec.insurance_line_id._fields:
                    vals["bank_payment_id"] = voucher.id
                rec.insurance_line_id.sudo().write(vals)

    def action_cancel(self):
        for rec in self:
            if rec.cash_payment_id or rec.bank_payment_id:
                raise UserError(_("Cannot cancel a request after a voucher has been created."))
            rec.state = "cancelled"


class PrEmployeePaymentRequestLine(models.Model):
    _name = "pr.employee.payment.request.line"
    _description = "Employee Payment Request Line"
    _order = "id"

    payment_request_id = fields.Many2one(
        "pr.employee.payment.request",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(related="payment_request_id.company_id", store=True, readonly=True)
    currency_id = fields.Many2one(related="payment_request_id.currency_id", readonly=True)
    description = fields.Char(string="Description", required=True)
    amount = fields.Monetary(string="Amount", currency_field="currency_id", readonly=True)
    expense_account_id = fields.Many2one(
        "account.account",
        string="Expense Account",
        domain="[('deprecated', '=', False)]",
    )
    remarks = fields.Char(string="Remarks")

    def _is_accounting_epr_user(self):
        return any(self.env.user.has_group(xmlid) for xmlid in ACCOUNTING_GROUP_XML_IDS)

    def _apply_ir_rules(self, query, mode="read"):
        if mode in ACCOUNTING_EPR_RULE_BYPASS_MODES and self._is_accounting_epr_user():
            return
        return super()._apply_ir_rules(query, mode=mode)

    def check_access_rule(self, operation):
        if operation in ACCOUNTING_EPR_RULE_BYPASS_MODES and self._is_accounting_epr_user():
            return True
        return super().check_access_rule(operation)

    @api.constrains("amount")
    def _check_positive_amount(self):
        for rec in self:
            if rec.amount <= 0.0:
                raise ValidationError(_("Payment request line amount must be greater than zero."))


class AccountCashPayment(models.Model):
    _inherit = "pr.account.cash.payment"

    employee_service_request_id = fields.Many2one(
        "pr.employee.service.request",
        string="Employee Request",
        readonly=True,
        copy=False,
        tracking=True,
    )
    employee_payment_request_id = fields.Many2one(
        "pr.employee.payment.request",
        string="Employee Payment Request",
        readonly=True,
        copy=False,
        tracking=True,
    )
    iqama_line_id = fields.Many2one("hr.employee.iqama.line", string="Iqama", readonly=True, copy=False, tracking=True)
    insurance_line_id = fields.Many2one(
        "hr.employee.medical.insurance.line",
        string="Insurance",
        readonly=True,
        copy=False,
        tracking=True,
    )

    def _check_employee_payment_request_budget(self, line_field):
        for voucher in self.filtered("employee_payment_request_id"):
            if voucher.state != "draft":
                continue
            amount = sum(voucher[line_field].mapped("total_amount"))
            voucher.employee_payment_request_id._check_selected_budget_or_raise(amount)

    def action_submit(self):
        self._check_employee_payment_request_budget("cash_payment_line_ids")
        return super().action_submit()

    def action_post(self):
        res = super().action_post()
        for rec in self.filtered("employee_payment_request_id"):
            rec.employee_payment_request_id._mark_source_paid_from_voucher(rec)
        for rec in self.filtered(lambda voucher: voucher.employee_service_request_id and not voucher.employee_payment_request_id):
            rec.employee_service_request_id._mark_paid_from_voucher(rec)
        for rec in self.filtered(lambda voucher: voucher.iqama_line_id and not voucher.employee_payment_request_id):
            rec.iqama_line_id.sudo().state = "issued"
        for rec in self.filtered(lambda voucher: voucher.insurance_line_id and not voucher.employee_payment_request_id):
            rec.insurance_line_id.sudo().state = "issued"
        return res


class AccountBankPayment(models.Model):
    _inherit = "pr.account.bank.payment"

    employee_service_request_id = fields.Many2one(
        "pr.employee.service.request",
        string="Employee Request",
        readonly=True,
        copy=False,
        tracking=True,
    )
    employee_payment_request_id = fields.Many2one(
        "pr.employee.payment.request",
        string="Employee Payment Request",
        readonly=True,
        copy=False,
        tracking=True,
    )

    def _check_employee_payment_request_budget(self, line_field):
        for voucher in self.filtered("employee_payment_request_id"):
            if voucher.state != "draft":
                continue
            amount = sum(voucher[line_field].mapped("total_amount"))
            voucher.employee_payment_request_id._check_selected_budget_or_raise(amount)

    def action_submit(self):
        self._check_employee_payment_request_budget("bank_payment_line_ids")
        return super().action_submit()

    def action_post(self):
        res = super().action_post()
        for rec in self.filtered("employee_payment_request_id"):
            rec.employee_payment_request_id._mark_source_paid_from_voucher(rec)
        for rec in self.filtered(lambda voucher: voucher.employee_service_request_id and not voucher.employee_payment_request_id):
            rec.employee_service_request_id._mark_paid_from_voucher(rec)
        return res


class HREmployeeIqamaLine(models.Model):
    _inherit = "hr.employee.iqama.line"

    payment_request_id = fields.Many2one(
        "pr.employee.payment.request",
        string="Payment Request",
        readonly=True,
        copy=False,
    )


class HREmployeeMedicalInsuranceLine(models.Model):
    _inherit = "hr.employee.medical.insurance.line"

    payment_request_id = fields.Many2one(
        "pr.employee.payment.request",
        string="Payment Request",
        readonly=True,
        copy=False,
    )


class HREmployeeIqamaLineAddWizard(models.Model):
    _inherit = "hr.employee.iqama.line.add.wizard"

    expense_bucket_id = fields.Many2one(
        "crossovered.budget",
        string="Budget",
        required=True,
        domain="[('state', 'in', ['validate', 'done']), ('pr_under_revision', '=', False)]",
    )
    cost_center_id = fields.Many2one(
        "account.analytic.account",
        string="Cost Center",
        required=True,
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        employee = self.env["hr.employee"].browse(values.get("employee_id") or self.env.context.get("default_employee_id"))
        cost_center = self._get_default_hr_cost_center(employee)
        if cost_center and "cost_center_id" in fields_list:
            values["cost_center_id"] = cost_center.id
        if cost_center and "expense_bucket_id" in fields_list:
            budget = self._get_default_hr_budget(cost_center, values.get("from_date"))
            if budget:
                values["expense_bucket_id"] = budget.id
        return values

    @api.onchange("employee_id", "from_date", "cost_center_id")
    def _onchange_hr_budget_fields(self):
        for rec in self:
            if rec.employee_id and not rec.cost_center_id:
                rec.cost_center_id = rec._get_default_hr_cost_center(rec.employee_id)
            if rec.cost_center_id and not rec.expense_bucket_id:
                rec.expense_bucket_id = rec._get_default_hr_budget(rec.cost_center_id, rec.from_date)

    def _get_default_hr_cost_center(self, employee):
        for field_name in (
            "employee_cost_center_id",
            "project_cost_center_id",
            "section_cost_center_id",
            "department_cost_center_id",
        ):
            if field_name in employee._fields:
                cost_center = employee[field_name]
                if cost_center:
                    return cost_center
        department = employee.department_id
        if department and "department_cost_center_id" in department._fields and department.department_cost_center_id:
            return department.department_cost_center_id
        return self.env["account.analytic.account"]

    def _get_default_hr_budget(self, cost_center, target_date=False):
        if not cost_center:
            return self.env["crossovered.budget"]
        target_date = target_date or fields.Date.context_today(self)
        return self.env["crossovered.budget"].sudo().search([
            ("state", "in", ["validate", "done"]),
            ("date_from", "<=", target_date),
            ("date_to", ">=", target_date),
            ("crossovered_budget_line.analytic_account_id", "=", cost_center.id),
            ("pr_under_revision", "=", False),
        ], order="date_from desc, id desc", limit=1)


class HREmployeeMedicalInsuranceLineAddWizard(models.Model):
    _inherit = "hr.employee.medical.insurance.line.add.wizard"

    expense_bucket_id = fields.Many2one(
        "crossovered.budget",
        string="Budget",
        required=True,
        domain="[('state', 'in', ['validate', 'done']), ('pr_under_revision', '=', False)]",
    )
    cost_center_id = fields.Many2one(
        "account.analytic.account",
        string="Cost Center",
        required=True,
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        employee = self.env["hr.employee"].browse(values.get("employee_id") or self.env.context.get("default_employee_id"))
        cost_center = self._get_default_hr_cost_center(employee)
        if cost_center and "cost_center_id" in fields_list:
            values["cost_center_id"] = cost_center.id
        if cost_center and "expense_bucket_id" in fields_list:
            budget = self._get_default_hr_budget(cost_center, values.get("from_date"))
            if budget:
                values["expense_bucket_id"] = budget.id
        return values

    @api.onchange("employee_id", "from_date", "cost_center_id")
    def _onchange_hr_budget_fields(self):
        for rec in self:
            if rec.employee_id and not rec.cost_center_id:
                rec.cost_center_id = rec._get_default_hr_cost_center(rec.employee_id)
            if rec.cost_center_id and not rec.expense_bucket_id:
                rec.expense_bucket_id = rec._get_default_hr_budget(rec.cost_center_id, rec.from_date)

    def _get_default_hr_cost_center(self, employee):
        for field_name in (
            "employee_cost_center_id",
            "project_cost_center_id",
            "section_cost_center_id",
            "department_cost_center_id",
        ):
            if field_name in employee._fields:
                cost_center = employee[field_name]
                if cost_center:
                    return cost_center
        department = employee.department_id
        if department and "department_cost_center_id" in department._fields and department.department_cost_center_id:
            return department.department_cost_center_id
        return self.env["account.analytic.account"]

    def _get_default_hr_budget(self, cost_center, target_date=False):
        if not cost_center:
            return self.env["crossovered.budget"]
        target_date = target_date or fields.Date.context_today(self)
        return self.env["crossovered.budget"].sudo().search([
            ("state", "in", ["validate", "done"]),
            ("date_from", "<=", target_date),
            ("date_to", ">=", target_date),
            ("crossovered_budget_line.analytic_account_id", "=", cost_center.id),
            ("pr_under_revision", "=", False),
        ], order="date_from desc, id desc", limit=1)


class HrWorkspaceDashboardService(models.AbstractModel):
    _inherit = "de.hr.workspace.dashboard.service"

    @api.model
    def _style_for_menu(self, menu_name):
        name = (menu_name or "").lower()
        if "reimbursement" in name:
            return "fa-money", "danger"
        if "exit" in name or "re-entry" in name:
            return "fa-plane", "warning"
        if "iqama" in name:
            return "fa-id-card-o", "info"
        if "medical" in name or "insurance" in name:
            return "fa-medkit", "success"
        if "work permit" in name:
            return "fa-briefcase", "primary"
        if "letter" in name:
            return "fa-file-text-o", "primary"
        return super()._style_for_menu(menu_name)
