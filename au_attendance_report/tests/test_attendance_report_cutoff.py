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
        rows, summary = wizard._get_attendance_data(self.employee)
        self.assertEqual(len(rows), 3)
        self.assertFalse(rows[0]["absent"])
        self.assertFalse(rows[1]["absent"])
        self.assertTrue(rows[2]["absent"])
        self.assertEqual(rows[2]["worked_hours"], "Absent (Late Check-in after 09:00:00)")
        self.assertEqual(summary["summary_absent_days"], 1)

    def test_non_etm_scheduled_off_saturday_is_never_absent(self):
        """Saturday follows the work schedule of employees outside the ETM policy."""
        self.env["ir.config_parameter"].sudo().set_param(
            "pr_task_attendance.enforce_from", "2026-06-01",
        )
        check_in = datetime(2026, 7, 4, 7, 30)  # Sat 10:30 Riyadh
        self.env["hr.attendance"].sudo().with_context(
            attendance_policy_source="biometric",
        ).create({
            "employee_id": self.employee.id,
            "check_in": check_in,
            "check_out": check_in + timedelta(hours=4),
        })
        wizard = self.env["attendance.report.wizard"].create({
            "year": "2026",
            "month": "7",
            "date_from": date(2026, 7, 4),
            "date_to": date(2026, 7, 11),
            "employee_ids": [Command.set(self.employee.ids)],
            "show_leaves": False,
        })
        rows, _summary = wizard._get_attendance_data(self.employee)
        self.assertFalse(rows[0]["absent"])  # Sat 4 July: late punch
        self.assertEqual(rows[0]["actual_hours"], 0.0)
        self.assertFalse(rows[7]["absent"])  # Sat 11 July: no punch
        self.assertEqual(rows[7]["worked_hours"], "Holiday")

        # The ETM rule is unchanged: below 40 approved hours Saturday is required.
        self.employee.etm_attendance_policy_enabled = True
        rows, _summary = wizard._get_attendance_data(self.employee)
        self.assertTrue(rows[0]["absent"])
        self.assertTrue(rows[7]["absent"])
