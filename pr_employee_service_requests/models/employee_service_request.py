from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


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
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("hr_supervisor_approval", "HR Supervisor"),
            ("employee_manager_approval", "Employee Manager"),
            ("hr_manager_approval", "HR Manager"),
            ("md_approval", "Managing Director"),
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
            ("travel", "Travel"),
            ("medical", "Medical"),
            ("fuel", "Fuel"),
            ("mobile", "Mobile/Internet"),
            ("office", "Office Expense"),
            ("government", "Government Fee"),
            ("other", "Other"),
        ],
        string="Reimbursement Category",
        default="other",
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

    reason = fields.Text(string="Reason / Notes", required=True, tracking=True)
    rejection_reason = fields.Text(string="Rejection Reason", readonly=True, tracking=True)

    hr_supervisor_approved_by_id = fields.Many2one("res.users", string="HR Supervisor Approved By", readonly=True, copy=False)
    hr_supervisor_approved_date = fields.Datetime(string="HR Supervisor Approved On", readonly=True, copy=False)
    employee_manager_approved_by_id = fields.Many2one("res.users", string="Manager Approved By", readonly=True, copy=False)
    employee_manager_approved_date = fields.Datetime(string="Manager Approved On", readonly=True, copy=False)
    hr_manager_approved_by_id = fields.Many2one("res.users", string="HR Manager Approved By", readonly=True, copy=False)
    hr_manager_approved_date = fields.Datetime(string="HR Manager Approved On", readonly=True, copy=False)
    md_approved_by_id = fields.Many2one("res.users", string="MD Approved By", readonly=True, copy=False)
    md_approved_date = fields.Datetime(string="MD Approved On", readonly=True, copy=False)

    can_hr_supervisor_approve = fields.Boolean(compute="_compute_action_flags")
    can_employee_manager_approve = fields.Boolean(compute="_compute_action_flags")
    can_hr_manager_approve = fields.Boolean(compute="_compute_action_flags")
    can_md_approve = fields.Boolean(compute="_compute_action_flags")
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

    @api.depends("cash_payment_id.state", "bank_payment_id.state")
    def _compute_payment_voucher_state(self):
        for rec in self:
            voucher = rec.cash_payment_id or rec.bank_payment_id
            rec.payment_voucher_state = voucher.state if voucher else False

    @api.depends("travel_date", "return_date")
    def _compute_duration_days(self):
        for rec in self:
            if rec.travel_date and rec.return_date and rec.return_date >= rec.travel_date:
                rec.duration_days = (rec.return_date - rec.travel_date).days + 1
            else:
                rec.duration_days = 0

    @api.depends_context("uid")
    @api.depends("state", "request_type", "requested_by_id", "employee_manager_user_id")
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
        is_admin = user.has_group("base.group_system")
        for rec in self:
            is_owner = rec.requested_by_id == user or rec.employee_id.user_id == user
            is_employee_manager = rec.employee_manager_user_id == user
            rec.can_hr_supervisor_approve = rec.state == "hr_supervisor_approval" and (is_hr_supervisor or is_admin)
            rec.can_employee_manager_approve = rec.state == "employee_manager_approval" and (is_employee_manager or is_admin)
            rec.can_hr_manager_approve = rec.state == "hr_manager_approval" and (is_hr_manager or is_admin)
            rec.can_md_approve = rec.state == "md_approval" and (is_md or is_admin)
            rec.can_issue = rec.request_type == "exit_reentry" and rec.state == "paid" and (is_hr_manager or is_hr_supervisor or is_admin)
            rec.can_reject = (
                rec.state in ("hr_supervisor_approval", "employee_manager_approval", "hr_manager_approval", "md_approval")
                and (
                    (rec.state == "hr_supervisor_approval" and is_hr_supervisor)
                    or (rec.state == "employee_manager_approval" and is_employee_manager)
                    or (rec.state == "hr_manager_approval" and is_hr_manager)
                    or (rec.state == "md_approval" and is_md)
                    or is_admin
                )
            )
            rec.can_reset_to_draft = rec.state == "rejected" and (is_owner or is_hr_manager or is_admin)
            rec.can_cancel = rec.state in ("draft", "hr_supervisor_approval") and is_owner

    @api.onchange("employee_id", "payment_method")
    def _onchange_employee_or_payment_method(self):
        for rec in self:
            if rec.employee_id:
                rec.company_id = rec.employee_id.company_id or self.env.company
                rec.passport_no = rec.employee_id.passport_id or rec.passport_no
                rec.iqama_no = rec.employee_id.identification_id or rec.iqama_no
                employee_account = rec._get_employee_account()
                if employee_account and not rec.expense_account_id:
                    rec.expense_account_id = employee_account
            if not rec.payment_account_id:
                rec.payment_account_id = rec._get_default_payment_account()

    @api.onchange("requested_amount", "visa_fee", "request_type")
    def _onchange_amounts(self):
        for rec in self:
            if not rec.approved_amount:
                rec.approved_amount = rec._get_payment_amount()

    @api.constrains("request_type", "requested_amount", "travel_date", "return_date")
    def _check_request_values(self):
        for rec in self:
            if rec.request_type == "reimbursement" and rec.requested_amount <= 0.0:
                raise ValidationError(_("Requested Amount must be greater than zero for reimbursement requests."))
            if rec.request_type == "exit_reentry" and rec.travel_date and rec.return_date:
                if rec.return_date < rec.travel_date:
                    raise ValidationError(_("Return Date cannot be before Travel Date."))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.name in (False, "New", _("New")):
                rec.name = self.env["ir.sequence"].next_by_code("pr.employee.service.request") or _("New")
            if not rec.passport_no:
                rec.passport_no = rec.employee_id.passport_id or False
            if not rec.iqama_no:
                rec.iqama_no = rec.employee_id.identification_id or False
            updates = {}
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
        return records

    def write(self, vals):
        protected = {
            "request_type",
            "employee_id",
            "reimbursement_type",
            "expense_date",
            "requested_amount",
            "payment_method",
            "attachment_ids",
            "destination_country_id",
            "travel_date",
            "return_date",
            "passport_no",
            "iqama_no",
            "reason",
        }
        if protected.intersection(vals):
            for rec in self:
                if rec.state != "draft":
                    raise UserError(_("Submitted requests cannot be edited. Reject and reset to draft first."))
        approval_fields = {"approved_amount", "payment_account_id", "expense_account_id", "visa_fee"}
        if approval_fields.intersection(vals):
            can_edit_approval = (
                self.env.user.has_group("pr_hr_recruitment_request.group_onboarding_supervisor")
                or self.env.user.has_group("hr.group_hr_manager")
                or self.env.user.has_group("pr_hr_recruitment_request.group_onboarding_manager")
                or self.env.user.has_group("pr_custom_purchase.managing_director")
                or self.env.user.has_group("pr_hr_recruitment_request.group_onboarding_md")
                or self.env.user.has_group("base.group_system")
            )
            for rec in self:
                if rec.state != "draft" and not can_edit_approval:
                    raise UserError(_("Only HR/MD approvers can edit approval and voucher accounting fields."))
        return super().write(vals)

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
            if not rec.employee_manager_user_id:
                raise UserError(_("Please set a manager user on the employee before submitting."))
            if rec.request_type == "reimbursement":
                if rec.requested_amount <= 0.0:
                    raise UserError(_("Please enter a reimbursement amount greater than zero."))
                if not rec.expense_date:
                    raise UserError(_("Please enter the expense date."))
            if rec.request_type == "exit_reentry":
                if not rec.destination_country_id:
                    raise UserError(_("Please select the destination country."))
                if not rec.travel_date or not rec.return_date:
                    raise UserError(_("Please enter travel and return dates."))
                if rec.return_date < rec.travel_date:
                    raise UserError(_("Return Date cannot be before Travel Date."))

    def _check_before_md_approval(self):
        for rec in self:
            amount = rec._get_payment_amount()
            if amount <= 0.0:
                if rec.request_type == "exit_reentry":
                    raise UserError(_("Please enter the visa fee or approved payable amount before MD approval."))
                raise UserError(_("Please enter an approved amount greater than zero before MD approval."))
            if not rec.payment_account_id:
                payment_account = rec._get_default_payment_account()
                if payment_account:
                    rec.payment_account_id = payment_account.id
            if not rec.expense_account_id:
                employee_account = rec._get_employee_account()
                if employee_account:
                    rec.expense_account_id = employee_account.id
            if not rec.payment_account_id:
                raise UserError(_("Please select the Pay From Account before MD approval."))
            if not rec.expense_account_id:
                raise UserError(_("Please select the Employee / Expense Account before MD approval."))

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
        self._check_before_submit()
        for rec in self:
            if rec.state != "draft":
                continue
            rec.write({"state": "hr_supervisor_approval", "rejection_reason": False, "approved_amount": False})
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
            rec.write({
                "state": "employee_manager_approval",
                "hr_supervisor_approved_by_id": self.env.user.id,
                "hr_supervisor_approved_date": fields.Datetime.now(),
            })
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

    def action_md_approve(self):
        for rec in self:
            if not rec.can_md_approve:
                raise UserError(_("Only MD can approve this stage."))
            rec._check_before_md_approval()
            voucher = rec._create_payment_voucher()
            rec.write({
                "state": "payment_approval",
                "approved_amount": rec._get_payment_amount(),
                "md_approved_by_id": self.env.user.id,
                "md_approved_date": fields.Datetime.now(),
            })
            rec.message_post(
                body=_("MD approved this request and created payment voucher %s.") % voucher.display_name
            )

    def action_issue(self):
        for rec in self:
            if not rec.can_issue:
                raise UserError(_("Only HR can issue a paid exit/re-entry request."))
            if not rec.visa_number:
                raise UserError(_("Please enter the Exit/Re-entry Visa No. before issuing."))
            rec.write({"state": "issued", "issue_date": rec.issue_date or fields.Date.context_today(rec)})
            rec.message_post(body=_("Exit/Re-entry request has been issued."))

    def action_cancel(self):
        for rec in self:
            if not rec.can_cancel:
                raise UserError(_("You can only cancel your own draft or submitted requests."))
            rec.write({"state": "cancelled"})
            rec.message_post(body=_("Request cancelled by employee."))

    def action_reset_to_draft(self):
        for rec in self:
            if not rec.can_reset_to_draft:
                raise UserError(_("You cannot reset this request to draft."))
            rec.write({"state": "draft", "rejection_reason": False})
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
        return {
            "type": "ir.actions.act_window",
            "name": _("Payment Voucher"),
            "res_model": voucher._name,
            "view_mode": "form",
            "res_id": voucher.id,
            "target": "current",
        }

    def _create_payment_voucher(self):
        self.ensure_one()
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
            payment_vals["cash_payment_line_ids"] = [(0, 0, line_vals)]
            voucher = self.env["pr.account.cash.payment"].sudo().create(payment_vals)
            self.cash_payment_id = voucher.id
        else:
            payment_vals["bank_payment_line_ids"] = [(0, 0, line_vals)]
            voucher = self.env["pr.account.bank.payment"].sudo().create(payment_vals)
            self.bank_payment_id = voucher.id

        voucher.sudo().action_submit()
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

    def _get_payment_amount(self):
        self.ensure_one()
        if self.approved_amount:
            return self.approved_amount
        if self.request_type == "exit_reentry":
            return self.visa_fee
        return self.requested_amount

    def _get_payment_description(self):
        self.ensure_one()
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
        if "employee_cost_center_id" in self.employee_id._fields and self.employee_id.employee_cost_center_id:
            return self.employee_id.employee_cost_center_id
        return self.env["account.analytic.account"]

    def _get_employee_analytic_distribution(self):
        self.ensure_one()
        employee_cost_center = self._get_employee_cost_center()
        if not employee_cost_center:
            return False
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


