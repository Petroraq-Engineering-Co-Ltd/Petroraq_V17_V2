from datetime import date, datetime, timedelta

from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAttendanceReportCutoff(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create({
            "name": "Riyadh Report Cutoff Calendar",
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
            "name": "Report Cutoff Employee",
            "identification_id": "RPT-CUTOFF-001",
            "company_id": cls.env.company.id,
            "resource_calendar_id": cls.calendar.id,
            "compute_attendance": True,
        })

    def test_report_cutoff_uses_local_time_and_exact_second_boundary(self):
        """08:59:59 and 09:00:00 Asia/Riyadh are present; 09:00:01 is absent."""
        Attendance = self.env["hr.attendance"].sudo().with_context(
            attendance_policy_source="biometric",
        )
        punches = [
            datetime(2026, 7, 5, 5, 59, 59),  # Sun 08:59:59 Riyadh -> present
            datetime(2026, 7, 6, 6, 0, 0),    # Mon 09:00:00 Riyadh -> present
            datetime(2026, 7, 7, 6, 0, 1),    # Tue 09:00:01 Riyadh -> absent
        ]
        for check_in in punches:
            Attendance.create({
                "employee_id": self.employee.id,
                "check_in": check_in,
                "check_out": check_in + timedelta(hours=9),
            })

        wizard = self.env["attendance.report.wizard"].create({
            "year": "2026",
            "month": "7",
            "date_from": date(2026, 7, 5),
            "date_to": date(2026, 7, 7),
            "employee_ids": [Command.set(self.employee.ids)],
            "show_leaves": False,
        })
        rows, summary = wizard.get_attendance_data(self.employee)
        self.assertEqual(len(rows), 3)
        self.assertFalse(rows[0]["absent"])
        self.assertFalse(rows[1]["absent"])
        self.assertTrue(rows[2]["absent"])
        self.assertEqual(rows[2]["worked_hours"], "Absent (Late Check-in after 09:00:00)")
        self.assertEqual(summary["summary_absent_days"], 1)
