from datetime import datetime, timedelta

from odoo import Command
from odoo.tests.common import TransactionCase


class AttendancePolicyCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Attendance = cls.env["hr.attendance"]
        cls.Request = cls.env["hr.attendance.mode.change.request"]
        internal = cls.env.ref("base.group_user")
        attendance_manager = cls.env.ref(
            "hr_attendance.group_hr_attendance_manager"
        )
        hr_manager_group = cls.env.ref("hr.group_hr_manager")
        md_group = cls.env.ref(
            "pr_hr_recruitment_request.group_onboarding_md"
        )
        cls.hr_user = cls.env["res.users"].create(
            {
                "name": "Attendance Policy HR",
                "login": "attendance.policy.hr",
                "company_id": cls.env.company.id,
                "company_ids": [Command.set(cls.env.company.ids)],
                "groups_id": [
                    Command.set((internal | attendance_manager | hr_manager_group).ids)
                ],
            }
        )
        cls.md_user = cls.env["res.users"].create(
            {
                "name": "Attendance Policy MD",
                "login": "attendance.policy.md",
                "company_id": cls.env.company.id,
                "company_ids": [Command.set(cls.env.company.ids)],
                "groups_id": [Command.set((internal | md_group).ids)],
            }
        )
        cls.hr_md_user = cls.env["res.users"].create(
            {
                "name": "Attendance Policy HR MD",
                "login": "attendance.policy.hr.md",
                "company_id": cls.env.company.id,
                "company_ids": [Command.set(cls.env.company.ids)],
                "groups_id": [Command.set((internal | hr_manager_group | md_group).ids)],
            }
        )
        cls.basic_user = cls.env["res.users"].create(
            {
                "name": "Attendance Policy Basic",
                "login": "attendance.policy.basic",
                "company_id": cls.env.company.id,
                "company_ids": [Command.set(cls.env.company.ids)],
                "groups_id": [Command.set(internal.ids)],
            }
        )
        cls.biometric_employee = cls.env["hr.employee"].create(
            {
                "name": "Biometric Policy Employee",
                "identification_id": "ATT-POLICY-001",
                "company_id": cls.env.company.id,
                "compute_attendance": True,
            }
        )
        cls.scheduled_employee = cls.env["hr.employee"].create(
            {
                "name": "Scheduled Policy Employee",
                "identification_id": "ATT-POLICY-002",
                "company_id": cls.env.company.id,
                "compute_attendance": False,
            }
        )
        cls.manual_employee = cls.env["hr.employee"].create(
            {
                "name": "Manual Site Policy Employee",
                "identification_id": "ATT-POLICY-003",
                "company_id": cls.env.company.id,
                "compute_attendance": True,
            }
        )
        request = cls.Request.with_user(cls.hr_user).create(
            {
                "employee_id": cls.manual_employee.id,
                "requested_mode": "manual",
                "reason": "Employee works at a field site.",
            }
        )
        request.with_user(cls.hr_user).action_submit()
        request.with_user(cls.hr_user).action_hr_manager_approve()
        request.with_user(cls.md_user).action_md_approve()
        cls.manual_employee.invalidate_recordset()

    def attendance_values(self, employee, offset_days=0):
        check_in = datetime(2026, 6, 1, 8, 0) + timedelta(days=offset_days)
        return {
            "employee_id": employee.id,
            "check_in": check_in,
            "check_out": check_in + timedelta(hours=9),
        }
