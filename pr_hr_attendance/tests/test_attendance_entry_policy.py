from datetime import timedelta

import pytz

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import tagged

from .common import AttendancePolicyCase


@tagged("post_install", "-at_install")
class TestAttendanceEntryPolicy(AttendancePolicyCase):

    def test_manual_hr_create_modify_and_delete_is_allowed(self):
        attendance = self.Attendance.with_user(self.hr_user).create(
            self.attendance_values(self.manual_employee)
        )
        self.assertEqual(attendance.attendance_entry_source, "manual")
        new_checkout = attendance.check_out + timedelta(hours=1)
        attendance.with_user(self.hr_user).write({"check_out": new_checkout})
        self.assertEqual(attendance.check_out, new_checkout)
        attendance.with_user(self.hr_user).unlink()
        self.assertFalse(attendance.exists())

    def test_non_hr_cannot_manage_manual_site_attendance(self):
        with self.assertRaises(AccessError):
            self.Attendance.with_user(self.basic_user).create(
                self.attendance_values(self.manual_employee)
            )

    def test_automated_attendance_cannot_be_manually_created_modified_or_deleted(self):
        with self.assertRaises(AccessError):
            self.Attendance.with_user(self.hr_user).create(
                self.attendance_values(self.biometric_employee)
            )

        attendance = self.Attendance.sudo().with_context(
            attendance_policy_source="biometric"
        ).create(self.attendance_values(self.biometric_employee))
        with self.assertRaises(AccessError):
            attendance.with_user(self.hr_user).write(
                {"check_out": attendance.check_out + timedelta(minutes=1)}
            )
        with self.assertRaises(AccessError):
            attendance.with_user(self.hr_user).unlink()

    def test_biometric_and_scheduled_sources_require_matching_employee_category(self):
        biometric = self.Attendance.sudo().with_context(
            attendance_policy_source="biometric"
        ).create(self.attendance_values(self.biometric_employee))
        self.assertEqual(biometric.attendance_entry_source, "biometric")

        scheduled = self.Attendance.sudo().with_context(
            attendance_policy_source="scheduled"
        ).create(self.attendance_values(self.scheduled_employee, offset_days=1))
        self.assertEqual(scheduled.attendance_entry_source, "scheduled")

        with self.assertRaises(ValidationError):
            self.Attendance.sudo().with_context(
                attendance_policy_source="scheduled"
            ).create(self.attendance_values(self.biometric_employee, offset_days=2))
        with self.assertRaises(ValidationError):
            self.Attendance.sudo().with_context(
                attendance_policy_source="biometric"
            ).create(self.attendance_values(self.scheduled_employee, offset_days=3))
        with self.assertRaises(ValidationError):
            self.Attendance.sudo().with_context(
                attendance_policy_source="biometric"
            ).create(self.attendance_values(self.manual_employee, offset_days=4))

    def test_source_context_cannot_be_forged_by_normal_user(self):
        with self.assertRaises(AccessError):
            self.Attendance.with_user(self.hr_user).with_context(
                attendance_policy_source="biometric"
            ).create(self.attendance_values(self.biometric_employee))

    def test_approved_shortage_is_audited_system_source(self):
        attendance = self.Attendance.sudo().with_context(
            attendance_policy_source="approved_shortage"
        ).create(self.attendance_values(self.biometric_employee))
        self.assertEqual(
            attendance.attendance_entry_source, "approved_shortage"
        )
        attendance.sudo().with_context(
            attendance_policy_source="approved_shortage"
        ).write({"check_out": attendance.check_out + timedelta(minutes=30)})

    def test_archiving_manual_employee_closes_open_attendance(self):
        values = self.attendance_values(self.manual_employee, offset_days=20)
        values.pop("check_out")
        attendance = self.Attendance.with_user(self.hr_user).create(values)

        self.manual_employee.with_user(self.hr_user).action_archive()

        attendance.invalidate_recordset(["check_out"])
        self.assertTrue(attendance.check_out)

    def test_archiving_automated_employee_closes_open_attendance(self):
        values = self.attendance_values(self.biometric_employee, offset_days=21)
        values.pop("check_out")
        attendance = self.Attendance.sudo().with_context(
            attendance_policy_source="biometric"
        ).create(values)

        self.biometric_employee.sudo().action_archive()

        attendance.invalidate_recordset(["check_out"])
        self.assertTrue(attendance.check_out)

    def test_direct_inactive_write_closes_open_automated_attendance(self):
        values = self.attendance_values(self.scheduled_employee, offset_days=23)
        values.pop("check_out")
        attendance = self.Attendance.sudo().with_context(
            attendance_policy_source="scheduled"
        ).create(values)

        self.scheduled_employee.sudo().write({"active": False})

        attendance.invalidate_recordset(["check_out"])
        self.assertTrue(attendance.check_out)

    def test_empty_attendance_write_and_unlink_are_noops(self):
        empty_attendance = self.Attendance.browse()

        self.assertTrue(empty_attendance.write({"check_out": False}))
        self.assertTrue(empty_attendance.unlink())

    def test_historical_attendance_can_be_corrected_after_employee_archive(self):
        attendance = self.Attendance.with_user(self.hr_user).create(
            self.attendance_values(self.manual_employee, offset_days=22)
        )

        self.manual_employee.with_user(self.hr_user).action_archive()
        self.env.invalidate_all()
        attendance = self.Attendance.browse(attendance.id)
        new_checkout = attendance.check_out + timedelta(minutes=15)
        attendance.with_user(self.hr_user).write({"check_out": new_checkout})

        self.assertEqual(attendance.check_out, new_checkout)

    def test_attendance_source_cannot_be_relabelled(self):
        attendance = self.Attendance.with_user(self.hr_user).create(
            self.attendance_values(self.manual_employee)
        )
        with self.assertRaises(AccessError):
            attendance.with_user(self.hr_user).write(
                {"attendance_entry_source": "biometric"}
            )

    def test_scheduled_employee_search_excludes_manual_site_staff(self):
        employees = self.Attendance._get_auto_attendance_employees(self.env.company)
        self.assertIn(self.scheduled_employee, employees)
        self.assertNotIn(self.manual_employee, employees)
        self.assertNotIn(self.biometric_employee, employees)

    def test_opted_in_manual_site_employee_uses_schedule_and_remains_editable(self):
        site_calendar = self.env["resource.calendar"].create({
            "name": "Site 06:00 to 16:00",
            "tz": "Asia/Riyadh",
            "company_id": self.env.company.id,
            "attendance_ids": [Command.create({
                "name": "Monday Site Shift",
                "dayofweek": "0",
                "day_period": "morning",
                "hour_from": 6.0,
                "hour_to": 16.0,
            })],
        })
        self.manual_employee.with_user(self.hr_user).write({
            "resource_calendar_id": site_calendar.id,
            "include_in_scheduled_attendance": True,
        })

        employees = self.Attendance._get_auto_attendance_employees(self.env.company)
        self.assertIn(self.manual_employee, employees)

        created = self.Attendance.cron_create_auto_management_attendance_check_in(
            target_date="2099-06-01"
        ).filtered(lambda attendance: attendance.employee_id == self.manual_employee)
        self.assertEqual(len(created), 1)
        local_check_in = pytz.UTC.localize(created.check_in).astimezone(
            pytz.timezone("Asia/Riyadh")
        )
        self.assertEqual((local_check_in.hour, local_check_in.minute), (6, 0))
        self.assertEqual(created.attendance_entry_source, "scheduled")

        self.Attendance.cron_checkout_auto_management_attendance(
            target_date="2099-06-01"
        )
        created.invalidate_recordset(["check_out"])
        local_check_out = pytz.UTC.localize(created.check_out).astimezone(
            pytz.timezone("Asia/Riyadh")
        )
        self.assertEqual((local_check_out.hour, local_check_out.minute), (16, 0))

        corrected_checkout = created.check_out + timedelta(minutes=15)
        created.with_user(self.hr_user).write({"check_out": corrected_checkout})
        self.assertEqual(created.check_out, corrected_checkout)