class PrEmployeeServiceRequestRejectWizard(models.TransientModel):
    _name = "pr.employee.service.request.reject.wizard"
    _description = "Employee Service Request Reject Wizard"

    request_id = fields.Many2one("pr.employee.service.request", string="Request", required=True)
    rejection_reason = fields.Text(string="Rejection Reason", required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        self.request_id._set_rejected(self.rejection_reason)
        return {"type": "ir.actions.act_window_close"}


class AccountCashPayment(models.Model):
    _inherit = "pr.account.cash.payment"

    employee_service_request_id = fields.Many2one(
        "pr.employee.service.request",
        string="Employee Request",
        readonly=True,
        copy=False,
        tracking=True,
    )

    def action_post(self):
        res = super().action_post()
        for rec in self.filtered("employee_service_request_id"):
            rec.employee_service_request_id._mark_paid_from_voucher(rec)
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

    def action_post(self):
        res = super().action_post()
        for rec in self.filtered("employee_service_request_id"):
            rec.employee_service_request_id._mark_paid_from_voucher(rec)
        return res


class HrWorkspaceDashboardService(models.AbstractModel):
    _inherit = "de.hr.workspace.dashboard.service"

    @api.model
    def _style_for_menu(self, menu_name):
        name = (menu_name or "").lower()
        if "reimbursement" in name:
            return "fa-money", "danger"
        if "exit" in name or "re-entry" in name:
            return "fa-plane", "warning"
        return super()._style_for_menu(menu_name)
