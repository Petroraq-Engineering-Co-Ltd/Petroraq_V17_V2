from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestLeaveRequestApproval(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.LeaveRequest = cls.env["pr.hr.leave.request"]
        cls.approval_company = cls.env["res.company"].create(
            {"name": "Leave Request Approval Test Company"}
        )
        cls.env.user.sudo().write(
            {"company_ids": [Command.link(cls.approval_company.id)]}
        )

        internal = cls.env.ref("base.group_user")
        workspace_group = cls.env.ref(
            "de_hr_workspace.group_hr_employee_workspace", raise_if_not_found=False
        )
        approvals_group = cls.env.ref(
            "de_hr_workspace.group_hr_employee_approvals", raise_if_not_found=False
        )
        base_employee_groups = workspace_group or cls.env.ref("hr_holidays.group_hr_holidays_user")
        dept_mgr_groups = base_employee_groups | (approvals_group or cls.env["res.groups"])
        hr_sup_group = cls.env.ref("pr_hr.group_hr_supervisor")
        hr_mgr_group = cls.env.ref("pr_hr.group_hr_manager")
        legacy_sup_group = cls.env.ref("pr_hr_holidays.custom_group_hr_holidays_supervisor")
        legacy_mgr_group = cls.env.ref("hr_holidays.group_hr_holidays_manager")

        def _make_user(name, login, groups, active=True):
            return cls.env["res.users"].sudo().create({
                "name": name,
                "login": login,
                "email": f"{login}@example.com",
                "active": active,
                "company_id": cls.approval_company.id,
                "company_ids": [Command.set(cls.approval_company.ids)],
                "groups_id": [Command.set((internal | groups).ids)],
            })

        cls.basic_user = _make_user("Basic Leave User", "leave.approval.basic", base_employee_groups)
        cls.dept_manager_user = _make_user("Dept Manager Leave User", "leave.approval.dept.mgr", dept_mgr_groups)
        cls.hr_supervisor_user = _make_user("HR Supervisor Leave User", "leave.approval.hr.sup", hr_sup_group)
        cls.hr_manager_user = _make_user("HR Manager Leave User", "leave.approval.hr.mgr", hr_mgr_group)
        cls.dual_hr_user = _make_user(
            "Dual HR Sup+Mgr Leave User",
            "leave.approval.dual.hr",
            hr_sup_group | hr_mgr_group,
            active=False,
        )
        cls.dual_dept_hr_mgr_user = _make_user(
            "Dual Dept+HR Mgr Leave User",
            "leave.approval.dept.hr.mgr",
            hr_mgr_group,
            active=False,
        )
        cls.legacy_hr_user = _make_user(
            "Legacy TimeOff Approver",
            "leave.approval.legacy",
            legacy_sup_group | legacy_mgr_group,
        )

        cls.dept_manager_emp = cls.env["hr.employee"].sudo().create({
            "name": "Dept Manager Employee",
            "user_id": cls.dept_manager_user.id,
            "company_id": cls.approval_company.id,
        })
        cls.employee = cls.env["hr.employee"].sudo().create({
            "name": "Regular Leave Employee",
            "user_id": cls.basic_user.id,
            "parent_id": cls.dept_manager_emp.id,
            "company_id": cls.approval_company.id,
        })
        cls.no_manager_employee = cls.env["hr.employee"].sudo().create({
            "name": "No Manager Leave Employee",
            "company_id": cls.approval_company.id,
        })
        cls.dual_dept_hr_mgr_emp = cls.env["hr.employee"].sudo().create({
            "name": "Dual Dept+HR Mgr Employee",
            "user_id": cls.dual_dept_hr_mgr_user.id,
            "company_id": cls.approval_company.id,
        })
        cls.employee_under_dual_mgr = cls.env["hr.employee"].sudo().create({
            "name": "Employee Under Dual Dept+HR Mgr",
            "parent_id": cls.dual_dept_hr_mgr_emp.id,
            "company_id": cls.approval_company.id,
        })

        cls.leave_type = cls.env["hr.leave.type"].sudo().create({
            "name": "Annual Leave Approval Test",
            "time_type": "leave",
            "request_unit": "day",
            "requires_allocation": "no",
            "leave_type": "annual_leave",
        })
        cls._date_offset = 20

    def _next_date_pair(self, span_days=2):
        today = fields.Date.context_today(self.env.user)
        start = today + timedelta(days=self._date_offset)
        # Ensure we never start on a weekend for single-day edge cases
        while start.weekday() >= 4:
            start += timedelta(days=1)
        end = start + timedelta(days=span_days)
        self.__class__._date_offset += span_days + 5
        return start, end

    def _create_request(self, user, employee=None, span_days=2):
        employee = employee or self.employee
        date_from, date_to = self._next_date_pair(span_days=span_days)
        return self.LeaveRequest.with_user(user).sudo().create({
            "employee_id": employee.id,
            "company_id": self.approval_company.id,
            "leave_type_id": self.leave_type.id,
            "date_from": date_from,
            "date_to": date_to,
        })

    def _reject_via_wizard(self, request, user, reason="Not approved"):
        action = request.with_user(user).action_reject()
        wizard = self.env["pr.reject.record.wizard"].with_user(user).with_context(
            **action["context"]
        ).create({"reject_reason": reason})
        wizard.action_reject()
        request.invalidate_recordset()

    def test_standard_three_stage_approval_creates_validated_leave(self):
        request = self._create_request(self.basic_user)
        self.assertEqual(request.state, "draft")
        self.assertFalse(request.leave_id)

        # Unauthorized & legacy-only users cannot approve
        with self.assertRaises(AccessError):
            request.with_user(self.basic_user).action_manager_approve()
        with self.assertRaises(AccessError):
            request.with_user(self.legacy_hr_user).action_hr_manager_approve()

        # Stage 1: Dept Manager approves -> manager_approve
        request.with_user(self.dept_manager_user).action_manager_approve()
        self.assertEqual(request.state, "manager_approve")
        self.assertEqual(request.manager_approved_user_id, self.dept_manager_user)
        self.assertTrue(request.manager_approved_date)

        with self.assertRaises(AccessError):
            request.with_user(self.legacy_hr_user).action_hr_supervisor_approve()

        # Stage 2: HR Supervisor approves -> hr_supervisor
        request.with_user(self.hr_supervisor_user).action_hr_supervisor_approve()
        self.assertEqual(request.state, "hr_supervisor")
        self.assertEqual(request.hr_supervisor_approved_user_id, self.hr_supervisor_user)
        self.assertTrue(request.hr_supervisor_approved_date)

        # HR Supervisor cannot perform final HR Manager approval
        with self.assertRaises(AccessError):
            request.with_user(self.hr_supervisor_user).action_hr_manager_approve()

        # Stage 3: HR Manager approves -> hr_approve + validated hr.leave
        request.with_user(self.hr_manager_user).action_hr_manager_approve()
        self.assertEqual(request.state, "hr_approve")
        self.assertEqual(request.approval_state, "hr_approve")
        self.assertEqual(request.hr_manager_approved_user_id, self.hr_manager_user)
        self.assertTrue(request.hr_manager_approved_date)
        self.assertTrue(request.leave_id)
        self.assertEqual(request.leave_id.state, "validate")

    def test_hr_manager_skip_level_approval_from_draft_and_manager_approve(self):
        # Skip-level from draft (Department Manager stage)
        req_draft = self._create_request(self.basic_user)
        self.assertEqual(req_draft.state, "draft")
        req_draft.with_user(self.hr_manager_user).action_hr_manager_approve()
        self.assertEqual(req_draft.state, "hr_approve")
        self.assertEqual(req_draft.hr_manager_approved_user_id, self.hr_manager_user)
        self.assertFalse(req_draft.manager_approved_user_id)
        self.assertFalse(req_draft.hr_supervisor_approved_user_id)
        self.assertTrue(req_draft.leave_id)
        self.assertEqual(req_draft.leave_id.state, "validate")
        self.assertTrue(
            any("skip-level approval" in (msg.body or "") for msg in req_draft.message_ids)
        )

        # Skip-level from manager_approve (HR Supervisor stage)
        req_sup = self._create_request(self.basic_user)
        req_sup.with_user(self.dept_manager_user).action_manager_approve()
        self.assertEqual(req_sup.state, "manager_approve")
        req_sup.with_user(self.hr_manager_user).action_hr_manager_approve()
        self.assertEqual(req_sup.state, "hr_approve")
        self.assertEqual(req_sup.manager_approved_user_id, self.dept_manager_user)
        self.assertFalse(req_sup.hr_supervisor_approved_user_id)
        self.assertEqual(req_sup.hr_manager_approved_user_id, self.hr_manager_user)
        self.assertTrue(req_sup.leave_id)
        self.assertEqual(req_sup.leave_id.state, "validate")
        self.assertTrue(
            any("skip-level approval" in (msg.body or "") for msg in req_sup.message_ids)
        )

    def test_hr_manager_skip_level_rejection_and_reset_preserves_original_stage(self):
        # Reject from draft -> reset reopens back to draft
        req_draft = self._create_request(self.basic_user)
        self.assertEqual(req_draft.state, "draft")
        self._reject_via_wizard(req_draft, self.hr_manager_user, reason="Rejected at draft")
        self.assertEqual(req_draft.state, "reject")
        self.assertEqual(req_draft.rejected_stage, "hr_manager")
        self.assertEqual(req_draft.rejected_from_state, "draft")
        self.assertFalse(req_draft.leave_id)

        # Dept manager cannot reset HR Manager's rejection
        with self.assertRaises(UserError):
            req_draft.with_user(self.dept_manager_user).action_reset_rejection()

        req_draft.with_user(self.hr_manager_user).action_reset_rejection()
        self.assertEqual(req_draft.state, "draft")
        self.assertFalse(req_draft.rejected_stage)
        self.assertFalse(req_draft.rejected_from_state)

        # Reject from manager_approve -> reset reopens back to manager_approve
        req_sup = self._create_request(self.basic_user)
        req_sup.with_user(self.dept_manager_user).action_manager_approve()
        self.assertEqual(req_sup.state, "manager_approve")
        self._reject_via_wizard(req_sup, self.hr_manager_user, reason="Rejected at sup stage")
        self.assertEqual(req_sup.state, "reject")
        self.assertEqual(req_sup.rejected_from_state, "manager_approve")

        req_sup.with_user(self.hr_manager_user).action_reset_rejection()
        self.assertEqual(req_sup.state, "manager_approve")
        self.assertEqual(req_sup.manager_approved_user_id, self.dept_manager_user)

    def test_dual_hr_supervisor_and_manager_submit_auto_approves_immediately(self):
        self.dual_hr_user.sudo().write({"active": True})
        # Even when employee has a distinct Department Manager, dual HR Sup+Mgr auto-approves immediately
        request = self._create_request(self.dual_hr_user, employee=self.employee)
        self.assertEqual(request.state, "hr_approve")
        self.assertEqual(request.approval_state, "hr_approve")
        self.assertEqual(request.hr_supervisor_approved_user_id, self.dual_hr_user)
        self.assertTrue(request.hr_supervisor_approved_date)
        self.assertEqual(request.hr_manager_approved_user_id, self.dual_hr_user)
        self.assertTrue(request.hr_manager_approved_date)
        self.assertTrue(request.leave_id)
        self.assertEqual(request.leave_id.state, "validate")
        self.assertTrue(
            any("Auto-approved on submission" in (msg.body or "") for msg in request.message_ids)
        )

    def test_hr_supervisor_submit_auto_advances_to_hr_manager(self):
        # Employee WITHOUT a distinct Dept Manager -> advances directly to hr_supervisor on creation
        req_no_mgr = self._create_request(self.hr_supervisor_user, employee=self.no_manager_employee)
        self.assertEqual(req_no_mgr.state, "hr_supervisor")
        self.assertEqual(req_no_mgr.hr_supervisor_approved_user_id, self.hr_supervisor_user)
        self.assertTrue(req_no_mgr.hr_supervisor_approved_date)
        self.assertFalse(req_no_mgr.hr_manager_approved_user_id)
        self.assertFalse(req_no_mgr.leave_id)

        # Employee WITH a distinct Dept Manager -> starts at draft, then auto-advances past HR Supervisor
        req_with_mgr = self._create_request(self.hr_supervisor_user, employee=self.employee)
        self.assertEqual(req_with_mgr.state, "draft")
        self.assertFalse(req_with_mgr.hr_supervisor_approved_user_id)

        req_with_mgr.with_user(self.dept_manager_user).action_manager_approve()
        self.assertEqual(req_with_mgr.state, "hr_supervisor")
        self.assertEqual(req_with_mgr.manager_approved_user_id, self.dept_manager_user)
        self.assertEqual(req_with_mgr.hr_supervisor_approved_user_id, self.hr_supervisor_user)
        self.assertTrue(req_with_mgr.hr_supervisor_approved_date)
        self.assertFalse(req_with_mgr.hr_manager_approved_user_id)

    def test_hr_manager_only_submit_does_not_auto_approve(self):
        # With distinct Dept Manager -> stays at draft
        req_with_mgr = self._create_request(self.hr_manager_user, employee=self.employee)
        self.assertEqual(req_with_mgr.state, "draft")
        self.assertFalse(req_with_mgr.hr_manager_approved_user_id)
        self.assertFalse(req_with_mgr.leave_id)

        # Without Dept Manager, while dedicated HR Supervisor exists -> routes to manager_approve
        req_no_mgr = self._create_request(self.hr_manager_user, employee=self.no_manager_employee)
        self.assertEqual(req_no_mgr.state, "manager_approve")
        self.assertFalse(req_no_mgr.hr_supervisor_approved_user_id)
        self.assertFalse(req_no_mgr.hr_manager_approved_user_id)
        self.assertFalse(req_no_mgr.leave_id)

    def test_forward_escalation_to_hr_manager_when_all_hr_supervisors_are_hr_managers(self):
        self.dual_hr_user.sudo().write({"active": True})

        # While dedicated HR Supervisor (without HR Manager) is active -> stay at manager_approve
        req_with_dedicated = self._create_request(self.basic_user)
        req_with_dedicated.with_user(self.dept_manager_user).action_manager_approve()
        self.assertEqual(req_with_dedicated.state, "manager_approve")

        # Deactivate dedicated HR Supervisor so every active HR Supervisor in the company also holds HR Manager
        self.hr_supervisor_user.sudo().write({"active": False})
        req_escalated = self._create_request(self.basic_user)
        self.assertEqual(req_escalated.state, "draft")
        req_escalated.with_user(self.dept_manager_user).action_manager_approve()
        self.assertEqual(req_escalated.state, "hr_supervisor")
        self.assertEqual(req_escalated.manager_approved_user_id, self.dept_manager_user)
        self.assertFalse(req_escalated.hr_supervisor_approved_user_id)
        self.assertTrue(
            any(
                "Routed directly to HR Manager Approval based on HR Supervisor approver access rights"
                in (msg.body or "")
                for msg in req_escalated.message_ids
            )
        )

        # Same forward escalation when no Dept Manager exists on creation
        req_no_mgr_escalated = self._create_request(self.basic_user, employee=self.no_manager_employee)
        self.assertEqual(req_no_mgr_escalated.state, "hr_supervisor")
        self.assertFalse(req_no_mgr_escalated.hr_supervisor_approved_user_id)

    def test_single_approve_and_reject_button_visibility_for_dual_role_approvers(self):
        self.dual_hr_user.sudo().write({"active": True})
        self.dual_dept_hr_mgr_user.sudo().write({"active": True})

        # 1. Request in draft under a Dual Dept Manager + HR Manager
        req_draft = self._create_request(self.basic_user, employee=self.employee_under_dual_mgr)
        self.assertEqual(req_draft.state, "draft")

        # Dual Dept+HR Mgr sees ONLY HR Manager Approve (not duplicate Dept Manager Approve) and single Reject
        as_dual_dept = req_draft.with_user(self.dual_dept_hr_mgr_user)
        self.assertFalse(as_dual_dept.can_manager_approve)
        self.assertFalse(as_dual_dept.can_hr_supervisor_approve)
        self.assertTrue(as_dual_dept.can_hr_manager_approve)
        self.assertTrue(as_dual_dept.can_reject)

        # Clicking HR Manager Approve records both Dept Manager and HR Manager approval
        as_dual_dept.action_hr_manager_approve()
        self.assertEqual(req_draft.state, "hr_approve")
        self.assertEqual(req_draft.manager_approved_user_id, self.dual_dept_hr_mgr_user)
        self.assertEqual(req_draft.hr_manager_approved_user_id, self.dual_dept_hr_mgr_user)

        # 2. Request in manager_approve
        req_sup = self._create_request(self.basic_user)
        req_sup.with_user(self.dept_manager_user).action_manager_approve()
        self.assertEqual(req_sup.state, "manager_approve")

        # HR Supervisor only sees HR Supervisor Approve & Reject
        as_sup = req_sup.with_user(self.hr_supervisor_user)
        self.assertFalse(as_sup.can_manager_approve)
        self.assertTrue(as_sup.can_hr_supervisor_approve)
        self.assertFalse(as_sup.can_hr_manager_approve)
        self.assertTrue(as_sup.can_reject)

        # HR Manager only sees HR Manager Approve & Reject (skip-level)
        as_mgr = req_sup.with_user(self.hr_manager_user)
        self.assertFalse(as_mgr.can_manager_approve)
        self.assertFalse(as_mgr.can_hr_supervisor_approve)
        self.assertTrue(as_mgr.can_hr_manager_approve)
        self.assertTrue(as_mgr.can_reject)

        # Dual HR Sup+Mgr sees ONLY HR Manager Approve (no duplicate HR Sup Approve) & single Reject
        as_dual_hr = req_sup.with_user(self.dual_hr_user)
        self.assertFalse(as_dual_hr.can_manager_approve)
        self.assertFalse(as_dual_hr.can_hr_supervisor_approve)
        self.assertTrue(as_dual_hr.can_hr_manager_approve)
        self.assertTrue(as_dual_hr.can_reject)

        # Basic user sees none
        as_basic = req_sup.with_user(self.basic_user)
        self.assertFalse(as_basic.can_manager_approve)
        self.assertFalse(as_basic.can_hr_supervisor_approve)
        self.assertFalse(as_basic.can_hr_manager_approve)
        self.assertFalse(as_basic.can_reject)

        # Dual HR Sup+Mgr clicking Approve records both HR Supervisor and HR Manager approval
        as_dual_hr.action_hr_manager_approve()
        self.assertEqual(req_sup.state, "hr_approve")
        self.assertEqual(req_sup.hr_supervisor_approved_user_id, self.dual_hr_user)
        self.assertEqual(req_sup.hr_manager_approved_user_id, self.dual_hr_user)
        self.assertTrue(req_sup.leave_id)

    def test_approval_dashboard_and_menu_own_stage_queues(self):
        self.dual_hr_user.sudo().write({"active": True})
        req_draft = self._create_request(self.basic_user)

        req_sup = self._create_request(self.basic_user)
        req_sup.with_user(self.dept_manager_user).action_manager_approve()

        req_mgr = self._create_request(self.basic_user)
        req_mgr.with_user(self.dept_manager_user).action_manager_approve()
        req_mgr.with_user(self.hr_supervisor_user).action_hr_supervisor_approve()

        req_cancel = self._create_request(self.basic_user)
        req_cancel.with_user(self.hr_manager_user).action_hr_manager_approve()
        req_cancel.with_user(self.basic_user).action_employee_cancel_request()

        all_test_ids = (req_draft | req_sup | req_mgr | req_cancel).ids

        def _visible_ids_for(user):
            domain = self.LeaveRequest.with_user(user)._get_pending_approval_domain(user)
            return set(
                self.LeaveRequest.with_user(user).search(
                    [("id", "in", all_test_ids)] + list(domain)
                ).ids
            )

        # Dept Manager sees ONLY their team's draft
        self.assertEqual(_visible_ids_for(self.dept_manager_user), {req_draft.id})

        # HR Supervisor sees ONLY manager_approve
        self.assertEqual(_visible_ids_for(self.hr_supervisor_user), {req_sup.id})

        # HR Manager sees ONLY hr_supervisor + cancel_request (own stages)
        self.assertEqual(_visible_ids_for(self.hr_manager_user), {req_mgr.id, req_cancel.id})

        # Dual HR Supervisor + HR Manager sees the union of manager_approve + hr_supervisor + cancel_request
        self.assertEqual(
            _visible_ids_for(self.dual_hr_user),
            {req_sup.id, req_mgr.id, req_cancel.id},
        )

        # Basic user sees nothing
        self.assertEqual(_visible_ids_for(self.basic_user), set())

        # If approval dashboard service is installed, verify it returns the same counts
        if "de.hr.approval.dashboard.service" in self.env:
            service = self.env["de.hr.approval.dashboard.service"]
            for user, expected in (
                (self.dept_manager_user, {req_draft.id}),
                (self.hr_supervisor_user, {req_sup.id}),
                (self.hr_manager_user, {req_mgr.id, req_cancel.id}),
                (self.dual_hr_user, {req_sup.id, req_mgr.id, req_cancel.id}),
            ):
                dash_domain = service.with_user(user)._leave_request_pending_domain()
                found = set(
                    self.LeaveRequest.with_user(user).search(
                        [("id", "in", all_test_ids)] + list(dash_domain)
                    ).ids
                )
                self.assertEqual(found, expected)

        # Verify approvals menu search_fetch filters consistently
        approvals_ctx = {"approvals_of_leave_request": True}
        for user, expected in (
            (self.dept_manager_user, {req_draft.id}),
            (self.hr_supervisor_user, {req_sup.id}),
            (self.hr_manager_user, {req_mgr.id, req_cancel.id}),
            (self.dual_hr_user, {req_sup.id, req_mgr.id, req_cancel.id}),
        ):
            fetched = self.LeaveRequest.with_user(user).with_context(**approvals_ctx).search_fetch(
                [("id", "in", all_test_ids)], ["name"]
            )
            self.assertEqual(set(fetched.ids), expected)
