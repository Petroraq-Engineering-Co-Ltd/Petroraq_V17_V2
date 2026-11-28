from datetime import date, datetime

from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAttendanceManagementDashboard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({
            "name": "Dashboard Joining Test Company",
            "vat": "PRATTDASHJOIN01",
        })
        cls.calendar = cls.env["resource.calendar"].create({
            "name": "Dashboard 08:00 - 17:00",
            "tz": "Asia/Riyadh",
            "company_id": cls.company.id,
            "attendance_ids": [Command.clear()] + [
                Command.create({
                    "name": str(day),
                    "dayofweek": str(day),
                    "day_period": "morning",
                    "hour_from": 8,
                    "hour_to": 17,
                })
                for day in range(7)
            ],
        })
        cls.company.resource_calendar_id = cls.calendar
        cls.department = cls.env["hr.department"].create({
            "name": "Dashboard Test Dept",
            "company_id": cls.company.id,
        })
        cls.Dashboard = cls.env["de.hr.attendance.management.dashboard"].with_company(cls.company)

    @classmethod
    def _create_employee(cls, name, ident):
        return cls.env["hr.employee"].create({
            "name": name,
            "identification_id": ident,
            "company_id": cls.company.id,
            "department_id": cls.department.id,
            "resource_calendar_id": cls.calendar.id,
            "compute_attendance": True,
        })

    @classmethod
    def _create_contract(cls, employee, joining_date, date_start=None, state="open"):
        return cls.env["hr.contract"].create({
            "name": f"Contract {employee.name}",
            "employee_id": employee.id,
            "company_id": cls.company.id,
            "resource_calendar_id": cls.calendar.id,
            "wage": 5000.0,
            "date_start": date_start or joining_date,
            "joining_date": joining_date,
            "state": state,
        })

    def test_pre_joining_employee_excluded_from_day_and_trend(self):
        existing_emp = self._create_employee("Existing Employee", "DASH-JOIN-001")
        self._create_contract(existing_emp, date(2026, 11, 1))

        new_emp = self._create_employee("New Joiner", "DASH-JOIN-002")
        contract = self._create_contract(new_emp, date(2026, 11, 19))
        new_emp.contract_id = contract

        # Day before joining (2026-11-18): new_emp must not appear at all
        before_data = self.Dashboard.get_dashboard_data(
            selected_date="2026-11-18",
            department_id=self.department.id,
        )
        before_ids = [row["employee_id"] for row in before_data["timeline_rows"]]
        self.assertEqual(before_ids, [existing_emp.id])
        self.assertEqual(before_data["summary"]["total"], 1)
        self.assertEqual(before_data["summary"]["absent"], 1)

        # Day of joining (2026-11-19): new_emp appears
        on_day_data = self.Dashboard.get_dashboard_data(
            selected_date="2026-11-19",
            department_id=self.department.id,
        )
        on_day_ids = {row["employee_id"] for row in on_day_data["timeline_rows"]}
        self.assertEqual(on_day_ids, {existing_emp.id, new_emp.id})
        self.assertEqual(on_day_data["summary"]["total"], 2)

        # 7-day trend ending 2026-11-22: Nov 16-18 have total=1, Nov 19-22 have total=2
        trend_data = self.Dashboard.get_dashboard_data(
            selected_date="2026-11-22",
            department_id=self.department.id,
        )
        totals_by_date = {item["date"]: item["total"] for item in trend_data["daily_trend"]}
        self.assertEqual(totals_by_date["2026-11-16"], 1)
        self.assertEqual(totals_by_date["2026-11-17"], 1)
        self.assertEqual(totals_by_date["2026-11-18"], 1)
        self.assertEqual(totals_by_date["2026-11-19"], 2)
        self.assertEqual(totals_by_date["2026-11-22"], 2)

    def test_contract_fallback_without_employee_contract_id(self):
        emp = self._create_employee("Draft Contract Joiner", "DASH-JOIN-003")
        # contract_id on hr.employee is not set, but a non-cancelled contract exists
        self._create_contract(emp, date(2026, 11, 19), state="draft")
        self.assertFalse(emp.joining_date)

        before_data = self.Dashboard.get_dashboard_data(
            selected_date="2026-11-18",
            department_id=self.department.id,
        )
        self.assertEqual(before_data["timeline_rows"], [])
        self.assertEqual(before_data["summary"]["total"], 0)

    def test_employee_without_joining_date_is_not_excluded(self):
        emp = self._create_employee("No Contract Employee", "DASH-JOIN-004")
        data = self.Dashboard.get_dashboard_data(
            selected_date="2026-11-18",
            department_id=self.department.id,
        )
        self.assertEqual([row["employee_id"] for row in data["timeline_rows"]], [emp.id])

    def test_actual_punch_before_joining_date_is_still_shown(self):
        emp = self._create_employee("Early Punch Joiner", "DASH-JOIN-005")
        contract = self._create_contract(emp, date(2026, 11, 19))
        emp.contract_id = contract

        self.env["hr.attendance"].sudo().with_context(
            attendance_policy_source="biometric",
        ).create({
            "employee_id": emp.id,
            "check_in": datetime(2026, 11, 18, 5, 0, 0),   # 08:00 Asia/Riyadh
            "check_out": datetime(2026, 11, 18, 14, 0, 0), # 17:00 Asia/Riyadh
        })

        data = self.Dashboard.get_dashboard_data(
            selected_date="2026-11-18",
            department_id=self.department.id,
        )
        self.assertEqual(len(data["timeline_rows"]), 1)
        self.assertEqual(data["timeline_rows"][0]["employee_id"], emp.id)
        self.assertEqual(data["timeline_rows"][0]["status"], "present")
