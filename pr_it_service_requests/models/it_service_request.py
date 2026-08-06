from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from markupsafe import Markup, escape


class PrItServiceRequest(models.Model):
    _name = "pr.it.service.request"
    _description = "IT Service Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(
        string="Request Number", default=lambda self: _("New"), readonly=True, copy=False, tracking=True
    )
    title = fields.Char(required=True, tracking=True)
    request_type_id = fields.Many2one(
        "pr.it.request.type", string="Request Type", required=True, tracking=True, ondelete="restrict"
    )
    requested_by_id = fields.Many2one(
        "res.users", default=lambda self: self.env.user, required=True, readonly=True, tracking=True
    )
    employee_id = fields.Many2one(
        "hr.employee", default=lambda self: self._default_employee(), required=True, tracking=True
    )
    department_id = fields.Many2one(
        "hr.department", related="employee_id.department_id", store=True, readonly=True
    )
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, required=True, tracking=True
    )
    request_date = fields.Date(default=fields.Date.context_today, required=True, tracking=True)
    required_date = fields.Date(string="Required By", tracking=True)
    priority = fields.Selection(
        [("0", "Low"), ("1", "Normal"), ("2", "High"), ("3", "Urgent")],
        default="1",
        required=True,
        tracking=True,
    )
    description = fields.Html(required=True, sanitize=True, tracking=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending", "Pending Approval"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        readonly=True,
        copy=False,
        tracking=True,
    )
    approver_line_ids = fields.One2many(
        "pr.it.service.request.approver", "request_id", string="Approval Sequence", copy=True
    )
    current_approver_id = fields.Many2one(
        "res.users", compute="_compute_approval_summary", store=True, string="Current Approver"
    )
    approval_progress = fields.Char(compute="_compute_approval_summary", store=True)
    rejection_reason = fields.Text(readonly=True, copy=False, tracking=True)
    rejected_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    rejected_at = fields.Datetime(readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False, tracking=True)
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "pr_it_service_request_attachment_rel",
        "request_id",
        "attachment_id",
        string="Supporting Files",
        copy=False,
    )
    is_current_approver = fields.Boolean(
        compute="_compute_is_current_approver", search="_search_is_current_approver"
    )
    can_approve = fields.Boolean(compute="_compute_action_flags")
    can_reject = fields.Boolean(compute="_compute_action_flags")
    can_reset_to_draft = fields.Boolean(compute="_compute_action_flags")

    _editable_fields = {
        "title", "request_type_id", "employee_id", "company_id", "request_date",
        "required_date", "priority", "description", "approver_line_ids", "attachment_ids",
    }

    @api.model
    def _default_employee(self):
        return self.env["hr.employee"].search(
            [("user_id", "=", self.env.user.id), ("active", "=", True)], limit=1
        )

    @api.depends("state", "approver_line_ids.status", "approver_line_ids.sequence", "approver_line_ids.approver_id")
    def _compute_approval_summary(self):
        for rec in self:
            lines = rec.approver_line_ids.sorted(lambda line: (line.sequence, line.id))
            approved = len(lines.filtered(lambda line: line.status == "approved"))
            rec.approval_progress = _("%(approved)s of %(total)s approved", approved=approved, total=len(lines))
            current = lines.filtered(lambda line: line.status == "pending")[:1] if rec.state == "pending" else False
            rec.current_approver_id = current.approver_id if current else False

    @api.depends("current_approver_id", "state")
    def _compute_is_current_approver(self):
        for rec in self:
            rec.is_current_approver = rec.state == "pending" and rec.current_approver_id == self.env.user

    @api.model
    def _search_is_current_approver(self, operator, value):
        if operator not in ("=", "!="):
            raise NotImplementedError("Current approver search only supports '=' and '!='.")
        domain = [("state", "=", "pending"), ("current_approver_id", "=", self.env.user.id)]
        positive = (operator == "=" and bool(value)) or (operator == "!=" and not bool(value))
        return domain if positive else [
            "|", ("state", "!=", "pending"), ("current_approver_id", "!=", self.env.user.id)
        ]

    @api.depends("state", "current_approver_id")
    def _compute_action_flags(self):
        is_manager = self.env.user.has_group("pr_it_service_requests.group_it_service_manager")
        for rec in self:
            current = rec.state == "pending" and rec.current_approver_id == self.env.user
            rec.can_approve = current
            rec.can_reject = current
            rec.can_reset_to_draft = is_manager and rec.state in ("rejected", "cancelled")

    @api.onchange("request_type_id")
    def _onchange_request_type_id(self):
        for rec in self:
            rec.approver_line_ids = [(5, 0, 0)] + [
                (0, 0, {"sequence": line.sequence, "approver_id": line.approver_id.id})
                for line in rec.request_type_id.default_approver_line_ids.sorted("sequence")
            ]

    @api.constrains("required_date", "request_date")
    def _check_required_date(self):
        for rec in self:
            if rec.required_date and rec.request_date and rec.required_date < rec.request_date:
                raise ValidationError(_("Required By cannot be earlier than the request date."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("pr.it.service.request") or _("New")
            requested_by_id = vals.get("requested_by_id")
            if (
                requested_by_id
                and requested_by_id != self.env.user.id
                and not self.env.user.has_group("pr_it_service_requests.group_it_service_manager")
            ):
                raise AccessError(_("You cannot create an IT service request on behalf of another user."))
            vals.setdefault("requested_by_id", self.env.user.id)
            if "approver_line_ids" not in vals and vals.get("request_type_id"):
                request_type = self.env["pr.it.request.type"].browse(vals["request_type_id"])
                vals["approver_line_ids"] = [
                    (0, 0, {"sequence": line.sequence, "approver_id": line.approver_id.id})
                    for line in request_type.default_approver_line_ids.sorted("sequence")
                ]
        return super().create(vals_list)

    def write(self, vals):
        workflow_write = self.env.context.get("it_request_workflow_write")
        if "state" in vals and not workflow_write:
            raise AccessError(_("Use the workflow buttons to change an IT request status."))
        if self._editable_fields.intersection(vals) and not workflow_write:
            locked = self.filtered(lambda rec: rec.state != "draft")
            if locked:
                raise UserError(_("Only draft IT service requests can be edited."))
        return super().write(vals)

    def unlink(self):
        if any(rec.state != "draft" for rec in self):
            raise UserError(_("Only draft IT service requests can be deleted."))
        return super().unlink()

    def _validate_approval_chain(self):
        for rec in self:
            lines = rec.approver_line_ids.sorted("sequence")
            if not lines:
                raise ValidationError(_("Add at least one approver before submitting the request."))
            if rec.requested_by_id in lines.mapped("approver_id"):
                raise ValidationError(_("The requester cannot approve their own IT service request."))
            if any(line.approver_id.share or not line.approver_id.active for line in lines):
                raise ValidationError(_("All approvers must be active internal users."))

    def _schedule_current_approver(self):
        approval_activity_type = self.env.ref(
            "pr_it_service_requests.mail_activity_type_it_service_approval"
        )
        for rec in self.filtered(lambda item: item.state == "pending" and item.current_approver_id):
            existing = rec.activity_ids.filtered(
                lambda activity: activity.user_id == rec.current_approver_id
                and activity.activity_type_id == approval_activity_type
            )
            if not existing:
                rec.activity_schedule(
                    "pr_it_service_requests.mail_activity_type_it_service_approval",
                    user_id=rec.current_approver_id.id,
                    summary=_("Approve IT Service Request %(request)s", request=rec.name),
                    note=_("Your approval is required for %(title)s.", title=rec.title),
                )

    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only draft requests can be submitted."))
            if rec.requested_by_id != self.env.user and not self.env.user.has_group(
                "pr_it_service_requests.group_it_service_manager"
            ):
                raise AccessError(_("Only the requester or an IT Service Manager can submit this request."))
            rec._validate_approval_chain()
            lines = rec.approver_line_ids.sorted("sequence")
            lines.with_context(it_request_workflow_write=True).write({
                "status": "waiting", "action_date": False, "remarks": False
            })
            lines[:1].with_context(it_request_workflow_write=True).write({"status": "pending"})
            rec.with_context(it_request_workflow_write=True).write({
                "state": "pending", "rejection_reason": False,
                "rejected_by_id": False, "rejected_at": False, "approved_at": False,
            })
            rec.message_subscribe(partner_ids=lines.mapped("approver_id.partner_id").ids)
            rec.message_post(body=_("IT service request submitted for sequential approval."))
            rec._schedule_current_approver()
        return True

    def _ensure_current_approver(self):
        self.ensure_one()
        if self.state != "pending" or self.current_approver_id != self.env.user:
            raise AccessError(_("Only the current approver can process this request."))

    def action_approve(self):
        for rec in self:
            rec._ensure_current_approver()
            line = rec.approver_line_ids.filtered(
                lambda item: item.status == "pending" and item.approver_id == self.env.user
            ).sorted("sequence")[:1]
            if not line:
                raise UserError(_("No pending approval step was found for your user."))
            line.with_context(it_request_workflow_write=True).write({
                "status": "approved", "action_date": fields.Datetime.now()
            })
            approval_activity_type = self.env.ref(
                "pr_it_service_requests.mail_activity_type_it_service_approval"
            )
            rec.activity_ids.filtered(
                lambda activity: activity.user_id == self.env.user
                and activity.activity_type_id == approval_activity_type
            ).action_done()
            next_line = rec.approver_line_ids.filtered(lambda item: item.status == "pending").sorted("sequence")[:1]
            if not next_line:
                next_line = rec.approver_line_ids.filtered(lambda item: item.status == "waiting").sorted("sequence")[:1]
            if next_line:
                next_line.with_context(it_request_workflow_write=True).write({"status": "pending"})
                rec.message_post(body=_("Approved by %(approver)s. Sent to %(next)s.", approver=self.env.user.name, next=next_line.approver_id.name))
                rec._schedule_current_approver()
            else:
                rec.with_context(it_request_workflow_write=True).write({
                    "state": "approved", "approved_at": fields.Datetime.now()
                })
                rec.message_post(body=_("IT service request fully approved."))
        return True

    def action_open_reject_wizard(self):
        self.ensure_one()
        self._ensure_current_approver()
        return {
            "type": "ir.actions.act_window",
            "name": _("Reject IT Service Request"),
            "res_model": "pr.it.service.request.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_request_id": self.id},
        }

    def _action_reject(self, reason):
        self.ensure_one()
        self._ensure_current_approver()
        reason = (reason or "").strip()
        if not reason:
            raise ValidationError(_("A rejection reason is required."))
        current_line = self.approver_line_ids.filtered(
            lambda line: line.status == "pending" and line.approver_id == self.env.user
        ).sorted("sequence")[:1]
        current_line.with_context(it_request_workflow_write=True).write({
            "status": "rejected", "action_date": fields.Datetime.now(), "remarks": reason
        })
        self.approver_line_ids.filtered(
            lambda line: line.status == "pending" and line != current_line
        ).with_context(it_request_workflow_write=True).write({"status": "waiting"})
        approval_activity_type = self.env.ref(
            "pr_it_service_requests.mail_activity_type_it_service_approval"
        )
        self.activity_ids.filtered(
            lambda activity: activity.activity_type_id == approval_activity_type
        ).action_done()
        self.with_context(it_request_workflow_write=True).write({
            "state": "rejected", "rejection_reason": reason,
            "rejected_by_id": self.env.user.id, "rejected_at": fields.Datetime.now(),
        })
        self.message_post(body=Markup("<p><strong>{title}</strong></p><p>{reason}</p>").format(
            title=escape(_("Rejected by %(approver)s", approver=self.env.user.name)),
            reason=escape(reason),
        ))
        return True

    def action_reset_to_draft(self):
        if not self.env.user.has_group("pr_it_service_requests.group_it_service_manager"):
            raise AccessError(_("Only an IT Service Manager can reset requests to draft."))
        for rec in self:
            if rec.state not in ("rejected", "cancelled"):
                raise UserError(_("Only rejected or cancelled requests can be reset to draft."))
            approval_activity_type = self.env.ref(
                "pr_it_service_requests.mail_activity_type_it_service_approval"
            )
            rec.activity_ids.filtered(
                lambda activity: activity.activity_type_id == approval_activity_type
            ).action_done()
            rec.approver_line_ids.with_context(it_request_workflow_write=True).write({
                "status": "waiting", "action_date": False, "remarks": False
            })
            rec.with_context(it_request_workflow_write=True).write({
                "state": "draft", "rejection_reason": False,
                "rejected_by_id": False, "rejected_at": False, "approved_at": False,
            })
            rec.message_post(body=_("IT service request reset to draft by %(user)s.", user=self.env.user.name))
        return True

    def action_cancel(self):
        for rec in self:
            allowed = rec.requested_by_id == self.env.user or self.env.user.has_group(
                "pr_it_service_requests.group_it_service_manager"
            )
            if not allowed or rec.state not in ("draft", "pending"):
                raise AccessError(_("You cannot cancel this IT service request."))
            approval_activity_type = self.env.ref(
                "pr_it_service_requests.mail_activity_type_it_service_approval"
            )
            rec.activity_ids.filtered(
                lambda activity: activity.activity_type_id == approval_activity_type
            ).action_done()
            rec.approver_line_ids.filtered(lambda line: line.status == "pending").with_context(
                it_request_workflow_write=True
            ).write({"status": "waiting"})
            rec.with_context(it_request_workflow_write=True).write({"state": "cancelled"})
            rec.message_post(body=_("IT service request cancelled by %(user)s.", user=self.env.user.name))
        return True


class PrItServiceRequestApprover(models.Model):
    _name = "pr.it.service.request.approver"
    _description = "IT Service Request Approver"
    _order = "sequence, id"

    request_id = fields.Many2one("pr.it.service.request", required=True, ondelete="cascade")
    sequence = fields.Integer(string="Approval Order", required=True, default=10)
    approver_id = fields.Many2one(
        "res.users", required=True, domain="[('share', '=', False), ('active', '=', True)]"
    )
    status = fields.Selection(
        [("waiting", "Waiting"), ("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="waiting", required=True, readonly=True, copy=False
    )
    action_date = fields.Datetime(readonly=True, copy=False)
    remarks = fields.Text(readonly=True, copy=False)

    _sql_constraints = [
        ("it_request_approver_sequence_unique", "unique(request_id, sequence)", "Each approval step must have a unique sequence."),
        ("it_request_approver_user_unique", "unique(request_id, approver_id)", "An approver can only appear once in a request."),
    ]

    @api.constrains("sequence", "approver_id", "request_id")
    def _check_approval_line(self):
        for line in self:
            if line.sequence <= 0:
                raise ValidationError(_("Approval sequence must be greater than zero."))
            if line.request_id.requested_by_id == line.approver_id:
                raise ValidationError(_("The requester cannot be an approver on their own request."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            request_record = self.env["pr.it.service.request"].browse(vals.get("request_id"))
            if request_record and request_record.state != "draft" and not self.env.context.get("it_request_workflow_write"):
                raise UserError(_("Approvers can only be changed while the request is in draft."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get("it_request_workflow_write") and any(line.request_id.state != "draft" for line in self):
            raise UserError(_("Approvers can only be changed while the request is in draft."))
        if {"status", "action_date", "remarks"}.intersection(vals) and not self.env.context.get("it_request_workflow_write"):
            raise AccessError(_("Approval results can only be changed through workflow actions."))
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get("it_request_workflow_write") and any(line.request_id.state != "draft" for line in self):
            raise UserError(_("Approvers can only be changed while the request is in draft."))
        return super().unlink()
