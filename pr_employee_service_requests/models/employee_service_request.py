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
            ("hr_approval", "HR Approval"),
            ("accounts_approval", "Accounts Approval"),
            ("approved", "Approved"),
            ("issued", "Issued"),
            ("paid", "Paid"),
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
        string="Approved Amount",
        currency_field="currency_id",
        tracking=True,
    )
    payment_method = fields.Selection(
        [("bank", "Bank Transfer"), ("cash", "Cash")],
        string="Payment Method",
        default="bank",
        tracking=True,
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

    can_hr_approve = fields.Boolean(compute="_compute_action_flags")
    can_accounts_approve = fields.Boolean(compute="_compute_action_flags")
    can_issue = fields.Boolean(compute="_compute_action_flags")
    can_mark_paid = fields.Boolean(compute="_compute_action_flags")
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

    @api.depends("travel_date", "return_date")
    def _compute_duration_days(self):
        for rec in self:
            if rec.travel_date and rec.return_date and rec.return_date >= rec.travel_date:
                rec.duration_days = (rec.return_date - rec.travel_date).days + 1
            else:
                rec.duration_days = 0

    @api.depends_context("uid")
    @api.depends("state", "request_type", "requested_by_id")
    def _compute_action_flags(self):
        user = self.env.user
        is_hr = (
            user.has_group("hr.group_hr_manager")
            or user.has_group("de_hr_workspace.group_hr_employee_approvals")
        )
        is_accounts = (
            user.has_group("account.group_account_manager")
            or user.has_group("pr_account.custom_group_accounting_manager")
        )
        for rec in self:
            is_owner = rec.requested_by_id == user or rec.employee_id.user_id == user
            rec.can_hr_approve = rec.state == "hr_approval" and is_hr
            rec.can_accounts_approve = (
                rec.request_type == "reimbursement"
                and rec.state == "accounts_approval"
                and is_accounts
            )
            rec.can_issue = (
                rec.request_type == "exit_reentry"
                and rec.state == "approved"
                and is_hr
            )
            rec.can_mark_paid = (
                rec.request_type == "reimbursement"
                and rec.state == "approved"
                and is_accounts
            )
            rec.can_reject = (
                rec.state in ("hr_approval", "accounts_approval", "approved")
                and (
                    (rec.state in ("hr_approval", "approved") and is_hr)
                    or (rec.state == "accounts_approval" and is_accounts)
                )
            )
            rec.can_reset_to_draft = rec.state == "rejected" and (is_owner or is_hr)
            rec.can_cancel = rec.state in ("draft", "hr_approval") and is_owner

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        for rec in self:
            if rec.employee_id:
                rec.company_id = rec.employee_id.company_id or self.env.company
                rec.passport_no = rec.employee_id.passport_id or rec.passport_no
                rec.iqama_no = rec.employee_id.identification_id or rec.iqama_no

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
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state not in ("draft", "cancelled", "rejected"):
                raise UserError(_("Only draft, cancelled, or rejected requests can be deleted."))
        return super().unlink()

    def _check_before_submit(self):
        for rec in self:
            if not rec.employee_id:
                raise UserError(_("Please select an employee."))
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
            rec.write({"state": "hr_approval", "rejection_reason": False})
            rec._notify_group(
                ["hr.group_hr_manager", "de_hr_workspace.group_hr_employee_approvals"],
                _("Employee Request Approval Needed"),
                _("%s <b>%s</b> is waiting for HR approval.") % (rec._get_type_label(), rec.display_name),
            )
            rec.message_post(body=_("Request submitted for HR approval."))

    def action_hr_approve(self):
        for rec in self:
            if not rec.can_hr_approve:
                raise UserError(_("Only HR can approve this stage."))
            if rec.request_type == "reimbursement":
                rec.write({
                    "state": "accounts_approval",
                    "approved_amount": rec.approved_amount or rec.requested_amount,
                })
                rec._notify_group(
                    ["account.group_account_manager", "pr_account.custom_group_accounting_manager"],
                    _("Employee Reimbursement Approval Needed"),
                    _("Reimbursement <b>%s</b> is waiting for Accounts approval.") % rec.display_name,
                )
            else:
                rec.write({"state": "approved"})
            rec.message_post(body=_("HR approved this request."))

    def action_accounts_approve(self):
        for rec in self:
            if not rec.can_accounts_approve:
                raise UserError(_("Only Accounts can approve reimbursement requests."))
            rec.write({
                "state": "approved",
                "approved_amount": rec.approved_amount or rec.requested_amount,
            })
            rec.message_post(body=_("Accounts approved this reimbursement."))

    def action_issue(self):
        for rec in self:
            if not rec.can_issue:
                raise UserError(_("Only HR can issue an approved exit/re-entry request."))
            if not rec.visa_number:
                raise UserError(_("Please enter the Exit/Re-entry Visa No. before issuing."))
            rec.write({"state": "issued", "issue_date": rec.issue_date or fields.Date.context_today(rec)})
            rec.message_post(body=_("Exit/Re-entry request has been issued."))

    def action_mark_paid(self):
        for rec in self:
            if not rec.can_mark_paid:
                raise UserError(_("Only Accounts can mark an approved reimbursement as paid."))
            rec.write({"state": "paid", "paid_date": rec.paid_date or fields.Date.context_today(rec)})
            rec.message_post(body=_("Reimbursement has been marked as paid."))

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

    def _get_type_label(self):
        self.ensure_one()
        return dict(self._fields["request_type"].selection).get(self.request_type, _("Request"))


class PrEmployeeServiceRequestRejectWizard(models.TransientModel):
    _name = "pr.employee.service.request.reject.wizard"
    _description = "Employee Service Request Reject Wizard"

    request_id = fields.Many2one("pr.employee.service.request", string="Request", required=True)
    rejection_reason = fields.Text(string="Rejection Reason", required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        self.request_id._set_rejected(self.rejection_reason)
        return {"type": "ir.actions.act_window_close"}


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
