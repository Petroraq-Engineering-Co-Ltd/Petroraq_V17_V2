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
        """Explicitly repair ETM attendance for selected opted-out staff."""
        if not self.env.su and not any(
            self.env.user.has_group(group) for group in REPAIR_GROUPS
        ):
            raise AccessError(_(
                "Only an HR or Attendance Manager can repair task-management attendance."
            ))
        employees = self.exists().filtered(
            lambda employee: not employee.etm_attendance_policy_enabled
        )
        if not employees:
            raise UserError(_(
                "Select at least one employee whose Task Management Attendance "
                "Policy toggle is disabled."
            ))

        repaired_days = self.env["hr.task.attendance.day"].sudo()._repair_non_etm_absences(
            from_date=from_date,
            employee_ids=employees.ids,
        )
        rebuilt_sheets = self.env["attendance.sheet"].sudo()._repair_non_etm_saturday_results(
            from_date=from_date,
            employee_ids=employees.ids,
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Task Management Attendance Repaired"),
                "message": _(
                    "%(employees)s employee(s) checked; %(days)s daily absence "
                    "record(s) restored and %(sheets)s attendance sheet(s) rebuilt. "
                    "From the configured enforcement date, the attendance dashboard "
                    "treats their Saturdays as off days.",
                    employees=len(employees), days=repaired_days, sheets=rebuilt_sheets,
                ),
                "type": "success",
                "sticky": True,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }
