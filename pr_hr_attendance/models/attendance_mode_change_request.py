from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


ATTENDANCE_ENTRY_MODES = [
    ("automated", "Automated Attendance"),
    ("manual", "Manual / Site Attendance"),
]


class AttendanceModeChangeRequest(models.Model):
    _name = "hr.attendance.mode.change.request"
    _description = "Attendance Mode Change Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "request_date desc, id desc"

    @api.model
    def _default_current_mode(self):
        employee_id = self.env.context.get("default_employee_id")
        employee = self.env["hr.employee"].browse(employee_id).exists()
        return employee.attendance_entry_mode if len(employee) == 1 else False

    name = fields.Char(
        string="Reference",
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _("New"),
    )
    employee_id = fields.Many2one(
        "hr.employee",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        related="employee_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    current_mode = fields.Selection(
        ATTENDANCE_ENTRY_MODES,
        required=True,
        readonly=True,
        tracking=True,
        default=lambda self: self._default_current_mode(),
    )
    requested_mode = fields.Selection(
        ATTENDANCE_ENTRY_MODES,
        required=True,
        tracking=True,
    )
    reason = fields.Text(required=True, tracking=True)
    state = fields.Selection(
        [
            ("pending", "Pending MD Approval"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="pending",
        readonly=True,
        copy=False,
        tracking=True,
        index=True,
    )
    requested_by_id = fields.Many2one(
        "res.users",
        required=True,
        readonly=True,
        default=lambda self: self.env.user,
        copy=False,
        tracking=True,
    )
    request_date = fields.Datetime(
        required=True,
        readonly=True,
        default=fields.Datetime.now,
        copy=False,
    )
    decision_by_id = fields.Many2one(
        "res.users", readonly=True, copy=False, tracking=True
    )
    decision_date = fields.Datetime(readonly=True, copy=False, tracking=True)

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        for request in self:
            request.current_mode = (
                request.employee_id.attendance_entry_mode
                if request.employee_id
                else False
            )
            if request.employee_id and request.requested_mode == request.current_mode:
                request.requested_mode = (
                    "manual" if request.current_mode == "automated" else "automated"
                )

    @api.model
    def _user_can_request(self):
        return self.env.is_superuser() or any(
            self.env.user.has_group(group)
            for group in (
                "hr_attendance.group_hr_attendance_officer",
                "hr_attendance.group_hr_attendance_manager",
                "hr.group_hr_manager",
            )
        )

    @api.model
    def _check_md_user(self):
        if not self.env.is_superuser() and not self.env.user.has_group(
            "pr_hr_recruitment_request.group_onboarding_md"
        ):
            raise AccessError(_("Only the Managing Director can decide this request."))

    @api.model_create_multi
    def create(self, vals_list):
        if not self._user_can_request():
            raise AccessError(_("Only HR can request an attendance mode change."))

        employee_ids = [values.get("employee_id") for values in vals_list]
        employees = self.env["hr.employee"].browse(
            [employee_id for employee_id in employee_ids if employee_id]
        ).exists()
        if len(employees) != len(vals_list):
            raise ValidationError(_("Select a valid employee for every request."))

        self.env.cr.execute(
            "SELECT id FROM hr_employee WHERE id IN %s FOR UPDATE",
            [tuple(employees.ids)],
        )
        pending_by_employee = set(
            self.sudo().search(
                [("employee_id", "in", employees.ids), ("state", "=", "pending")]
            ).mapped("employee_id").ids
        )

        prepared = []
        for values in vals_list:
            employee = employees.filtered(
                lambda candidate: candidate.id == values.get("employee_id")
            )
            requested_mode = values.get("requested_mode")
            reason = (values.get("reason") or "").strip()
            if employee.id in pending_by_employee:
                raise ValidationError(
                    _("A pending attendance mode request already exists for %s.")
                    % employee.display_name
                )
            if requested_mode not in dict(ATTENDANCE_ENTRY_MODES):
                raise ValidationError(_("Select a valid requested attendance mode."))
            if requested_mode == employee.attendance_entry_mode:
                raise ValidationError(
                    _("The requested mode must be different from the employee's current mode.")
                )
            if not reason:
                raise ValidationError(_("Enter a reason for the attendance mode change."))
            prepared_values = dict(values)
            prepared_values.update(
                {
                    "name": self.env["ir.sequence"].next_by_code(
                        "hr.attendance.mode.change.request"
                    )
                    or _("New"),
                    "current_mode": employee.attendance_entry_mode,
                    "requested_mode": requested_mode,
                    "reason": reason,
                    "state": "pending",
                    "requested_by_id": self.env.uid,
                    "request_date": fields.Datetime.now(),
                    "decision_by_id": False,
                    "decision_date": False,
                }
            )
            prepared.append(prepared_values)
            pending_by_employee.add(employee.id)

        requests = super().create(prepared)
        requests._schedule_md_activities()
        return requests

    def write(self, values):
        immutable_fields = {
            "employee_id",
            "current_mode",
            "requested_mode",
            "reason",
            "state",
            "requested_by_id",
            "request_date",
            "decision_by_id",
            "decision_date",
        }
        if immutable_fields.intersection(values) and not (
            self.env.su and self.env.context.get("attendance_mode_internal_transition")
        ):
            raise UserError(
                _("Attendance mode requests can only be changed through workflow actions.")
            )
        return super().write(values)

    def unlink(self):
        if not (self.env.su and self.env.context.get("module_uninstall")):
            raise UserError(_("Attendance mode requests are retained for audit history."))
        return super().unlink()

    def _schedule_md_activities(self):
        md_group = self.env.ref(
            "pr_hr_recruitment_request.group_onboarding_md",
            raise_if_not_found=False,
        )
        if not md_group:
            return
        for request in self:
            for user in md_group.users.filtered(lambda candidate: candidate.active):
                request.sudo().activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=user.id,
                    summary=_("Attendance mode change approval"),
                    note=_("Review attendance mode change for %s.")
                    % request.employee_id.display_name,
                )

    def _complete_activities(self, feedback):
        activities = self.sudo().activity_ids.filtered(
            lambda activity: activity.activity_type_id
            == self.env.ref("mail.mail_activity_data_todo")
        )
        if activities:
            activities.action_feedback(feedback=feedback)

    def _lock_and_check_pending(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM hr_attendance_mode_change_request WHERE id = %s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset(["state"])
        if self.state != "pending":
            raise UserError(_("Only pending requests can be processed."))

    def action_approve(self):
        self._check_md_user()
        for request in self:
            request._lock_and_check_pending()
            if request.employee_id.attendance_entry_mode != request.current_mode:
                raise UserError(
                    _(
                        "The employee's attendance mode changed after this request was "
                        "submitted. Cancel it and create a new request."
                    )
                )
            request.employee_id.sudo().with_context(
                attendance_mode_approval_request_id=request.id
            ).write({"attendance_entry_mode": request.requested_mode})
            request.sudo().with_context(
                attendance_mode_internal_transition=True
            ).write(
                {
                    "state": "approved",
                    "decision_by_id": self.env.uid,
                    "decision_date": fields.Datetime.now(),
                }
            )
            request._complete_activities(_("Approved by the Managing Director."))
        return True

    def action_reject(self):
        self._check_md_user()
        for request in self:
            request._lock_and_check_pending()
            request.sudo().with_context(
                attendance_mode_internal_transition=True
            ).write(
                {
                    "state": "rejected",
                    "decision_by_id": self.env.uid,
                    "decision_date": fields.Datetime.now(),
                }
            )
            request._complete_activities(_("Rejected by the Managing Director."))
        return True

    def action_cancel(self):
        for request in self:
            is_requester = request.requested_by_id == self.env.user
            if not is_requester and not self._user_can_request():
                raise AccessError(_("Only the requester or HR can cancel this request."))
            request._lock_and_check_pending()
            request.sudo().with_context(
                attendance_mode_internal_transition=True
            ).write({"state": "cancelled"})
            request._complete_activities(_("Cancelled by HR."))
        return True
