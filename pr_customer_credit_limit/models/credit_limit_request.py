from odoo import Command, _, api, fields, models
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
            ("migration", "Opening / Migrated Facility"),
            ("revision", "Revise Facility"),
            ("renewal", "Renewal"),
            ("reset", "Reset / Close Facility"),
        ],
        string="Request Type",
        default="new",
        required=True,
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
    term_line_ids = fields.One2many(
        "pr.customer.credit.request.term",
        "request_id",
        string="Payment-Term Allocations",
        copy=True,
    )
    allocated_limit_amount = fields.Monetary(
        string="Total Allocated",
        compute="_compute_allocated_limit_amount",
        currency_field="currency_id",
    )
    unallocated_limit_amount = fields.Monetary(
        string="Unallocated",
        compute="_compute_allocated_limit_amount",
        currency_field="currency_id",
    )
    change_amount = fields.Monetary(
        string="Limit Change",
        compute="_compute_change_amount",
        currency_field="currency_id",
    )
    validity_start = fields.Date(string="Valid From", tracking=True)
    validity_end = fields.Date(string="Valid Until", tracking=True)
    reason = fields.Text(string="Business Justification", tracking=True)
    document_line_ids = fields.One2many(
        "pr.customer.credit.request.document",
        "request_id",
        string="Registration Documents",
        copy=True,
    )
    missing_required_document_count = fields.Integer(compute="_compute_document_compliance")
    requested_by_id = fields.Many2one(
        "res.users",
        string="Requested By",
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True,
    )
    submitted_date = fields.Datetime(string="Submitted On", readonly=True)
    migrated_by_id = fields.Many2one(
        "res.users",
        string="Opening Data Entered By",
        readonly=True,
    )
    migrated_date = fields.Datetime(string="Opening Data Entered On", readonly=True)
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
        requests = super().create(vals_list)
        requests._sync_document_requirements()
        return requests

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if "document_line_ids" in fields_list and not values.get("document_line_ids"):
            company_id = values.get("company_id") or self.env.company.id
            document_types = self.env["pr.customer.credit.document.type"].search([
                ("active", "=", True),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", company_id),
            ])
            values["document_line_ids"] = [
                Command.create({
                    "document_type_id": document_type.id,
                    "required": document_type.required,
                })
                for document_type in document_types
            ]
        return values

    def write(self, vals):
        draft_only_fields = {
            "partner_id",
            "company_id",
            "request_type",
            "requested_limit_amount",
            "validity_start",
            "validity_end",
            "reason",
            "term_line_ids",
            "document_line_ids",
        }
        if draft_only_fields.intersection(vals) and any(rec.state != "draft" for rec in self):
            raise UserError(_("Credit facility details can only be changed while the request is in Draft."))
        return super().write(vals)

    def _get_applicable_document_types(self):
        self.ensure_one()
        return self.env["pr.customer.credit.document.type"].search([
            ("active", "=", True),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", self.company_id.id),
        ])

    def _sync_document_requirements(self):
        DocumentLine = self.env["pr.customer.credit.request.document"]
        for rec in self:
            existing_by_type = {
                line.document_type_id: line for line in rec.document_line_ids
            }
            for document_type, line in existing_by_type.items():
                if rec.state == "draft" and line.required != document_type.required:
                    line.required = document_type.required
            existing = self.env["pr.customer.credit.document.type"].browse(
                [document_type.id for document_type in existing_by_type]
            )
            for document_type in rec._get_applicable_document_types() - existing:
                previous = DocumentLine.search([
                    ("request_id", "!=", rec.id),
                    ("request_id.partner_id", "=", rec.partner_id.commercial_partner_id.id),
                    ("document_type_id", "=", document_type.id),
                    ("attachment_ids", "!=", False),
                ], order="request_id desc, id desc", limit=1)
                DocumentLine.create({
                    "request_id": rec.id,
                    "document_type_id": document_type.id,
                    "required": document_type.required,
                    "attachment_ids": [(6, 0, previous.attachment_ids.ids)] if previous else False,
                })
        return True

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        for rec in self:
            if rec.partner_id:
                rec.partner_id = rec.partner_id.commercial_partner_id
                if not rec.requested_limit_amount:
                    rec.requested_limit_amount = rec.partner_id.pr_credit_limit_amount or 0.0

    @api.depends("term_line_ids.limit_amount", "requested_limit_amount")
    def _compute_allocated_limit_amount(self):
        for rec in self:
            allocated = sum(rec.term_line_ids.mapped("limit_amount"))
            rec.allocated_limit_amount = allocated
            rec.unallocated_limit_amount = (rec.requested_limit_amount or 0.0) - allocated

    @api.depends(
        "document_line_ids.required",
        "document_line_ids.fulfilled",
        "document_line_ids.attachment_ids",
    )
    def _compute_document_compliance(self):
        for rec in self:
            required_lines = rec.document_line_ids.filtered("required")
            missing = required_lines.filtered(lambda line: not line.fulfilled)
            rec.missing_required_document_count = len(missing)

    @api.depends("partner_id", "partner_id.pr_credit_limit_amount", "partner_id.pr_credit_limit_enabled")
    def _compute_current_limit_amount(self):
        for rec in self:
            partner = rec.partner_id.commercial_partner_id if rec.partner_id else False
            rec.current_limit_amount = partner.pr_credit_limit_amount if partner and partner.pr_credit_limit_enabled else 0.0

    @api.depends("requested_limit_amount", "current_limit_amount")
    def _compute_change_amount(self):
        for rec in self:
            rec.change_amount = (rec.requested_limit_amount or 0.0) - (rec.current_limit_amount or 0.0)

    @api.constrains(
        "requested_limit_amount",
        "term_line_ids",
        "term_line_ids.limit_amount",
        "validity_start",
        "validity_end",
        "request_type",
    )
    def _check_credit_request_values(self):
        for rec in self:
            currency = rec.currency_id or rec.env.company.currency_id
            amount_comparison = float_compare(
                rec.requested_limit_amount or 0.0,
                0.0,
                precision_rounding=currency.rounding,
            )
            if rec.request_type == "reset":
                if amount_comparison != 0 or rec.term_line_ids:
                    raise ValidationError(
                        _("A Reset / Close Facility request must have a zero total and no term allocations.")
                    )
            elif amount_comparison <= 0:
                raise ValidationError(_("Requested credit limit must be greater than zero."))
            if rec.validity_start and rec.validity_end and rec.validity_end < rec.validity_start:
                raise ValidationError(_("Valid Until cannot be before Valid From."))

    def _check_ready_for_submission(self, check_documents=True):
        for rec in self:
            if check_documents:
                rec._sync_document_requirements()
                missing = rec.document_line_ids.filtered(
                    lambda line: line.required and not line.fulfilled
                )
                if missing:
                    raise ValidationError(
                        _("Upload the following required registration documents before submission:\n- %s")
                        % "\n- ".join(missing.mapped("document_type_id.name"))
                    )
            if rec.request_type != "reset":
                if not rec.term_line_ids:
                    raise ValidationError(
                        _("Add at least one payment-term allocation before submission.")
                    )
                currency = rec.currency_id
                if float_compare(
                    rec.allocated_limit_amount,
                    rec.requested_limit_amount,
                    precision_rounding=currency.rounding,
                ) != 0:
                    raise ValidationError(
                        _(
                            "Payment-term allocations must equal the requested customer limit.\n"
                            "Requested: %(requested).2f\nAllocated: %(allocated).2f"
                        )
                        % {
                            "requested": rec.requested_limit_amount,
                            "allocated": rec.allocated_limit_amount,
                        }
                    )

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
        if not (
            self.env.user.has_group(group_xml_id)
            or self.env.user.has_group("base.group_system")
        ):
            raise UserError(message)

    def _assign_reference(self):
        for rec in self:
            if not rec.name or rec.name == _("New"):
                rec.name = (
                    self.env["ir.sequence"].sudo().next_by_code(
                        "pr.customer.credit.limit.request"
                    )
                    or _("New")
                )

    def _apply_facility_to_customer(self):
        for rec in self:
            partner = rec.partner_id.commercial_partner_id
            approved_lines = self.env["pr.customer.credit.term.limit"].sudo()
            approved_lines.search([
                ("partner_id", "=", partner.id),
                ("company_id", "=", rec.company_id.id),
            ]).unlink()
            if rec.request_type != "reset":
                approved_lines.create([
                    {
                        "partner_id": partner.id,
                        "company_id": rec.company_id.id,
                        "payment_term_id": line.payment_term_id.id,
                        "limit_amount": line.limit_amount,
                        "approved_request_id": rec.id,
                        "validity_start": rec.validity_start,
                        "validity_end": rec.validity_end,
                    }
                    for line in rec.term_line_ids
                ])
            partner.with_context(pr_credit_limit_approval_write=True).write({
                "pr_credit_limit_enabled": rec.request_type != "reset",
                "pr_credit_limit_amount": rec.requested_limit_amount,
                "pr_credit_limit_approved_request_id": rec.id,
            })

    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only draft credit limit requests can be submitted."))
            if rec.request_type == "migration":
                raise UserError(
                    _(
                        "Use Activate Opening Facility for a migrated facility; "
                        "it does not follow the approval workflow."
                    )
                )
        self._check_ready_for_submission()
        for rec in self:
            rec._assign_reference()
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

    def unlink(self):
        protected = self.filtered(lambda rec: rec.state not in ("draft", "cancelled"))
        if protected:
            raise UserError(
                _("Submitted credit facility requests cannot be deleted because they are part of the approval audit trail.")
            )
        return super().unlink()

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
            rec._apply_facility_to_customer()
            rec.write({
                "state": "approved",
                "md_approved_by_id": self.env.user.id,
                "md_approved_date": fields.Datetime.now(),
            })
            rec.activity_unlink(["mail.mail_activity_data_todo"])
            if rec.request_type == "reset":
                message = _("Credit facility closed and all active payment-term limits removed for %s.")
            else:
                message = _("Credit facility approved and payment-term limits applied on customer %s.")
            rec.message_post(body=message % partner.display_name)
        return True

    def action_activate_migrated_facility(self):
        self._check_group(
            "petroraq_sale_workflow.group_sale_approval_md",
            _("Only Sales MD or system administrators can activate opening credit data."),
        )
        for rec in self:
            if rec.state != "draft" or rec.request_type != "migration":
                raise UserError(
                    _("Only draft Opening / Migrated Facility records can be activated directly.")
                )
        self._check_ready_for_submission(check_documents=False)
        now = fields.Datetime.now()
        for rec in self:
            rec._assign_reference()
            rec.write({
                "partner_id": rec.partner_id.commercial_partner_id.id,
                "state": "approved",
                "submitted_date": now,
                "migrated_by_id": self.env.user.id,
                "migrated_date": now,
            })
            rec._apply_facility_to_customer()
            rec.message_post(
                body=_(
                    "Opening credit facility entered directly from an externally approved "
                    "legacy facility by %s. No approval workflow was applied."
                )
                % self.env.user.display_name
            )
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
