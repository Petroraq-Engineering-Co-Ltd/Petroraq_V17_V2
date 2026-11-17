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

    def test_hr_manager_then_md_approval_changes_employee_atomically(self):
        request = self.Request.with_user(self.officer_user).create(
            {
                "employee_id": self.biometric_employee.id,
                "requested_mode": "manual",
                "reason": "Permanent transfer to site.",
            }
        )
        self.assertEqual(request.state, "draft")
        with self.assertRaises(AccessError):
            request.with_user(self.basic_user).action_hr_manager_approve()

        request.with_user(self.officer_user).action_submit()
        self.assertEqual(request.state, "hr_manager_approval")
        request.with_user(self.hr_user).action_hr_manager_approve()
        self.assertEqual(request.state, "md_approval")
        self.assertEqual(request.hr_manager_approved_by_id, self.hr_user)
        self.assertTrue(request.hr_manager_approved_date)

        with self.assertRaises(AccessError):
            request.with_user(self.hr_user).action_md_approve()

        request.with_user(self.md_user).action_md_approve()
        self.biometric_employee.invalidate_recordset()
        self.assertEqual(request.state, "approved")
        self.assertEqual(self.biometric_employee.attendance_entry_mode, "manual")
        self.assertEqual(request.decision_by_id, self.md_user)
        self.assertTrue(request.decision_date)
        self.assertEqual(request.md_approved_by_id, self.md_user)
        self.assertTrue(request.md_approved_date)

    def test_dual_hr_manager_md_user_approves_once(self):
        employee = self.env["hr.employee"].create(
            {
                "name": "Dual Role Approval Employee",
                "identification_id": "ATT-POLICY-004",
                "company_id": self.env.company.id,
                "compute_attendance": True,
            }
        )
        request = self.Request.with_user(self.officer_user).create(
            {
                "employee_id": employee.id,
                "requested_mode": "manual",
                "reason": "Field leadership assignment.",
            }
        )

        request.with_user(self.officer_user).action_submit()
        request.with_user(self.hr_md_user).action_hr_manager_approve()
        employee.invalidate_recordset()
        self.assertEqual(request.state, "approved")
        self.assertEqual(employee.attendance_entry_mode, "manual")
        self.assertEqual(request.hr_manager_approved_by_id, self.hr_md_user)
        self.assertEqual(request.md_approved_by_id, self.hr_md_user)
        self.assertEqual(request.decision_by_id, self.hr_md_user)

    def test_rejection_and_cancellation_do_not_change_employee(self):
        rejected = self.Request.with_user(self.officer_user).create(
            {
                "employee_id": self.biometric_employee.id,
                "requested_mode": "manual",
                "reason": "Requested site transfer.",
            }
        )
        rejected.with_user(self.officer_user).action_submit()
        rejected.with_user(self.hr_user).action_hr_manager_approve()
        rejected.with_user(self.md_user).action_reject()
        self.assertEqual(rejected.state, "rejected")
        self.assertEqual(self.biometric_employee.attendance_entry_mode, "automated")

        cancelled = self.Request.with_user(self.officer_user).create(
            {
                "employee_id": self.scheduled_employee.id,
                "requested_mode": "manual",
                "reason": "Temporary field assignment.",
            }
        )
        cancelled.with_user(self.officer_user).action_cancel()
        self.assertEqual(cancelled.state, "cancelled")
        self.assertEqual(self.scheduled_employee.attendance_entry_mode, "automated")

    def test_request_is_immutable_and_retained_for_audit(self):
        request = self.Request.with_user(self.officer_user).create(
            {
                "employee_id": self.biometric_employee.id,
                "requested_mode": "manual",
                "reason": "Field deployment.",
            }
        )
        request.with_user(self.officer_user).action_submit()
        with self.assertRaises(UserError):
            request.with_user(self.hr_user).write({"reason": "Changed reason"})
        with self.assertRaises(UserError):
            request.sudo().unlink()

    def test_dashboard_menu_and_approval_activities_are_created(self):
        request = self.Request.with_user(self.officer_user).create(
            {
                "employee_id": self.biometric_employee.id,
                "requested_mode": "manual",
                "reason": "Site assignment.",
            }
        )
        self.assertFalse(
            request.activity_ids.filtered(lambda activity: activity.user_id == self.hr_user)
        )
        request.with_user(self.officer_user).action_submit()
        self.assertTrue(
            self.env.ref(
                "pr_hr_attendance.menu_attendance_mode_change_request_approval"
            )
        )
        self.assertTrue(request.activity_ids.filtered(lambda activity: activity.user_id == self.hr_user))

        request.with_user(self.hr_user).action_hr_manager_approve()
        request.invalidate_recordset(["activity_ids"])
        self.assertTrue(request.activity_ids.filtered(lambda activity: activity.user_id == self.md_user))

        approvals_group = self.env.ref("de_hr_workspace.group_hr_employee_approvals")
        hr_manager_group = self.env.ref("pr_hr.group_hr_manager")
        md_group = self.env.ref("pr_hr.group_hr_md")
        self.assertIn(approvals_group, hr_manager_group.implied_ids)
        self.assertIn(approvals_group, md_group.implied_ids)

    def test_submit_auto_advance_for_hr_manager_and_md(self):
        # HR Manager submit auto-advances to md_approval and records HR Manager approval
        req_hr = self.Request.with_user(self.hr_user).create(
            {
                "employee_id": self.biometric_employee.id,
                "requested_mode": "manual",
                "reason": "Direct HR Manager submission.",
            }
        )
        req_hr.with_user(self.hr_user).action_submit()
        self.assertEqual(req_hr.state, "md_approval")
        self.assertEqual(req_hr.hr_manager_approved_by_id, self.hr_user)
        self.assertTrue(req_hr.hr_manager_approved_date)
        self.assertFalse(req_hr.md_approved_by_id)

        # Cancel req_hr so employee has no open request
        req_hr.with_user(self.hr_user).action_cancel()

        # MD-only submit (without HR Manager rights) must route to hr_manager_approval
        req_md = self.Request.with_user(self.md_user).create(
            {
                "employee_id": self.biometric_employee.id,
                "requested_mode": "manual",
                "reason": "Direct MD submission without HR Manager rights.",
            }
        )
        req_md.with_user(self.md_user).action_submit()
        self.assertEqual(req_md.state, "hr_manager_approval")
        self.assertFalse(req_md.hr_manager_approved_by_id)
        self.assertFalse(req_md.md_approved_by_id)
        self.assertFalse(
            any("auto-advanced to MD Approval" in msg.body for msg in req_md.message_ids)
        )
        self.assertTrue(
            req_md.activity_ids.filtered(lambda activity: activity.user_id == self.hr_user)
        )

    def test_dual_hr_manager_md_submit_auto_approves(self):
        employee = self.env["hr.employee"].create(
            {
                "name": "Dual Role Auto Approve Employee",
                "identification_id": "ATT-POLICY-007",
                "company_id": self.env.company.id,
                "compute_attendance": True,
            }
        )
        request = self.Request.with_user(self.hr_md_user).create(
            {
                "employee_id": employee.id,
                "requested_mode": "manual",
                "reason": "Auto-approved by user with both HR Manager and HR MD rights.",
            }
        )
        self.assertEqual(request.state, "draft")
        self.assertEqual(employee.attendance_entry_mode, "automated")

        # Draft requests must still be rejected by HrEmployee.write() guard directly
        with self.assertRaises(ValidationError):
            employee.sudo().with_context(
                attendance_mode_approval_request_id=request.id
            ).write({"attendance_entry_mode": "manual"})

        request.with_user(self.hr_md_user).action_submit()
        employee.invalidate_recordset()
        self.assertEqual(request.state, "approved")
        self.assertEqual(employee.attendance_entry_mode, "manual")
        self.assertEqual(request.hr_manager_approved_by_id, self.hr_md_user)
        self.assertTrue(request.hr_manager_approved_date)
        self.assertEqual(request.md_approved_by_id, self.hr_md_user)
        self.assertTrue(request.md_approved_date)
        self.assertEqual(request.decision_by_id, self.hr_md_user)
        self.assertTrue(request.decision_date)
        self.assertFalse(request.activity_ids)
        self.assertTrue(
            any("Auto-approved on submission" in msg.body for msg in request.message_ids)
        )

    def test_dual_role_button_visibility_and_md_approve_on_hr_manager_stage(self):
        employee = self.env["hr.employee"].create(
            {
                "name": "Button Visibility Employee",
                "identification_id": "ATT-POLICY-008",
                "company_id": self.env.company.id,
                "compute_attendance": True,
            }
        )
        request = self.Request.with_user(self.officer_user).create(
            {
                "employee_id": employee.id,
                "requested_mode": "manual",
                "reason": "Officer submission for visibility verification.",
            }
        )
        request.with_user(self.officer_user).action_submit()
        self.assertEqual(request.state, "hr_manager_approval")

        # HR Manager only sees HR Manager Approve & Reject
        req_as_hr = request.with_user(self.hr_user)
        self.assertTrue(req_as_hr.can_hr_manager_approve)
        self.assertFalse(req_as_hr.can_md_approve)
        self.assertTrue(req_as_hr.can_reject)

        # MD only sees MD Approve & Reject
        req_as_md = request.with_user(self.md_user)
        self.assertFalse(req_as_md.can_hr_manager_approve)
        self.assertTrue(req_as_md.can_md_approve)
        self.assertTrue(req_as_md.can_reject)

        # Dual-role user sees only MD Approve & single Reject (no duplicate HR Manager Approve)
        req_as_dual = request.with_user(self.hr_md_user)
        self.assertFalse(req_as_dual.can_hr_manager_approve)
        self.assertTrue(req_as_dual.can_md_approve)
        self.assertTrue(req_as_dual.can_reject)

        # Basic user sees none
        req_as_basic = request.with_user(self.basic_user)
        self.assertFalse(req_as_basic.can_hr_manager_approve)
        self.assertFalse(req_as_basic.can_md_approve)
        self.assertFalse(req_as_basic.can_reject)

        # Dual-role clicking MD Approve records both HR Manager and MD approval
        req_as_dual.action_md_approve()
        employee.invalidate_recordset()
        self.assertEqual(request.state, "approved")
        self.assertEqual(employee.attendance_entry_mode, "manual")
        self.assertEqual(request.hr_manager_approved_by_id, self.hr_md_user)
        self.assertTrue(request.hr_manager_approved_date)
        self.assertEqual(request.md_approved_by_id, self.hr_md_user)
        self.assertTrue(request.md_approved_date)
        self.assertEqual(request.decision_by_id, self.hr_md_user)

    def test_md_skip_level_approval_from_hr_manager_stage(self):
        employee = self.env["hr.employee"].create(
            {
                "name": "Skip Level Employee",
                "identification_id": "ATT-POLICY-005",
                "company_id": self.env.company.id,
                "compute_attendance": True,
            }
        )
        request = self.Request.with_user(self.officer_user).create(
            {
                "employee_id": employee.id,
                "requested_mode": "manual",
                "reason": "Direct skip-level authorization.",
            }
        )
        request.with_user(self.officer_user).action_submit()
        self.assertEqual(request.state, "hr_manager_approval")

        # MD directly approves via skip-level
        request.with_user(self.md_user).action_md_approve()
        employee.invalidate_recordset()
        self.assertEqual(request.state, "approved")
        self.assertEqual(employee.attendance_entry_mode, "manual")
        self.assertEqual(request.md_approved_by_id, self.md_user)
        self.assertFalse(request.hr_manager_approved_by_id)
        self.assertTrue(
            any("skip-level approval" in msg.body for msg in request.message_ids)
        )

    def test_md_skip_level_rejection_from_hr_manager_stage(self):
        employee = self.env["hr.employee"].create(
            {
                "name": "Skip Level Rejection Employee",
                "identification_id": "ATT-POLICY-006",
                "company_id": self.env.company.id,
                "compute_attendance": True,
            }
        )
        request = self.Request.with_user(self.officer_user).create(
            {
                "employee_id": employee.id,
                "requested_mode": "manual",
                "reason": "Request to be rejected by MD early.",
            }
        )
        request.with_user(self.officer_user).action_submit()
        self.assertEqual(request.state, "hr_manager_approval")

        # MD rejects while in hr_manager_approval
        request.with_user(self.md_user).action_reject()
        employee.invalidate_recordset()
        self.assertEqual(request.state, "rejected")
        self.assertEqual(employee.attendance_entry_mode, "automated")
        self.assertEqual(request.decision_by_id, self.md_user)

    def test_approval_dashboard_pending_domain(self):
        service = self.env["de.hr.approval.dashboard.service"]

        hr_domain = service.with_user(self.hr_user)._attendance_mode_pending_domain()
        self.assertEqual(hr_domain, [("state", "in", ["hr_manager_approval"])])

        md_domain = service.with_user(self.md_user)._attendance_mode_pending_domain()
        self.assertEqual(md_domain, [("state", "in", ["md_approval"])])

        hr_md_domain = service.with_user(self.hr_md_user)._attendance_mode_pending_domain()
        self.assertEqual(hr_md_domain, [("state", "in", ["md_approval", "hr_manager_approval"])])

        basic_domain = service.with_user(self.basic_user)._attendance_mode_pending_domain()
        self.assertEqual(basic_domain, [("id", "=", False)])
