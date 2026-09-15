import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


DAILY_SUBMISSION_STATES = ("submitted_manager", "manager_approved", "in_progress", "completed")


class EmployeeTaskList(models.Model):
    _inherit = "employee.task.list"

    can_submit_for_today = fields.Boolean(compute="_compute_can_submit_for_today")

    def _daily_submission_context(self):
        self.ensure_one()
        employee = self.employee_id.sudo()
        timezone = employee.tz or employee.resource_calendar_id.tz or employee.company_id.partner_id.tz or "Asia/Riyadh"
        day = pytz.UTC.localize(fields.Datetime.to_datetime(fields.Datetime.now())).astimezone(pytz.timezone(timezone)).date()
        Day = self.env["hr.task.attendance.day"]
        start, end = Day._day_bounds(day, timezone)
        return Day, employee, day, start, end, timezone

    @api.depends("state", "employee_id", "task_line_ids.start_date", "task_line_ids.end_date")
    @api.depends_context("uid")
    def _compute_can_submit_for_today(self):
        for task in self:
            task.can_submit_for_today = False
            if task.state not in DAILY_SUBMISSION_STATES or task.employee_id.sudo().user_id != self.env.user:
                continue
            Day, employee, day, start, end, timezone = task._daily_submission_context()
            task.can_submit_for_today = (
                any(line.start_date and line.end_date and line.start_date <= day <= line.end_date for line in task.task_line_ids)
                and Day.sudo()._requires_submission(employee, day, start, end, timezone)
                and not Day._has_daily_submission(employee, day, start, end)
            )

    def action_submit_for_today(self):
        self.ensure_one()
        self.check_access_rights("read")
        self.check_access_rule("read")
        if self.employee_id.sudo().user_id != self.env.user:
            raise AccessError(_("Only the employee can submit their task list for today."))
        self.invalidate_recordset(["can_submit_for_today"])
        if not self.can_submit_for_today:
            raise UserError(_("A daily submission is already recorded, or this task list is not eligible for today's working schedule."))
        self._check_ready_for_execution()
        self._log_approval_history("submitted", _("Daily task submission for attendance."))
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": _("Submitted for Today"), "message": _("Your daily task submission has been recorded."), "type": "success", "sticky": False, "next": {"type": "ir.actions.client", "tag": "reload"}},
        }
