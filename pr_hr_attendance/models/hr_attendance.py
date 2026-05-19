from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    auto_generated_attendance = fields.Boolean(
        string="Auto Generated",
        readonly=True,
        copy=False,
    )

    attachment_ids = fields.Many2many(
        "ir.attachment",
        "hr_attendance_attachment_rel",
        "attendance_id",
        "attachment_id",
        string="Attachments",
        help="Optional supporting attachments for this attendance/overtime entry.",
    )

    @api.depends("worked_hours", "check_in", "check_out", "employee_id")
    def _compute_overtime_for_approval(self):
        """
        Compute overtime eligibility directly from worked hours and the
        employee's configured calendar hours per day.
        """
        for rec in self:
            if not rec.employee_id or not rec.check_out:
                rec.overtime_for_approval = 0.0
                continue

            allows_overtime = (
                ("allow_overtime" in rec.employee_id._fields and rec.employee_id.allow_overtime)
                or ("add_overtime" in rec.employee_id._fields and rec.employee_id.add_overtime)
            )
            if not allows_overtime:
                rec.overtime_for_approval = 0.0
                continue

            hours_per_day = rec.employee_id.resource_calendar_id.hours_per_day or 8.0
            worked_hours = rec.worked_hours or 0.0
            rec.overtime_for_approval = max(worked_hours - hours_per_day, 0.0)

    @api.model
    def _get_auto_attendance_timezone(self, employee):
        calendar = (
            employee.resource_calendar_id
            or employee.contract_id.resource_calendar_id
            or employee.company_id.resource_calendar_id
            or self.env.company.resource_calendar_id
        )
        return calendar.tz or employee.user_id.tz or self.env.user.tz or "Asia/Riyadh"

    @api.model
    def _get_auto_attendance_day_bounds(self, employee, target_date):
        timezone = pytz.timezone(self._get_auto_attendance_timezone(employee))
        day_start = timezone.localize(datetime.combine(target_date, time.min))
        day_end = day_start + timedelta(days=1)
        return (
            day_start.astimezone(pytz.UTC).replace(tzinfo=None),
            day_end.astimezone(pytz.UTC).replace(tzinfo=None),
            timezone,
        )

    @api.model
    def _get_auto_attendance_datetimes(self, employee, target_date):
        timezone = pytz.timezone(self._get_auto_attendance_timezone(employee))
        check_in = timezone.localize(datetime.combine(target_date, time(hour=9)))
        check_out = timezone.localize(datetime.combine(target_date, time(hour=18)))
        return (
            check_in.astimezone(pytz.UTC).replace(tzinfo=None),
            check_out.astimezone(pytz.UTC).replace(tzinfo=None),
        )

    @api.model
    def _is_auto_attendance_public_holiday(self, employee, target_date):
        if "hr.public.holiday" not in self.env:
            return False

        PublicHoliday = self.env["hr.public.holiday"].sudo()
        holiday_domain = [
            ("date_from", "<=", target_date),
            ("date_to", ">=", target_date),
        ]
        if "state" in PublicHoliday._fields:
            holiday_domain.append(("state", "=", "active"))

        for holiday in PublicHoliday.search(holiday_domain):
            is_employee_holiday = bool(
                ("emp_ids" in holiday._fields and employee in holiday.emp_ids)
                or ("dep_ids" in holiday._fields and employee.department_id in holiday.dep_ids)
                or ("cat_ids" in holiday._fields and bool(employee.category_ids & holiday.cat_ids))
            )
            is_global_holiday = not any((
                "emp_ids" in holiday._fields and holiday.emp_ids,
                "dep_ids" in holiday._fields and holiday.dep_ids,
                "cat_ids" in holiday._fields and holiday.cat_ids,
            ))
            if is_employee_holiday or is_global_holiday:
                return True
        return False

    @api.model
    def _is_auto_attendance_working_day(self, employee, target_date, day_start_utc, day_end_utc):
        calendar = (
            employee.resource_calendar_id
            or employee.contract_id.resource_calendar_id
            or employee.company_id.resource_calendar_id
            or self.env.company.resource_calendar_id
        )
        if not calendar:
            return False

        weekday = str(target_date.weekday())
        attendance_lines = calendar.attendance_ids.filtered(
            lambda attendance:
                attendance.dayofweek == weekday
                and (not attendance.date_from or attendance.date_from <= target_date)
                and (not attendance.date_to or attendance.date_to >= target_date)
        )
        if not attendance_lines:
            return False

        leave_domain = [
            ("calendar_id", "in", [False, calendar.id]),
            ("date_from", "<", fields.Datetime.to_string(day_end_utc)),
            ("date_to", ">", fields.Datetime.to_string(day_start_utc)),
        ]
        if "resource_id" in self.env["resource.calendar.leaves"]._fields and employee.resource_id:
            leave_domain += ["|", ("resource_id", "=", False), ("resource_id", "=", employee.resource_id.id)]
        if self.env["resource.calendar.leaves"].sudo().search_count(leave_domain):
            return False

        if self._is_auto_attendance_public_holiday(employee, target_date):
            return False

        hr_leave_domain = [
            ("employee_id", "=", employee.id),
            ("state", "in", ["validate", "validate1"]),
            ("date_from", "<", fields.Datetime.to_string(day_end_utc)),
            ("date_to", ">", fields.Datetime.to_string(day_start_utc)),
        ]
        if self.env["hr.leave"].sudo().search_count(hr_leave_domain):
            return False

        return True

    @api.model
    def _has_attendance_on_day(self, employee, day_start_utc, day_end_utc):
        return bool(self.sudo().search_count([
            ("employee_id", "=", employee.id),
            ("check_in", "<", fields.Datetime.to_string(day_end_utc)),
            "|",
            ("check_out", "=", False),
            ("check_out", ">", fields.Datetime.to_string(day_start_utc)),
        ]))

    @api.model
    def _get_auto_attendance_target_date(self, company):
        timezone = (
            company.resource_calendar_id.tz
            or self.env.user.tz
            or "Asia/Riyadh"
        )
        return fields.Date.context_today(self.with_context(tz=timezone))

    @api.model
    def cron_create_auto_management_attendance(self, target_date=False):
        Attendance = self.env["hr.attendance"].sudo()
        Employee = self.env["hr.employee"].sudo()
        companies = self.env["res.company"].sudo().search([])
        created_attendances = Attendance.browse()

        for company in companies:
            attendance_date = (
                fields.Date.to_date(target_date)
                if target_date else self._get_auto_attendance_target_date(company)
            )
            employees = Employee.search([
                ("active", "=", True),
                ("company_id", "=", company.id),
                ("compute_attendance", "=", False),
            ])
            for employee in employees:
                day_start_utc, day_end_utc, _timezone = self._get_auto_attendance_day_bounds(employee, attendance_date)
                if self._has_attendance_on_day(employee, day_start_utc, day_end_utc):
                    continue
                if not self._is_auto_attendance_working_day(employee, attendance_date, day_start_utc, day_end_utc):
                    continue

                check_in, check_out = self._get_auto_attendance_datetimes(employee, attendance_date)
                created_attendances |= Attendance.create({
                    "employee_id": employee.id,
                    "check_in": fields.Datetime.to_string(check_in),
                    "check_out": fields.Datetime.to_string(check_out),
                    "auto_generated_attendance": True,
                })

        return created_attendances
