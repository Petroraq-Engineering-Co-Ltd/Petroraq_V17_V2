from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import tagged

from .common import AttendancePolicyCase


@tagged("post_install", "-at_install")
class TestAttendanceModeApproval(AttendancePolicyCase):

    def test_request_form_defaults_show_current_and_target_modes(self):
        action = self.biometric_employee.with_user(
            self.hr_user
        ).action_request_attendance_mode_change()
        defaults = self.Request.with_user(self.hr_user).with_context(
            **action["context"]
        ).default_get(["employee_id", "current_mode", "requested_mode"])

        self.assertEqual(defaults["employee_id"], self.biometric_employee.id)
        self.assertEqual(defaults["current_mode"], "automated")
        self.assertEqual(defaults["requested_mode"], "manual")

    def test_direct_mode_changes_are_blocked(self):
        with self.assertRaises(ValidationError):
            self.biometric_employee.with_user(self.hr_user).write(
                {"attendance_entry_mode": "manual"}
            )
        with self.assertRaises(ValidationError):
            self.biometric_employee.sudo().write(
                {"attendance_entry_mode": "manual"}
            )

    def test_request_requires_hr_reason_and_a_real_change(self):
        with self.assertRaises(AccessError):
            self.Request.with_user(self.basic_user).create(
                {
                    "employee_id": self.biometric_employee.id,
                    "requested_mode": "manual",
                    "reason": "Not authorized",
                }
            )
        with self.assertRaises(ValidationError):
            self.Request.with_user(self.hr_user).create(
                {
                    "employee_id": self.biometric_employee.id,
                    "requested_mode": "automated",
                    "reason": "No actual change",
                }
            )
        with self.assertRaises(ValidationError):
            self.Request.with_user(self.hr_user).create(
                {
                    "employee_id": self.biometric_employee.id,
                    "requested_mode": "manual",
                    "reason": "   ",
                }
            )

    def test_duplicate_pending_request_is_rejected(self):
        values = {
            "employee_id": self.biometric_employee.id,
            "requested_mode": "manual",
            "reason": "Move to field assignment",
        }
        self.Request.with_user(self.hr_user).create(values)
        with self.assertRaises(ValidationError):
            self.Request.with_user(self.hr_user).create(values)

    def test_only_md_can_approve_and_approval_changes_employee_atomically(self):
        request = self.Request.with_user(self.hr_user).create(
            {
                "employee_id": self.biometric_employee.id,
                "requested_mode": "manual",
                "reason": "Permanent transfer to site.",
            }
        )
        with self.assertRaises(AccessError):
            request.with_user(self.hr_user).action_approve()

        request.with_user(self.md_user).action_approve()
        self.biometric_employee.invalidate_recordset()
        self.assertEqual(request.state, "approved")
        self.assertEqual(self.biometric_employee.attendance_entry_mode, "manual")
        self.assertEqual(request.decision_by_id, self.md_user)
        self.assertTrue(request.decision_date)

    def test_rejection_and_cancellation_do_not_change_employee(self):
        rejected = self.Request.with_user(self.hr_user).create(
            {
                "employee_id": self.biometric_employee.id,
                "requested_mode": "manual",
                "reason": "Requested site transfer.",
            }
        )
        rejected.with_user(self.md_user).action_reject()
        self.assertEqual(rejected.state, "rejected")
        self.assertEqual(self.biometric_employee.attendance_entry_mode, "automated")

        cancelled = self.Request.with_user(self.hr_user).create(
            {
                "employee_id": self.scheduled_employee.id,
                "requested_mode": "manual",
                "reason": "Temporary field assignment.",
            }
        )
        cancelled.with_user(self.hr_user).action_cancel()
        self.assertEqual(cancelled.state, "cancelled")
        self.assertEqual(self.scheduled_employee.attendance_entry_mode, "automated")

    def test_request_is_immutable_and_retained_for_audit(self):
        request = self.Request.with_user(self.hr_user).create(
            {
                "employee_id": self.biometric_employee.id,
                "requested_mode": "manual",
                "reason": "Field deployment.",
            }
        )
        with self.assertRaises(UserError):
            request.with_user(self.hr_user).write({"reason": "Changed reason"})
        with self.assertRaises(UserError):
            request.sudo().unlink()

    def test_dashboard_menu_and_md_activity_are_created(self):
        request = self.Request.with_user(self.hr_user).create(
            {
                "employee_id": self.biometric_employee.id,
                "requested_mode": "manual",
                "reason": "Site assignment.",
            }
        )
        self.assertTrue(
            self.env.ref(
                "pr_hr_attendance.menu_attendance_mode_change_request_approval"
            )
        )
        self.assertTrue(request.activity_ids.filtered(lambda activity: activity.user_id == self.md_user))
        approvals_group = self.env.ref("de_hr_workspace.group_hr_employee_approvals")
        md_group = self.env.ref("pr_hr_recruitment_request.group_onboarding_md")
        self.assertIn(approvals_group, md_group.implied_ids)
