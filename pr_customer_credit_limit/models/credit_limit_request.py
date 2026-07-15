from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


class CustomerCreditLimitRequest(models.Model):
    _name = "pr.customer.credit.limit.request"
    _description = "Customer Credit Limit Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        string="Reference",
        default=lambda self: _("New"),
        copy=False,
        readonly=True,
        tracking=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
        tracking=True,
        domain="[('customer_rank', '>', 0)]",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
        tracking=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        related="company_id.currency_id",
        readonly=True,
    )
    request_type = fields.Selection(
        [
            ("new", "New Facility"),
            ("increase", "Increase Limit"),
            ("decrease", "Decrease Limit"),
            ("renewal", "Renewal"),
            ("temporary", "Temporary Facility"),
        ],
        string="Request Type",
        default="new",
        required=True,
        tracking=True,
    )
    credit_facility_type = fields.Selection(
        [
            ("standard", "Standard Credit"),
            ("project", "Project Based"),
            ("temporary", "Temporary"),
            ("other", "Other"),
        ],
        string="Credit Facility",
        default="standard",
        required=True,
        tracking=True,
    )
    payment_term_id = fields.Many2one(
        "account.payment.term",
        string="Preferred Credit Term",
        domain="[('petroraq_selectable', '=', True)]",
        tracking=True,
    )
    current_limit_amount = fields.Monetary(
        string="Current Approved Limit",
        compute="_compute_current_limit_amount",
        currency_field="currency_id",
    )
    requested_limit_amount = fields.Monetary(
        string="Requested Credit Limit",
        required=True,
        currency_field="currency_id",
        tracking=True,
    )
    change_amount = fields.Monetary(
        string="Limit Change",
        compute="_compute_change_amount",
        currency_field="currency_id",
    )
    validity_start = fields.Date(string="Valid From", tracking=True)
    validity_end = fields.Date(string="Valid Until", tracking=True)
    reason = fields.Text(string="Business Justification", tracking=True)
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "pr_customer_credit_limit_request_attachment_rel",
        "request_id",
        "attachment_id",
        string="Attachments",
        help="Attach CR, bank details, customer letter, internal approval documents, or supporting analysis.",
    )
    requested_by_id = fields.Many2one(
        "res.users",
        string="Requested By",
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True,
    )
    submitted_date = fields.Datetime(string="Submitted On", readonly=True)
    sale_manager_approved_by_id = fields.Many2one("res.users", string="Sales Manager Approved By", readonly=True)
    sale_manager_approved_date = fields.Datetime(string="Sales Manager Approved On", readonly=True)
    md_approved_by_id = fields.Many2one("res.users", string="Sales MD Approved By", readonly=True)
    md_approved_date = fields.Datetime(string="Sales MD Approved On", readonly=True)
    rejected_by_id = fields.Many2one("res.users", string="Rejected By", readonly=True)
    rejected_date = fields.Datetime(string="Rejected On", readonly=True)
    rejection_reason = fields.Text(string="Rejection Reason", tracking=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("sale_manager_approval", "Sales Manager Approval"),
            ("sales_md_approval", "Sales MD Approval"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"].sudo()
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = sequence.next_by_code("pr.customer.credit.limit.request") or _("New")
        return super().create(vals_list)

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        for rec in self:
            if rec.partner_id:
                rec.partner_id = rec.partner_id.commercial_partner_id
                if not rec.requested_limit_amount:
                    rec.requested_limit_amount = rec.partner_id.pr_credit_limit_amount or 0.0

    @api.depends("partner_id", "partner_id.pr_credit_limit_amount", "partner_id.pr_credit_limit_enabled")
    def _compute_current_limit_amount(self):
        for rec in self:
            partner = rec.partner_id.commercial_partner_id if rec.partner_id else False
            rec.current_limit_amount = partner.pr_credit_limit_amount if partner and partner.pr_credit_limit_enabled else 0.0

    @api.depends("requested_limit_amount", "current_limit_amount")
    def _compute_change_amount(self):
        for rec in self:
            rec.change_amount = (rec.requested_limit_amount or 0.0) - (rec.current_limit_amount or 0.0)

    @api.constrains("requested_limit_amount", "validity_start", "validity_end")
    def _check_credit_request_values(self):
        for rec in self:
            currency = rec.currency_id or rec.env.company.currency_id
            if float_compare(
                rec.requested_limit_amount or 0.0,
                0.0,
                precision_rounding=currency.rounding,
            ) <= 0:
                raise ValidationError(_("Requested credit limit must be greater than zero."))
            if rec.validity_start and rec.validity_end and rec.validity_end < rec.validity_start:
                raise ValidationError(_("Valid Until cannot be before Valid From."))

    def _get_group_users(self, group_xml_id):
        group = self.env.ref(group_xml_id, raise_if_not_found=False)
        return group.users.filtered(lambda user: user.active) if group else self.env["res.users"]

    def _schedule_group_activity(self, group_xml_id, summary):
        activity_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        users = self._get_group_users(group_xml_id)
        if not activity_type or not users:
            return
        for rec in self:
            for user in users:
                rec.activity_schedule(
                    activity_type_id=activity_type.id,
                    user_id=user.id,
                    summary=summary,
                    note=_("Please review credit limit request %s.") % rec.name,
                )

    def _check_group(self, group_xml_id, message):
        if not self.env.user.has_group(group_xml_id):
            raise UserError(message)

    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only draft credit limit requests can be submitted."))
            rec.write({
                "partner_id": rec.partner_id.commercial_partner_id.id,
                "state": "sale_manager_approval",
                "submitted_date": fields.Datetime.now(),
            })
            rec.message_post(body=_("Credit limit request submitted for Sales Manager approval."))
        self._schedule_group_activity(
            "petroraq_sale_workflow.group_sale_approval_manager",
            _("Customer credit limit approval required"),
        )
        return True

    def action_sale_manager_approve(self):
        self._check_group(
            "petroraq_sale_workflow.group_sale_approval_manager",
            _("Only Sales Approval Managers can approve this stage."),
        )
        for rec in self:
            if rec.state != "sale_manager_approval":
                raise UserError(_("This request is not waiting for Sales Manager approval."))
            rec.write({
                "state": "sales_md_approval",
                "sale_manager_approved_by_id": self.env.user.id,
                "sale_manager_approved_date": fields.Datetime.now(),
            })
            rec.message_post(body=_("Approved by Sales Manager and sent to Sales MD."))
        self._schedule_group_activity(
            "petroraq_sale_workflow.group_sale_approval_md",
            _("Customer credit limit final approval required"),
        )
        return True

    def action_md_approve(self):
        self._check_group(
            "petroraq_sale_workflow.group_sale_approval_md",
            _("Only Sales MD approvers can approve this stage."),
        )
        for rec in self:
            if rec.state != "sales_md_approval":
                raise UserError(_("This request is not waiting for Sales MD approval."))
            partner = rec.partner_id.commercial_partner_id
            partner.with_context(pr_credit_limit_approval_write=True).write({
                "pr_credit_limit_enabled": True,
                "pr_credit_limit_amount": rec.requested_limit_amount,
                "pr_credit_limit_approved_request_id": rec.id,
            })
            rec.write({
                "state": "approved",
                "md_approved_by_id": self.env.user.id,
                "md_approved_date": fields.Datetime.now(),
            })
            rec.activity_unlink(["mail.mail_activity_data_todo"])
            rec.message_post(body=_("Credit limit approved and applied on customer %s.") % partner.display_name)
        return True

    def action_reject(self):
        for rec in self:
            if rec.state not in ("sale_manager_approval", "sales_md_approval"):
                raise UserError(_("Only requests waiting for approval can be rejected."))
            if rec.state == "sale_manager_approval":
                self._check_group(
                    "petroraq_sale_workflow.group_sale_approval_manager",
                    _("Only Sales Approval Managers can reject this request."),
                )
            else:
                self._check_group(
                    "petroraq_sale_workflow.group_sale_approval_md",
                    _("Only Sales MD approvers can reject this request."),
                )
            rec.write({
                "state": "rejected",
                "rejected_by_id": self.env.user.id,
                "rejected_date": fields.Datetime.now(),
            })
            rec.activity_unlink(["mail.mail_activity_data_todo"])
            rec.message_post(body=_("Credit limit request rejected."))
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state in ("approved", "cancelled"):
                raise UserError(_("Approved or cancelled credit limit requests cannot be cancelled."))
            rec.write({"state": "cancelled"})
            rec.activity_unlink(["mail.mail_activity_data_todo"])
        return True

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ("rejected", "cancelled"):
                raise UserError(_("Only rejected or cancelled credit limit requests can be reset to draft."))
            rec.write({
                "state": "draft",
                "rejected_by_id": False,
                "rejected_date": False,
                "rejection_reason": False,
            })
        return True
