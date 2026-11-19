from datetime import timedelta

from odoo import Command, fields, http
from odoo.exceptions import UserError
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestLeaveRequestPortal(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({"name": "Timeoff Portal Test Company"})
        internal = cls.env.ref("base.group_user")
        workspace = cls.env.ref("de_hr_workspace.group_hr_employee_workspace")
        approvals = cls.env.ref("de_hr_workspace.group_hr_employee_approvals")

        def _make_user(login, groups):
            return cls.env["res.users"].with_context(no_reset_password=True).create({
                "name": login,
                "login": login,
                "password": login,
                "email": f"{login}@example.com",
                "company_id": cls.company.id,
                "company_ids": [Command.set(cls.company.ids)],
                "groups_id": [Command.set(groups.ids)],
            })

        cls.manager_user = _make_user("tp.manager", internal | workspace | approvals)
        cls.employee_user = _make_user("tp.employee", internal | workspace)
        cls.portal_user = _make_user("tp.portal", cls.env.ref("base.group_portal"))

        Employee = cls.env["hr.employee"]
        cls.manager_emp = Employee.create({
            "name": "TP Manager",
            "user_id": cls.manager_user.id,
            "company_id": cls.company.id,
        })
        cls.employee = Employee.create({
            "name": "TP Employee",
            "user_id": cls.employee_user.id,
            "parent_id": cls.manager_emp.id,
            "company_id": cls.company.id,
        })
        cls.portal_emp = Employee.create({
            "name": "TP Portal Employee",
            "user_id": cls.portal_user.id,
            "company_id": cls.company.id,
        })
        cls.leave_type = cls.env["hr.leave.type"].create({
            "name": "Timeoff Portal Test Leave",
            "time_type": "leave",
            "request_unit": "day",
            "requires_allocation": "no",
            "leave_type": "annual_leave",
        })
        cls._date_offset = 20

    def _create_request(self, employee, submit_user=None):
        start = fields.Date.context_today(self.env.user) + timedelta(days=self._date_offset)
        while start.weekday() >= 4:
            start += timedelta(days=1)
        self.__class__._date_offset += 7
        leave_request = self.env["pr.hr.leave.request"].create({
            "employee_id": employee.id,
            "company_id": self.company.id,
            "leave_type_id": self.leave_type.id,
            "date_from": start,
            "date_to": start + timedelta(days=2),
        })
        if submit_user:
            leave_request.with_user(submit_user).action_submit()
            self.assertEqual(leave_request.state, "employee_manager_approval")
        return leave_request

    def test_get_on_approve_route_does_not_approve(self):
        leave_request = self._create_request(self.employee, submit_user=self.employee_user)
        self.authenticate("tp.manager", "tp.manager")
        response = self.url_open(f"/my/leave_requests_approved/{leave_request.id}")
        # POST-only route: werkzeug answers 405 (404 if a website handler rewrites it).
        self.assertIn(response.status_code, (404, 405))
        leave_request.invalidate_recordset()
        self.assertEqual(leave_request.state, "employee_manager_approval")
        self.assertFalse(leave_request.manager_approved_user_id)

    def test_post_approve_route_approves(self):
        leave_request = self._create_request(self.employee, submit_user=self.employee_user)
        self.authenticate("tp.manager", "tp.manager")
        self.url_open(
            f"/my/leave_requests_approved/{leave_request.id}",
            data={"csrf_token": http.Request.csrf_token(self)},
        )
        leave_request.invalidate_recordset()
        self.assertEqual(leave_request.manager_approved_user_id, self.manager_user)
        self.assertNotEqual(leave_request.state, "employee_manager_approval")

    def test_portal_reject_requires_reason(self):
        leave_request = self._create_request(self.employee, submit_user=self.employee_user)
        self.authenticate("tp.manager", "tp.manager")
        url = f"/my/leave_requests_rejected/{leave_request.id}"
        self.url_open(url, data={"csrf_token": http.Request.csrf_token(self), "reject_reason": "   "})
        leave_request.invalidate_recordset()
        self.assertEqual(leave_request.state, "employee_manager_approval")

        self.url_open(url, data={"csrf_token": http.Request.csrf_token(self), "reject_reason": "Busy period"})
        leave_request.invalidate_recordset()
        self.assertEqual(leave_request.state, "rejected")
        self.assertEqual(leave_request.rejected_stage, "manager")
        self.assertEqual(leave_request.reject_reason, "Busy period")
        self.assertEqual(leave_request.rejected_by_user_id, self.manager_user)

    def test_approval_queue_uses_parent_manager(self):
        leave_request = self._create_request(self.employee, submit_user=self.employee_user)
        # Clear the stored manager: the model still treats employee_id.parent_id as Dept. Manager.
        leave_request.employee_manager_id = False
        self.authenticate("tp.manager", "tp.manager")
        response = self.url_open("/my/leave_requests_approval")
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"/my/leave_requests_approval/{leave_request.id}", response.text)

    def test_portal_user_reads_only_own_requests(self):
        own_request = self._create_request(self.portal_emp)
        other_request = self._create_request(self.employee)
        visible = self.env["pr.hr.leave.request"].with_user(self.portal_user).search([
            ("id", "in", (own_request | other_request).ids),
        ])
        self.assertEqual(visible, own_request)

    def test_hr_officer_can_submit_public_holiday(self):
        officer = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "TP Holiday Officer",
            "login": "tp.holiday.officer",
            "company_id": self.company.id,
            "company_ids": [Command.set(self.company.ids)],
            "groups_id": [Command.set((
                self.env.ref("base.group_user") | self.env.ref("hr_holidays.group_hr_holidays_manager")
            ).ids)],
        })
        self.assertFalse(officer.has_group("hr.group_hr_manager"))
        holiday = self.env["hr.public.holiday"].with_user(officer).create({
            "name": "TP National Day",
            "date_from": fields.Date.today() + timedelta(days=60),
            "date_to": fields.Date.today() + timedelta(days=60),
        })
        holiday.action_submit_for_approval()
        self.assertEqual(holiday.approval_state, "to_approve")
        with self.assertRaises(UserError):
            holiday.action_hr_manager_approve()
        with self.assertRaises(UserError):
            holiday.write({"approval_state": "approved"})

        pr_hr_manager = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "TP PR HR Manager",
            "login": "tp.pr.hr.manager",
            "company_id": self.company.id,
            "company_ids": [Command.set(self.company.ids)],
            "groups_id": [Command.set((
                self.env.ref("base.group_user") | self.env.ref("pr_hr.group_hr_manager")
            ).ids)],
        })
        holiday.with_user(pr_hr_manager).action_hr_manager_approve()
        self.assertEqual(holiday.approval_state, "approved")
        self.assertEqual(holiday.approved_by_id, pr_hr_manager)
