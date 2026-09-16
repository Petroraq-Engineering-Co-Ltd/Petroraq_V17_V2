from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


HR_GROUPS = ("hr.group_hr_manager", "pr_hr_recruitment_request.group_onboarding_manager")


class TaskAttendanceDay(models.Model):
    _name = "hr.task.attendance.day"
    _description = "Daily Task Absence / Mark Present Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"
    _rec_name = "name"

    name = fields.Char(compute="_compute_name", store=True)
    employee_id = fields.Many2one("hr.employee", required=True, readonly=True, index=True, ondelete="restrict")
    company_id = fields.Many2one(related="employee_id.company_id", store=True, index=True)
    date = fields.Date(required=True, readonly=True, index=True)
    timezone = fields.Char(required=True, readonly=True)
    attendance_ids = fields.One2many("hr.attendance", "task_attendance_day_id", readonly=True)
    state = fields.Selection([
        ("absent", "Absent — No Daily Submission"),
        ("pending", "HR Manager Approval"),
        ("approved", "Approved — Actual Attendance Applies"),
        ("rejected", "Rejected"),
    ], default="absent", required=True, readonly=True, tracking=True, index=True, copy=False)
    reason = fields.Text(string="Request Reason", tracking=True)
    hr_comment = fields.Text(string="HR Decision Notes", tracking=True)
    requested_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    requested_at = fields.Datetime(readonly=True, copy=False)
    decision_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    decision_at = fields.Datetime(readonly=True, copy=False)
    can_request = fields.Boolean(compute="_compute_permissions")
    can_decide = fields.Boolean(compute="_compute_permissions")

    _sql_constraints = [
        ("employee_date_unique", "unique(employee_id, date)", "There is already a daily task attendance record for this employee and date."),
    ]

    @api.depends("employee_id.name", "date")
    def _compute_name(self):
        for rec in self:
            rec.name = "%s — %s" % (rec.employee_id.name, rec.date)

    @api.model
    def _is_hr_manager(self):
        return self.env.su or any(self.env.user.has_group(group) for group in HR_GROUPS)

    @api.depends("state", "employee_id.user_id")
    @api.depends_context("uid")
    def _compute_permissions(self):
        for rec in self:
            rec.can_request = rec.state in ("absent", "rejected") and (
                rec.employee_id.sudo().user_id == self.env.user or rec._is_hr_manager()
            )
            rec.can_decide = rec.state == "pending" and rec._is_hr_manager()

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_("Only the attendance process can create daily task absence records."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            self.check_access_rights("write")
            self.check_access_rule("write")
            if set(vals) - {"reason", "hr_comment"}:
                raise AccessError(_("Use the request and HR approval buttons to change this record."))
            for rec in self:
                if "reason" in vals and not rec.can_request:
                    raise AccessError(_("The request reason can only be edited before submission."))
                if "hr_comment" in vals and not rec.can_decide:
                    raise AccessError(_("Only the HR Manager can enter a decision on a pending request."))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_("Daily task attendance records must be retained for audit."))

    def _lock_for_transition(self):
        self.ensure_one()
        self.check_access_rights("write")
        self.check_access_rule("write")
        self.env.cr.execute("SELECT id FROM hr_task_attendance_day WHERE id = %s FOR UPDATE", [self.id])
        self.invalidate_recordset()

    def action_request_present(self):
        self._lock_for_transition()
        if not self.can_request:
            raise AccessError(_("You cannot submit this mark-present request."))
        if not (self.reason or "").strip():
            raise UserError(_("Enter why your actual attendance should be accepted."))
        user = self.env.user
        self.sudo().write({
            "state": "pending", "requested_by_id": user.id,
            "requested_at": fields.Datetime.now(), "decision_by_id": False,
            "decision_at": False, "hr_comment": False,
        })
        groups = self.env["res.groups"].sudo()
        for xmlid in HR_GROUPS:
            groups |= self.env.ref(xmlid).sudo()
        managers = groups.mapped("users").filtered(
            lambda manager: manager.active and self.company_id in manager.company_ids
        )
        for manager in managers:
            self.sudo().activity_schedule(
                "mail.mail_activity_data_todo", user_id=manager.id,
                summary=_("Review mark-present request"),
            )
        return True

    def _decide(self, approve):
        self._lock_for_transition()
        if self.state != "pending" or not self._is_hr_manager():
            raise AccessError(_("Only the HR Manager can decide a pending mark-present request."))
        if approve and not self.sudo().attendance_ids:
            raise UserError(_("No actual attendance remains for this day. Review any approved leave or attendance correction first."))
        if not approve and not (self.hr_comment or "").strip():
            raise UserError(_("Enter the reason for rejecting the request."))
        self.sudo().write({
            "state": "approved" if approve else "rejected",
            "decision_by_id": self.env.uid, "decision_at": fields.Datetime.now(),
        })
        self.sudo().activity_feedback(["mail.mail_activity_data_todo"])
        self.sudo().attendance_ids._refresh_daily_attendance_status()
        self._sync_unfinalized_sheets()
        return True

    def action_approve(self):
        return self._decide(True)

    def action_reject(self):
        return self._decide(False)

    def _sync_unfinalized_sheets(self):
        for day in self:
            sheets = self.env["attendance.sheet"].sudo().search([
                ("employee_id", "=", day.employee_id.id),
                ("date_from", "<=", day.date), ("date_to", ">=", day.date),
                ("state", "in", ["draft", "confirm"]),
            ])
            sheets._apply_daily_task_absences()

    @api.model
    def _day_bounds(self, day, timezone):
        zone = pytz.timezone(timezone)
        return tuple(
            zone.localize(datetime.combine(value, time.min)).astimezone(pytz.UTC)
            for value in (day, day + timedelta(days=1))
        )

    @api.model
    def _requires_submission(self, employee, day, start, end, timezone):
        calendar = employee.resource_calendar_id or employee.company_id.resource_calendar_id
        if not calendar or self.env["hr.attendance"]._is_auto_attendance_public_holiday(employee, day):
            return False
        intervals = calendar._work_intervals_batch(
            start, end, resources=employee.resource_id, tz=pytz.timezone(timezone),
        )
        return bool(intervals.get(employee.resource_id.id))

    @api.model
    def _has_daily_submission(self, employee, day, start, end):
        # A historical submission, approval, or manager assignment does not
        # satisfy today's requirement. Returned submissions still count.
        submissions = self.env["employee.task.approval.history"].sudo().search([
            ("task_list_id.employee_id", "=", employee.id),
            ("action", "=", "submitted"),
            ("action_datetime", ">=", start.replace(tzinfo=None)),
            ("action_datetime", "<", end.replace(tzinfo=None)),
        ])
        return any(
            line.start_date and line.end_date and line.start_date <= day <= line.end_date
            for line in submissions.mapped("task_list_id.task_line_ids")
        )

    @api.model
    def cron_finalize_task_attendance(self, now=None):
        """Process ended local days once, including punches imported late.

        Apply from installation day onwards; never retroactively penalize
        historical attendance when this module is first enabled.
        """
        if not self.env.su and not self.env.user.has_group("base.group_system"):
            raise AccessError(_("Only the system can finalize daily task attendance."))
        self.env.cr.execute("SELECT pg_try_advisory_xact_lock(hashtext('pr_task_attendance.finalize'))")
        if not self.env.cr.fetchone()[0]:
            return
        utc_now = fields.Datetime.to_datetime(now or fields.Datetime.now())
        start_date = fields.Date.to_date(self.env["ir.config_parameter"].sudo().get_param(
            "pr_task_attendance.enforce_from"
        ))
        if not start_date:
            return
        Attendance = self.env["hr.attendance"].sudo()
        candidates = Attendance.search([
            ("task_attendance_checked", "=", False),
            ("check_in", ">=", datetime.combine(start_date - timedelta(days=1), time.min)),
            ("check_in", "<", utc_now),
        ], order="employee_id, check_in")
        grouped = {}
        for att in candidates:
            local_check_in = att._attendance_local_datetime(att.check_in)
            day = local_check_in.date()
            if day < start_date:
                att.write({"task_attendance_checked": True})
                continue
            if att._attendance_local_datetime(utc_now).date() <= day:
                continue
            key = (att.employee_id.id, day, local_check_in.tzinfo.zone)
            grouped[key] = grouped.get(key, Attendance) | att
        for (employee_id, day, timezone), attendances in grouped.items():
            employee = attendances[0].employee_id
            start, end = self._day_bounds(day, timezone)
            record = self.sudo().search([("employee_id", "=", employee_id), ("date", "=", day)], limit=1)
            if (
                not record
                and self._requires_submission(employee, day, start, end, timezone)
                and not self._has_daily_submission(employee, day, start, end)
            ):
                record = self.sudo().create({"employee_id": employee_id, "date": day, "timezone": timezone})
            values = {"task_attendance_checked": True}
            if record:
                record._lock_for_transition()
                attendances = Attendance.search([
                    ("employee_id", "=", employee_id),
                    ("check_in", ">=", start.replace(tzinfo=None)),
                    ("check_in", "<", end.replace(tzinfo=None)),
                ])
                values["task_attendance_day_id"] = record.id
            attendances.write(values)
            attendances._refresh_daily_attendance_status(now=utc_now)
            if record:
                record._sync_unfinalized_sheets()
