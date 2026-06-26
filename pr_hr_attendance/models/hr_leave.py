from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models


class HrLeave(models.Model):
    _inherit = "hr.leave"

    _ATTENDANCE_REPLACING_LEAVE_TYPES = {
        "annual_leave",
        "sick_leave",
        "emergency_leave",
    }
    _ATTENDANCE_REPLACING_LEAVE_NAME_KEYWORDS = (
        "annual",
        "sick",
        "emergency",
    )

    def _pr_leave_replaces_attendance(self):
        self.ensure_one()
        leave_type = self.holiday_status_id
        if not leave_type:
            return False

        leave_type_code = ""
        if "leave_type" in leave_type._fields:
            leave_type_code = (leave_type.leave_type or "").casefold()
        if leave_type_code in self._ATTENDANCE_REPLACING_LEAVE_TYPES:
            return True

        leave_type_name = (leave_type.display_name or "").casefold()
        return any(
            keyword in leave_type_name
            for keyword in self._ATTENDANCE_REPLACING_LEAVE_NAME_KEYWORDS
        )

    def _pr_attendance_cleanup_timezone(self, employee):
        calendar = (
            employee.resource_calendar_id
            or employee.contract_id.resource_calendar_id
            or employee.company_id.resource_calendar_id
            or self.env.company.resource_calendar_id
        )
        return calendar.tz or employee.user_id.tz or self.env.user.tz or "Asia/Riyadh"

    def _pr_attendance_cleanup_bounds(self, employee):
        self.ensure_one()
        start_date = fields.Date.to_date(self.request_date_from or self.date_from)
        end_date = fields.Date.to_date(self.request_date_to or self.date_to)
        if not start_date or not end_date:
            return False, False

        timezone = pytz.timezone(self._pr_attendance_cleanup_timezone(employee))
        start_local = timezone.localize(datetime.combine(start_date, time.min))
        end_local = timezone.localize(datetime.combine(end_date, time.min)) + timedelta(days=1)
        return (
            start_local.astimezone(pytz.UTC).replace(tzinfo=None),
            end_local.astimezone(pytz.UTC).replace(tzinfo=None),
        )

    def _pr_leave_attendance_cleanup_employees(self):
        self.ensure_one()
        employees = self.env["hr.employee"]
        if self.employee_id:
            employees |= self.employee_id
        if "employee_ids" in self._fields:
            employees |= self.employee_ids
        return employees.with_context(active_test=False).exists()

    def _pr_cleanup_attendance_for_approved_leave(self):
        Attendance = self.env["hr.attendance"].sudo().with_context(
            attendance_policy_source="approved_leave",
        )
        for leave in self.sudo():
            if leave.state != "validate" or not leave._pr_leave_replaces_attendance():
                continue

            for employee in leave._pr_leave_attendance_cleanup_employees():
                date_start, date_end = leave._pr_attendance_cleanup_bounds(employee)
                if not date_start or not date_end:
                    continue

                attendances = Attendance.search([
                    ("employee_id", "=", employee.id),
                    ("check_in", "<", fields.Datetime.to_string(date_end)),
                    "|",
                    ("check_out", "=", False),
                    ("check_out", ">", fields.Datetime.to_string(date_start)),
                ])
                if attendances:
                    attendances.unlink()

    @api.model_create_multi
    def create(self, vals_list):
        leaves = super().create(vals_list)
        leaves.filtered(lambda leave: leave.state == "validate")._pr_cleanup_attendance_for_approved_leave()
        return leaves

    def write(self, vals):
        res = super().write(vals)
        if vals.get("state") == "validate":
            self.filtered(lambda leave: leave.state == "validate")._pr_cleanup_attendance_for_approved_leave()
        return res
