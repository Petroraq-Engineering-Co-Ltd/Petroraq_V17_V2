from datetime import datetime, time

import pytz

from odoo import api, fields, models, SUPERUSER_ID
from odoo.tools import date_utils
from dateutil.relativedelta import relativedelta


class HrAttendance(models.Model):
    # region [Initial]
    _inherit = 'hr.attendance'
    # endregion [Initial]

    shortage_time = fields.Text(string="Shortage Time", compute="_compute_shortage_time_text")
    minute_rate = fields.Char(string="Minute Rate", compute="_compute_minute_rate_text")
    show_shortage_button = fields.Boolean(compute="_compute_shortage_time_text")

    def action_open_shortage_request(self):
        for rec in self:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            url = f"{base_url}/shortage_request?check_in={rec.check_in}&check_out={rec.check_out}"
            if rec.shortage_time:
                url+= f"&shortage_text={rec.shortage_time}"
            action = {
                'type': 'ir.actions.act_url',
                'url': url,
                'target': 'new',
            }
            return action


    def _sync_overtime_for_approval(self):
        """Keep optional overtime field in sync for approval grids that show hr.attendance.overtime."""
        overtime_field = self._fields.get('overtime')
        if not overtime_field or overtime_field.compute:
            return

        for rec in self:
            if not rec.check_in or not rec.check_out:
                rec.with_context(skip_overtime_sync=True).write({'overtime': 0.0})
                continue

            hours_per_day = rec.employee_id.resource_calendar_id.hours_per_day or 8.0
            overtime_threshold = 11.0 if (rec.employee_id.resource_calendar_id.id == 6 and hours_per_day >= 9.0) else hours_per_day
            overtime_hours = max((rec.worked_hours or 0.0) - overtime_threshold, 0.0)
            rec.with_context(skip_overtime_sync=True).write({'overtime': overtime_hours})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get('skip_overtime_sync'):
            records._sync_overtime_for_approval()
        return records

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get('skip_overtime_sync'):
            self._sync_overtime_for_approval()
        return result

    def _get_shortage_calendar(self):
        self.ensure_one()
        return (
            self.employee_id.resource_calendar_id
            or self.employee_id.contract_id.resource_calendar_id
            or self.employee_id.company_id.resource_calendar_id
            or self.env.company.resource_calendar_id
        )

    def _get_shortage_timezone_name(self):
        calendar = self._get_shortage_calendar()
        return (
            calendar.tz
            or self.employee_id.user_id.tz
            or self.env.user.tz
            or "Asia/Riyadh"
        )

    def _get_shortage_local_date(self):
        self.ensure_one()
        timezone = pytz.timezone(self._get_shortage_timezone_name())
        check_in = fields.Datetime.to_datetime(self.check_in)
        return pytz.UTC.localize(check_in).astimezone(timezone).date()

    def _get_shortage_day_bounds(self, target_date):
        self.ensure_one()
        timezone = pytz.timezone(self._get_shortage_timezone_name())
        day_start = timezone.localize(datetime.combine(target_date, time.min))
        day_end = day_start + relativedelta(days=1)
        return (
            day_start.astimezone(pytz.UTC).replace(tzinfo=None),
            day_end.astimezone(pytz.UTC).replace(tzinfo=None),
        )

    def _get_planned_hours_for_shortage_date(self, target_date):
        self.ensure_one()
        calendar = self._get_shortage_calendar()
        if not calendar:
            return 0.0

        weekday = str(target_date.weekday())
        attendance_lines = calendar.attendance_ids.filtered(
            lambda attendance:
                attendance.dayofweek == weekday
                and (not attendance.date_from or attendance.date_from <= target_date)
                and (not attendance.date_to or attendance.date_to >= target_date)
        )
        if not attendance_lines:
            return 0.0

        start_hour = min(attendance_lines.mapped("hour_from"))
        end_hour = max(attendance_lines.mapped("hour_to"))
        return max(end_hour - start_hour, 0.0)

    def _get_shortage_day_attendances(self, target_date):
        self.ensure_one()
        day_start_utc, day_end_utc = self._get_shortage_day_bounds(target_date)
        return self.search([
            ("employee_id", "=", self.employee_id.id),
            ("check_in", "<", fields.Datetime.to_string(day_end_utc)),
            "|",
            ("check_out", "=", False),
            ("check_out", ">", fields.Datetime.to_string(day_start_utc)),
        ], order="check_in")

    def _get_attendance_span_hours_for_shortage_date(self, target_date):
        self.ensure_one()
        attendances = self._get_shortage_day_attendances(target_date)
        if not attendances or attendances.filtered(lambda attendance: not attendance.check_out):
            return 0.0

        day_start_utc, day_end_utc = self._get_shortage_day_bounds(target_date)
        earliest_check_in = min(attendances.mapped("check_in"))
        latest_check_out = max(attendances.mapped("check_out"))
        start_utc = max(fields.Datetime.to_datetime(earliest_check_in), day_start_utc)
        stop_utc = min(fields.Datetime.to_datetime(latest_check_out), day_end_utc)
        return max((stop_utc - start_utc).total_seconds() / 3600.0, 0.0)

    def _format_shortage_time(self, shortage_hours):
        total_minutes = int(round((shortage_hours or 0.0) * 60.0))
        hours = total_minutes // 60
        minutes = total_minutes % 60
        parts = []
        if hours:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes or not parts:
            parts.append(f"{minutes} min{'s' if minutes != 1 else ''}")
        return " ".join(parts)

    @api.depends("employee_id", 'check_in', 'check_out', "worked_hours", "employee_id.resource_calendar_id")
    def _compute_shortage_time_text(self):
        for rec in self:
            rec.shortage_time = False
            rec.show_shortage_button = False
            if not rec.check_in or not rec.check_out:
                continue

            shortage_date = rec._get_shortage_local_date()
            planned_hours = rec._get_planned_hours_for_shortage_date(shortage_date)
            attendance_span_hours = rec._get_attendance_span_hours_for_shortage_date(shortage_date)
            shortage_hours = max((planned_hours or 0.0) - (attendance_span_hours or 0.0), 0.0)
            if shortage_hours > 0:
                rec.shortage_time = rec._format_shortage_time(shortage_hours)
                today_date = fields.Date.context_today(rec.with_context(tz=rec._get_shortage_timezone_name()))
                rec.show_shortage_button = shortage_date == today_date or today_date == (shortage_date + relativedelta(days=1))

    @api.depends("employee_id", "check_in", "employee_id.contract_id", "employee_id.resource_calendar_id", "employee_id.resource_calendar_id.hours_per_day")
    def _compute_minute_rate_text(self):
        self = self.sudo()
        for rec in self:
            rec = rec.sudo()
            if rec.employee_id and rec.check_in:
                contract_id = rec.employee_id.contract_id.with_user(SUPERUSER_ID)
                resource_calendar_id = rec.employee_id.resource_calendar_id
                hours_per_day = resource_calendar_id.hours_per_day
                gross_salary = contract_id.sudo().gross_amount
                start_of_month = date_utils.start_of(rec.check_in, 'month')
                end_of_month = date_utils.end_of(rec.check_in, 'month')
                month_days = (end_of_month - start_of_month).days + 1
                day_amount = gross_salary / month_days
                hour_amount_rate = day_amount / hours_per_day
                rec.minute_rate = f"{round((hour_amount_rate / 60), 2)} SR"
            else:
                rec.minute_rate = False
