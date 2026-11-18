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

    def _create_etm_idle_hours(self, employee, saturday, hours_per_day):
        IdleDay = self.env["employee.task.idle.day"].sudo()
        sunday = saturday - timedelta(days=6)
        for offset in range(5):  # Sun-Thu
            IdleDay.create({
                "employee_id": employee.id,
                "date": sunday + timedelta(days=offset),
                "approved_hours": hours_per_day,
            })

    def test_etm_saturday_earned_off_and_required_working_parity(self):
        """Earned-off Saturdays (>=40h) are never absent; <40h Saturdays are required."""
        if (
            not hasattr(self.env["hr.employee"], "_etm_saturday_off_map")
            or "employee.task.idle.day" not in self.env
        ):
            self.skipTest("ETM attendance policy modules are not installed.")

        saturday = date(2026, 7, 11)  # Saturday >= 2026-07-01
        self.env["ir.config_parameter"].sudo().set_param(
            "pr_task_attendance.enforce_from", "2026-07-01"
        )

        six_day_calendar = self.env["resource.calendar"].create({
            "name": "Riyadh 6-Day Calendar (Sun-Thu + Sat)",
            "tz": "Asia/Riyadh",
            "company_id": self.env.company.id,
            "attendance_ids": [Command.clear()] + [
                Command.create({
                    "name": f"Workday {weekday}",
                    "dayofweek": str(weekday),
                    "day_period": "morning",
                    "hour_from": 8.0,
                    "hour_to": 17.0,
                })
                for weekday in (6, 0, 1, 2, 3, 5)  # Sun-Thu + Sat
            ],
        })

        Attendance = self.env["hr.attendance"].sudo().with_context(
            attendance_policy_source="biometric",
        )
        Leave = self.env["hr.leave"]
        Detail = self.env["de.hr.leave.absentee.detail"]

        # 1. Earned-off Saturday (>= 40h) + voluntary punch after 09:00:00 -> NOT absent.
        emp_earned_late = self.env["hr.employee"].create({
            "name": "ETM Earned Late Saturday Employee",
            "identification_id": "ETM-SAT-001",
            "company_id": self.env.company.id,
            "resource_calendar_id": six_day_calendar.id,
            "compute_attendance": True,
            "etm_attendance_policy_enabled": True,
        })
        self._create_etm_idle_hours(emp_earned_late, saturday, 8.0)  # 40.0h
        Attendance.create({
            "employee_id": emp_earned_late.id,
            "check_in": datetime(2026, 7, 11, 7, 30, 0),  # 10:30:00 Asia/Riyadh
            "check_out": datetime(2026, 7, 11, 14, 0, 0),
        })
        self.assertEqual(
            Leave._get_employee_absentee_day_rows(emp_earned_late, saturday, saturday),
            [],
        )
        action = Detail.action_open_employee_absentees(
            emp_earned_late.id,
            duration="custom",
            date_from=saturday,
            date_to=saturday,
        )
        self.assertEqual(action["domain"], [("id", "in", [])])

        # 2. Earned-off Saturday (>= 40h) + no punch -> NOT absent.
        emp_earned_nopunch = self.env["hr.employee"].create({
            "name": "ETM Earned Off No Punch Employee",
            "identification_id": "ETM-SAT-002",
            "company_id": self.env.company.id,
            "resource_calendar_id": six_day_calendar.id,
            "compute_attendance": True,
            "etm_attendance_policy_enabled": True,
        })
        self._create_etm_idle_hours(emp_earned_nopunch, saturday, 8.0)  # 40.0h
        self.assertEqual(
            Leave._get_employee_absentee_day_rows(emp_earned_nopunch, saturday, saturday),
            [],
        )

        # 3. Earned-off Saturday (>= 40h) + missing-checkout sentinel (check_in == check_out) -> NOT absent.
        emp_earned_sentinel = self.env["hr.employee"].create({
            "name": "ETM Earned Sentinel Employee",
            "identification_id": "ETM-SAT-003",
            "company_id": self.env.company.id,
            "resource_calendar_id": six_day_calendar.id,
            "compute_attendance": True,
            "etm_attendance_policy_enabled": True,
        })
        self._create_etm_idle_hours(emp_earned_sentinel, saturday, 8.0)  # 40.0h
        sentinel_ts = datetime(2026, 7, 11, 7, 30, 0)
        Attendance.with_context(allow_late_attendance=True).create({
            "employee_id": emp_earned_sentinel.id,
            "check_in": sentinel_ts,
            "check_out": sentinel_ts,
        })
        self.assertEqual(
            Leave._get_employee_absentee_day_rows(emp_earned_sentinel, saturday, saturday),
            [],
        )

        # 4. Non-earned Saturday (< 40h) on 6-day calendar + late punch -> IS absent.
        emp_under_6d = self.env["hr.employee"].create({
            "name": "ETM Under 40h 6-Day Employee",
            "identification_id": "ETM-SAT-004",
            "company_id": self.env.company.id,
            "resource_calendar_id": six_day_calendar.id,
            "compute_attendance": True,
            "etm_attendance_policy_enabled": True,
        })
        self._create_etm_idle_hours(emp_under_6d, saturday, 6.4)  # 32.0h
        Attendance.create({
            "employee_id": emp_under_6d.id,
            "check_in": datetime(2026, 7, 11, 7, 30, 0),  # 10:30:00 Asia/Riyadh
            "check_out": datetime(2026, 7, 11, 14, 0, 0),
        })
        under_6d_rows = Leave._get_employee_absentee_day_rows(emp_under_6d, saturday, saturday)
        self.assertEqual(len(under_6d_rows), 1)
        self.assertEqual(under_6d_rows[0]["reason"], "Late check-in after 09:00:00")

        # 5. Non-earned Saturday (< 40h) on 5-day Sun-Thu calendar + no punch -> IS absent with fallback shift.
        emp_under_5d = self.env["hr.employee"].create({
            "name": "ETM Under 40h 5-Day Employee",
            "identification_id": "ETM-SAT-005",
            "company_id": self.env.company.id,
            "resource_calendar_id": self.calendar.id,  # Sun-Thu only
            "compute_attendance": True,
            "etm_attendance_policy_enabled": True,
        })
        self._create_etm_idle_hours(emp_under_5d, saturday, 6.0)  # 30.0h
        under_5d_rows = Leave._get_employee_absentee_day_rows(emp_under_5d, saturday, saturday)
        self.assertEqual(len(under_5d_rows), 1)
        self.assertEqual(under_5d_rows[0]["reason"], "No attendance")
        self.assertEqual(under_5d_rows[0]["shift"], "08:00-17:00")

        # 6. Non-ETM employee on 6-day calendar with 40h idle rows + late punch -> IS absent.
        emp_non_etm = self.env["hr.employee"].create({
            "name": "Non-ETM 6-Day Employee",
            "identification_id": "ETM-SAT-006",
            "company_id": self.env.company.id,
            "resource_calendar_id": six_day_calendar.id,
            "compute_attendance": True,
            "etm_attendance_policy_enabled": False,
        })
        self._create_etm_idle_hours(emp_non_etm, saturday, 8.0)  # 40.0h (ignored because policy disabled)
        Attendance.create({
            "employee_id": emp_non_etm.id,
            "check_in": datetime(2026, 7, 11, 7, 30, 0),
            "check_out": datetime(2026, 7, 11, 14, 0, 0),
        })
        non_etm_rows = Leave._get_employee_absentee_day_rows(emp_non_etm, saturday, saturday)
        self.assertEqual(len(non_etm_rows), 1)
        self.assertEqual(non_etm_rows[0]["reason"], "Late check-in after 09:00:00")

        # Verify Period Absentees card matches all 6 employees consistently.
        with patch.object(
            type(Leave),
            "_get_period_date_range",
            return_value=(saturday, saturday),
        ):
            period_by_emp = {
                row["employee_id"]: row["absent_days"]
                for row in Leave.get_period_absentees("custom")
            }
        self.assertEqual(period_by_emp[emp_earned_late.id], 0)
        self.assertEqual(period_by_emp[emp_earned_nopunch.id], 0)
        self.assertEqual(period_by_emp[emp_earned_sentinel.id], 0)
        self.assertEqual(period_by_emp[emp_under_6d.id], 1)
        self.assertEqual(period_by_emp[emp_under_5d.id], 1)
        self.assertEqual(period_by_emp[emp_non_etm.id], 1)
