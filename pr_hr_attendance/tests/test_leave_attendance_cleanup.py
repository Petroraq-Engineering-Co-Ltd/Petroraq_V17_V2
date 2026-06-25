from datetime import date

from odoo.tests.common import tagged

from .common import AttendancePolicyCase


@tagged("post_install", "-at_install")
class TestLeaveAttendanceCleanup(AttendancePolicyCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        leave_type_values = {
            "name": "Sick Leave",
            "requires_allocation": "no",
            "request_unit": "day",
        }
        if "leave_type" in cls.env["hr.leave.type"]._fields:
            leave_type_values["leave_type"] = "sick_leave"
            leave_type_values["is_paid"] = True
        cls.sick_leave_type = cls.env["hr.leave.type"].create(leave_type_values)

        other_leave_type_values = {
            "name": "Business Trip",
            "requires_allocation": "no",
            "request_unit": "day",
        }
        if "leave_type" in cls.env["hr.leave.type"]._fields:
            other_leave_type_values["leave_type"] = "business_leave"
            other_leave_type_values["is_paid"] = True
        cls.business_leave_type = cls.env["hr.leave.type"].create(other_leave_type_values)

    def _validated_leave(self, employee, leave_type, leave_date):
        leave_values = {
            "name": "%s for %s" % (leave_type.display_name, employee.display_name),
            "employee_id": employee.id,
            "holiday_status_id": leave_type.id,
            "request_date_from": leave_date,
            "request_date_to": leave_date,
        }
        if "employee_ids" in self.env["hr.leave"]._fields:
            leave_values["employee_ids"] = [(6, 0, employee.ids)]
        leave = self.env["hr.leave"].sudo().with_context(
            tracking_disable=True,
            leave_fast_create=True,
            leave_skip_state_check=True,
        ).create(leave_values)
        leave.sudo().write({"state": "validate"})
        return leave

    def test_validated_sick_leave_deletes_overlapping_attendance(self):
        attendance = self.Attendance.sudo().with_context(
            attendance_policy_source="biometric",
        ).create(self.attendance_values(self.biometric_employee))

        self._validated_leave(
            self.biometric_employee,
            self.sick_leave_type,
            date(2026, 6, 1),
        )

        self.assertFalse(attendance.exists())

    def test_non_replacing_leave_keeps_attendance(self):
        attendance = self.Attendance.sudo().with_context(
            attendance_policy_source="biometric",
        ).create(self.attendance_values(self.biometric_employee, offset_days=1))

        self._validated_leave(
            self.biometric_employee,
            self.business_leave_type,
            date(2026, 6, 2),
        )

        self.assertTrue(attendance.exists())
