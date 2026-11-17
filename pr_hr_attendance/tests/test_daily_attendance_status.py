from datetime import datetime, timedelta

from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDailyAttendanceStatus(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Attendance = cls.env["hr.attendance"]
        cls.calendar = cls.env["resource.calendar"].create({
            "name": "Riyadh Daily Status Calendar",
            "tz": "Asia/Riyadh",
            "company_id": cls.env.company.id,
            "attendance_ids": [Command.clear()],
        })
        cls.biometric_employee = cls.env["hr.employee"].create({
            "name": "Daily Status Biometric Employee",
            "identification_id": "DAILY-STATUS-001",
            "company_id": cls.env.company.id,
            "resource_calendar_id": cls.calendar.id,
            "compute_attendance": True,
        })

    def test_sentinel_checkout_stays_missing_or_absent_until_real_checkout(self):
        check_in = datetime(2026, 6, 1, 5, 30, 0)  # 08:30 Asia/Riyadh
        attendance = self.Attendance.sudo().with_context(
            attendance_policy_source="biometric",
        ).create({
            "employee_id": self.biometric_employee.id,
            "check_in": check_in,
        })

        attendance.sudo().with_context(
            attendance_policy_source="biometric",
            allow_late_attendance=True,
        ).write({"check_out": check_in})

        # Same local day: sentinel check_out == check_in is still missing_punch.
        attendance._refresh_daily_attendance_status(now=datetime(2026, 6, 1, 18, 0, 0))
        self.assertEqual(attendance.attendance_day_status, "missing_punch")

        # After local midnight: sentinel check_out == check_in becomes absent.
        attendance._refresh_daily_attendance_status(now=datetime(2026, 6, 1, 21, 5, 0))
        self.assertEqual(attendance.attendance_day_status, "absent")
        self.assertEqual(
            attendance.attendance_status_reason,
            "The missing daily punch was not resolved before midnight.",
        )

        # Real checkout > check_in recovers status to normal even days later.
        attendance.sudo().with_context(
            attendance_policy_source="biometric",
            allow_late_attendance=True,
        ).write({"check_out": check_in + timedelta(hours=9)})
        self.assertEqual(attendance.attendance_day_status, "normal")
        self.assertFalse(attendance.attendance_status_reason)

    def test_finalize_cron_recovers_missing_punch_absent_with_valid_checkout_only(self):
        check_in = datetime(2026, 6, 2, 5, 30, 0)
        # Case 1: Completed attendance still stuck as missing-punch absent.
        recoverable = self.Attendance.sudo().with_context(
            attendance_policy_source="biometric",
        ).create({
            "employee_id": self.biometric_employee.id,
            "check_in": check_in,
            "check_out": check_in + timedelta(hours=9),
        })
        recoverable.with_context(skip_daily_attendance_status=True).write({
            "attendance_day_status": "absent",
            "attendance_status_reason": "The missing daily punch was not resolved before midnight.",
        })

        # Case 2: Genuine missing punch with stale worked_hours from legacy SQL.
        genuine_sentinel = self.Attendance.sudo().with_context(
            attendance_policy_source="biometric",
        ).create({
            "employee_id": self.biometric_employee.id,
            "check_in": datetime(2026, 6, 3, 5, 30, 0),
            "check_out": datetime(2026, 6, 3, 5, 30, 0),
        })
        self.env.cr.execute(
            """
            UPDATE hr_attendance
               SET worked_hours = 8.5,
                   attendance_day_status = 'absent',
                   attendance_status_reason = 'The missing daily punch was not resolved before midnight.'
             WHERE id = %s
            """,
            [genuine_sentinel.id],
        )
        genuine_sentinel.invalidate_recordset()

        # Case 3: Late check-in (>= 09:00 Asia/Riyadh) must stay absent even with valid checkout.
        late_att = self.Attendance.sudo().with_context(
            attendance_policy_source="biometric",
        ).create({
            "employee_id": self.biometric_employee.id,
            "check_in": datetime(2026, 6, 4, 6, 15, 0),  # 09:15 Asia/Riyadh
            "check_out": datetime(2026, 6, 4, 15, 15, 0),
        })
        self.assertEqual(late_att.attendance_day_status, "absent")

        # Case 4: Unrelated absent reason (e.g. task-list absence) must NOT be cleared.
        task_absent = self.Attendance.sudo().with_context(
            attendance_policy_source="biometric",
        ).create({
            "employee_id": self.biometric_employee.id,
            "check_in": datetime(2026, 6, 7, 5, 30, 0),
            "check_out": datetime(2026, 6, 7, 14, 30, 0),
        })
        task_absent.with_context(skip_daily_attendance_status=True).write({
            "attendance_day_status": "absent",
            "attendance_status_reason": "No task list was submitted for this working day before midnight.",
        })

        self.Attendance.cron_finalize_daily_attendance_statuses()

        recoverable.invalidate_recordset()
        genuine_sentinel.invalidate_recordset()
        late_att.invalidate_recordset()
        task_absent.invalidate_recordset()

        self.assertEqual(recoverable.attendance_day_status, "normal")
        self.assertFalse(recoverable.attendance_status_reason)

        self.assertEqual(genuine_sentinel.worked_hours, 0.0)
        self.assertEqual(genuine_sentinel.attendance_day_status, "absent")

        self.assertEqual(late_att.attendance_day_status, "absent")

        self.assertEqual(task_absent.attendance_day_status, "absent")
        self.assertEqual(
            task_absent.attendance_status_reason,
            "No task list was submitted for this working day before midnight.",
        )
