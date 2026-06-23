from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


ATTENDANCE_ENTRY_MODES = [
    ("automated", "Automated Attendance"),
    ("manual", "Manual / Site Attendance"),
]
PENDING_STATES = ("hr_manager_approval", "md_approval")
HR_MANAGER_GROUPS = (
    "hr.group_hr_manager",
    "pr_hr_recruitment_request.group_onboarding_manager",
)
MD_GROUPS = ("pr_hr_recruitment_request.group_onboarding_md",)


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
            ("hr_manager_approval", "HR Manager Approval"),
            ("md_approval", "MD Approval"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="hr_manager_approval",
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
    hr_manager_approved_by_id = fields.Many2one(
        "res.users",
        string="HR Manager Approved By",
        readonly=True,
        copy=False,
        tracking=True,
    )
    hr_manager_approved_date = fields.Datetime(
        string="HR Manager Approved On",
        readonly=True,
        copy=False,
        tracking=True,
    )
    md_approved_by_id = fields.Many2one(
        "res.users",
        string="MD Approved By",
        readonly=True,
        copy=False,
        tracking=True,
    )
    md_approved_date = fields.Datetime(
        string="MD Approved On",
        readonly=True,
        copy=False,
        tracking=True,
    )

    def init(self):
        self.env.cr.execute(
            """
            UPDATE hr_attendance_mode_change_request
               SET state = 'hr_manager_approval'
             WHERE state = 'pending'
            """
        )

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
    def _user_has_any_group(self, groups):
        return self.env.is_superuser() or any(
            self.env.user.has_group(group) for group in groups
        )

    @api.model
    def _current_user_is_hr_manager(self):
        return self._user_has_any_group(HR_MANAGER_GROUPS)

    @api.model
    def _current_user_is_md(self):
        return self._user_has_any_group(MD_GROUPS)

    @api.model
    def _check_hr_manager_user(self):
        if not self._current_user_is_hr_manager():
            raise AccessError(_("Only the HR Manager can approve this stage."))

    @api.model
    def _check_md_user(self):
        if not self._current_user_is_md():
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
                [("employee_id", "in", employees.ids), ("state", "in", PENDING_STATES)]
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
                    "state": "hr_manager_approval",
                    "requested_by_id": self.env.uid,
                    "request_date": fields.Datetime.now(),
                    "decision_by_id": False,
                    "decision_date": False,
                    "hr_manager_approved_by_id": False,
                    "hr_manager_approved_date": False,
                    "md_approved_by_id": False,
                    "md_approved_date": False,
                }
            )
            prepared.append(prepared_values)
            pending_by_employee.add(employee.id)

        requests = super().create(prepared)
        requests._schedule_hr_manager_activities()
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
            "hr_manager_approved_by_id",
            "hr_manager_approved_date",
            "md_approved_by_id",
            "md_approved_date",
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

    def _schedule_group_activities(self, group_xmlids, summary, note):
        users = self.env["res.users"]
        for group_xmlid in group_xmlids:
            group = self.env.ref(group_xmlid, raise_if_not_found=False)
            if group:
                users |= group.users
        for request in self:
            for user in users.filtered(lambda candidate: candidate.active):
                request.sudo().activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=user.id,
                    summary=summary,
                    note=note % request.employee_id.display_name,
                )

    def _schedule_hr_manager_activities(self):
        self._schedule_group_activities(
            HR_MANAGER_GROUPS,
            _("Attendance mode change approval"),
            _("Review attendance mode change for %s as HR Manager."),
        )

    def _schedule_md_activities(self):
        self._schedule_group_activities(
            MD_GROUPS,
            _("Attendance mode change approval"),
            _("Review attendance mode change for %s as Managing Director."),
        )

    def _complete_activities(self, feedback):
        activities = self.sudo().activity_ids.filtered(
            lambda activity: activity.activity_type_id
            == self.env.ref("mail.mail_activity_data_todo")
        )
        if activities:
            activities.action_feedback(feedback=feedback)

    def _lock_and_check_state(self, allowed_states):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM hr_attendance_mode_change_request WHERE id = %s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset(["state"])
        if self.state not in allowed_states:
            raise UserError(_("This request cannot be processed in its current state."))

    def _approve_as_md(self, approval_date, feedback):
        self.ensure_one()
        for request in self:
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
                    "md_approved_by_id": self.env.uid,
                    "md_approved_date": approval_date,
                    "decision_by_id": self.env.uid,
                    "decision_date": approval_date,
                }
            )
            request._complete_activities(feedback)
        return True

    def action_hr_manager_approve(self):
        self._check_hr_manager_user()
        for request in self:
            request._lock_and_check_state(("hr_manager_approval",))
            approval_date = fields.Datetime.now()
            request.sudo().with_context(
                attendance_mode_internal_transition=True
            ).write(
                {
                    "hr_manager_approved_by_id": self.env.uid,
                    "hr_manager_approved_date": approval_date,
                }
            )
            if request._current_user_is_md():
                request._approve_as_md(
                    approval_date,
                    _("Approved by HR Manager and Managing Director."),
                )
                continue
            request.sudo().with_context(
                attendance_mode_internal_transition=True
            ).write({"state": "md_approval"})
            request._complete_activities(_("Approved by HR Manager."))
            request._schedule_md_activities()
        return True

    def action_md_approve(self):
        self._check_md_user()
        for request in self:
            request._lock_and_check_state(("md_approval",))
            request._approve_as_md(
                fields.Datetime.now(),
                _("Approved by the Managing Director."),
            )
        return True

    def action_approve(self):
        for request in self:
            if request.state == "hr_manager_approval":
                request.action_hr_manager_approve()
            elif request.state == "md_approval":
                request.action_md_approve()
            else:
                raise UserError(_("This request cannot be approved in its current state."))
        return True

    def action_reject(self):
        for request in self:
            request._lock_and_check_state(PENDING_STATES)
            if request.state == "hr_manager_approval":
                request._check_hr_manager_user()
                feedback = _("Rejected by HR Manager.")
            else:
                request._check_md_user()
                feedback = _("Rejected by the Managing Director.")
            request.sudo().with_context(
                attendance_mode_internal_transition=True
            ).write(
                {
                    "state": "rejected",
                    "decision_by_id": self.env.uid,
                    "decision_date": fields.Datetime.now(),
                }
            )
            request._complete_activities(feedback)
        return True

    def action_cancel(self):
        for request in self:
            is_requester = request.requested_by_id == self.env.user
            if not is_requester and not self._user_can_request():
                raise AccessError(_("Only the requester or HR can cancel this request."))
            request._lock_and_check_state(PENDING_STATES)
            request.sudo().with_context(
                attendance_mode_internal_transition=True
            ).write({"state": "cancelled"})
            request._complete_activities(_("Cancelled by HR."))
        return True
