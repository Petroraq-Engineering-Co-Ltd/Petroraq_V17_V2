from datetime import datetime, timedelta

from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMissingCheckoutCron(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Attendance = cls.env["hr.attendance"]
        internal = cls.env.ref("base.group_user")
        attendance_manager = cls.env.ref("hr_attendance.group_hr_attendance_manager")
        hr_manager_group = cls.env.ref("hr.group_hr_manager")
        cls.hr_user = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Missing Checkout Test HR",
            "login": "missing.checkout.cron.hr",
            "company_id": cls.env.company.id,
            "company_ids": [Command.set(cls.env.company.ids)],
            "groups_id": [
                Command.set((internal | attendance_manager | hr_manager_group).ids)
            ],
        })
        cls.calendar = cls.env["resource.calendar"].create({
            "name": "Riyadh Cron Calendar",
            "tz": "Asia/Riyadh",
            "company_id": cls.env.company.id,
            "attendance_ids": [Command.clear()],
        })
        cls.biometric_employee = cls.env["hr.employee"].create({
            "name": "Missing Checkout Biometric Employee",
            "identification_id": "MISSING-CRON-001",
            "company_id": cls.env.company.id,
            "resource_calendar_id": cls.calendar.id,
            "compute_attendance": True,
        })
        cls.manual_employee = cls.env["hr.employee"].with_context(
            install_mode=True,
        ).create({
            "name": "Missing Checkout Manual Employee",
            "identification_id": "MISSING-CRON-002",
            "company_id": cls.env.company.id,
            "resource_calendar_id": cls.calendar.id,
            "attendance_entry_mode": "manual",
            "compute_attendance": False,
        })

    def test_midnight_cron_closes_overdue_open_attendance_via_orm_in_local_tz(self):
        # 2026-09-01 05:30 UTC == 08:30 Asia/Riyadh; 2026-09-01 21:05 UTC == 2026-09-02 00:05 Asia/Riyadh.
        bio_att = self.Attendance.sudo().with_context(
            attendance_policy_source="biometric",
        ).create({
            "employee_id": self.biometric_employee.id,
            "check_in": datetime(2026, 9, 1, 5, 30, 0),
        })
        manual_att = self.Attendance.with_user(self.hr_user).create({
            "employee_id": self.manual_employee.id,
            "check_in": datetime(2026, 9, 1, 5, 40, 0),
        })

        # Same Riyadh evening (2026-09-01 23:30 AST == 20:30 UTC) must NOT close yet.
        closed_early = self.Attendance._cron_auto_handle_missing_checkouts(
            now=datetime(2026, 9, 1, 20, 30, 0),
        )
        self.assertFalse(bio_att.check_out)
        self.assertFalse(manual_att.check_out)
        self.assertNotIn(bio_att, closed_early)

        # Even though UTC date is still 2026-09-01 at 21:05 UTC, Riyadh is past midnight (2026-09-02 00:05).
        closed = self.Attendance._cron_auto_handle_missing_checkouts(
            now=datetime(2026, 9, 1, 21, 5, 0),
        )
        self.assertIn(bio_att, closed)
        self.assertIn(manual_att, closed)

        self.assertEqual(bio_att.check_out, bio_att.check_in)
        self.assertEqual(bio_att.worked_hours, 0.0)
        self.assertEqual(bio_att.attendance_day_status, "absent")
        self.assertEqual(
            bio_att.attendance_status_reason,
            "The missing daily punch was not resolved before midnight.",
        )

        self.assertEqual(manual_att.check_out, manual_att.check_in)
        self.assertEqual(manual_att.worked_hours, 0.0)
        self.assertEqual(manual_att.attendance_day_status, "absent")

    def test_shortage_approval_recovers_sentinel_attendance_cleanly(self):
        check_in = datetime(2026, 9, 7, 5, 30, 0)
        att = self.Attendance.sudo().with_context(
            attendance_policy_source="biometric",
        ).create({
            "employee_id": self.biometric_employee.id,
            "check_in": check_in,
        })
        self.Attendance._cron_auto_handle_missing_checkouts(
            now=datetime(2026, 9, 7, 21, 5, 0),
        )
        self.assertEqual(att.attendance_day_status, "absent")

        shortage = self.env["pr.hr.shortage.request"].create({
            "employee_id": self.biometric_employee.id,
            "company_id": self.env.company.id,
            "date": "2026-09-07",
            "request_type": "shortage",
            "check_in": check_in,
            "check_out": check_in + timedelta(hours=9),
        })
        shortage._apply_shortage_in_attendance()

        att.invalidate_recordset()
        self.assertEqual(att.check_out, check_in + timedelta(hours=9))
        self.assertAlmostEqual(att.worked_hours, 9.0, places=2)
        self.assertEqual(att.attendance_day_status, "normal")
        self.assertFalse(att.attendance_status_reason)