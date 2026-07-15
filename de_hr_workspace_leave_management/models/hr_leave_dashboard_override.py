import pytz
from datetime import timedelta, datetime, time
from odoo import api, fields, models
from odoo.osv import expression
from odoo.tools import format_date


class HrLeaveDashboardOverride(models.Model):
    _inherit = 'hr.leave'

    @api.model
    def _format_dashboard_date(self, value):
        if not value:
            return False
        return format_date(self.env, fields.Date.to_date(value))

    @api.model
    def _is_time_based_allocation_leave_type(self, leave_type):
        """Leave types whose total allocation must follow selected date range."""
        name = (leave_type.name or '').strip().lower()
        return any(keyword in name for keyword in ('annual', 'hajj', 'emergency', 'marriage'))

    @api.model
    def _get_allocation_date_bounds(self, allocation):
        start = (
            allocation.date_from
            or getattr(allocation, 'accrual_plan_start_date', False)
            or getattr(allocation, 'request_date_from', False)
        )
        end = allocation.date_to or getattr(allocation, 'request_date_to', False)
        return start, end

    @api.model
    def _compute_accrual_allocation_in_range(self, allocation, start, end):
        """
        Estimate accrued days as of the selected range end.

        We pro-rate the currently validated accrued balance by elapsed days between
        allocation start and today, then cap by the selected period.
        """
        alloc_start, _alloc_end = self._get_allocation_date_bounds(allocation)
        if not alloc_start:
            return allocation.number_of_days or 0.0

        today = fields.Date.context_today(self)
        current_total = allocation.number_of_days or 0.0
        elapsed_until_today = (today - alloc_start).days + 1
        if elapsed_until_today <= 0 or current_total <= 0:
            return 0.0

        effective_end = min(end, today)
        if effective_end < alloc_start:
            return 0.0

        effective_start = max(start, alloc_start)
        if effective_start > effective_end:
            return 0.0

        days_in_selected_window = (effective_end - effective_start).days + 1
        days_in_selected_window = max(0, min(days_in_selected_window, elapsed_until_today))
        return current_total * (days_in_selected_window / elapsed_until_today)

    @api.model
    def _compute_allocation_days_for_summary(self, allocation, leave_type, start, end):
        """Compute allocation amount to be shown in summary for selected range."""
        base_days = allocation.number_of_days or 0.0
        if not self._is_time_based_allocation_leave_type(leave_type):
            return base_days

        alloc_start, alloc_end = self._get_allocation_date_bounds(allocation)
        if alloc_start and alloc_start > end:
            return 0.0
        if alloc_end and alloc_end < start:
            return 0.0

        if allocation.allocation_type == 'accrual':
            return self._compute_accrual_allocation_in_range(allocation, start, end)

        return base_days

    def _get_employee_joining_date(self, employee):
        joining_date = False
        if 'hr.contract' in self.env:
            contract = self.env['hr.contract'].sudo().search([
                ('employee_id', '=', employee.id),
                ('state', '!=', 'cancel'),
                ('date_start', '!=', False),
            ], order='date_start asc', limit=1)
            joining_date = contract.joining_date
        return fields.Date.to_string(joining_date) if joining_date else False

    def _get_employee_current_contract_start_date(self, employee):
        contract_start = False
        if 'hr.contract' in self.env:
            today = fields.Date.context_today(self)
            contract = self.env['hr.contract'].sudo().search([
                ('employee_id', '=', employee.id),
                ('state', '!=', 'cancel'),
                ('date_start', '!=', False),
                ('date_start', '<=', today),
                '|',
                ('date_end', '=', False),
                ('date_end', '>=', today),
            ], order='date_start desc', limit=1)
            if not contract:
                contract = self.env['hr.contract'].sudo().search([
                    ('employee_id', '=', employee.id),
                    ('state', '!=', 'cancel'),
                    ('date_start', '!=', False),
                ], order='date_start desc', limit=1)
            contract_start = contract.date_start
        return fields.Date.to_string(contract_start) if contract_start else False

    def _get_employee_effective_start_date(self, employee):
        """Earliest date from which summary metrics should be computed for an employee."""
        start_dates = []
        joining_date = self._get_employee_joining_date(employee)
        if joining_date:
            start_dates.append(fields.Date.to_date(joining_date))
        contract_start = self._get_employee_current_contract_start_date(employee)
        if contract_start:
            start_dates.append(fields.Date.to_date(contract_start))
        if employee.create_date:
            start_dates.append(fields.Datetime.to_datetime(employee.create_date).date())
        return min(start_dates) if start_dates else fields.Date.context_today(self)

    @api.model
    def _sanitize_summary_date_range(self, employee, duration='current_contract', date_from=False, date_to=False):
        """Build and sanitize summary range so it never exceeds employee lifetime/today."""
        today = fields.Date.context_today(self)
        employee_start = self._get_employee_effective_start_date(employee)
        start = employee_start
        end = today

        if duration == 'custom':
            if date_from:
                start = fields.Date.to_date(date_from)
            if date_to:
                end = fields.Date.to_date(date_to)
        elif duration == 'this_year':
            start = today.replace(month=1, day=1)
        elif duration == 'this_month':
            start = today.replace(day=1)
        elif duration == 'date_of_joining':
            joining_date = self._get_employee_joining_date(employee)
            start = fields.Date.to_date(joining_date) if joining_date else employee_start
        else:
            current_contract_start = self._get_employee_current_contract_start_date(employee)
            start = fields.Date.to_date(current_contract_start) if current_contract_start else employee_start

        if end < start:
            start, end = end, start
        start = max(start, employee_start)
        end = min(end, today)
        if end < start:
            end = start
        return start, end, employee_start

    @api.model
    def _get_employee_absentee_days(self, employee, start, end):
        """Count employee absent working days excluding public holidays, approved leaves and attendances."""
        return len(self._get_employee_absentee_day_rows(employee, start, end))

    @api.model
    def _format_calendar_hour(self, hour_float):
        hour_float = hour_float or 0.0
        hours = int(hour_float)
        minutes = int(round((hour_float - hours) * 60))
        if minutes == 60:
            hours += 1
            minutes = 0
        return '%02d:%02d' % (hours, minutes)

    @api.model
    def _get_employee_absentee_calendar(self, employee):
        return (
            employee.resource_calendar_id
            or employee.contract_id.resource_calendar_id
            or employee.company_id.resource_calendar_id
            or self.env.company.resource_calendar_id
        )

    @api.model
    def _get_employee_absentee_shift_label(self, employee, absent_date):
        calendar = self._get_employee_absentee_calendar(employee)
        if not calendar:
            return ''
        attendance_lines = calendar.attendance_ids.filtered(
            lambda attendance: int(attendance.dayofweek) == absent_date.weekday()
        )
        shift_parts = []
        for attendance in attendance_lines:
            time_range = '%s-%s' % (
                self._format_calendar_hour(attendance.hour_from),
                self._format_calendar_hour(attendance.hour_to),
            )
            shift_parts.append('%s (%s)' % (attendance.name, time_range) if attendance.name else time_range)
        return ', '.join(shift_parts)

    @api.model
    def _get_absentee_timezone_name(self, employee):
        calendar = self._get_employee_absentee_calendar(employee)
        return (
            (calendar and calendar.tz)
            or employee.user_id.tz
            or self.env.user.tz
            or 'Asia/Riyadh'
        )

    @api.model
    def _get_absentee_timezone(self, employee):
        try:
            return pytz.timezone(self._get_absentee_timezone_name(employee))
        except pytz.UnknownTimeZoneError:
            return pytz.timezone('Asia/Riyadh')

    @api.model
    def _get_absentee_day_bounds_utc(self, employee, target_date):
        timezone = self._get_absentee_timezone(employee)
        local_start = timezone.localize(datetime.combine(target_date, time.min))
        local_end = local_start + timedelta(days=1)
        return (
            local_start.astimezone(pytz.UTC).replace(tzinfo=None),
            local_end.astimezone(pytz.UTC).replace(tzinfo=None),
        )

    @api.model
    def _to_absentee_local_datetime(self, employee, value):
        value = fields.Datetime.to_datetime(value)
        if not value:
            return False
        if value.tzinfo:
            utc_value = value.astimezone(pytz.UTC)
        else:
            utc_value = pytz.UTC.localize(value)
        return utc_value.astimezone(self._get_absentee_timezone(employee))

    @api.model
    def _get_absentee_cutoff_time(self):
        return time(9, 0, 0)

    @api.model
    def _get_absentee_late_policy_start_date(self):
        return fields.Date.to_date('2026-07-01')

    @api.model
    def _format_absentee_check_in(self, local_check_in):
        return local_check_in.strftime('%H:%M:%S') if local_check_in else ''

    @api.model
    def _add_absentee_date_range(self, dates, range_start, range_end, limit_start, limit_end):
        first_day = max(fields.Date.to_date(range_start), limit_start)
        last_day = min(fields.Date.to_date(range_end), limit_end)
        current = first_day
        while current <= last_day:
            dates.add(current)
            current += timedelta(days=1)

    @api.model
    def _get_employee_public_holiday_dates(self, employee, start, end):
        public_holiday_dates = set()

        holidays = self.env['hr.public.holiday'].sudo().search([
            ('state', '=', 'active'),
            ('date_from', '<=', end),
            ('date_to', '>=', start),
        ])
        for holiday in holidays:
            self._add_absentee_date_range(
                public_holiday_dates,
                holiday.date_from,
                holiday.date_to,
                start,
                end,
            )

        CalendarLeave = self.env['resource.calendar.leaves'].sudo()
        range_start_dt, _range_start_end_dt = self._get_absentee_day_bounds_utc(employee, start)
        _range_end_start_dt, range_end_dt = self._get_absentee_day_bounds_utc(employee, end)
        domain = [
            ('date_from', '<', fields.Datetime.to_string(range_end_dt)),
            ('date_to', '>', fields.Datetime.to_string(range_start_dt)),
        ]

        calendar = self._get_employee_absentee_calendar(employee)
        if 'calendar_id' in CalendarLeave._fields:
            calendar_domain = [('calendar_id', '=', False)]
            if calendar:
                calendar_domain = ['|', ('calendar_id', '=', False), ('calendar_id', '=', calendar.id)]
            domain = expression.AND([domain, calendar_domain])

        if 'resource_id' in CalendarLeave._fields:
            resource_domain = [('resource_id', '=', False)]
            if employee.resource_id:
                resource_domain = ['|', ('resource_id', '=', False), ('resource_id', '=', employee.resource_id.id)]
            domain = expression.AND([domain, resource_domain])

        if 'company_id' in CalendarLeave._fields:
            company_ids = list(filter(None, {employee.company_id.id, self.env.company.id}))
            company_domain = [('company_id', '=', False)]
            if company_ids:
                company_domain = ['|', ('company_id', '=', False), ('company_id', 'in', company_ids)]
            domain = expression.AND([domain, company_domain])

        for leave in CalendarLeave.search(domain):
            local_start = self._to_absentee_local_datetime(employee, leave.date_from)
            local_end = self._to_absentee_local_datetime(employee, leave.date_to)
            if not local_start or not local_end or local_end <= local_start:
                continue
            local_end = local_end - timedelta(microseconds=1)
            self._add_absentee_date_range(
                public_holiday_dates,
                local_start.date(),
                local_end.date(),
                start,
                end,
            )
        return public_holiday_dates

    @api.model
    def _get_employee_absentee_day_rows(self, employee, start, end):
        """Return one row per absent working day for dashboard drill-down."""
        if not employee or not start or not end or end < start:
            return []
        if not getattr(employee, 'compute_attendance', False):
            # Employees without attendance tracking enabled should not be counted as absentees.
            return []

        calendar = self._get_employee_absentee_calendar(employee)
        if calendar and calendar.attendance_ids:
            working_days = {int(att.dayofweek) for att in calendar.attendance_ids}
        else:
            working_days = {0, 1, 2, 3, 4}

        public_holiday_dates = self._get_employee_public_holiday_dates(employee, start, end)

        leave_days = set()
        leaves = self.env['hr.leave'].sudo().search([
            ('state', '=', 'validate'),
            ('employee_id', '=', employee.id),
            ('request_date_from', '<=', end),
            ('request_date_to', '>=', start),
        ])
        for leave in leaves:
            leave_start = max(leave.request_date_from, start)
            leave_end = min(leave.request_date_to, end)
            current = leave_start
            while current <= leave_end:
                leave_days.add(current)
                current += timedelta(days=1)

        on_time_attendance_days = set()
        late_attendance_by_day = {}
        start_dt, _start_end_dt = self._get_absentee_day_bounds_utc(employee, start)
        _end_start_dt, end_dt = self._get_absentee_day_bounds_utc(employee, end)
        attendances = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', fields.Datetime.to_string(start_dt)),
            ('check_in', '<', fields.Datetime.to_string(end_dt)),
        ], order='check_in')
        for attendance in attendances:
            local_check_in = self._to_absentee_local_datetime(employee, attendance.check_in)
            if not local_check_in:
                continue
            attendance_date = local_check_in.date()
            if attendance_date < start or attendance_date > end:
                continue
            if (
                    attendance_date < self._get_absentee_late_policy_start_date()
                    or local_check_in.time() < self._get_absentee_cutoff_time()
            ):
                on_time_attendance_days.add(attendance_date)
                late_attendance_by_day.pop(attendance_date, None)
            elif attendance_date not in on_time_attendance_days and attendance_date not in late_attendance_by_day:
                late_attendance_by_day[attendance_date] = local_check_in

        rows = []
        current = start
        while current <= end:
            if (
                    current.weekday() in working_days
                    and current not in public_holiday_dates
                    and current not in leave_days
                    and current not in on_time_attendance_days
            ):
                late_check_in = late_attendance_by_day.get(current)
                rows.append({
                    'employee_id': employee.id,
                    'employee_code': employee.code or employee.barcode or '',
                    'employee_name': employee.name,
                    'department': employee.department_id.name or '',
                    'job_position': employee.job_title or employee.job_id.name or '',
                    'date': fields.Date.to_string(current),
                    'date_display': self._format_dashboard_date(current),
                    'day_name': current.strftime('%A'),
                    'shift': self._get_employee_absentee_shift_label(employee, current),
                    'check_in': self._format_absentee_check_in(late_check_in),
                    'reason': 'Late check-in after 08:59:59' if late_check_in else 'No attendance',
                })
            current += timedelta(days=1)
        return rows

    @api.model
    def get_employee_absentee_day_details(self, employee_id=None, duration='current_contract', date_from=False, date_to=False):
        employee = self.env['hr.employee'].sudo().browse(employee_id).exists() if employee_id else self.env.user.employee_id
        if not employee:
            return {
                'employee_id': False,
                'employee_name': '',
                'date_from': False,
                'date_to': False,
                'date_from_display': False,
                'date_to_display': False,
                'rows': [],
                'count': 0,
            }
        start, end, _employee_start = self._sanitize_summary_date_range(
            employee,
            duration=duration,
            date_from=date_from,
            date_to=date_to,
        )
        rows = self._get_employee_absentee_day_rows(employee, start, end)
        return {
            'employee_id': employee.id,
            'employee_name': employee.name,
            'date_from': fields.Date.to_string(start),
            'date_to': fields.Date.to_string(end),
            'date_from_display': self._format_dashboard_date(start),
            'date_to_display': self._format_dashboard_date(end),
            'rows': rows,
            'count': len(rows),
        }

    @api.model
    def _get_period_date_range(self, duration):
        today = fields.Date.context_today(self)
        if duration == 'today':
            return today, today
        if duration == 'this_week':
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            return start, end
        if duration == 'this_year':
            start = today.replace(month=1, day=1)
            end = today.replace(month=12, day=31)
            return start, end
        start = today.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)
        return start, end

    def _prepare_employee_data(self, employee):
        return {
            'id': employee.id,
            'code': employee.code,
            'name': employee.name,
            'job_id': employee.job_id.name,
            'approval_status_count': self.get_approval_status_count(employee.id),
        }

    @api.model
    def get_current_employee(self):
        current_employee = self.env.user.employee_id
        if not current_employee and self.env.context.get('employee_id'):
            current_employee = self.env['hr.employee'].browse(self.env.context['employee_id'])
        if not current_employee:
            return {}
        if self.env.context.get('show_all_leave_dashboard'):
            children = self.env['hr.employee'].sudo().search([('active', '=', True)])
        else:
            children = current_employee.child_ids
        return {
            'id': current_employee.id,
            'code': current_employee.code,
            'name': current_employee.name,
            'employee_code': current_employee.code or current_employee.barcode or '',
            'joining_date': self._get_employee_joining_date(current_employee),
            'joining_date_display': self._format_dashboard_date(self._get_employee_joining_date(current_employee)),
            'job_id': current_employee.job_id.id,
            'image_1920': current_employee.image_1920,
            'work_email': current_employee.work_email,
            'work_phone': current_employee.work_phone,
            'resource_calendar_id': current_employee.resource_calendar_id.name,
            'link': '/mail/view?model=%s&res_id=%s' % ('hr.employee.public', current_employee.id),
            'department_id': current_employee.department_id.name,
            'company': current_employee.company_id.name,
            'job_position': current_employee.job_id.name,
            'parent_id': current_employee.parent_id.ids,
            'child_ids': children.ids,
            'child_all_count': len(children),
            'manager': self._prepare_employee_data(current_employee.parent_id) if current_employee.parent_id else {},
            'manager_all_count': len(current_employee.parent_id.ids),
            'children': [self._prepare_employee_data(child) for child in children],
        }

    @api.model
    def get_absentees(self):
        now = fields.Datetime.now()
        domain = [('state', '=', 'validate'), ('date_from', '<=', now), ('date_to', '>=', now)]
        if not self.env.context.get('show_all_leave_dashboard'):
            current_employee = self.env.user.employee_id
            if current_employee:
                domain.append(('employee_id', 'in', current_employee.child_ids.ids))
        leaves = self.env['hr.leave'].sudo().search(domain)
        return [{'employee_id': l.employee_id.id, 'name': l.employee_id.name, 'date_from': l.date_from,
                 'date_to': l.date_to} for l in leaves]

    @api.model
    def get_current_shift(self):
        current_employee = self.env.user.employee_id
        if not current_employee and self.env.context.get('employee_id'):
            current_employee = self.env['hr.employee'].browse(self.env.context['employee_id'])
        if not current_employee:
            return False
        employee_tz = current_employee.tz or self.env.context.get('tz')
        employee_pytz = pytz.timezone(employee_tz) if employee_tz else pytz.utc
        employee_datetime = fields.Datetime.now().astimezone(employee_pytz)
        hour = employee_datetime.strftime('%H')
        minute = employee_datetime.strftime('%M')
        day = employee_datetime.strftime('%A')
        time = hour + '.' + minute
        day_num = '0' if day == 'Monday' else '1' if day == 'Tuesday' else '2' if day == 'Wednesday' else '3' if day == 'Thursday' else '4' if day == 'Friday' else '5' if day == 'Saturday' else '6'
        for shift in current_employee.resource_calendar_id.attendance_ids:
            if shift.dayofweek == day_num and shift.hour_from <= float(time) <= shift.hour_to:
                return shift.name
        return False

    @api.model
    def get_upcoming_holidays(self):
        employee_tz = self.env.user.employee_id.tz or self.env.context.get('tz')
        employee_pytz = pytz.timezone(employee_tz) if employee_tz else pytz.utc
        employee_datetime = fields.Datetime.now().astimezone(employee_pytz)
        holidays = self.env['hr.public.holiday'].sudo().search([('state', '=', 'active')])
        rows = []
        for holiday in holidays:
            if employee_datetime.date() < holiday.date_to:
                row = holiday.read()[0]
                row['date_from_display'] = self._format_dashboard_date(holiday.date_from)
                row['date_to_display'] = self._format_dashboard_date(holiday.date_to)
                rows.append(row)
        return rows

    @api.model
    def get_approval_status_count(self, current_employee):
        return {
            'validate_count': self.env['hr.leave'].search_count(
                [('employee_id', '=', current_employee), ('state', '=', 'validate')]),
            'confirm_count': self.env['hr.leave'].search_count(
                [('employee_id', '=', current_employee), ('state', '=', 'confirm')]),
            'refuse_count': self.env['hr.leave'].search_count(
                [('employee_id', '=', current_employee), ('state', '=', 'refuse')]),
        }

    @api.model
    def get_all_validated_leaves(self):
        domain = [('state', '=', 'validate')]
        if not self.env.context.get('show_all_leave_dashboard'):
            current_employee = self.env.user.employee_id
            if current_employee:
                domain.append(('employee_id', 'in', current_employee.child_ids.ids))
        leaves = self.env['hr.leave'].sudo().search(domain)
        return [{
            'id': leave.id,
            'employee_id': leave.employee_id.id,
            'employee_name': leave.employee_id.name,
            'request_date_from': leave.request_date_from,
            'request_date_to': leave.request_date_to,
            'leave_type_id': leave.holiday_status_id.id,
            'leave_type': leave.holiday_status_id.name,
            'number_of_days': leave.number_of_days,
        } for leave in leaves]

    @api.model
    def get_period_absentees(self, duration='this_month'):
        date_from, date_to = self._get_period_date_range(duration or 'this_month')
        today = fields.Date.context_today(self)
        if date_from > today:
            return []
        date_to = min(date_to, today)
        employees = self.env['hr.employee'].sudo().search([('active', '=', True)])

        leave_days_map = {employee.id: set() for employee in employees}
        approved_leaves = self.env['hr.leave'].sudo().search([
            ('state', '=', 'validate'),
            ('employee_id', 'in', employees.ids),
            ('request_date_from', '<=', date_to),
            ('request_date_to', '>=', date_from),
        ])
        for leave in approved_leaves:
            current = max(leave.request_date_from, date_from)
            end = min(leave.request_date_to, date_to)
            while current <= end:
                leave_days_map.setdefault(leave.employee_id.id, set()).add(current)
                current += timedelta(days=1)

        on_time_attendance_days_map = {employee.id: set() for employee in employees}
        date_from_dt = datetime.combine(date_from - timedelta(days=1), time.min)
        date_to_dt = datetime.combine(date_to + timedelta(days=2), time.min)
        attendances = self.env['hr.attendance'].sudo().search([
            ('employee_id', 'in', employees.ids),
            ('check_in', '>=', fields.Datetime.to_string(date_from_dt)),
            ('check_in', '<', fields.Datetime.to_string(date_to_dt)),
        ], order='check_in')
        for attendance in attendances:
            local_check_in = self._to_absentee_local_datetime(attendance.employee_id, attendance.check_in)
            if not local_check_in:
                continue
            attendance_date = local_check_in.date()
            if attendance_date < date_from or attendance_date > date_to:
                continue
            if (
                    attendance_date < self._get_absentee_late_policy_start_date()
                    or local_check_in.time() < self._get_absentee_cutoff_time()
            ):
                on_time_attendance_days_map.setdefault(attendance.employee_id.id, set()).add(attendance_date)

        rows = []
        for employee in employees:
            if not getattr(employee, 'compute_attendance', False):
                continue
            calendar = self._get_employee_absentee_calendar(employee)
            if calendar and calendar.attendance_ids:
                working_days = {int(a.dayofweek) for a in calendar.attendance_ids}
            else:
                working_days = {0, 1, 2, 3, 4}
            public_holiday_dates = self._get_employee_public_holiday_dates(employee, date_from, date_to)

            absent_count = 0
            current = date_from
            while current <= date_to:
                if (
                        current.weekday() in working_days
                        and current not in public_holiday_dates
                        and current not in leave_days_map.get(employee.id, set())
                        and current not in on_time_attendance_days_map.get(employee.id, set())
                ):
                    absent_count += 1
                current += timedelta(days=1)
            rows.append({
                'employee_id': employee.id,
                'employee_name': employee.name,
                'absent_days': absent_count,
            })
        return rows

    @api.model
    def get_period_leaves(self, duration='this_month', category=None):
        date_from, date_to = self._get_period_date_range(duration or 'this_month')
        domain = [
            ('state', 'in', ['confirm', 'validate']),
            ('request_date_from', '<=', date_to),
            ('request_date_to', '>=', date_from),
        ]
        leaves = self.env['hr.leave'].sudo().search(domain, order='request_date_from asc')
        rows = [{
            'employee_id': leave.employee_id.id,
            'employee_name': leave.employee_id.name,
            'leave_type': leave.holiday_status_id.name,
            'state': leave.state,
            'date_from': self._format_dashboard_date(leave.request_date_from),
            'date_to': self._format_dashboard_date(leave.request_date_to),
            'number_of_days': leave.number_of_days,
        } for leave in leaves]
        if not category:
            return rows

        def _category(value):
            name = (value or '').lower()
            if 'sick' in name:
                return 'sick'
            if 'annual' in name:
                return 'annual'
            return 'other'

        return [row for row in rows if _category(row.get('leave_type')) == category]

    @api.model
    def get_period_leave_type_metrics(self, duration='this_month'):
        metrics = {}
        for leave in self.get_period_leaves(duration):
            leave_type = leave['leave_type'] or 'Unknown'
            if leave_type not in metrics:
                metrics[leave_type] = {
                    'leave_type': leave_type,
                    'approved_days': 0.0,
                    'approved_count': 0,
                    'pending_count': 0,
                    'refused_count': 0,
                }
            if leave['state'] == 'validate':
                metrics[leave_type]['approved_days'] += leave['number_of_days'] or 0.0
                metrics[leave_type]['approved_count'] += 1
            elif leave['state'] == 'confirm':
                metrics[leave_type]['pending_count'] += 1
            elif leave['state'] == 'refuse':
                metrics[leave_type]['refused_count'] += 1
        return list(metrics.values())

    @api.model
    def get_leave_request_filter_options(self):
        employees = self.env['hr.employee'].sudo().search([('active', '=', True)], order='name asc')
        leave_types = self.env['hr.leave.type'].sudo().search([('active', '=', True)], order='name asc')
        return {
            'employees': [{
                'id': emp.id,
                'name': emp.name,
                'code': emp.code or emp.barcode or '',
            } for emp in employees],
            'leave_types': [{'id': leave_type.id, 'name': leave_type.name} for leave_type in leave_types],
        }

    @api.model
    def get_leave_request_count_by_filters(self, duration='this_month', employee_id=False, leave_type_id=False,
                                           date_from=False, date_to=False):
        if duration == 'custom' and date_from and date_to:
            start = fields.Date.to_date(date_from)
            end = fields.Date.to_date(date_to)
        else:
            start, end = self._get_period_date_range(duration or 'this_month')

        domain = [
            ('state', '=', 'validate'),
            ('request_date_from', '<=', end),
            ('request_date_to', '>=', start),
        ]
        if employee_id:
            domain.append(('employee_id', '=', int(employee_id)))
        if leave_type_id:
            domain.append(('holiday_status_id', '=', int(leave_type_id)))

        leaves = self.env['hr.leave'].sudo().search(domain)
        total_days = sum(leaves.mapped('number_of_days'))
        return {
            'duration': duration,
            'date_from': start,
            'date_to': end,
            'total_requests': len(leaves),
            'total_days': round(total_days, 2),
        }

    @api.model
    def get_period_dashboard_data(self, duration='this_month'):
        return {
            'duration': duration,
            'absentees': self.get_period_absentees(duration),
            'sick_leaves': self.get_period_leaves(duration, 'sick'),
            'annual_leaves': self.get_period_leaves(duration, 'annual'),
            'other_leaves': self.get_period_leaves(duration, 'other'),
            'leave_type_metrics': self.get_period_leave_type_metrics(duration),
            'leave_availability': self.get_leave_availability_summary(),
        }

    @api.model
    def get_leave_availability_summary(self):
        employees = self.env['hr.employee'].sudo().search([('active', '=', True)])
        leave_types = self.env['hr.leave.type'].sudo().search([('active', '=', True)])
        allocations = self.env['hr.leave.allocation'].sudo().search([
            ('state', '=', 'validate'),
            ('employee_id', 'in', employees.ids),
            ('holiday_status_id', 'in', leave_types.ids),
        ])
        leaves = self.env['hr.leave'].sudo().search([
            ('state', '=', 'validate'),
            ('employee_id', 'in', employees.ids),
            ('holiday_status_id', 'in', leave_types.ids),
        ])

        allocated = {}
        consumed = {}
        for allocation in allocations:
            key = (allocation.employee_id.id, allocation.holiday_status_id.id)
            allocated[key] = allocated.get(key, 0.0) + (allocation.number_of_days or 0.0)
        for leave in leaves:
            key = (leave.employee_id.id, leave.holiday_status_id.id)
            consumed[key] = consumed.get(key, 0.0) + (leave.number_of_days or 0.0)

        def _category(name):
            lname = (name or '').lower()
            if 'sick' in lname:
                return 'sick'
            if 'annual' in lname:
                return 'annual'
            return 'other'

        rows = []
        for employee in employees:
            values = {'sick': 0.0, 'annual': 0.0, 'other': 0.0}
            for leave_type in leave_types:
                key = (employee.id, leave_type.id)
                remaining = allocated.get(key, 0.0) - consumed.get(key, 0.0)
                values[_category(leave_type.name)] += remaining
            rows.append({
                'employee_id': employee.id,
                'employee_name': employee.name,
                'annual_remaining': round(values['annual'], 2),
                'sick_remaining': round(values['sick'], 2),
                'other_remaining': round(values['other'], 2),
                'total_remaining': round(values['annual'] + values['sick'] + values['other'], 2),
            })
        return rows

    @api.model
    def get_current_employee_leave_breakdown(self):
        employee = self.env.user.employee_id
        if not employee and self.env.context.get('employee_id'):
            employee = self.env['hr.employee'].browse(self.env.context['employee_id'])
        if not employee:
            return []
        leave_types = self.env['hr.leave.type'].sudo().search([('active', '=', True)])
        allocations = self.env['hr.leave.allocation'].sudo().search([
            ('state', '=', 'validate'),
            ('employee_id', '=', employee.id),
            ('holiday_status_id', 'in', leave_types.ids),
        ])
        leaves = self.env['hr.leave'].sudo().search([
            ('state', '=', 'validate'),
            ('employee_id', '=', employee.id),
            ('holiday_status_id', 'in', leave_types.ids),
        ])
        allocated = {}
        consumed = {}
        for allocation in allocations:
            allocated[allocation.holiday_status_id.id] = allocated.get(allocation.holiday_status_id.id, 0.0) + (
                        allocation.number_of_days or 0.0)
        for leave in leaves:
            consumed[leave.holiday_status_id.id] = consumed.get(leave.holiday_status_id.id, 0.0) + (
                        leave.number_of_days or 0.0)
        return [{
            'leave_type': leave_type.name,
            'remaining_days': round(allocated.get(leave_type.id, 0.0) - consumed.get(leave_type.id, 0.0), 2),
        } for leave_type in leave_types]

    @api.model
    def get_employee_leave_simple_summary(self, employee_id=None, duration='current_contract', date_from=False,
                                          date_to=False):
        employee = self.env['hr.employee'].browse(employee_id) if employee_id else self.env.user.employee_id
        if not employee:
            return {'employee_id': False, 'employee_name': '', 'lines': []}
        leave_types = self.env['hr.leave.type'].sudo().search([('active', '=', True)])
        start, end, employee_start = self._sanitize_summary_date_range(
            employee,
            duration=duration,
            date_from=date_from,
            date_to=date_to,
        )

        allocations = self.env['hr.leave.allocation'].sudo().search([
            ('state', '=', 'validate'),
            ('employee_id', '=', employee.id),
            ('holiday_status_id', 'in', leave_types.ids),
        ])
        leaves_domain = [
            ('state', '=', 'validate'),
            ('employee_id', '=', employee.id),
            ('holiday_status_id', 'in', leave_types.ids),
        ]
        if start and end:
            leaves_domain += [
                ('request_date_from', '<=', end),
                ('request_date_to', '>=', start),
            ]
        leaves = self.env['hr.leave'].sudo().search(leaves_domain)

        allocated = {}
        used = {}
        for allocation in allocations:
            leave_type = allocation.holiday_status_id
            key = leave_type.id
            allocated[key] = allocated.get(key, 0.0) + self._compute_allocation_days_for_summary(
                allocation,
                leave_type,
                start,
                end,
            )
        for leave in leaves:
            key = leave.holiday_status_id.id
            used[key] = used.get(key, 0.0) + (leave.number_of_days or 0.0)

        lines = []
        for leave_type in leave_types:
            used_days = round(used.get(leave_type.id, 0.0), 2)
            allocated_days = round(allocated.get(leave_type.id, 0.0), 2)
            requires_allocation = leave_type.requires_allocation == 'yes'
            lines.append({
                'leave_type_id': leave_type.id,
                'leave_type': leave_type.name,
                'used_days': used_days,
                'allocated_days': allocated_days,
                'balance_days': round(allocated_days - used_days, 2) if requires_allocation else 0.0,
                'requires_allocation': requires_allocation,
            })
        lines.append({
            'leave_type_id': False,
            'leave_type': 'Absentees',
            'used_days': self._get_employee_absentee_days(employee, start, end),
            'allocated_days': 0.0,
            'balance_days': 0.0,
            'requires_allocation': False,
        })

        return {
            'employee_id': employee.id,
            'employee_name': employee.name,
            'employee_profile': {
                'id': employee.id,
                'name': employee.name,
                'employee_code': employee.code or employee.barcode or '',
                'joining_date': self._get_employee_joining_date(employee),
                'joining_date_display': self._format_dashboard_date(self._get_employee_joining_date(employee)),
                'current_contract_start_date': self._get_employee_current_contract_start_date(employee),
                'current_contract_start_date_display': self._format_dashboard_date(
                    self._get_employee_current_contract_start_date(employee)
                ),
                'effective_start_date': fields.Date.to_string(employee_start),
                'effective_start_date_display': self._format_dashboard_date(employee_start),
                'job_position': employee.job_title or '',
                'department': employee.department_id.name or '',
                'company': employee.company_id.name or '',
                'image_1920': employee.image_1920 or False,
            },
            'lines': lines,
        }
