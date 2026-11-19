from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestLeaveRequestApproval(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.LeaveRequest = cls.env["pr.hr.leave.request"]
        cls.approval_company = cls.env["res.company"].create(
            # pr_base requires a unique VAT on company partners
            {"name": "Leave Request Approval Test Company", "vat": "PRLEAVETESTAPPROVAL01"}
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
        # Real HR approvers are also HR officers (needed to read private
        # employee fields such as the direct manager).
        hr_user_group = cls.env.ref("hr.group_hr_user")
        hr_sup_group = cls.env.ref("pr_hr.group_hr_supervisor") | hr_user_group
        hr_mgr_group = cls.env.ref("pr_hr.group_hr_manager") | hr_user_group
        md_group = cls.env.ref("pr_hr.group_hr_md") | hr_user_group
        legacy_sup_group = cls.env.ref("pr_hr_holidays.custom_group_hr_holidays_supervisor")
        legacy_mgr_group = cls.env.ref("hr_holidays.group_hr_holidays_manager")

        def _make_user(name, login, groups, active=True):
            return cls.env["res.users"].sudo().with_context(no_reset_password=True).create({
                "name": name,
                "login": login,
                "email": f"{login}@example.com",
                "active": active,
                "company_id": cls.approval_company.id,
                "company_ids": [Command.set(cls.approval_company.ids)],
                "groups_id": [Command.set((internal | groups).ids)],
            })

        employee_seq = iter(range(1, 100))

        def _make_employee(vals):
            # pr_base requires a unique identification_id on employees
            return cls.env["hr.employee"].sudo().create(
                dict(vals, identification_id="PRLEAVEAPPR%04d" % next(employee_seq))
            )

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
        cls.dual_dept_hr_sup_user = _make_user(
            "Dual Dept+HR Sup Leave User",
            "leave.approval.dept.hr.sup",
            hr_sup_group,
            active=False,
        )
        cls.dual_dept_hr_mgr_user = _make_user(
            "Dual Dept+HR Mgr Leave User",
            "leave.approval.dept.hr.mgr",
            hr_mgr_group,
            active=False,
        )
        cls.triple_dept_hr_user = _make_user(
            "Triple Dept+HR Sup+Mgr Leave User",
            "leave.approval.triple.hr",
            hr_sup_group | hr_mgr_group,
            active=False,
        )
        cls.legacy_hr_user = _make_user(
            "Legacy TimeOff Approver",
            "leave.approval.legacy",
            legacy_sup_group | legacy_mgr_group | hr_user_group,
        )
        cls.md_user = _make_user("MD Leave User", "leave.approval.md", md_group)
        cls.hr_mgr_md_user = _make_user(
            "Dual HR Mgr+MD Leave User",
            "leave.approval.hr.mgr.md",
            hr_mgr_group | md_group,
            active=False,
        )
        cls.all_hr_md_user = _make_user(
            "HR Sup+Mgr+MD Leave User",
            "leave.approval.all.hr.md",
            hr_sup_group | hr_mgr_group | md_group,
            active=False,
        )
        cls.quad_dept_hr_md_user = _make_user(
            "Quad Dept+HR Sup+Mgr+MD Leave User",
            "leave.approval.quad",
            hr_sup_group | hr_mgr_group | md_group,
            active=False,
        )
        cls.under_quad_user = _make_user(
            "Employee Under Quad Leave User", "leave.approval.under.quad", base_employee_groups,
        )

        cls.dept_manager_emp = _make_employee({
            "name": "Dept Manager Employee",
            "user_id": cls.dept_manager_user.id,
            "company_id": cls.approval_company.id,
        })
        cls.employee = _make_employee({
            "name": "Regular Leave Employee",
            "user_id": cls.basic_user.id,
            "parent_id": cls.dept_manager_emp.id,
            "company_id": cls.approval_company.id,
        })
        cls.no_manager_employee = _make_employee({
            "name": "No Manager Leave Employee",
            "company_id": cls.approval_company.id,
        })
        cls.dual_dept_hr_sup_emp = _make_employee({
            "name": "Dual Dept+HR Sup Employee",
            "user_id": cls.dual_dept_hr_sup_user.id,
            "company_id": cls.approval_company.id,
        })
        cls.employee_under_dual_sup = _make_employee({
            "name": "Employee Under Dual Dept+HR Sup",
            "parent_id": cls.dual_dept_hr_sup_emp.id,
            "company_id": cls.approval_company.id,
        })
        cls.dual_dept_hr_mgr_emp = _make_employee({
            "name": "Dual Dept+HR Mgr Employee",
            "user_id": cls.dual_dept_hr_mgr_user.id,
            "company_id": cls.approval_company.id,
        })
        cls.employee_under_dual_mgr = _make_employee({
            "name": "Employee Under Dual Dept+HR Mgr",
            "parent_id": cls.dual_dept_hr_mgr_emp.id,
            "company_id": cls.approval_company.id,
        })
        cls.triple_dept_hr_emp = _make_employee({
            "name": "Triple Dept+HR Sup+Mgr Employee",
            "user_id": cls.triple_dept_hr_user.id,
            "company_id": cls.approval_company.id,
        })
        cls.employee_under_triple_mgr = _make_employee({
            "name": "Employee Under Triple Dept+HR Sup+Mgr",
            "parent_id": cls.triple_dept_hr_emp.id,
            "company_id": cls.approval_company.id,
        })

        cls.quad_dept_hr_md_emp = _make_employee({
            "name": "Quad Dept+HR Sup+Mgr+MD Employee",
            "user_id": cls.quad_dept_hr_md_user.id,
            "company_id": cls.approval_company.id,
        })
        cls.employee_under_quad = _make_employee({
            "name": "Employee Under Quad",
            "user_id": cls.under_quad_user.id,
            "parent_id": cls.quad_dept_hr_md_emp.id,
            "company_id": cls.approval_company.id,
        })

        cls.leave_type = cls.env["hr.leave.type"].sudo().create({
            "name": "Annual Leave Approval Test",
            "time_type": "leave",
            "request_unit": "day",
            # Readable by the test users, who only belong to the test company
            "company_id": cls.approval_company.id,
            # A type without allocation reports 0 available days
            "requires_allocation": "yes",
            "allocation_validation_type": "no",
            "leave_type": "annual_leave",
        })
        for employee in (
            cls.employee, cls.no_manager_employee, cls.dept_manager_emp,
            cls.employee_under_dual_sup, cls.employee_under_dual_mgr,
            cls.employee_under_triple_mgr, cls.employee_under_quad,
        ):
            allocation = cls.env["hr.leave.allocation"].sudo().create({
                "name": "Approval Test Allocation",
                "holiday_type": "employee",
                "employee_id": employee.id,
                "holiday_status_id": cls.leave_type.id,
                "allocation_type": "regular",
                "number_of_days": 500,
                "date_from": fields.Date.context_today(cls.env.user) - timedelta(days=1),
            })
            if allocation.state != "validate":
                allocation.action_validate()
        cls._date_offset = 20

    def _next_date_pair(self, span_days=2):
        today = fields.Date.context_today(self.env.user)
        start = today + timedelta(days=self._date_offset)
        while start.weekday() >= 4:
            start += timedelta(days=1)
        end = start + timedelta(days=span_days)
        self.__class__._date_offset += span_days + 5
        return start, end

    def _create_draft_request(self, user, employee=None, span_days=2):
        employee = employee or self.employee
        date_from, date_to = self._next_date_pair(span_days=span_days)
        return self.LeaveRequest.with_user(user).sudo().create({
            "employee_id": employee.id,
            "company_id": self.approval_company.id,
            "leave_type_id": self.leave_type.id,
            "date_from": date_from,
            "date_to": date_to,
        })

    def _create_request(self, user, employee=None, span_days=2):
        # A request for another employee is submitted by a user allowed to pick
        # any employee; legacy_hr_user holds no pr_hr role, so routing is neutral.
        request = self._create_draft_request(user, employee=employee, span_days=span_days)
        request.with_user(user).action_submit()
        return request

    def _reject_via_wizard(self, request, user, reason="Not approved", from_dashboard=False):
        ctx = {"from_approval_dashboard": True} if from_dashboard else {}
        action = request.with_user(user).with_context(**ctx).action_reject()
        wizard = self.env["pr.reject.record.wizard"].with_user(user).with_context(
            **action["context"]
        ).create({"reject_reason": reason})
        wizard.action_reject()
        request.invalidate_recordset()

    def test_draft_created_editable_and_routed_only_on_submit(self):
        # Unsaved new record shows Submit immediately and defaults employee/company
        unsaved = self.LeaveRequest.with_user(self.basic_user).new({})
        self.assertEqual(unsaved.state, "draft")
        self.assertTrue(unsaved.can_submit)
        self.assertFalse(unsaved.can_select_employee)
        self.assertEqual(unsaved.employee_id, self.employee)
        self.assertEqual(unsaved.company_id, self.approval_company)

        # HR users can select any employee
        unsaved_hr = self.LeaveRequest.with_user(self.hr_supervisor_user).new({})
        self.assertTrue(unsaved_hr.can_select_employee)

        # Workspace employee can create their own draft directly (without sudo), edit, and delete it
        date_from, date_to = self._next_date_pair()
        own_draft = self.LeaveRequest.with_user(self.basic_user).create({
            "leave_type_id": self.leave_type.id,
            "date_from": date_from,
            "date_to": date_to,
        })
        self.assertEqual(own_draft.state, "draft")
        self.assertEqual(own_draft.employee_id, self.employee)
        own_draft.with_user(self.basic_user).write({"note": "Updated while draft"})
        own_draft.with_user(self.basic_user).unlink()
        self.assertFalse(own_draft.exists())

        # Non-HR user cannot create a request for another employee or delete someone else's draft
        date_from2, date_to2 = self._next_date_pair()
        with self.assertRaises(AccessError):
            self.LeaveRequest.with_user(self.basic_user).create({
                "employee_id": self.dept_manager_emp.id,
                "company_id": self.approval_company.id,
                "leave_type_id": self.leave_type.id,
                "date_from": date_from2,
                "date_to": date_to2,
            })

        other_draft = self._create_draft_request(self.hr_supervisor_user, employee=self.dept_manager_emp)
        with self.assertRaises(AccessError):
            other_draft.with_user(self.basic_user).unlink()

        request = self._create_draft_request(self.basic_user)
        self.assertEqual(request.state, "draft")
        self.assertEqual(request.approval_state, "draft")
        self.assertTrue(request.with_user(self.basic_user).can_submit)
        self.assertFalse(request.with_user(self.dept_manager_user).can_manager_approve)
        self.assertFalse(request.with_user(self.hr_manager_user).can_hr_manager_approve)
        self.assertFalse(request.leave_id)

        # Submitting routes to Dept. Manager approval and blocks unlink
        request.with_user(self.basic_user).action_submit()
        self.assertEqual(request.state, "employee_manager_approval")
        self.assertEqual(request.approval_state, "employee_manager_approval")
        self.assertEqual(request.submitted_by_id, self.basic_user)
        with self.assertRaises(ValidationError):
            request.sudo().unlink()

    def test_standard_four_stage_approval_creates_validated_leave(self):
        request = self._create_request(self.basic_user)
        self.assertEqual(request.state, "employee_manager_approval")
        self.assertFalse(request.leave_id)

        # Unauthorized & legacy-only users cannot approve
        with self.assertRaises(AccessError):
            request.with_user(self.basic_user).action_manager_approve()
        with self.assertRaises(AccessError):
            request.with_user(self.legacy_hr_user).action_hr_manager_approve()

        # Stage 1: Dept. Manager approves -> hr_supervisor_approval
        request.with_user(self.dept_manager_user).action_manager_approve()
        self.assertEqual(request.state, "hr_supervisor_approval")
        self.assertEqual(request.approval_state, "hr_supervisor_approval")
        self.assertEqual(request.manager_approved_user_id, self.dept_manager_user)
        self.assertTrue(request.manager_approved_date)

        with self.assertRaises(AccessError):
            request.with_user(self.legacy_hr_user).action_hr_supervisor_approve()

        # Stage 2: HR Supervisor approves -> hr_manager_approval
        request.with_user(self.hr_supervisor_user).action_hr_supervisor_approve()
        self.assertEqual(request.state, "hr_manager_approval")
        self.assertEqual(request.approval_state, "hr_manager_approval")
        self.assertEqual(request.hr_supervisor_approved_user_id, self.hr_supervisor_user)
        self.assertTrue(request.hr_supervisor_approved_date)

        # HR Supervisor cannot perform final HR Manager approval
        with self.assertRaises(AccessError):
            request.with_user(self.hr_supervisor_user).action_hr_manager_approve()

        # Stage 3: HR Manager approves -> md_approval, no hr.leave yet
        request.with_user(self.hr_manager_user).action_hr_manager_approve()
        self.assertEqual(request.state, "md_approval")
        self.assertEqual(request.approval_state, "md_approval")
        self.assertEqual(request.hr_manager_approved_user_id, self.hr_manager_user)
        self.assertTrue(request.hr_manager_approved_date)
        self.assertFalse(request.leave_id)

        # HR Manager can neither approve again nor take the MD decision
        with self.assertRaises(UserError):
            request.with_user(self.hr_manager_user).action_hr_manager_approve()
        with self.assertRaises(AccessError):
            request.with_user(self.hr_manager_user).action_md_approve()
        self.assertFalse(request.with_user(self.hr_manager_user).can_reject)
        self.assertTrue(request.with_user(self.md_user).can_md_approve)

        # Stage 4: MD approves -> approved + validated hr.leave
        request.with_user(self.md_user).action_md_approve()
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.approval_state, "approved")
        self.assertEqual(request.md_approved_user_id, self.md_user)
        self.assertTrue(request.md_approved_date)
        self.assertTrue(request.leave_id)
        self.assertEqual(request.leave_id.state, "validate")

    def test_sequential_submit_routing_for_distinct_manager_consecutive_roles(self):
        self.dual_dept_hr_sup_user.sudo().write({"active": True})
        self.dual_dept_hr_mgr_user.sudo().write({"active": True})
        self.triple_dept_hr_user.sudo().write({"active": True})

        # Dept. Manager + HR Supervisor -> submit routes directly to hr_supervisor_approval
        req_sup = self._create_request(self.legacy_hr_user, employee=self.employee_under_dual_sup)
        self.assertEqual(req_sup.state, "hr_supervisor_approval")
        self.assertFalse(req_sup.leave_id)

        # Dept. Manager + HR Supervisor + HR Manager -> submit routes directly to hr_manager_approval
        req_triple = self._create_request(self.legacy_hr_user, employee=self.employee_under_triple_mgr)
        self.assertEqual(req_triple.state, "hr_manager_approval")
        self.assertFalse(req_triple.leave_id)

        # Dept. Manager + HR Manager WITHOUT HR Supervisor -> stops at employee_manager_approval
        req_gap = self._create_request(self.legacy_hr_user, employee=self.employee_under_dual_mgr)
        self.assertEqual(req_gap.state, "employee_manager_approval")
        self.assertFalse(req_gap.leave_id)

        # Dept. Manager + HR Supervisor + HR Manager + MD -> submit routes directly to md_approval
        self.quad_dept_hr_md_user.sudo().write({"active": True})
        req_quad = self._create_request(self.under_quad_user, employee=self.employee_under_quad)
        self.assertEqual(req_quad.state, "md_approval")
        self.assertFalse(req_quad.leave_id)

    def test_backend_skip_level_approval_for_hr_supervisor_and_hr_manager(self):
        # HR Supervisor skip-level from employee_manager_approval -> hr_manager_approval
        req_sup_skip = self._create_request(self.basic_user)
        self.assertEqual(req_sup_skip.state, "employee_manager_approval")
        self.assertTrue(req_sup_skip.with_user(self.hr_supervisor_user).can_hr_supervisor_approve)
        req_sup_skip.with_user(self.hr_supervisor_user).action_hr_supervisor_approve()
        self.assertEqual(req_sup_skip.state, "hr_manager_approval")
        self.assertFalse(req_sup_skip.manager_approved_user_id)
        self.assertEqual(req_sup_skip.hr_supervisor_approved_user_id, self.hr_supervisor_user)
        self.assertTrue(
            any("skip-level approval" in (msg.body or "") for msg in req_sup_skip.message_ids)
        )

        # HR Manager skip-level from employee_manager_approval -> md_approval
        req_mgr_skip1 = self._create_request(self.basic_user)
        self.assertEqual(req_mgr_skip1.state, "employee_manager_approval")
        req_mgr_skip1.with_user(self.hr_manager_user).action_hr_manager_approve()
        self.assertEqual(req_mgr_skip1.state, "md_approval")
        self.assertEqual(req_mgr_skip1.hr_manager_approved_user_id, self.hr_manager_user)
        self.assertFalse(req_mgr_skip1.manager_approved_user_id)
        self.assertFalse(req_mgr_skip1.hr_supervisor_approved_user_id)
        self.assertFalse(req_mgr_skip1.leave_id)
        self.assertTrue(
            any("skip-level approval" in (msg.body or "") for msg in req_mgr_skip1.message_ids)
        )
        req_mgr_skip1.with_user(self.md_user).action_md_approve()
        self.assertEqual(req_mgr_skip1.state, "approved")
        self.assertEqual(req_mgr_skip1.leave_id.state, "validate")

        # HR Manager skip-level from hr_supervisor_approval -> md_approval
        req_mgr_skip2 = self._create_request(self.basic_user)
        req_mgr_skip2.with_user(self.dept_manager_user).action_manager_approve()
        self.assertEqual(req_mgr_skip2.state, "hr_supervisor_approval")
        req_mgr_skip2.with_user(self.hr_manager_user).action_hr_manager_approve()
        self.assertEqual(req_mgr_skip2.state, "md_approval")
        self.assertEqual(req_mgr_skip2.manager_approved_user_id, self.dept_manager_user)
        self.assertFalse(req_mgr_skip2.hr_supervisor_approved_user_id)
        self.assertEqual(req_mgr_skip2.hr_manager_approved_user_id, self.hr_manager_user)
        self.assertFalse(req_mgr_skip2.leave_id)
        self.assertTrue(
            any("skip-level approval" in (msg.body or "") for msg in req_mgr_skip2.message_ids)
        )

        # MD skip-level from employee_manager_approval -> approved, only the MD stage recorded
        req_md_skip = self._create_request(self.basic_user)
        self.assertTrue(req_md_skip.with_user(self.md_user).can_md_approve)
        self.assertTrue(req_md_skip.with_user(self.md_user).can_reject)
        req_md_skip.with_user(self.md_user).action_md_approve()
        self.assertEqual(req_md_skip.state, "approved")
        self.assertFalse(req_md_skip.manager_approved_user_id)
        self.assertFalse(req_md_skip.hr_supervisor_approved_user_id)
        self.assertFalse(req_md_skip.hr_manager_approved_user_id)
        self.assertEqual(req_md_skip.md_approved_user_id, self.md_user)
        self.assertEqual(req_md_skip.leave_id.state, "validate")
        self.assertTrue(
            any("skip-level approval" in (msg.body or "") for msg in req_md_skip.message_ids)
        )

    def test_dashboard_intermediate_rights_safeguard(self):
        dash_ctx = {"from_approval_dashboard": True}

        # At employee_manager_approval: HR Supervisor without Dept. Manager rights is blocked on dashboard
        req_mgr = self._create_request(self.basic_user)
        self.assertEqual(req_mgr.state, "employee_manager_approval")
        as_sup_dash = req_mgr.with_user(self.hr_supervisor_user).with_context(**dash_ctx)
        self.assertEqual(as_sup_dash.dashboard_approve_role, "none")
        self.assertFalse(as_sup_dash.can_hr_supervisor_approve)
        self.assertFalse(as_sup_dash.can_reject)
        with self.assertRaises(UserError):
            as_sup_dash.action_hr_supervisor_approve()

        # HR Manager without Dept. Manager / HR Supervisor rights is also blocked on dashboard
        as_hrm_dash = req_mgr.with_user(self.hr_manager_user).with_context(**dash_ctx)
        self.assertEqual(as_hrm_dash.dashboard_approve_role, "none")
        self.assertFalse(as_hrm_dash.can_hr_manager_approve)
        with self.assertRaises(UserError):
            as_hrm_dash.action_hr_manager_approve()

        # Dept. Manager + HR Manager (lacking HR Supervisor) on dashboard sees ONLY Dept. Manager Approve
        self.dual_dept_hr_mgr_user.sudo().write({"active": True})
        req_gap = self._create_request(self.legacy_hr_user, employee=self.employee_under_dual_mgr)
        as_gap_dash = req_gap.with_user(self.dual_dept_hr_mgr_user).with_context(**dash_ctx)
        self.assertEqual(as_gap_dash.dashboard_approve_role, "employee_manager")
        self.assertTrue(as_gap_dash.can_manager_approve)
        self.assertFalse(as_gap_dash.can_hr_manager_approve)
        with self.assertRaises(UserError):
            as_gap_dash.action_hr_manager_approve()

        # At hr_supervisor_approval: HR Manager without HR Supervisor rights is blocked on dashboard
        req_sup = self._create_request(self.basic_user)
        req_sup.with_user(self.dept_manager_user).action_manager_approve()
        self.assertEqual(req_sup.state, "hr_supervisor_approval")
        with self.assertRaises(UserError):
            req_sup.with_user(self.hr_manager_user).with_context(**dash_ctx).action_hr_manager_approve()

        # MD without the earlier roles is blocked on dashboard (approve and reject)
        as_md_dash = req_sup.with_user(self.md_user).with_context(**dash_ctx)
        self.assertEqual(as_md_dash.dashboard_approve_role, "none")
        self.assertFalse(as_md_dash.can_md_approve)
        with self.assertRaises(UserError):
            as_md_dash.action_md_approve()
        with self.assertRaises(AccessError):
            as_md_dash.action_md_reject()

        # Dual HR Supervisor + HR Manager CAN approve at hr_supervisor_approval from dashboard
        self.dual_hr_user.sudo().write({"active": True})
        as_dual_dash = req_sup.with_user(self.dual_hr_user).with_context(**dash_ctx)
        self.assertEqual(as_dual_dash.dashboard_approve_role, "hr_manager")
        self.assertTrue(as_dual_dash.can_hr_manager_approve)
        as_dual_dash.action_hr_manager_approve()
        self.assertEqual(req_sup.state, "md_approval")

        # At md_approval only the MD gets a dashboard role
        self.assertEqual(
            req_sup.with_user(self.hr_manager_user).with_context(**dash_ctx).dashboard_approve_role, "none"
        )
        as_md_dash = req_sup.with_user(self.md_user).with_context(**dash_ctx)
        self.assertEqual(as_md_dash.dashboard_approve_role, "md")
        as_md_dash.action_md_approve()
        self.assertEqual(req_sup.state, "approved")

    def test_rejection_reset_and_reset_to_draft(self):
        # Reject from employee_manager_approval via HR Manager skip-level -> reset reopens back
        req_mgr = self._create_request(self.basic_user)
        self.assertEqual(req_mgr.state, "employee_manager_approval")
        self._reject_via_wizard(req_mgr, self.hr_manager_user, reason="Rejected at dept mgr stage")
        self.assertEqual(req_mgr.state, "rejected")
        self.assertEqual(req_mgr.approval_state, "rejected")
        self.assertEqual(req_mgr.rejected_stage, "hr_manager")
        self.assertEqual(req_mgr.rejected_from_state, "employee_manager_approval")
        self.assertFalse(req_mgr.leave_id)

        # Dept. Manager cannot reset HR Manager's rejection
        with self.assertRaises(UserError):
            req_mgr.with_user(self.dept_manager_user).action_reset_rejection()

        req_mgr.with_user(self.hr_manager_user).action_reset_rejection()
        self.assertEqual(req_mgr.state, "employee_manager_approval")
        self.assertFalse(req_mgr.rejected_stage)
        self.assertFalse(req_mgr.rejected_from_state)

        # Reject from hr_supervisor_approval -> reset reopens back to hr_supervisor_approval
        req_sup = self._create_request(self.basic_user)
        req_sup.with_user(self.dept_manager_user).action_manager_approve()
        self.assertEqual(req_sup.state, "hr_supervisor_approval")
        self._reject_via_wizard(req_sup, self.hr_manager_user, reason="Rejected at sup stage")
        self.assertEqual(req_sup.state, "rejected")
        self.assertEqual(req_sup.rejected_from_state, "hr_supervisor_approval")

        req_sup.with_user(self.hr_manager_user).action_reset_rejection()
        self.assertEqual(req_sup.state, "hr_supervisor_approval")
        self.assertEqual(req_sup.manager_approved_user_id, self.dept_manager_user)

        # Reject again and use Reset to Draft as the employee -> clears approvals and returns to Draft
        self._reject_via_wizard(req_sup, self.hr_supervisor_user, reason="Please adjust dates")
        self.assertEqual(req_sup.state, "rejected")
        self.assertTrue(req_sup.with_user(self.basic_user).can_reset_to_draft)
        req_sup.with_user(self.basic_user).action_reset_to_draft()
        self.assertEqual(req_sup.state, "draft")
        self.assertEqual(req_sup.approval_state, "draft")
        self.assertFalse(req_sup.manager_approved_user_id)
        self.assertFalse(req_sup.hr_supervisor_approved_user_id)
        self.assertFalse(req_sup.reject_reason)
        self.assertFalse(req_sup.rejected_stage)
        self.assertFalse(req_sup.rejected_from_state)

        # Employee can edit and re-submit after Reset to Draft
        req_sup.with_user(self.basic_user).action_submit()
        self.assertEqual(req_sup.state, "employee_manager_approval")

    def test_direct_manager_with_dual_hr_roles_submit_waits_for_md(self):
        self.triple_dept_hr_user.sudo().write({"active": True})
        # Direct manager who also holds HR Supervisor + HR Manager (no MD) covers
        # every stage up to HR Manager on submit; the MD still has to approve
        request = self._create_request(self.triple_dept_hr_user, employee=self.employee_under_triple_mgr)
        self.assertEqual(request.state, "md_approval")
        self.assertEqual(request.approval_state, "md_approval")
        self.assertEqual(request.manager_approved_user_id, self.triple_dept_hr_user)
        self.assertEqual(request.hr_supervisor_approved_user_id, self.triple_dept_hr_user)
        self.assertTrue(request.hr_supervisor_approved_date)
        self.assertEqual(request.hr_manager_approved_user_id, self.triple_dept_hr_user)
        self.assertTrue(request.hr_manager_approved_date)
        self.assertFalse(request.md_approved_user_id)
        self.assertFalse(request.leave_id)
        self.assertTrue(
            any("auto-advanced to MD Approval" in (msg.body or "") for msg in request.message_ids)
        )

    def test_direct_manager_with_all_four_roles_submit_auto_approves_immediately(self):
        self.quad_dept_hr_md_user.sudo().write({"active": True})
        request = self._create_request(self.quad_dept_hr_md_user, employee=self.employee_under_quad)
        self.assertEqual(request.state, "approved")
        for fname in ("manager_approved_user_id", "hr_supervisor_approved_user_id",
                      "hr_manager_approved_user_id", "md_approved_user_id"):
            self.assertEqual(request[fname], self.quad_dept_hr_md_user, fname)
        self.assertEqual(request.leave_id.state, "validate")
        self.assertTrue(
            any("Auto-approved on submission" in (msg.body or "") for msg in request.message_ids)
        )

        # Same without any other direct manager
        self.all_hr_md_user.sudo().write({"active": True})
        request = self._create_request(self.all_hr_md_user, employee=self.no_manager_employee)
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.md_approved_user_id, self.all_hr_md_user)
        self.assertTrue(request.leave_id)

    def test_dual_hr_submit_without_other_direct_manager_waits_for_md(self):
        self.dual_hr_user.sudo().write({"active": True})
        request = self._create_request(self.dual_hr_user, employee=self.no_manager_employee)
        self.assertEqual(request.state, "md_approval")
        self.assertEqual(request.hr_supervisor_approved_user_id, self.dual_hr_user)
        self.assertEqual(request.hr_manager_approved_user_id, self.dual_hr_user)
        self.assertFalse(request.leave_id)

    def test_dual_hr_submit_for_other_managers_employee_waits_for_direct_manager(self):
        self.dual_hr_user.sudo().write({"active": True})
        # Dual HR Sup+Mgr who is NOT the direct manager: the direct manager must approve first
        request = self._create_request(self.dual_hr_user, employee=self.employee)
        self.assertEqual(request.state, "employee_manager_approval")
        self.assertFalse(request.hr_supervisor_approved_user_id)
        self.assertFalse(request.hr_manager_approved_user_id)
        self.assertFalse(request.leave_id)

        # Once the direct manager approves, the creator covers both HR stages -> md_approval
        request.with_user(self.dept_manager_user).action_manager_approve()
        self.assertEqual(request.state, "md_approval")
        self.assertEqual(request.manager_approved_user_id, self.dept_manager_user)
        self.assertEqual(request.hr_supervisor_approved_user_id, self.dual_hr_user)
        self.assertEqual(request.hr_manager_approved_user_id, self.dual_hr_user)
        self.assertFalse(request.leave_id)

        request.with_user(self.md_user).action_md_approve()
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.md_approved_user_id, self.md_user)
        self.assertTrue(request.leave_id)
        self.assertEqual(request.leave_id.state, "validate")

    def test_hr_and_md_creator_for_other_managers_employee_approves_after_direct_manager(self):
        self.all_hr_md_user.sudo().write({"active": True})
        request = self._create_request(self.all_hr_md_user, employee=self.employee)
        self.assertEqual(request.state, "employee_manager_approval")
        request.with_user(self.dept_manager_user).action_manager_approve()
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.manager_approved_user_id, self.dept_manager_user)
        self.assertEqual(request.hr_manager_approved_user_id, self.all_hr_md_user)
        self.assertEqual(request.md_approved_user_id, self.all_hr_md_user)
        self.assertEqual(request.leave_id.state, "validate")

    def test_direct_manager_with_all_four_roles_routes_to_md_and_approves_in_one_click(self):
        self.quad_dept_hr_md_user.sudo().write({"active": True})
        request = self._create_request(self.under_quad_user, employee=self.employee_under_quad)
        self.assertEqual(request.state, "md_approval")
        self.assertEqual(request.manager_approved_user_id, self.quad_dept_hr_md_user)
        self.assertEqual(request.hr_supervisor_approved_user_id, self.quad_dept_hr_md_user)
        self.assertEqual(request.hr_manager_approved_user_id, self.quad_dept_hr_md_user)
        self.assertFalse(request.md_approved_user_id)
        self.assertFalse(request.leave_id)

        as_quad = request.with_user(self.quad_dept_hr_md_user)
        self.assertTrue(as_quad.can_md_approve)
        self.assertEqual(
            as_quad.with_context(from_approval_dashboard=True).dashboard_approve_role, "md"
        )
        as_quad.action_md_approve()
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.md_approved_user_id, self.quad_dept_hr_md_user)
        self.assertEqual(request.leave_id.state, "validate")

    def test_hr_manager_who_is_md_approves_both_stages_in_one_click(self):
        self.hr_mgr_md_user.sudo().write({"active": True})
        for use_md_button in (True, False):
            request = self._create_request(self.basic_user)
            request.with_user(self.dept_manager_user).action_manager_approve()
            request.with_user(self.hr_supervisor_user).action_hr_supervisor_approve()
            self.assertEqual(request.state, "hr_manager_approval")
            as_dual = request.with_user(self.hr_mgr_md_user)
            # Backend and dashboard both show a single MD Approve button
            self.assertTrue(as_dual.can_md_approve)
            self.assertFalse(as_dual.can_hr_manager_approve)
            self.assertEqual(
                as_dual.with_context(from_approval_dashboard=True).dashboard_approve_role, "md"
            )
            if use_md_button:
                as_dual.with_context(from_approval_dashboard=True).action_md_approve()
            else:
                as_dual.action_hr_manager_approve()
            self.assertEqual(request.state, "approved")
            self.assertEqual(request.hr_manager_approved_user_id, self.hr_mgr_md_user)
            self.assertEqual(request.md_approved_user_id, self.hr_mgr_md_user)
            self.assertEqual(request.leave_id.state, "validate")

    def test_md_rejection_and_reset_reopens_md_stage(self):
        request = self._create_request(self.basic_user)
        request.with_user(self.dept_manager_user).action_manager_approve()
        request.with_user(self.hr_supervisor_user).action_hr_supervisor_approve()
        request.with_user(self.hr_manager_user).action_hr_manager_approve()
        self.assertEqual(request.state, "md_approval")

        self._reject_via_wizard(request, self.md_user, reason="Not this month")
        self.assertEqual(request.state, "rejected")
        self.assertEqual(request.rejected_stage, "md")
        self.assertEqual(request.rejected_from_state, "md_approval")
        self.assertEqual(request.rejected_by_user_id, self.md_user)

        # Only an MD can reopen the MD decision
        with self.assertRaises(UserError):
            request.with_user(self.hr_manager_user).action_reset_rejection()
        self.assertTrue(request.with_user(self.md_user).can_reset_rejection)
        request.with_user(self.md_user).action_reset_rejection()
        self.assertEqual(request.state, "md_approval")
        self.assertEqual(request.hr_manager_approved_user_id, self.hr_manager_user)
        self.assertFalse(request.md_approved_user_id)
        self.assertFalse(request.rejected_stage)

        # MD skip-level rejection from an earlier stage reopens that stage
        early = self._create_request(self.basic_user)
        self._reject_via_wizard(early, self.md_user, reason="Skip-level no")
        self.assertEqual(early.rejected_stage, "md")
        self.assertEqual(early.rejected_from_state, "employee_manager_approval")
        early.with_user(self.md_user).action_reset_rejection()
        self.assertEqual(early.state, "employee_manager_approval")

    def test_dual_hr_submit_routes_to_direct_managers_highest_role(self):
        self.dual_hr_user.sudo().write({"active": True})
        self.dual_dept_hr_sup_user.sudo().write({"active": True})
        # Direct manager also holds HR Supervisor -> request skips the Dept. Manager
        # stage and waits for that manager at HR Supervisor
        request = self._create_request(self.dual_hr_user, employee=self.employee_under_dual_sup)
        self.assertEqual(request.state, "hr_supervisor_approval")
        self.assertEqual(request.manager_approved_user_id, self.dual_dept_hr_sup_user)
        self.assertFalse(request.leave_id)

        # Manager approves as HR Supervisor; the creator covers HR Manager -> md_approval
        request.with_user(self.dual_dept_hr_sup_user).action_hr_supervisor_approve()
        self.assertEqual(request.state, "md_approval")
        self.assertEqual(request.manager_approved_user_id, self.dual_dept_hr_sup_user)
        self.assertEqual(request.hr_supervisor_approved_user_id, self.dual_dept_hr_sup_user)
        self.assertEqual(request.hr_manager_approved_user_id, self.dual_hr_user)
        self.assertFalse(request.leave_id)

    def test_hr_supervisor_submit_auto_advances_to_hr_manager(self):
        # Employee WITHOUT a distinct Dept. Manager -> advances directly to hr_manager_approval on submit
        req_no_mgr = self._create_request(self.hr_supervisor_user, employee=self.no_manager_employee)
        self.assertEqual(req_no_mgr.state, "hr_manager_approval")
        self.assertEqual(req_no_mgr.hr_supervisor_approved_user_id, self.hr_supervisor_user)
        self.assertTrue(req_no_mgr.hr_supervisor_approved_date)
        self.assertFalse(req_no_mgr.hr_manager_approved_user_id)
        self.assertFalse(req_no_mgr.leave_id)

        # Employee WITH a distinct Dept. Manager -> starts at employee_manager_approval,
        # then auto-advances past HR Supervisor on Dept. Manager approval
        req_with_mgr = self._create_request(self.hr_supervisor_user, employee=self.employee)
        self.assertEqual(req_with_mgr.state, "employee_manager_approval")
        self.assertFalse(req_with_mgr.hr_supervisor_approved_user_id)

        req_with_mgr.with_user(self.dept_manager_user).action_manager_approve()
        self.assertEqual(req_with_mgr.state, "hr_manager_approval")
        self.assertEqual(req_with_mgr.manager_approved_user_id, self.dept_manager_user)
        self.assertEqual(req_with_mgr.hr_supervisor_approved_user_id, self.hr_supervisor_user)
        self.assertTrue(req_with_mgr.hr_supervisor_approved_date)
        self.assertFalse(req_with_mgr.hr_manager_approved_user_id)

    def test_hr_manager_only_submit_does_not_auto_approve(self):
        # With distinct Dept. Manager -> stays at employee_manager_approval
        req_with_mgr = self._create_request(self.hr_manager_user, employee=self.employee)
        self.assertEqual(req_with_mgr.state, "employee_manager_approval")
        self.assertFalse(req_with_mgr.hr_manager_approved_user_id)
        self.assertFalse(req_with_mgr.leave_id)

        # Without Dept. Manager, while dedicated HR Supervisor exists -> routes to hr_supervisor_approval
        req_no_mgr = self._create_request(self.hr_manager_user, employee=self.no_manager_employee)
        self.assertEqual(req_no_mgr.state, "hr_supervisor_approval")
        self.assertFalse(req_no_mgr.hr_supervisor_approved_user_id)
        self.assertFalse(req_no_mgr.hr_manager_approved_user_id)
        self.assertFalse(req_no_mgr.leave_id)

    def test_forward_escalation_to_hr_manager_when_all_hr_supervisors_are_hr_managers(self):
        self.dual_hr_user.sudo().write({"active": True})

        # While dedicated HR Supervisor (without HR Manager) is active -> stay at hr_supervisor_approval
        req_with_dedicated = self._create_request(self.basic_user)
        req_with_dedicated.with_user(self.dept_manager_user).action_manager_approve()
        self.assertEqual(req_with_dedicated.state, "hr_supervisor_approval")

        # Deactivate dedicated HR Supervisor so every active HR Supervisor also holds HR Manager
        self.hr_supervisor_user.sudo().write({"active": False})
        req_escalated = self._create_request(self.basic_user)
        self.assertEqual(req_escalated.state, "employee_manager_approval")
        req_escalated.with_user(self.dept_manager_user).action_manager_approve()
        self.assertEqual(req_escalated.state, "hr_manager_approval")
        self.assertEqual(req_escalated.manager_approved_user_id, self.dept_manager_user)
        self.assertFalse(req_escalated.hr_supervisor_approved_user_id)
        self.assertTrue(
            any(
                "Routed directly to HR Manager Approval based on HR Supervisor approver access rights"
                in (msg.body or "")
                for msg in req_escalated.message_ids
            )
        )

        # Same forward escalation when no Dept. Manager exists on submit
        req_no_mgr_escalated = self._create_request(self.legacy_hr_user, employee=self.no_manager_employee)
        self.assertEqual(req_no_mgr_escalated.state, "hr_manager_approval")
        self.assertFalse(req_no_mgr_escalated.hr_supervisor_approved_user_id)

    def test_single_approve_and_reject_button_visibility_for_dual_role_approvers(self):
        self.dual_hr_user.sudo().write({"active": True})
        self.dual_dept_hr_mgr_user.sudo().write({"active": True})

        # 1. Request in employee_manager_approval under a Dual Dept. Manager + HR Manager
        req_mgr = self._create_request(self.legacy_hr_user, employee=self.employee_under_dual_mgr)
        self.assertEqual(req_mgr.state, "employee_manager_approval")

        # Backend: Dual Dept+HR Mgr sees ONLY HR Manager Approve and single Reject
        as_dual_dept = req_mgr.with_user(self.dual_dept_hr_mgr_user)
        self.assertFalse(as_dual_dept.can_manager_approve)
        self.assertFalse(as_dual_dept.can_hr_supervisor_approve)
        self.assertTrue(as_dual_dept.can_hr_manager_approve)
        self.assertTrue(as_dual_dept.can_reject)

        # Clicking HR Manager Approve records both Dept. Manager and HR Manager approval
        as_dual_dept.action_hr_manager_approve()
        self.assertEqual(req_mgr.state, "md_approval")
        self.assertEqual(req_mgr.manager_approved_user_id, self.dual_dept_hr_mgr_user)
        self.assertEqual(req_mgr.hr_manager_approved_user_id, self.dual_dept_hr_mgr_user)

        # 2. Request in hr_supervisor_approval
        req_sup = self._create_request(self.basic_user)
        req_sup.with_user(self.dept_manager_user).action_manager_approve()
        self.assertEqual(req_sup.state, "hr_supervisor_approval")

        # HR Supervisor only sees HR Supervisor Approve & Reject
        as_sup = req_sup.with_user(self.hr_supervisor_user)
        self.assertFalse(as_sup.can_manager_approve)
        self.assertTrue(as_sup.can_hr_supervisor_approve)
        self.assertFalse(as_sup.can_hr_manager_approve)
        self.assertTrue(as_sup.can_reject)

        # HR Manager only sees HR Manager Approve & Reject (skip-level in backend)
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

        # MD sees ONLY MD Approve (backend skip-level) & single Reject
        as_md = req_sup.with_user(self.md_user)
        self.assertFalse(as_md.can_hr_supervisor_approve)
        self.assertFalse(as_md.can_hr_manager_approve)
        self.assertTrue(as_md.can_md_approve)
        self.assertTrue(as_md.can_reject)

        # Basic user sees none
        as_basic = req_sup.with_user(self.basic_user)
        self.assertFalse(as_basic.can_manager_approve)
        self.assertFalse(as_basic.can_hr_supervisor_approve)
        self.assertFalse(as_basic.can_hr_manager_approve)
        self.assertFalse(as_basic.can_md_approve)
        self.assertFalse(as_basic.can_reject)

        # Dual HR Sup+Mgr clicking Approve records both HR Supervisor and HR Manager approval
        as_dual_hr.action_hr_manager_approve()
        self.assertEqual(req_sup.state, "md_approval")
        self.assertEqual(req_sup.hr_supervisor_approved_user_id, self.dual_hr_user)
        self.assertEqual(req_sup.hr_manager_approved_user_id, self.dual_hr_user)
        self.assertFalse(req_sup.leave_id)

        # At md_approval the HR roles see nothing, the MD sees MD Approve
        self.assertFalse(req_sup.with_user(self.dual_hr_user).can_hr_manager_approve)
        self.assertFalse(req_sup.with_user(self.dual_hr_user).can_reject)
        self.assertTrue(req_sup.with_user(self.md_user).can_md_approve)

    def test_approval_dashboard_and_menu_own_stage_queues(self):
        self.dual_hr_user.sudo().write({"active": True})
        req_draft = self._create_draft_request(self.basic_user)
        req_dept = self._create_request(self.basic_user)

        req_sup = self._create_request(self.basic_user)
        req_sup.with_user(self.dept_manager_user).action_manager_approve()

        req_mgr = self._create_request(self.basic_user)
        req_mgr.with_user(self.dept_manager_user).action_manager_approve()
        req_mgr.with_user(self.hr_supervisor_user).action_hr_supervisor_approve()

        req_md = self._create_request(self.basic_user)
        req_md.with_user(self.hr_manager_user).action_hr_manager_approve()
        self.assertEqual(req_md.state, "md_approval")

        req_cancel = self._create_request(self.basic_user)
        req_cancel.with_user(self.hr_manager_user).action_hr_manager_approve()
        req_cancel.with_user(self.md_user).action_md_approve()
        req_cancel.with_user(self.basic_user).action_employee_cancel_request()

        all_test_ids = (req_draft | req_dept | req_sup | req_mgr | req_md | req_cancel).ids

        def _visible_ids_for(user):
            domain = self.LeaveRequest.with_user(user)._get_pending_approval_domain(user)
            return set(
                self.LeaveRequest.with_user(user).search(
                    [("id", "in", all_test_ids)] + list(domain)
                ).ids
            )

        # Draft is never shown in anyone's approval queue
        # Dept. Manager sees ONLY their team's employee_manager_approval
        self.assertEqual(_visible_ids_for(self.dept_manager_user), {req_dept.id})

        # HR Supervisor sees ONLY hr_supervisor_approval
        self.assertEqual(_visible_ids_for(self.hr_supervisor_user), {req_sup.id})

        # HR Manager sees ONLY hr_manager_approval + cancel_request (own stages)
        self.assertEqual(_visible_ids_for(self.hr_manager_user), {req_mgr.id, req_cancel.id})

        # Dual HR Supervisor + HR Manager sees the union of hr_supervisor_approval + hr_manager_approval + cancel_request
        self.assertEqual(
            _visible_ids_for(self.dual_hr_user),
            {req_sup.id, req_mgr.id, req_cancel.id},
        )

        # MD sees ONLY md_approval (cancellations stay with the HR Manager)
        self.assertEqual(_visible_ids_for(self.md_user), {req_md.id})

        # Basic user sees nothing
        self.assertEqual(_visible_ids_for(self.basic_user), set())

        # If approval dashboard service is installed, verify it returns the same counts
        if "de.hr.approval.dashboard.service" in self.env:
            service = self.env["de.hr.approval.dashboard.service"]
            for user, expected in (
                (self.dept_manager_user, {req_dept.id}),
                (self.hr_supervisor_user, {req_sup.id}),
                (self.hr_manager_user, {req_mgr.id, req_cancel.id}),
                (self.dual_hr_user, {req_sup.id, req_mgr.id, req_cancel.id}),
                (self.md_user, {req_md.id}),
            ):
                dash_domain = service.with_user(user)._leave_request_pending_domain()
                found = set(
                    self.LeaveRequest.with_user(user).search(
                        [("id", "in", all_test_ids)] + list(dash_domain)
                    ).ids
                )
                self.assertEqual(found, expected)

        # Verify approvals menu search_fetch filters consistently (filter lives in de_hr_workspace_timeoff)
        timeoff_portal = self.env["ir.module.module"].sudo().search(
            [("name", "=", "de_hr_workspace_timeoff"), ("state", "=", "installed")]
        )
        if not timeoff_portal:
            self.skipTest("de_hr_workspace_timeoff is not installed: approver queue search_fetch filter not available")
        approvals_ctx = {"approvals_of_leave_request": True}
        for user, expected in (
            (self.dept_manager_user, {req_dept.id}),
            (self.hr_supervisor_user, {req_sup.id}),
            (self.hr_manager_user, {req_mgr.id, req_cancel.id}),
            (self.dual_hr_user, {req_sup.id, req_mgr.id, req_cancel.id}),
            (self.md_user, {req_md.id}),
        ):
            fetched =self.LeaveRequest.with_user(user).with_context(**approvals_ctx).search_fetch(
                [("id", "in", all_test_ids)], ["name"]
            )
            self.assertEqual(set(fetched.ids), expected)
