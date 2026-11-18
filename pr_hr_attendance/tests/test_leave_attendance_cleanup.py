from datetime import date, datetime

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

    def test_future_validated_leave_keeps_earlier_open_checkin(self):
        """Approving a future leave must never delete today's open check-in."""
        open_today = self.Attendance.sudo().with_context(
            attendance_policy_source="biometric",
        ).create({
            "employee_id": self.biometric_employee.id,
            "check_in": datetime(2026, 10, 29, 4, 54, 37),  # 07:54:37 Asia/Riyadh
        })

        self._validated_leave(
            self.biometric_employee,
            self.sick_leave_type,
            date(2026, 11, 5),
        )

        self.assertTrue(open_today.exists())
        self.assertFalse(open_today.check_out)

    def test_same_day_validated_leave_deletes_open_checkin(self):
        """An open check-in on the leave day itself is still cleaned up."""
        open_on_leave_day = self.Attendance.sudo().with_context(
            attendance_policy_source="biometric",
        ).create({
            "employee_id": self.biometric_employee.id,
            "check_in": datetime(2026, 11, 6, 5, 0, 0),  # 08:00:00 Asia/Riyadh
        })

        self._validated_leave(
            self.biometric_employee,
            self.sick_leave_type,
            date(2026, 11, 6),
        )

        self.assertFalse(open_on_leave_day.exists())

    def test_validated_leave_deletes_overnight_overlap_and_keeps_prior_closed(self):
        """Closed overnight attendance crossing into leave day is deleted; prior day is kept."""
        prior_closed = self.Attendance.sudo().with_context(
            attendance_policy_source="biometric",
        ).create({
            "employee_id": self.biometric_employee.id,
            "check_in": datetime(2026, 11, 8, 5, 0, 0),   # 08:00 Asia/Riyadh
            "check_out": datetime(2026, 11, 8, 14, 0, 0),  # 17:00 Asia/Riyadh
        })
        overnight_overlap = self.Attendance.sudo().with_context(
            attendance_policy_source="biometric",
        ).create({
            "employee_id": self.biometric_employee.id,
            "check_in": datetime(2026, 11, 8, 19, 0, 0),  # 22:00 Nov 8 Asia/Riyadh
            "check_out": datetime(2026, 11, 9, 2, 0, 0),  # 05:00 Nov 9 Asia/Riyadh
        })

        self._validated_leave(
            self.biometric_employee,
            self.sick_leave_type,
            date(2026, 11, 9),
        )

        self.assertTrue(prior_closed.exists())
        self.assertFalse(overnight_overlap.exists())
