# -*- coding: utf-8 -*-

from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _


class HrAttendanceManagementDashboard(models.AbstractModel):
    _name = "de.hr.attendance.management.dashboard"
    _description = "Attendance Management Dashboard Service"

    STATUS_META = {
        "present": {
            "label": "Present",
            "color": "#208a5d",
            "tone": "success",
            "rank": 40,
        },
        "checked_in": {
            "label": "Checked In",
            "color": "#0ea5e9",
            "tone": "info",
            "rank": 35,
        },
        "late": {
            "label": "Late",
            "color": "#d88716",
            "tone": "warning",
            "rank": 20,
        },
        "early_exit": {
            "label": "Early Exit",
            "color": "#bf6b17",
            "tone": "warning",
            "rank": 25,
        },
        "missing_checkout": {
            "label": "Missing Checkout",
            "color": "#b42318",
            "tone": "danger",
            "rank": 10,
        },
        "absent": {
            "label": "Absent",
            "color": "#d92d20",
            "tone": "danger",
            "rank": 5,
        },
        "on_leave": {
            "label": "On Leave",
            "color": "#2f80ed",
            "tone": "info",
            "rank": 30,
        },
        "off_day": {
            "label": "Off Day",
            "color": "#77818f",
            "tone": "muted",
            "rank": 60,
        },
    }

    @api.model
    def get_dashboard_data(self, selected_date=False, department_id=False):
        dashboard_date = fields.Date.to_date(selected_date) if selected_date else fields.Date.context_today(self)
        department_id = int(department_id or 0)
        employees = self._get_dashboard_employees(department_id)
        departments = self._get_department_options()

        day_start_utc, day_end_utc, timezone = self._get_day_bounds(dashboard_date)
        week_dates = [dashboard_date - timedelta(days=index) for index in range(6, -1, -1)]
        week_start_utc, _week_start_end, _tz = self._get_day_bounds(week_dates[0])
        _week_end_start, week_end_utc, _tz = self._get_day_bounds(week_dates[-1])

        attendance_map = self._attendance_map(employees, week_start_utc, week_end_utc)
        leave_map = self._leave_map(employees, week_start_utc, week_end_utc)

        rows = self._get_day_rows(
            employees,
            dashboard_date,
            day_start_utc,
            day_end_utc,
            timezone,
            attendance_map,
            leave_map,
        )
        summary = self._get_summary(rows)
        departments_breakdown = self._get_department_breakdown(rows)
        daily_trend = [
            self._get_trend_day(
                day,
                employees,
                attendance_map,
                leave_map,
            )
            for day in week_dates
        ]

        return {
            "selected_date": fields.Date.to_string(dashboard_date),
            "display_date": dashboard_date.strftime("%A, %B %d, %Y"),
            "department_id": department_id,
            "departments": departments,
            "company": self.env.company.display_name,
            "summary": summary,
            "status_breakdown": self._get_status_breakdown(rows),
            "department_breakdown": departments_breakdown,
            "daily_trend": daily_trend,
            "timeline_rows": rows,
            "hours": list(range(24)),
        }

    @api.model
    def _get_dashboard_employees(self, department_id=False):
        domain = [
            ("active", "=", True),
            ("company_id", "in", [False, self.env.company.id]),
        ]
        if department_id:
            domain.append(("department_id", "=", department_id))
        return self.env["hr.employee"].sudo().search(domain, order="department_id, name")

    @api.model
    def _get_department_options(self):
        departments = self.env["hr.department"].sudo().search([], order="name")
        return [
            {
                "id": department.id,
                "name": department.display_name,
            }
            for department in departments
        ]

    @api.model
    def _get_dashboard_timezone(self):
        calendar = self.env.company.resource_calendar_id
        return (
            self.env.user.tz
            or calendar.tz
            or "Asia/Riyadh"
        )

    @api.model
    def _get_day_bounds(self, day):
        timezone = pytz.timezone(self._get_dashboard_timezone())
        local_start = timezone.localize(datetime.combine(day, time.min))
        local_end = local_start + timedelta(days=1)
        return (
            local_start.astimezone(pytz.UTC).replace(tzinfo=None),
            local_end.astimezone(pytz.UTC).replace(tzinfo=None),
            timezone,
        )

    @api.model
    def _attendance_map(self, employees, start_utc, end_utc):
        if not employees:
            return defaultdict(lambda: self.env["hr.attendance"])
        attendances = self.env["hr.attendance"].sudo().search([
            ("employee_id", "in", employees.ids),
            ("check_in", "<", fields.Datetime.to_string(end_utc)),
            "|",
            ("check_out", "=", False),
            ("check_out", ">", fields.Datetime.to_string(start_utc)),
        ], order="check_in")
        grouped = defaultdict(lambda: self.env["hr.attendance"])
        for attendance in attendances:
            grouped[attendance.employee_id.id] |= attendance
        return grouped

    @api.model
    def _leave_map(self, employees, start_utc, end_utc):
        if not employees or "hr.leave" not in self.env:
            return defaultdict(lambda: self.env["hr.leave"])
        leaves = self.env["hr.leave"].sudo().search([
            ("employee_id", "in", employees.ids),
            ("state", "in", ["validate", "validate1"]),
            ("date_from", "<", fields.Datetime.to_string(end_utc)),
            ("date_to", ">", fields.Datetime.to_string(start_utc)),
        ], order="date_from")
        grouped = defaultdict(lambda: self.env["hr.leave"])
        for leave in leaves:
            grouped[leave.employee_id.id] |= leave
        return grouped

    @api.model
    def _records_overlapping_day(self, records, start_utc, end_utc, start_field, stop_field):
        result = records.browse()
        for record in records:
            record_start = fields.Datetime.to_datetime(record[start_field])
            record_stop = fields.Datetime.to_datetime(record[stop_field]) if record[stop_field] else end_utc
            if record_start and record_start < end_utc and record_stop > start_utc:
                result |= record
        return result

    @api.model
    def _get_calendar(self, employee):
        return (
            employee.resource_calendar_id
            or employee.contract_id.resource_calendar_id
            or employee.company_id.resource_calendar_id
            or self.env.company.resource_calendar_id
        )

    @api.model
    def _get_schedule(self, employee, day, timezone):
        calendar = self._get_calendar(employee)
        if not calendar:
            return self._empty_schedule()

        attendances = calendar.attendance_ids.filtered(
            lambda attendance:
                attendance.dayofweek == str(day.weekday())
                and (not attendance.date_from or attendance.date_from <= day)
                and (not attendance.date_to or attendance.date_to >= day)
        )
        if not attendances:
            return self._empty_schedule()

        start_hour = min(attendances.mapped("hour_from"))
        end_hour = max(attendances.mapped("hour_to"))
        planned_hours = sum(max(line.hour_to - line.hour_from, 0.0) for line in attendances)
        return {
            "working_day": True,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "planned_hours": planned_hours,
            "start_dt": self._float_hour_to_datetime(day, start_hour, timezone),
            "end_dt": self._float_hour_to_datetime(day, end_hour, timezone),
            "label": "%s - %s" % (self._format_float_hour(start_hour), self._format_float_hour(end_hour)),
        }

    @api.model
    def _empty_schedule(self):
        return {
            "working_day": False,
            "start_hour": 8.0,
            "end_hour": 17.0,
            "planned_hours": 0.0,
            "start_dt": False,
            "end_dt": False,
            "label": _("No shift"),
        }

    @api.model
    def _float_hour_to_datetime(self, day, float_hour, timezone):
        hour = int(float_hour)
        minute = int(round((float_hour - hour) * 60))
        day_start = timezone.localize(datetime.combine(day, time.min))
        return day_start + timedelta(hours=hour, minutes=minute)

    @api.model
    def _format_float_hour(self, float_hour):
        hour = int(float_hour)
        minute = int(round((float_hour - hour) * 60))
        return "%02d:%02d" % (hour % 24, minute)

    @api.model
    def _to_local(self, value, timezone):
        if not value:
            return False
        value = fields.Datetime.to_datetime(value)
        return pytz.UTC.localize(value).astimezone(timezone)

    @api.model
    def _format_dt_time(self, value, timezone):
        local_value = self._to_local(value, timezone)
        return local_value.strftime("%H:%M") if local_value else "-"

    @api.model
    def _is_calendar_blocked(self, employee, calendar, day_start_utc, day_end_utc):
        if not calendar:
            return False
        Leave = self.env["resource.calendar.leaves"].sudo()
        domain = [
            ("calendar_id", "in", [False, calendar.id]),
            ("date_from", "<", fields.Datetime.to_string(day_end_utc)),
            ("date_to", ">", fields.Datetime.to_string(day_start_utc)),
        ]
        if "resource_id" in Leave._fields and employee.resource_id:
            domain += ["|", ("resource_id", "=", False), ("resource_id", "=", employee.resource_id.id)]
        return bool(Leave.search_count(domain))

    @api.model
    def _day_segment(self, label, start_hour, end_hour, status_key):
        start_percent = max(0.0, min(100.0, (start_hour / 24.0) * 100.0))
        width_percent = max(1.2, min(100.0 - start_percent, ((end_hour - start_hour) / 24.0) * 100.0))
        return {
            "label": label,
            "start_percent": round(start_percent, 2),
            "width_percent": round(width_percent, 2),
            "status": status_key,
        }

    @api.model
    def _attendance_segments(self, attendances, timezone, day_start_utc, day_end_utc, status_key):
        segments = []
        for attendance in attendances:
            start_utc = max(fields.Datetime.to_datetime(attendance.check_in), day_start_utc)
            stop_value = fields.Datetime.to_datetime(attendance.check_out) if attendance.check_out else day_end_utc
            stop_utc = min(stop_value, day_end_utc)
            start_local = pytz.UTC.localize(start_utc).astimezone(timezone)
            stop_local = pytz.UTC.localize(stop_utc).astimezone(timezone)
            start_hour = start_local.hour + start_local.minute / 60.0
            stop_hour = stop_local.hour + stop_local.minute / 60.0
            if stop_hour <= start_hour:
                stop_hour = start_hour + 0.25
            label = "%s - %s" % (
                start_local.strftime("%H:%M"),
                stop_local.strftime("%H:%M") if attendance.check_out else _("Open"),
            )
            segments.append(self._day_segment(label, start_hour, stop_hour, status_key))
        return segments

    @api.model
    def _get_day_rows(self, employees, day, day_start_utc, day_end_utc, timezone, attendance_map, leave_map):
        rows = []
        for employee in employees:
            schedule = self._get_schedule(employee, day, timezone)
            calendar = self._get_calendar(employee)
            is_calendar_blocked = self._is_calendar_blocked(employee, calendar, day_start_utc, day_end_utc)
            attendances = self._records_overlapping_day(
                attendance_map[employee.id],
                day_start_utc,
                day_end_utc,
                "check_in",
                "check_out",
            )
            leaves = self._records_overlapping_day(
                leave_map[employee.id],
                day_start_utc,
                day_end_utc,
                "date_from",
                "date_to",
            )
            row = self._build_employee_row(
                employee,
                day,
                day_start_utc,
                day_end_utc,
                timezone,
                schedule,
                is_calendar_blocked,
                attendances,
                leaves,
            )
            rows.append(row)

        rows.sort(key=lambda row: (
            self.STATUS_META[row["status"]]["rank"],
            row["department"] or "",
            row["employee_name"] or "",
        ))
        return rows

    @api.model
    def _build_employee_row(self, employee, day, day_start_utc, day_end_utc, timezone, schedule, is_calendar_blocked, attendances, leaves):
        earliest_check_in = min(attendances.mapped("check_in")) if attendances else False
        checked_out_attendances = attendances.filtered("check_out")
        latest_check_out = max(checked_out_attendances.mapped("check_out")) if checked_out_attendances else False
        worked_hours = sum(attendances.mapped("worked_hours")) if attendances else 0.0

        late_minutes = 0.0
        early_minutes = 0.0
        if schedule["working_day"] and earliest_check_in:
            check_in_local = self._to_local(earliest_check_in, timezone)
            grace_start = schedule["start_dt"] + timedelta(minutes=60)
            if check_in_local > grace_start:
                late_minutes = round((check_in_local - grace_start).total_seconds() / 60.0, 2)
        if schedule["working_day"] and latest_check_out:
            check_out_local = self._to_local(latest_check_out, timezone)
            if check_out_local < schedule["end_dt"]:
                early_minutes = round((schedule["end_dt"] - check_out_local).total_seconds() / 60.0, 2)

        open_attendances = attendances.filtered(lambda attendance: not attendance.check_out)
        dashboard_today = datetime.now(timezone).date()
        is_current_day_open_attendance = bool(
            open_attendances
            and day == dashboard_today
            and all(self._to_local(attendance.check_in, timezone).date() == day for attendance in open_attendances)
        )

        if is_current_day_open_attendance:
            status = "checked_in"
        elif open_attendances:
            status = "missing_checkout"
        elif attendances and late_minutes:
            status = "late"
        elif attendances and early_minutes:
            status = "early_exit"
        elif attendances:
            status = "present"
        elif leaves:
            status = "on_leave"
        elif schedule["working_day"] and not is_calendar_blocked:
            status = "absent"
        else:
            status = "off_day"

        if attendances:
            segments = self._attendance_segments(attendances, timezone, day_start_utc, day_end_utc, status)
        else:
            segment_start = schedule["start_hour"]
            segment_end = schedule["end_hour"] if schedule["end_hour"] > segment_start else segment_start + 8.0
            if status == "off_day":
                segment_start, segment_end = 8.0, 17.0
            label = self.STATUS_META[status]["label"]
            if status == "on_leave" and leaves:
                label = leaves[0].holiday_status_id.display_name or label
            segments = [self._day_segment(label, segment_start, segment_end, status)]

        leave_names = [leave.holiday_status_id.display_name for leave in leaves if leave.holiday_status_id]
        return {
            "employee_id": employee.id,
            "employee_name": employee.display_name,
            "employee_code": employee.code if "code" in employee._fields else "",
            "department_id": employee.department_id.id or False,
            "department": employee.department_id.display_name or _("No Department"),
            "manager": employee.parent_id.display_name or "",
            "job": employee.job_id.display_name or "",
            "status": status,
            "status_label": self.STATUS_META[status]["label"],
            "status_color": self.STATUS_META[status]["color"],
            "status_tone": self.STATUS_META[status]["tone"],
            "check_in": self._format_dt_time(earliest_check_in, timezone),
            "check_out": self._format_dt_time(latest_check_out, timezone),
            "worked_hours": round(worked_hours, 2),
            "planned_hours": round(schedule["planned_hours"], 2),
            "schedule": schedule["label"],
            "late_minutes": late_minutes,
            "early_minutes": early_minutes,
            "leave": ", ".join(leave_names),
            "attendance_ids": attendances.ids,
            "leave_ids": leaves.ids,
            "segments": segments,
        }

    @api.model
    def _get_summary(self, rows):
        counts = defaultdict(int)
        for row in rows:
            counts[row["status"]] += 1

        with_punch = sum(counts[key] for key in ["present", "checked_in", "late", "early_exit", "missing_checkout"])
        scheduled = max(len(rows) - counts["off_day"], 0)
        issue_count = counts["absent"] + counts["late"] + counts["early_exit"] + counts["missing_checkout"]
        return {
            "total": len(rows),
            "scheduled": scheduled,
            "with_punch": with_punch,
            "present": counts["present"],
            "checked_in": counts["checked_in"],
            "late": counts["late"],
            "early_exit": counts["early_exit"],
            "missing_checkout": counts["missing_checkout"],
            "absent": counts["absent"],
            "on_leave": counts["on_leave"],
            "off_day": counts["off_day"],
            "issues": issue_count,
            "worked_hours": round(sum(row["worked_hours"] for row in rows), 2),
            "coverage": self._percent(with_punch, scheduled),
        }

    @api.model
    def _get_status_breakdown(self, rows):
        total = len(rows)
        counts = defaultdict(int)
        for row in rows:
            counts[row["status"]] += 1
        order = ["present", "checked_in", "late", "early_exit", "missing_checkout", "absent", "on_leave", "off_day"]
        return [
            {
                "key": key,
                "label": self.STATUS_META[key]["label"],
                "count": counts[key],
                "percent": self._percent(counts[key], total),
                "color": self.STATUS_META[key]["color"],
                "tone": self.STATUS_META[key]["tone"],
            }
            for key in order
        ]

    @api.model
    def _get_department_breakdown(self, rows):
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["department"]].append(row)

        departments = []
        for department, department_rows in grouped.items():
            summary = self._get_summary(department_rows)
            departments.append({
                "name": department,
                "total": summary["total"],
                "present": summary["present"],
                "checked_in": summary["checked_in"],
                "absent": summary["absent"],
                "late": summary["late"],
                "early_exit": summary["early_exit"],
                "on_leave": summary["on_leave"],
                "missing_checkout": summary["missing_checkout"],
                "coverage": summary["coverage"],
            })

        departments.sort(key=lambda item: (-(item["absent"] + item["late"] + item["missing_checkout"]), item["name"]))
        return departments

    @api.model
    def _get_trend_day(self, day, employees, attendance_map, leave_map):
        day_start_utc, day_end_utc, timezone = self._get_day_bounds(day)
        rows = self._get_day_rows(
            employees,
            day,
            day_start_utc,
            day_end_utc,
            timezone,
            attendance_map,
            leave_map,
        )
        summary = self._get_summary(rows)
        return {
            "date": fields.Date.to_string(day),
            "label": day.strftime("%a"),
            "day": day.strftime("%d"),
            "present": summary["present"],
            "checked_in": summary["checked_in"],
            "absent": summary["absent"],
            "on_leave": summary["on_leave"],
            "late": summary["late"] + summary["early_exit"],
            "missing_checkout": summary["missing_checkout"],
            "coverage": summary["coverage"],
            "total": summary["total"],
        }

    @api.model
    def _percent(self, value, total):
        if not total:
            return 0
        return round((float(value or 0.0) / float(total or 0.0)) * 100.0, 2)
