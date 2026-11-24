from datetime import date, datetime, time, timedelta
from itertools import count

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestShortageRequestApproval(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Request = cls.env["pr.hr.shortage.request"]
        cls.Attendance = cls.env["hr.attendance"]
        # Own company: the approvers of the database must not interfere.
        cls.company = cls.env["res.company"].create({
            "name": "Shortage Approval Test Company",
            # pr_base requires a unique VAT on company partners
            "vat": "PRSHORTAGETEST01",
        })
        cls.env.user.write({"company_ids": [Command.link(cls.company.id)]})
        cls.employee_seq = iter(range(1, 100))
        cls.request_days = count()

        cls.sup_group = cls.env.ref("pr_hr.group_hr_supervisor")
        cls.mgr_group = cls.env.ref("pr_hr.group_hr_manager")
        cls.md_group = cls.env.ref("pr_hr.group_hr_md")
        cls.workspace = cls.env.ref("de_hr_workspace.group_hr_employee_workspace")

        cls.basic_user = cls._create_user("basic", cls.workspace)
        cls.dept_manager = cls._create_user("manager", cls.workspace)
        cls.hr_supervisor = cls._create_user("hr.supervisor", cls.sup_group)
        cls.hr_manager = cls._create_user("hr.manager", cls.mgr_group)
        cls.md_user = cls._create_user("md", cls.md_group)
        cls.old_supervisor = cls._create_user(
            "old.supervisor", cls.env.ref("pr_hr_attendance.custom_group_hr_attendance_supervisor"))
        cls.old_manager = cls._create_user(
            "old.manager", cls.env.ref("hr_attendance.group_hr_attendance_manager"))
        cls.manager_employee = cls._create_employee("Dept Manager", user=cls.dept_manager)
        cls.employee = cls._create_employee(
            "Employee", user=cls.basic_user, manager=cls.manager_employee)

    @classmethod
    def _create_user(cls, login, groups):
        return cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": login,
            "login": "shortage.approval.%s" % login,
            "email": "shortage.approval.%s@example.com" % login,
            "company_id": cls.company.id,
            "company_ids": [Command.set(cls.company.ids)],
            "groups_id": [Command.set((cls.env.ref("base.group_user") | groups).ids)],
        })

    @classmethod
    def _create_employee(cls, name, user=None, manager=None):
        return cls.env["hr.employee"].create({
            "name": "Shortage %s" % name,
            "identification_id": "PRSHORT%04d" % next(cls.employee_seq),
            "company_id": cls.company.id,
            "user_id": user.id if user else False,
            "parent_id": manager.id if manager else False,
        })

    def _managed_by(self, groups, login="special.manager"):
        """An employee whose manager holds `groups`, and that manager's user."""
        user = self._create_user(login, groups | self.workspace)
        manager = self._create_employee(login, user=user)
        return self._create_employee("of %s" % login, manager=manager), user

    def _create_request(self, employee=None, **vals):
        day = datetime.combine(date(2026, 6, 1) + timedelta(days=next(self.request_days)), time.min)
        return self.Request.create({
            "employee_id": (employee or self.employee).id,
            "company_id": self.company.id,
            "date": day.date(),
            "check_in": day + timedelta(hours=5),
            "check_out": day + timedelta(hours=14),
            **vals,
        })

    def _submit(self, request, user=None):
        request.with_user(user or self.basic_user).action_submit()
        return request

    def _submitted(self, employee=None, **vals):
        request = self._create_request(employee, **vals)
        # submitted by the employee, or by a user without any approval role
        return self._submit(request) if not employee else self._submit_as_creator(request)

    def _submit_as_creator(self, request):
        creator = self._create_user("creator.%s" % request.id, self.workspace)
        request.sudo().employee_id.user_id = creator
        return self._submit(request, creator)

    def _punches(self, request):
        return self.Attendance.search([
            ("employee_id", "=", request.employee_id.id),
            ("check_in", ">=", datetime.combine(request.date, datetime.min.time()) - timedelta(hours=3)),
            ("check_in", "<", datetime.combine(request.date, datetime.min.time()) + timedelta(hours=21)),
        ])

    # ------------------------------------------------------------ standard flow

    def test_draft_is_editable_until_submitted(self):
        request = self.Request.with_user(self.basic_user).create({
            "employee_id": self.employee.id,
            "date": "2026-07-01",
            "check_in": datetime(2026, 7, 1, 5, 0),
            "check_out": datetime(2026, 7, 1, 14, 0),
            "employee_reason": "Forgot",
        })
        self.assertEqual(request.state, "draft")
        self.assertTrue(request.can_submit)
        self.assertEqual(request.company_id, self.company)
        request.employee_reason = "Forgot to punch"
        request.action_submit()
        self.assertEqual(request.state, "employee_manager_approval")
        self.assertEqual(request.submitted_by_id, self.basic_user)
        with self.assertRaises(ValidationError):
            request.employee_reason = "Other"
        with self.assertRaises(UserError):
            request.action_submit()
        with self.assertRaises(ValidationError):
            request.unlink()

    def test_draft_can_be_deleted_by_its_employee_only(self):
        request = self._create_request()
        with self.assertRaises(AccessError):
            request.with_user(self.dept_manager).unlink()
        request.with_user(self.basic_user).unlink()
        self.assertFalse(request.exists())

    def test_four_stages_and_attendance_only_at_md(self):
        request = self._submitted()
        self.assertEqual(request.hr_supervisor_ids, self.hr_supervisor)
        self.assertEqual(request.hr_manager_ids, self.hr_manager)

        request.with_user(self.dept_manager).action_manager_approve()
        self.assertEqual(request.state, "hr_supervisor_approval")
        request.with_user(self.hr_supervisor).action_hr_supervisor_approve()
        self.assertEqual(request.state, "hr_manager_approval")
        request.with_user(self.hr_manager).action_hr_manager_approve()
        self.assertEqual(request.state, "md_approval")
        self.assertFalse(self._punches(request), "Attendance must only change at MD approval")

        request.with_user(self.md_user).action_md_approve()
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.approval_state, "approved")
        punch = self._punches(request)
        self.assertEqual(punch.check_in, request.check_in)
        self.assertEqual(punch.check_out, request.check_out)
        self.assertEqual(punch.attendance_entry_source, "approved_shortage")
        self.assertEqual(request.manager_approved_user_id, self.dept_manager)
        self.assertEqual(request.hr_supervisor_approved_user_id, self.hr_supervisor)
        self.assertEqual(request.hr_manager_approved_user_id, self.hr_manager)
        self.assertEqual(request.md_approved_user_id, self.md_user)

    def test_no_punch_request(self):
        request = self._submitted(request_type="no_punch")
        self.assertFalse(self._punches(request))
        request.with_user(self.md_user).action_md_approve()
        self.assertEqual(len(self._punches(request)), 1)

    def test_old_attendance_groups_cannot_decide(self):
        request = self._submitted()
        for user in (self.old_supervisor, self.old_manager):
            for action in (
                "action_manager_approve", "action_hr_supervisor_approve", "action_hr_manager_approve",
                "action_md_approve", "action_reject",
            ):
                with self.subTest(user=user.login, action=action), self.assertRaises(UserError):
                    getattr(request.with_user(user), action)()
        self.assertEqual(request.state, "employee_manager_approval")

    def test_stage_order_is_enforced(self):
        request = self._create_request()
        for user, action in (
            (self.dept_manager, "action_manager_approve"),
            (self.hr_supervisor, "action_hr_supervisor_approve"),
            (self.hr_manager, "action_hr_manager_approve"),
            (self.md_user, "action_md_approve"),
        ):
            with self.subTest(action=action), self.assertRaises(UserError):
                getattr(request.with_user(user), action)()
        self._submit(request)
        with self.assertRaises(UserError):
            request.with_user(self.hr_supervisor).action_manager_approve()
        request.sudo().state = "md_approval"
        with self.assertRaises(UserError):
            request.with_user(self.hr_manager).action_hr_manager_approve()

    # ------------------------------------------------------------------ routing

    def test_manager_who_is_hr_supervisor_covers_both_stages(self):
        employee, manager = self._managed_by(self.sup_group)
        request = self._submitted(employee)
        self.assertEqual(request.state, "hr_supervisor_approval")
        self.assertEqual(request.manager_approved_user_id, manager)
        request.with_user(manager).action_hr_supervisor_approve()
        self.assertEqual(request.state, "hr_manager_approval")

    def test_manager_with_hr_manager_and_md_waits_for_hr_supervisor(self):
        employee, manager = self._managed_by(self.mgr_group | self.md_group)
        self.hr_manager.groups_id -= self.mgr_group
        request = self._submitted(employee)
        self.assertEqual(request.state, "hr_supervisor_approval")
        self.assertEqual(request.manager_approved_user_id, manager)
        request.with_user(self.hr_supervisor).action_hr_supervisor_approve()
        self.assertEqual(request.state, "md_approval", "Every HR Manager is also MD")
        request.with_user(manager).action_md_approve()
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.hr_manager_approved_user_id, manager)

    def test_manager_with_every_role_approves_in_one_click(self):
        employee, manager = self._managed_by(self.sup_group | self.mgr_group | self.md_group)
        request = self._submitted(employee)
        self.assertEqual(request.state, "md_approval")
        request.with_user(manager).action_md_approve()
        self.assertEqual(request.state, "approved")

    def test_hr_manager_who_is_md_approves_both_stages(self):
        both = self._create_user("hr.manager.md", self.mgr_group | self.md_group)
        request = self._submitted()
        request.sudo().state = "hr_manager_approval"
        request.with_user(both).action_hr_manager_approve()
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.hr_manager_approved_user_id, both)
        self.assertEqual(request.md_approved_user_id, both)
        self.assertEqual(len(self._punches(request)), 1)

    def test_employee_without_manager_starts_at_hr_supervisor(self):
        request = self._submitted(self._create_employee("No Manager"))
        self.assertEqual(request.state, "hr_supervisor_approval")

    def test_own_request_of_a_user_holding_every_role(self):
        user = self._create_user("all.roles", self.sup_group | self.mgr_group | self.md_group)
        request = self._create_request(self._create_employee("All Roles", user=user))
        request.with_user(user).action_submit()
        self.assertEqual(request.state, "approved")

    def test_md_approves_own_request(self):
        request = self._create_request(
            self._create_employee("MD", user=self.md_user, manager=self.manager_employee))
        request.with_user(self.md_user).action_submit()
        self.assertEqual(request.state, "employee_manager_approval")
        request.with_user(self.md_user).action_md_approve()
        self.assertEqual(request.state, "approved")

    def test_hr_supervisor_submitter_covers_its_stage_after_the_manager(self):
        request = self._create_request()
        request.with_user(self.hr_supervisor).action_submit()
        self.assertEqual(request.state, "employee_manager_approval")
        request.with_user(self.dept_manager).action_manager_approve()
        self.assertEqual(request.state, "hr_manager_approval")
        self.assertEqual(request.hr_supervisor_approved_user_id, self.hr_supervisor)

    def test_other_company_approvers_are_ignored(self):
        other_company = self.env["res.company"].create({
            "name": "Shortage Other Company", "vat": "PRSHORTAGETEST02"})
        other = self._create_user("other.company", self.sup_group)
        other.write({"company_ids": [Command.set(other_company.ids)], "company_id": other_company.id})
        request = self._submitted()
        self.assertNotIn(other, request.hr_supervisor_ids)
        self.assertFalse(self.Request.with_user(other).search([("id", "=", request.id)]))

    # --------------------------------------------------- skip-level / dashboard

    def test_backend_skip_level(self):
        request = self._submitted()
        request.with_user(self.hr_manager).action_hr_manager_approve()
        self.assertEqual(request.state, "md_approval")
        self.assertFalse(request.manager_approved_user_id)

        request = self._submitted()
        self.assertTrue(request.with_user(self.md_user).can_md_approve)
        request.with_user(self.md_user).action_md_approve()
        self.assertEqual(request.state, "approved")

    def test_dashboard_requires_intermediate_roles(self):
        request = self._submitted()
        for user, action in (
            (self.hr_supervisor, "action_hr_supervisor_approve"),
            (self.hr_manager, "action_hr_manager_approve"),
            (self.md_user, "action_md_approve"),
            (self.md_user, "action_reject"),
        ):
            as_user = request.with_user(user).with_context(from_approval_dashboard=True)
            with self.subTest(action=action):
                self.assertFalse(as_user.can_reject)
                with self.assertRaises(UserError):
                    getattr(as_user, action)()
        self.assertEqual(request.state, "employee_manager_approval")

    def test_single_button_per_approver(self):
        request = self._submitted()
        both = self._create_user("mgr.md", self.mgr_group | self.md_group)
        as_both = request.with_user(both)
        self.assertTrue(as_both.can_md_approve)
        self.assertFalse(as_both.can_hr_manager_approve)
        as_manager = request.with_user(self.dept_manager)
        self.assertTrue(as_manager.can_manager_approve)
        self.assertTrue(as_manager.can_reject)
        self.assertFalse(request.with_user(self.basic_user).can_reject)

    def test_dashboard_queue(self):
        service = self.env.get("de.hr.approval.dashboard.service")
        if service is None:
            self.skipTest("Approval Dashboard is not installed")

        def queue(user):
            domain = service.with_user(user)._shortage_pending_domain()
            found = self.Request.with_user(user).search([("id", "=", request.id)] + domain)
            return bool(found)

        request = self._submitted()
        users = {
            "employee_manager_approval": self.dept_manager,
            "hr_supervisor_approval": self.hr_supervisor,
            "hr_manager_approval": self.hr_manager,
            "md_approval": self.md_user,
        }
        for state in users:
            request.sudo().state = state
            for user_state, user in users.items():
                self.assertEqual(queue(user), state == user_state, (state, user.login))
            self.assertFalse(queue(self.old_manager))

    def test_approval_queue_keeps_the_search_filters(self):
        if not self.env.ref(
            "de_hr_workspace_attendance.action_my_shortage_request_approvals", raise_if_not_found=False
        ):
            self.skipTest("Approval action is not installed")
        first, second = self._submitted(), self._submitted()
        queue = self.Request.with_user(self.dept_manager).with_context(approvals_of_shortage_request=True)
        self.assertEqual(queue.search([("id", "=", first.id)]), first)
        self.assertLessEqual(first | second, queue.search([]))

    def test_approver_added_later(self):
        request = self._submitted()
        newcomer = self._create_user("newcomer", self.env["res.groups"])
        self.sup_group.write({"users": [Command.link(newcomer.id)]})
        self.assertIn(newcomer, request.hr_supervisor_ids)
        request.with_user(newcomer).action_hr_supervisor_approve()
        self.assertEqual(request.state, "hr_manager_approval")

    # ---------------------------------------------------------------- rejection

    def _reject(self, request, user, reason):
        action = request.with_user(user).action_reject()
        wizard = self.env["pr.reject.record.wizard"].with_user(user).with_context(action["context"]).create({
            "record_id": "%s,%s" % (request._name, request.id),
            "reject_reason": reason,
        })
        return wizard.action_reject()

    def test_reject_needs_a_reason_and_records_the_stage(self):
        request = self._submitted()
        with self.assertRaises(UserError):
            self._reject(request, self.dept_manager, "  ")
        self._reject(request, self.dept_manager, "Wrong time")
        self.assertEqual(request.state, "rejected")
        self.assertEqual(request.approval_state, "rejected")
        self.assertEqual(request.rejected_stage, "manager")
        self.assertEqual(request.rejected_by_user_id, self.dept_manager)
        self.assertEqual(request.reject_reason, "Wrong time")

    def test_wizard_cannot_bypass_the_rights(self):
        request = self._submitted()
        for context in ({}, {"pr_shortage_rejection_stage": "md"}, {"pr_shortage_rejection_stage": "manager"}):
            wizard = self.env["pr.reject.record.wizard"].with_user(self.basic_user).with_context(**context).create({
                "record_id": "%s,%s" % (request._name, request.id),
                "reject_reason": "Bypass",
            })
            with self.subTest(context=context), self.assertRaises(UserError):
                wizard.action_reject()
        self.assertEqual(request.state, "employee_manager_approval")

    def test_reset_rejection_reopens_the_stage(self):
        request = self._submitted()
        request.with_user(self.dept_manager).action_manager_approve()
        request.with_user(self.hr_supervisor).action_hr_supervisor_approve()
        self._reject(request, self.hr_manager, "Check again")
        self.assertFalse(request.with_user(self.dept_manager).can_reset_rejection)
        with self.assertRaises(UserError):
            request.with_user(self.dept_manager).action_reset_rejection()
        request.with_user(self.hr_manager).action_reset_rejection()
        self.assertEqual(request.state, "hr_manager_approval")
        self.assertEqual(request.hr_supervisor_approved_user_id, self.hr_supervisor)
        self.assertFalse(request.reject_reason)

    def test_md_rejection_and_reset(self):
        request = self._submitted()
        request.with_user(self.hr_manager).action_hr_manager_approve()
        self._reject(request, self.md_user, "No")
        self.assertEqual(request.rejected_stage, "md")
        request.with_user(self.md_user).action_reset_rejection()
        self.assertEqual(request.state, "md_approval")

    def test_reset_to_draft_and_resubmit(self):
        request = self._submitted()
        request.with_user(self.hr_manager).action_hr_manager_approve()
        self._reject(request, self.md_user, "Fix the time")
        request.with_user(self.basic_user).action_reset_to_draft()
        self.assertEqual(request.state, "draft")
        self.assertFalse(request.hr_manager_approved_user_id)
        self.assertFalse(request.rejected_stage)
        request.with_user(self.basic_user).check_out = request.check_out + timedelta(minutes=5)
        self._submit(request)
        self.assertEqual(request.state, "employee_manager_approval")

    def test_old_rejection_without_stage_can_only_go_to_draft(self):
        request = self._submitted()
        request.sudo().write({"state": "rejected", "approval_state": "rejected"})
        for user in (self.dept_manager, self.hr_supervisor, self.hr_manager, self.md_user):
            self.assertFalse(request.with_user(user).can_reset_rejection)
        self.assertTrue(request.with_user(self.hr_manager).can_reset_to_draft)

    # ---------------------------------------------------------- submit / create

    def test_second_pending_request_is_blocked(self):
        first = self._submitted()
        vals = {"date": first.date, "check_in": first.check_in, "check_out": first.check_out}
        second = self._create_request(**vals)
        with self.assertRaises(ValidationError):
            self._submit(second)
        self._reject(first, self.dept_manager, "Duplicate")
        self._submit(second)
        self.assertEqual(second.state, "employee_manager_approval")
        # the rejected one cannot come back next to a pending request
        with self.assertRaises(ValidationError):
            first.with_user(self.dept_manager).action_reset_rejection()
        second.with_user(self.md_user).action_md_approve()
        third = self._submit(self._create_request(**vals))
        self.assertEqual(third.state, "employee_manager_approval")

    def test_submit_surfaces_attendance_errors(self):
        request = self._create_request(
            check_in=datetime(2030, 6, 15, 14, 0), check_out=datetime(2030, 6, 15, 5, 0), date="2030-06-15")
        with self.assertRaises(ValidationError):
            self._submit(request)
        self.assertEqual(request.state, "draft")
        self.assertFalse(self._punches(request))

    def test_create_only_for_oneself(self):
        vals = {
            "employee_id": self.manager_employee.id,
            "date": "2026-07-02",
            "check_in": datetime(2026, 7, 2, 5, 0),
            "check_out": datetime(2026, 7, 2, 14, 0),
        }
        for user in (self.basic_user, self._create_user("no.employee", self.workspace)):
            with self.subTest(user=user.login), self.assertRaises(AccessError):
                self.Request.with_user(user).create(dict(vals))
        for user in (self.hr_supervisor, self.hr_manager, self.old_manager, self.old_supervisor):
            with self.subTest(user=user.login):
                request = self.Request.with_user(user).create(dict(vals))
                self.assertEqual(request.state, "draft")

    def test_attendance_staff_submit_own_entries_only(self):
        request = self.Request.with_user(self.old_supervisor).create({
            "employee_id": self.employee.id,
            "date": "2026-07-03",
            "check_in": datetime(2026, 7, 3, 5, 0),
            "check_out": datetime(2026, 7, 3, 14, 0),
        })
        request.action_submit()
        self.assertEqual(request.state, "employee_manager_approval")
        other = self._create_request()
        with self.assertRaises(AccessError):
            other.with_user(self.old_supervisor).employee_reason = "Changed"
        with self.assertRaises(AccessError):
            other.with_user(self.old_supervisor).action_submit()

    def test_workflow_fields_are_protected_for_everyone(self):
        request = self._submitted()
        for user in (self.basic_user, self.dept_manager, self.hr_supervisor, self.hr_manager, self.md_user):
            for vals in (
                {"state": "approved"},
                {"approval_state": "approved"},
                {"md_approved_user_id": user.id},
                {"employee_manager_id": self.employee.id},
                {"hr_manager_ids": [Command.link(user.id)]},
            ):
                with self.subTest(user=user.login, vals=vals), self.assertRaises(AccessError):
                    request.with_user(user).write(vals)
        with self.assertRaises(AccessError):
            self.Request.with_user(self.basic_user).create({
                "employee_id": self.employee.id, "date": "2026-07-04", "state": "approved"})

    def test_web_client_create_and_submit(self):
        for user, employee in ((self.basic_user, None), (self.hr_supervisor, self.employee)):
            # Form() cannot be used: pr_acess_managment.get_views needs a request
            day = 6 if employee else 7
            Request = self.Request.with_user(user)
            vals = Request.default_get(list(Request._fields))
            vals.update({
                "date": "2030-07-0%s" % day,
                "check_in": datetime(2030, 7, day, 5, 0),
                "check_out": datetime(2030, 7, day, 14, 0),
                "employee_reason": "Forgot",
            })
            if employee:
                vals.update(employee_id=employee.id, company_id=self.company.id)
            request = Request.browse(Request.web_save(vals, {"id": {}})[0]["id"])
            self.assertEqual(request.employee_id, self.employee)
            request.action_submit()
            self.assertEqual(request.state, "employee_manager_approval")

    def test_payroll_warning(self):
        request = self._submitted()
        self.assertFalse(request.payroll_finalized)
        policy = self.env["hr.attendance.policy"].create({
            "name": "Shortage Test Policy",
            **{
                "%s_rule_id" % rule: self.env["hr.%s.rule" % rule].create({"name": "Shortage Test"}).id
                for rule in ("late", "early", "absence", "diff")
            },
        })
        self.env.cr.execute(
            "INSERT INTO attendance_sheet (employee_id, company_id, att_policy_id, date_from, date_to, state)"
            " VALUES (%s, %s, %s, '2026-06-01', '2028-12-31', 'done')",
            (self.employee.id, self.company.id, policy.id),
        )
        request.invalidate_recordset()
        self.assertTrue(request.payroll_finalized)
        # a warning only
        request.with_user(self.md_user).action_md_approve()
        self.assertEqual(request.state, "approved")
        self.assertFalse(request.payroll_finalized)

    # --------------------------------------------------------------- visibility

    def test_visibility(self):
        request = self._submitted()
        other = self._submitted(self._create_employee("Other"))

        def visible(user):
            return self.Request.with_user(user).search([("id", "in", (request | other).ids)])

        for user in (self.hr_supervisor, self.hr_manager, self.md_user, self.old_supervisor, self.old_manager):
            self.assertEqual(visible(user), request | other, user.login)
        for user in (self.basic_user, self.dept_manager):
            self.assertEqual(visible(user), request, user.login)
