from datetime import date, datetime, timedelta
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTaskAttendance(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Day = cls.env["hr.task.attendance.day"].sudo()
        cls.day = date(2026, 9, 14)  # Monday
        cls.midnight = datetime(2026, 9, 14, 21)  # Tuesday 00:00 Riyadh
        cls.env["ir.config_parameter"].sudo().set_param("pr_task_attendance.enforce_from", str(cls.day))
        base_group = cls.env.ref("base.group_user")
        workspace_group = cls.env.ref("de_hr_workspace.group_hr_employee_workspace")
        cls.employee_user = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Daily Task Employee", "login": "daily.task.employee.test",
            "groups_id": [Command.set((base_group | workspace_group | cls.env.ref("employee_task_management.group_task_employee")).ids)],
            "company_id": cls.env.company.id, "company_ids": [Command.set(cls.env.company.ids)],
            "tz": "Asia/Riyadh",
        })
        cls.other_user = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Other Task Employee", "login": "daily.task.other.test",
            "groups_id": [Command.set(base_group.ids)],
        })
        cls.hr_user = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Daily Task HR Manager", "login": "daily.task.hr.test",
            "groups_id": [Command.set((base_group | cls.env.ref("hr.group_hr_manager")).ids)],
            "company_id": cls.env.company.id, "company_ids": [Command.set(cls.env.company.ids)],
        })
        cls.calendar = cls.env["resource.calendar"].create({
            "name": "Daily Task Monday Tuesday Schedule", "tz": "Asia/Riyadh",
            "company_id": cls.env.company.id,
            "attendance_ids": [Command.clear()] + [Command.create({
                "name": "Shift", "dayofweek": weekday, "day_period": "morning",
                "hour_from": 8.0, "hour_to": 17.0,
            }) for weekday in ("0", "1")],
        })
        cls.manager = cls.env["hr.employee"].create({
            "name": "Task Line Manager", "company_id": cls.env.company.id,
        })
        cls.department = cls.env["hr.department"].create({
            "name": "Task Attendance Department", "manager_id": cls.manager.id,
        })
        cls.employee = cls.env["hr.employee"].create({
            "name": "Daily Task Attendance Employee", "user_id": cls.employee_user.id,
            "company_id": cls.env.company.id, "resource_calendar_id": cls.calendar.id,
            "department_id": cls.department.id, "parent_id": cls.manager.id,
            "compute_attendance": True,
        })

    def _attendance(self, offset=0, start_hour=5, end_hour=14):
        check_in = datetime(2026, 9, 14, start_hour) + timedelta(days=offset)
        return self.env["hr.attendance"].sudo().with_context(attendance_policy_source="biometric").create({
            "employee_id": self.employee.id, "check_in": check_in,
            "check_out": datetime(2026, 9, 14, end_hour) + timedelta(days=offset) if end_hour is not None else False,
        })

    def _submission(self, submitted_at, start=None, end=None, action="submitted"):
        task = self.env["employee.task.list"].sudo().with_context(etm_workflow=True).create({
            "employee_id": self.employee.id, "department_id": self.department.id,
            "manager_id": self.manager.id,
            "task_line_ids": [Command.create({
                "description": "Daily work", "start_date": start or self.day,
                "end_date": end or self.day,
                "subtask_ids": [Command.create({"name": "Daily activity", "hours": 1.0})],
            })],
        })
        return self.env["employee.task.approval.history"].sudo().create({
            "task_list_id": task.id, "action": action, "action_datetime": submitted_at,
        })

    def _absence(self):
        attendance = self._attendance()
        self.Day.cron_finalize_task_attendance(now=self.midnight)
        return attendance, attendance.task_attendance_day_id

    def test_absent_only_after_local_midnight_and_cron_is_idempotent(self):
        attendance = self._attendance()
        actual = (attendance.check_in, attendance.check_out, attendance.worked_hours, attendance.attendance_entry_source)
        self.Day.cron_finalize_task_attendance(now=self.midnight - timedelta(seconds=1))
        self.assertEqual(attendance.attendance_day_status, "normal")
        self.assertFalse(attendance.task_attendance_checked)
        self.Day.cron_finalize_task_attendance(now=self.midnight)
        self.assertEqual(attendance.attendance_day_status, "absent")
        self.assertEqual(attendance.task_attendance_day_id.date, self.day)
        self.Day.cron_finalize_task_attendance(now=self.midnight + timedelta(minutes=1))
        self.assertEqual(self.Day.search_count([("employee_id", "=", self.employee.id)]), 1)
        self.assertEqual(actual, (attendance.check_in, attendance.check_out, attendance.worked_hours, attendance.attendance_entry_source))

    def test_fresh_daily_submission_counts_but_previous_day_does_not(self):
        self._submission(datetime(2026, 9, 14, 12), end=self.day + timedelta(days=1))
        first = self._attendance()
        second = self._attendance(offset=1)
        self.Day.cron_finalize_task_attendance(now=self.midnight + timedelta(days=1))
        self.assertEqual(first.attendance_day_status, "normal")
        self.assertFalse(first.task_attendance_day_id)
        self.assertEqual(second.attendance_day_status, "absent")

    def test_assignment_or_future_task_does_not_count(self):
        self._submission(datetime(2026, 9, 14, 12), action="assigned")
        self._submission(datetime(2026, 9, 14, 13), start=self.day + timedelta(days=1), end=self.day + timedelta(days=1))
        attendance, unused = self._absence()
        self.assertEqual(attendance.attendance_day_status, "absent")

    def test_submitted_at_midnight_does_not_count_for_previous_day(self):
        self._submission(self.midnight)
        attendance, unused = self._absence()
        self.assertEqual(attendance.attendance_day_status, "absent")

    def test_off_day_and_calendar_leave_do_not_require_submission(self):
        off_day = self._attendance(offset=2)  # No Wednesday shift
        self.env["resource.calendar.leaves"].create({
            "name": "Employee leave", "calendar_id": self.calendar.id,
            "resource_id": self.employee.resource_id.id,
            "date_from": datetime(2026, 9, 14, 0), "date_to": datetime(2026, 9, 14, 20),
        })
        leave_day = self._attendance()
        self.Day.cron_finalize_task_attendance(now=self.midnight + timedelta(days=2))
        self.assertFalse((off_day | leave_day).mapped("task_attendance_day_id"))

    def test_partial_leave_still_requires_submission_for_remaining_work(self):
        self.env["resource.calendar.leaves"].create({
            "name": "Partial leave", "calendar_id": self.calendar.id,
            "resource_id": self.employee.resource_id.id,
            "date_from": datetime(2026, 9, 14, 5), "date_to": datetime(2026, 9, 14, 7),
        })
        attendance, unused = self._absence()
        self.assertEqual(attendance.attendance_day_status, "absent")

    def test_late_import_catches_up_without_changing_historical_attendance(self):
        old = self._attendance(offset=-7)
        self.Day.cron_finalize_task_attendance(now=self.midnight + timedelta(days=3))
        late = self._attendance()
        self.Day.cron_finalize_task_attendance(now=self.midnight + timedelta(days=3))
        self.assertFalse(old.task_attendance_day_id)
        self.assertEqual(late.attendance_day_status, "absent")

    def test_hr_approval_restores_actual_attendance_and_survives_refresh(self):
        attendance, day = self._absence()
        actual = (attendance.check_in, attendance.check_out, attendance.worked_hours)
        request = day.with_user(self.employee_user)
        request.write({"reason": "I worked onsite and could not submit."})
        request.action_request_present()
        with self.assertRaises(AccessError):
            request.action_approve()
        with self.assertRaises(AccessError):
            request.write({"state": "approved"})
        day.with_user(self.hr_user).action_approve()
        attendance._refresh_daily_attendance_status()
        self.assertEqual(attendance.attendance_day_status, "normal")
        self.assertEqual(actual, (attendance.check_in, attendance.check_out, attendance.worked_hours))
        self.assertEqual(day.decision_by_id, self.hr_user)
        self.Day.cron_finalize_task_attendance(now=self.midnight + timedelta(days=2))
        self.assertEqual(attendance.attendance_day_status, "normal")

    def test_rejection_and_late_submission_do_not_remove_absence(self):
        attendance, day = self._absence()
        request = day.with_user(self.employee_user)
        with self.assertRaises(UserError):
            request.action_request_present()
        request.write({"reason": "Please review my actual attendance."})
        request.action_request_present()
        hr_request = day.with_user(self.hr_user)
        hr_request.write({"hr_comment": "More evidence is needed."})
        hr_request.action_reject()
        self._submission(self.midnight + timedelta(hours=1))
        attendance._refresh_daily_attendance_status()
        self.assertEqual(attendance.attendance_day_status, "absent")
        self.assertEqual(day.state, "rejected")
        request.write({"reason": "Additional supporting explanation."})
        request.action_request_present()
        self.assertEqual(day.state, "pending")

    def test_approval_does_not_erase_other_attendance_issues(self):
        attendance = self._attendance(start_hour=7)  # 10:00 local, already late
        self.Day.cron_finalize_task_attendance(now=self.midnight)
        request = attendance.task_attendance_day_id.with_user(self.employee_user)
        request.write({"reason": "Accept my recorded arrival."})
        request.action_request_present()
        request.with_user(self.hr_user).action_approve()
        self.assertEqual(attendance.attendance_day_status, "absent")
        self.assertIn("09:00", attendance.attendance_status_reason)

    def test_other_employee_and_manual_state_override_are_blocked(self):
        attendance, day = self._absence()
        self.assertFalse(self.Day.with_user(self.other_user).search([("id", "=", day.id)]))
        with self.assertRaises(AccessError):
            day.with_user(self.other_user).action_request_present()
        with self.assertRaises(AccessError):
            attendance.with_user(self.employee_user).write({"task_attendance_day_id": False})
        with self.assertRaises(AccessError):
            self.Day.with_user(self.employee_user).cron_finalize_task_attendance(now=self.midnight)
        with self.assertRaises(AccessError):
            attendance.with_user(self.employee_user).unlink()

    def test_day_boundaries_follow_dst(self):
        start, end = self.Day._day_bounds(date(2026, 3, 8), "America/New_York")
        self.assertEqual((end - start).total_seconds(), 23 * 3600)

    def test_alternating_working_weeks_use_the_employee_calendar(self):
        self.calendar.write({"two_weeks_calendar": True})
        self.calendar.attendance_ids.write({"week_type": "0"})
        requirements = []
        for day in (self.day, self.day + timedelta(days=7)):
            start, end = self.Day._day_bounds(day, "Asia/Riyadh")
            requirements.append(self.Day._requires_submission(self.employee, day, start, end, "Asia/Riyadh"))
        self.assertEqual(sorted(requirements), [False, True])

    def test_daily_submit_records_new_submission_without_restarting_work(self):
        history = self._submission(datetime(2026, 9, 13, 12), end=self.day + timedelta(days=1))
        task = history.task_list_id
        task.with_context(etm_workflow=True).write({"state": "in_progress"})
        submitted_at = datetime(2026, 9, 14, 12)
        date_field = self.env["employee.task.approval.history"]._fields["action_datetime"]
        with patch("odoo.fields.Datetime.now", return_value=submitted_at), patch.object(date_field, "default", lambda rec: submitted_at):
            task.with_user(self.employee_user).action_submit_for_today()
            self.assertEqual(task.state, "in_progress")
            with self.assertRaises(UserError):
                task.with_user(self.employee_user).action_submit_for_today()
        attendance = self._attendance()
        self.Day.cron_finalize_task_attendance(now=self.midnight)
        self.assertFalse(attendance.task_attendance_day_id)

    def test_multiple_punches_share_one_absence_record(self):
        first = self._attendance(end_hour=8)
        self.Day.cron_finalize_task_attendance(now=self.midnight)
        late_import = self._attendance(start_hour=9)
        self.Day.cron_finalize_task_attendance(now=self.midnight + timedelta(hours=1))
        self.assertEqual(first.task_attendance_day_id, late_import.task_attendance_day_id)
        self.assertEqual(len(first.task_attendance_day_id.attendance_ids), 2)

    def test_global_calendar_holiday_is_exempt(self):
        self.env["resource.calendar.leaves"].create({
            "name": "Public calendar holiday", "calendar_id": self.calendar.id,
            "date_from": datetime(2026, 9, 14, 0), "date_to": datetime(2026, 9, 14, 20),
        })
        attendance = self._attendance()
        self.Day.cron_finalize_task_attendance(now=self.midnight)
        self.assertFalse(attendance.task_attendance_day_id)

    def test_hr_company_boundary_is_enforced(self):
        company = self.env["res.company"].create({"name": "Other task attendance company"})
        employee = self.env["hr.employee"].create({"name": "Other company employee", "company_id": company.id})
        day = self.Day.create({"employee_id": employee.id, "date": self.day, "timezone": "Asia/Riyadh"})
        with self.assertRaises(AccessError):
            day.with_user(self.hr_user).with_context(allowed_company_ids=self.env.company.ids).action_request_present()

    def test_unfinalized_sheet_restores_actual_values_on_approval(self):
        policy = self.env["hr.attendance.policy"].create({
            "name": "Daily task policy",
            **{field: self.env[model].create({"name": "Task policy rule"}).id for field, model in (
                ("late_rule_id", "hr.late.rule"), ("early_rule_id", "hr.early.rule"),
                ("absence_rule_id", "hr.absence.rule"), ("diff_rule_id", "hr.diff.rule"),
            )},
        })
        sheet = self.env["attendance.sheet"].create({
            "employee_id": self.employee.id, "date_from": self.day, "date_to": self.day,
            "att_policy_id": policy.id,
            "line_ids": [Command.create({
                "date": self.day, "day": "0", "pl_sign_in": 8, "pl_sign_out": 17,
                "ac_sign_in": 8, "ac_sign_out": 17, "worked_hours": 9,
            })],
        })
        attendance, day = self._absence()
        self.assertEqual(sheet.line_ids.status, "ab")
        self.assertEqual(sheet.line_ids.worked_hours, 0)
        request = day.with_user(self.employee_user)
        request.write({"reason": "Please accept the original attendance."})
        request.action_request_present()
        day.with_user(self.hr_user).action_approve()
        self.assertFalse(sheet.line_ids.status)
        self.assertEqual(sheet.line_ids.worked_hours, 9)
        self.assertFalse(sheet.line_ids.task_absence_snapshot)
