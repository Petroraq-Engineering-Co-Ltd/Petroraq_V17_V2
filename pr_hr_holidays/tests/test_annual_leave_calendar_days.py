from datetime import date, datetime

from odoo.tests.common import TransactionCase


class TestAnnualLeaveCalendarDays(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create({
            "name": "Annual Leave Calendar-Day Test Employee",
        })
        cls.annual_leave_type = cls.env["hr.leave.type"].create({
            "name": "Annual Leave Calendar-Day Test",
            "time_type": "leave",
            "request_unit": "day",
            "requires_allocation": "no",
            "leave_type": "annual_leave",
        })
        cls.business_leave_type = cls.env["hr.leave.type"].create({
            "name": "Business Leave Working-Day Test",
            "time_type": "leave",
            "request_unit": "day",
            "requires_allocation": "no",
            "leave_type": "business_leave",
        })

    def _new_time_off(self, leave_type):
        return self.env["hr.leave"].new({
            "employee_id": self.employee.id,
            "holiday_status_id": leave_type.id,
            "request_date_from": date(2099, 1, 1),  # Thursday
            "request_date_to": date(2099, 1, 4),    # Sunday
            "date_from": datetime(2099, 1, 1, 0, 0, 0),
            "date_to": datetime(2099, 1, 4, 23, 59, 59),
        })

    def _new_leave_request(self, leave_type):
        return self.env["pr.hr.leave.request"].new({
            "employee_id": self.employee.id,
            "company_id": self.env.company.id,
            "leave_type_id": leave_type.id,
            "date_from": date(2099, 1, 1),
            "date_to": date(2099, 1, 4),
        })

    def test_standard_time_off_consumes_inclusive_calendar_days(self):
        leave = self._new_time_off(self.annual_leave_type)
        self.assertEqual(leave._get_duration()[0], 4)

    def test_custom_request_consumes_inclusive_calendar_days(self):
        request = self._new_leave_request(self.annual_leave_type)
        request._compute_requested_days()
        self.assertEqual(request.requested_days, 4)

    def test_non_annual_request_keeps_working_day_calculation(self):
        request = self._new_leave_request(self.business_leave_type)
        request._compute_requested_days()
        self.assertEqual(request.requested_days, 2)

    def test_public_holiday_inside_annual_leave_is_consumed(self):
        if "hr.public.holiday" not in self.env:
            self.skipTest("Public-holiday module is not installed in this test database")
        self.env["hr.public.holiday"].create({
            "name": "Overlapping Annual Leave Test Holiday",
            "date_from": date(2099, 1, 3),
            "date_to": date(2099, 1, 3),
            "state": "active",
        })
        request = self._new_leave_request(self.annual_leave_type)
        request._compute_requested_days()
        self.assertEqual(request.requested_days, 4)
