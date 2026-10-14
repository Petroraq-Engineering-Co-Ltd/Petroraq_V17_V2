from odoo import _, models
from odoo.exceptions import AccessError, UserError


REPAIR_GROUPS = (
    "hr_attendance.group_hr_attendance_manager",
    "hr.group_hr_manager",
    "pr_hr_recruitment_request.group_onboarding_manager",
)


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    def action_repair_etm_attendance(self, from_date=None):
        """Explicitly repair ETM attendance for the selected employees."""
        if not self.env.su and not any(
            self.env.user.has_group(group) for group in REPAIR_GROUPS
        ):
            raise AccessError(_(
                "Only an HR or Attendance Manager can repair task-management attendance."
            ))
        employees = self.exists()
        if not employees:
            raise UserError(_("Select at least one employee to repair."))

        non_participants = employees.filtered(
            lambda employee: not employee.etm_attendance_policy_enabled
        )
        repaired_days = 0
        if non_participants:
            repaired_days = self.env[
                "hr.task.attendance.day"
            ].sudo()._repair_non_etm_absences(
                from_date=from_date, employee_ids=non_participants.ids,
            )
        repaired_attendances = self.env[
            "hr.attendance"
        ].sudo()._repair_etm_saturday_attendance_statuses(
            from_date=from_date,
            employee_ids=employees.ids,
        )
        rebuilt_sheets = self.env[
            "attendance.sheet"
        ].sudo()._repair_etm_saturday_off_results(
            from_date=from_date, employee_ids=employees.ids,
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Task Management Attendance Repaired"),
                "message": _(
                    "%(employees)s employee(s) checked; %(days)s daily absence "
                    "record(s) restored, %(attendances)s Saturday attendance "
                    "record(s) rechecked, and %(sheets)s attendance sheet(s) rebuilt. "
                    "From the configured enforcement date, the attendance dashboard "
                    "uses each employee's 40-hour Saturday policy.",
                    employees=len(employees), days=repaired_days,
                    attendances=repaired_attendances, sheets=rebuilt_sheets,
                ),
                "type": "success",
                "sticky": True,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }
