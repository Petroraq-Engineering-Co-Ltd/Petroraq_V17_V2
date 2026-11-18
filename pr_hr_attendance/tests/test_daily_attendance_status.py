from datetime import date, datetime, timedelta

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

        # Case 3: Late check-in (> 09:00:00 Asia/Riyadh) must stay absent even with valid checkout.
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

        # Case 5: Legacy historical 09:00:00 absent record must stay untouched (forward-only).
        legacy_nine_absent = self.Attendance.sudo().with_context(
            attendance_policy_source="biometric",
        ).create({
            "employee_id": self.biometric_employee.id,
            "check_in": datetime(2026, 6, 8, 6, 0, 0),  # 09:00:00 Asia/Riyadh
            "check_out": datetime(2026, 6, 8, 15, 0, 0),
        })
        legacy_nine_absent.with_context(skip_daily_attendance_status=True).write({
            "attendance_day_status": "absent",
            "attendance_status_reason": "Check-in was at or after 09:00:00.",
        })

        self.Attendance.cron_finalize_daily_attendance_statuses()

        recoverable.invalidate_recordset()
        genuine_sentinel.invalidate_recordset()
        late_att.invalidate_recordset()
        task_absent.invalidate_recordset()
        legacy_nine_absent.invalidate_recordset()

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

        self.assertEqual(legacy_nine_absent.attendance_day_status, "absent")
        self.assertEqual(
            legacy_nine_absent.attendance_status_reason,
            "Check-in was at or after 09:00:00.",
        )

    def test_late_cutoff_exact_second_boundary_on_attendance(self):
        """08:59:59 and 09:00:00 local are present; 09:00:01+ local are absent."""
        cases = [
            # (local day, UTC check_in, expected status, expected reason)
            (datetime(2026, 6, 9, 5, 59, 59), "normal", False),   # 08:59:59 Asia/Riyadh
            (datetime(2026, 6, 10, 6, 0, 0), "normal", False),    # 09:00:00 Asia/Riyadh
            (datetime(2026, 6, 11, 6, 0, 1), "absent", "Check-in was after 09:00:00."),   # 09:00:01 Asia/Riyadh
            (datetime(2026, 6, 14, 6, 0, 59), "absent", "Check-in was after 09:00:00."),  # 09:00:59 Asia/Riyadh
        ]
        for check_in, expected_status, expected_reason in cases:
            att = self.Attendance.sudo().with_context(
                attendance_policy_source="biometric",
            ).create({
                "employee_id": self.biometric_employee.id,
                "check_in": check_in,
                "check_out": check_in + timedelta(hours=9),
            })
            self.assertEqual(att.attendance_day_status, expected_status, f"Failed for {check_in}")
            if expected_reason:
                self.assertEqual(att.attendance_status_reason, expected_reason)
            else:
                self.assertFalse(att.attendance_status_reason)

    def test_late_cutoff_exact_second_boundary_on_attendance_sheet(self):
        """Sheet cutoff distinguishes 09:00:00 (present) from 09:00:01-09:00:59 (absent)."""
        policy = self.env["hr.attendance.policy"].create({
            "name": "Cutoff Boundary Policy",
            **{
                field: self.env[model].create({"name": f"Boundary {field}"}).id
                for field, model in (
                    ("late_rule_id", "hr.late.rule"),
                    ("early_rule_id", "hr.early.rule"),
                    ("absence_rule_id", "hr.absence.rule"),
                    ("diff_rule_id", "hr.diff.rule"),
                )
            },
        })
        # Create biometric attendances on 5 consecutive working days in Asia/Riyadh (UTC+3).
        day_specs = [
            (date(2026, 6, 15), datetime(2026, 6, 15, 5, 59, 59), 8 + 59 / 60.0, False),  # 08:59:59 -> present
            (date(2026, 6, 16), datetime(2026, 6, 16, 6, 0, 0), 9.0, False),              # 09:00:00 -> present
            (date(2026, 6, 17), datetime(2026, 6, 17, 6, 0, 1), 9.0, True),               # 09:00:01 -> absent
            (date(2026, 6, 18), datetime(2026, 6, 18, 6, 0, 59), 9.0, True),              # 09:00:59 -> absent
            (date(2026, 6, 21), datetime(2026, 6, 21, 6, 1, 0), 9 + 1 / 60.0, True),      # 09:01:00 -> absent
        ]
        line_vals = []
        for local_day, utc_in, ac_sign_in_float, _expect_absent in day_specs:
            self.Attendance.sudo().with_context(
                attendance_policy_source="biometric",
            ).create({
                "employee_id": self.biometric_employee.id,
                "check_in": utc_in,
                "check_out": utc_in + timedelta(hours=9),
            })
            line_vals.append(Command.create({
                "date": local_day,
                "day": str(local_day.weekday()),
                "pl_sign_in": 8.0,
                "pl_sign_out": 17.0,
                "ac_sign_in": ac_sign_in_float,
                "ac_sign_out": ac_sign_in_float + 9.0,
                "worked_hours": 9.0,
                "late_in": 0.0,
                "early_check_out": 0.5,
                "overtime": 0.5,
            }))
        # Also include a predictive projected line at ac_sign_in == 9.0 with no punch -> stays present.
        projected_day = date(2026, 6, 22)
        line_vals.append(Command.create({
            "date": projected_day,
            "day": str(projected_day.weekday()),
            "pl_sign_in": 9.0,
            "pl_sign_out": 18.0,
            "ac_sign_in": 9.0,
            "ac_sign_out": 18.0,
            "worked_hours": 9.0,
        }))

        sheet = self.env["attendance.sheet"].create({
            "employee_id": self.biometric_employee.id,
            "date_from": date(2026, 6, 15),
            "date_to": date(2026, 6, 22),
            "att_policy_id": policy.id,
            "line_ids": line_vals,
        })
        sheet._mark_late_checkins_as_absent()

        lines_by_date = {line.date: line for line in sheet.line_ids}
        for local_day, _utc_in, _ac_float, expect_absent in day_specs:
            line = lines_by_date[local_day]
            if expect_absent:
                self.assertEqual(line.status, "ab", f"Expected absent on {local_day}")
                self.assertEqual(line.late_in, 0.0)
                self.assertEqual(line.early_check_out, 0.0)
                self.assertEqual(line.overtime, 0.0)
            else:
                self.assertNotEqual(line.status, "ab", f"Expected present on {local_day}")

        self.assertNotEqual(lines_by_date[projected_day].status, "ab")
