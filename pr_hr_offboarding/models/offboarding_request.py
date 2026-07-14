from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


HR_SUPERVISOR_GROUP = "pr_hr_recruitment_request.group_onboarding_supervisor"
WORKFLOW_CONTROLLED_FIELDS = {
    "name",
    "requested_by_id",
    "state",
    "submitted_by_id",
    "submitted_date",
    "approved_by_id",
    "approved_date",
    "rejected_by_id",
    "rejected_date",
    "rejection_reason",
}


class PrHrOffboardingRequest(models.Model):
    _name = "pr.hr.offboarding.request"
    _description = "Termination / Resignation Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(
        string="Request Number",
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _("New"),
        tracking=True,
    )
    request_type = fields.Selection(
        [
            ("termination", "Termination"),
            ("resignation", "Resignation"),
        ],
        string="Request Type",
        required=True,
        default="resignation",
        tracking=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,
        tracking=True,
    )
    requested_by_id = fields.Many2one(
        "res.users",
        string="Created By",
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: self.env.user,
        tracking=True,
    )
    request_date = fields.Date(
        string="Request Date",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    last_working_date = fields.Date(
        string="Proposed Last Working Date",
        required=True,
        tracking=True,
    )
    request_reason = fields.Text(
        string="Reason / Details",
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        related="employee_id.company_id",
        store=True,
        readonly=True,
    )
    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        related="employee_id.department_id",
        store=True,
        readonly=True,
    )
    job_id = fields.Many2one(
        "hr.job",
        string="Job Position",
        related="employee_id.job_id",
        store=True,
        readonly=True,
    )
    department_manager_id = fields.Many2one(
        "hr.employee",
        string="Department Manager",
        compute="_compute_department_manager",
        store=True,
        readonly=True,
    )
    department_manager_user_id = fields.Many2one(
        "res.users",
        string="Department Manager User",
        compute="_compute_department_manager",
        store=True,
        readonly=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("accepted", "Accepted"),
            ("rejected", "Rejected"),
        ],
        string="Status",
        required=True,
        default="draft",
        readonly=True,
        copy=False,
        tracking=True,
    )
    submitted_by_id = fields.Many2one(
        "res.users",
        string="Submitted By",
        readonly=True,
        copy=False,
    )
    submitted_date = fields.Datetime(
        string="Submitted On",
        readonly=True,
        copy=False,
    )
    approved_by_id = fields.Many2one(
        "res.users",
        string="Accepted By",
        readonly=True,
        copy=False,
    )
    approved_date = fields.Datetime(
        string="Accepted On",
        readonly=True,
        copy=False,
    )
    rejected_by_id = fields.Many2one(
        "res.users",
        string="Rejected By",
        readonly=True,
        copy=False,
    )
    rejected_date = fields.Datetime(
        string="Rejected On",
        readonly=True,
        copy=False,
    )
    rejection_reason = fields.Text(
        string="Rejection Reason",
        readonly=True,
        copy=False,
        tracking=True,
    )
    is_hr_supervisor = fields.Boolean(compute="_compute_user_permissions")
    is_department_manager = fields.Boolean(compute="_compute_user_permissions")

    @api.depends(
        "employee_id",
        "employee_id.department_id",
        "employee_id.department_id.manager_id",
        "employee_id.department_id.manager_id.user_id",
    )
    def _compute_department_manager(self):
        for request in self:
            manager = request.employee_id.department_id.manager_id
            request.department_manager_id = manager
            request.department_manager_user_id = manager.user_id

    @api.depends("department_manager_user_id")
    @api.depends_context("uid")
    def _compute_user_permissions(self):
        is_hr_supervisor = self.env.user.has_group(HR_SUPERVISOR_GROUP)
        for request in self:
            request.is_hr_supervisor = is_hr_supervisor
            request.is_department_manager = (
                request.department_manager_user_id == self.env.user
            )

    def _current_user_can_manage(self):
        return self.env.su or self.env.user.has_group(
            HR_SUPERVISOR_GROUP
        ) or self.env.user.has_group("base.group_system")

    def _check_hr_supervisor(self):
        if not self._current_user_can_manage():
            raise AccessError(
                _("Only an HR Supervisor can perform this action.")
            )

    def _check_department_manager(self):
        self.ensure_one()
        if self.department_manager_user_id != self.env.user:
            raise AccessError(
                _(
                    "Only the employee's department manager can approve or "
                    "reject this request."
                )
            )

    @api.model_create_multi
    def create(self, vals_list):
        if not self._current_user_can_manage():
            raise AccessError(
                _("Only an HR Supervisor can create offboarding requests.")
            )
        prepared_vals_list = []
        for incoming_vals in vals_list:
            vals = dict(incoming_vals)
            vals.update(
                {
                    "name": self.env["ir.sequence"].next_by_code(
                        "pr.hr.offboarding.request"
                    )
                    or _("New"),
                    "requested_by_id": self.env.user.id,
                    "state": "draft",
                    "submitted_by_id": False,
                    "submitted_date": False,
                    "approved_by_id": False,
                    "approved_date": False,
                    "rejected_by_id": False,
                    "rejected_date": False,
                    "rejection_reason": False,
                }
            )
            prepared_vals_list.append(vals)
        return super().create(prepared_vals_list)

    def write(self, vals):
        if not self.env.su:
            if WORKFLOW_CONTROLLED_FIELDS.intersection(vals):
                raise AccessError(
                    _(
                        "Workflow and audit fields can only be changed using "
                        "the request actions."
                    )
                )
            if not self._current_user_can_manage():
                raise AccessError(
                    _("Only an HR Supervisor can edit offboarding requests.")
                )
            if any(request.state != "draft" for request in self):
                raise UserError(
                    _("Only draft offboarding requests can be edited.")
                )
        return super().write(vals)

    def unlink(self):
        self._check_hr_supervisor()
        if any(request.state != "draft" for request in self):
            raise UserError(
                _("Only draft offboarding requests can be deleted.")
            )
        return super().unlink()

    def action_submit(self):
        self._check_hr_supervisor()
        for request in self:
            if request.state != "draft":
                raise UserError(_("Only a draft request can be submitted."))
            if not request.department_id:
                raise UserError(
                    _("The selected employee must have a department.")
                )
            if not request.department_manager_id:
                raise UserError(
                    _("The employee's department must have a manager.")
                )
            if not request.department_manager_user_id:
                raise UserError(
                    _(
                        "The department manager must be linked to a user before "
                        "the request can be submitted."
                    )
                )
            request.sudo().write(
                {
                    "state": "submitted",
                    "submitted_by_id": self.env.user.id,
                    "submitted_date": fields.Datetime.now(),
                    "approved_by_id": False,
                    "approved_date": False,
                    "rejected_by_id": False,
                    "rejected_date": False,
                    "rejection_reason": False,
                }
            )
            request.message_post(
                body=_(
                    "Offboarding request submitted to %s for department "
                    "manager approval."
                )
                % request.department_manager_id.display_name
            )
        return True

    def action_accept(self):
        for request in self:
            request._check_department_manager()
            if request.state != "submitted":
                raise UserError(
                    _("Only a submitted request can be accepted.")
                )
            request.sudo().write(
                {
                    "state": "accepted",
                    "approved_by_id": self.env.user.id,
                    "approved_date": fields.Datetime.now(),
                    "rejected_by_id": False,
                    "rejected_date": False,
                    "rejection_reason": False,
                }
            )
            request.message_post(
                body=_("Offboarding request accepted by the department manager.")
            )
        return True

    def action_open_reject_wizard(self):
        self.ensure_one()
        self._check_department_manager()
        if self.state != "submitted":
            raise UserError(
                _("Only a submitted request can be rejected.")
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Reject Offboarding Request"),
            "res_model": "pr.hr.offboarding.reject.wizard",
            "view_mode": "form",
            "view_id": self.env.ref(
                "pr_hr_offboarding.view_offboarding_reject_wizard_form"
            ).id,
            "target": "new",
            "context": {
                "default_request_id": self.id,
            },
        }

    def _action_reject(self, reason):
        self.ensure_one()
        self._check_department_manager()
        if self.state != "submitted":
            raise UserError(
                _("Only a submitted request can be rejected.")
            )
        reason = (reason or "").strip()
        if not reason:
            raise UserError(_("A rejection reason is required."))
        self.sudo().write(
            {
                "state": "rejected",
                "rejected_by_id": self.env.user.id,
                "rejected_date": fields.Datetime.now(),
                "rejection_reason": reason,
                "approved_by_id": False,
                "approved_date": False,
            }
        )
        self.message_post(
            body=_("Offboarding request rejected. Reason: %s") % reason
        )
        return True

    def action_reset_to_draft(self):
        self._check_hr_supervisor()
        for request in self:
            if request.state != "rejected":
                raise UserError(
                    _("Only a rejected request can be reset to draft.")
                )
            request.sudo().write(
                {
                    "state": "draft",
                    "submitted_by_id": False,
                    "submitted_date": False,
                    "approved_by_id": False,
                    "approved_date": False,
                    "rejected_by_id": False,
                    "rejected_date": False,
                    "rejection_reason": False,
                }
            )
            request.message_post(body=_("Offboarding request reset to draft."))
        return True
