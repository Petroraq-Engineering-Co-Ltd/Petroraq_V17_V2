from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    task_attendance_checked = fields.Boolean(readonly=True, copy=False, index=True)
    task_attendance_day_id = fields.Many2one(
        "hr.task.attendance.day", string="Daily Task Absence",
        readonly=True, copy=False, index=True, ondelete="restrict",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any(
            {"task_attendance_checked", "task_attendance_day_id"}.intersection(vals)
            for vals in vals_list
        ):
            raise AccessError(_("Daily task attendance is managed by the system."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            if {"task_attendance_checked", "task_attendance_day_id"}.intersection(vals):
                raise AccessError(_("Daily task attendance is managed by the system."))
            if "attendance_day_status" in vals and vals["attendance_day_status"] != "absent":
                if self.sudo().filtered(
                    lambda att: att.task_attendance_day_id
                    and att.task_attendance_day_id.state != "approved"
                ):
                    raise AccessError(_("HR Manager approval is required to remove the task-list absence."))
        # Preserve the employee/day audit link once an absence has been recorded.
        if {"check_in", "employee_id"}.intersection(vals) and self.filtered("task_attendance_day_id"):
            for att in self.filtered("task_attendance_day_id"):
                employee_id = vals.get("employee_id", att.employee_id.id)
                check_in = vals.get("check_in", att.check_in)
                if employee_id != att.employee_id.id or not check_in or (
                    att._attendance_local_datetime(check_in).date() != att.task_attendance_day_id.date
                ):
                    raise AccessError(_("An attendance with a daily task absence cannot be moved to another employee or day."))
        result = super().write(vals)
        if {"check_in", "employee_id"}.intersection(vals):
            super(HrAttendance, self.sudo()).write({"task_attendance_checked": False})
        return result

    def _refresh_daily_attendance_status(self, now=None):
        blocked = self.sudo().filtered(
            lambda att: att.task_attendance_day_id
            and att.task_attendance_day_id.state != "approved"
        )
        super(HrAttendance, self - self.browse(blocked.ids))._refresh_daily_attendance_status(now=now)
        if blocked:
            blocked.with_context(skip_daily_attendance_status=True).write({
                "attendance_day_status": "absent",
                "attendance_status_reason": _("No task list was submitted for this working day before midnight."),
            })

    def action_open_task_attendance_day(self):
        self.ensure_one()
        self.check_access_rights("read")
        self.check_access_rule("read")
        day = self.task_attendance_day_id
        day.check_access_rights("read")
        day.check_access_rule("read")
        return {
            "type": "ir.actions.act_window",
            "name": _("Mark Present Request"),
            "res_model": "hr.task.attendance.day",
            "res_id": day.id,
            "view_mode": "form",
            "target": "current",
        }
