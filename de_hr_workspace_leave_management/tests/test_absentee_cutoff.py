from datetime import date, datetime, timedelta
from unittest.mock import patch

from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAbsenteeCutoff(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create({
            "name": "Riyadh Leave Absentee Calendar",
            "tz": "Asia/Riyadh",
            "company_id": cls.env.company.id,
            "attendance_ids": [Command.clear()] + [
                Command.create({
                    "name": f"Workday {weekday}",
                    "dayofweek": str(weekday),
                    "day_period": "morning",
                    "hour_from": 8.0,
                    "hour_to": 17.0,
                })
                for weekday in (6, 0, 1, 2, 3)  # Sun-Thu
            ],
        })
        cls.employee = cls.env["hr.employee"].create({
            "name": "Absentee Cutoff Employee",
            "identification_id": "ABS-CUTOFF-001",
            "company_id": cls.env.company.id,
            "resource_calendar_id": cls.calendar.id,
            "compute_attendance": True,
        })

    def test_absentee_cutoff_exact_second_boundary(self):
        """08:59:59 and 09:00:00 are on-time; 09:00:01 is late-absent."""
        Attendance = self.env["hr.attendance"].sudo().with_context(
            attendance_policy_source="biometric",
        )
        # Dates >= 2026-07-01 (absentee late policy start date) and Sun-Tue working days.
        punches = [
            datetime(2026, 7, 5, 5, 59, 59),  # Sun 08:59:59 Asia/Riyadh -> on-time
            datetime(2026, 7, 6, 6, 0, 0),    # Mon 09:00:00 Asia/Riyadh -> on-time
            datetime(2026, 7, 7, 6, 0, 1),    # Tue 09:00:01 Asia/Riyadh -> late absent
        ]
        for check_in in punches:
            Attendance.create({
                "employee_id": self.employee.id,
                "check_in": check_in,
                "check_out": check_in + timedelta(hours=9),
            })

        start = date(2026, 7, 5)
        end = date(2026, 7, 7)
        rows = self.env["hr.leave"]._get_employee_absentee_day_rows(
            self.employee, start, end
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2026-07-07")
        self.assertEqual(rows[0]["check_in"], "09:00:01")
        self.assertEqual(rows[0]["reason"], "Late check-in after 09:00:00")

        with patch.object(
            type(self.env["hr.leave"]),
            "_get_period_date_range",
            return_value=(start, end),
        ):
            period_rows = self.env["hr.leave"].get_period_absentees("custom")
        emp_row = next(
            row for row in period_rows if row["employee_id"] == self.employee.id
        )
        self.assertEqual(emp_row["absent_days"], 1)
