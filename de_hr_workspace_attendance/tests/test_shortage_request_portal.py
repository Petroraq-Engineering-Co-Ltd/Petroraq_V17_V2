from datetime import datetime

from odoo import Command, http
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestShortageRequestPortal(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # pr_base requires a unique VAT on companies and ID on employees
        cls.company = cls.env["res.company"].create({
            "name": "Shortage Portal Test Company", "vat": "PRSHORTAGEPORTAL01"})
        internal = cls.env.ref("base.group_user")
        workspace = cls.env.ref("de_hr_workspace.group_hr_employee_workspace")

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

        def _make_employee(name, user, manager=None):
            return cls.env["hr.employee"].create({
                "name": name,
                "identification_id": name,
                "user_id": user.id,
                "parent_id": manager.id if manager else False,
                "company_id": cls.company.id,
            })

        cls.manager_user = _make_user("sp.manager", internal | workspace)
        cls.other_manager = _make_user("sp.other.manager", internal | workspace)
        cls.employee_user = _make_user("sp.employee", internal | workspace)
        cls.portal_user = _make_user("sp.portal", cls.env.ref("base.group_portal"))
        cls.manager_emp = _make_employee("SP Manager", cls.manager_user)
        cls.other_manager_emp = _make_employee("SP Other Manager", cls.other_manager)
        cls.employee = _make_employee("SP Employee", cls.employee_user, cls.manager_emp)
        cls.portal_emp = _make_employee("SP Portal Employee", cls.portal_user, cls.other_manager_emp)

    def _create_request(self, employee, submit_user=None, day=1):
        request = self.env["pr.hr.shortage.request"].create({
            "employee_id": employee.id,
            "company_id": self.company.id,
            "date": "2026-06-%02d" % day,
            "check_in": datetime(2026, 6, day, 5, 0),
            "check_out": datetime(2026, 6, day, 14, 0),
            "employee_reason": "Forgot to punch",
        })
        if submit_user:
            request.sudo().with_user(submit_user).sudo().action_submit()
            self.assertEqual(request.state, "employee_manager_approval")
        return request

    def _post(self, url, **data):
        return self.url_open(url, data={"csrf_token": http.Request.csrf_token(self), **data})

    def test_get_does_not_decide(self):
        request = self._create_request(self.employee, self.employee_user)
        self.authenticate("sp.manager", "sp.manager")
        for route in ("approved", "rejected", "reset_rejection"):
            response = self.url_open(f"/my/shortage_requests_{route}/{request.id}")
            self.assertIn(response.status_code, (404, 405))
        request.invalidate_recordset()
        self.assertEqual(request.state, "employee_manager_approval")

    def test_manager_pages_and_approval(self):
        for user, employee, submitter in (
            (self.manager_user, self.employee, self.employee_user),
            (self.other_manager, self.portal_emp, self.portal_user),
        ):
            with self.subTest(user=user.login):
                request = self._create_request(employee, submitter)
                self.authenticate(user.login, user.login)
                response = self.url_open("/my/shortage_requests_approval")
                self.assertEqual(response.status_code, 200)
                self.assertIn(f"/my/shortage_requests_approval/{request.id}", response.text)
                response = self.url_open(f"/my/shortage_requests_approval/{request.id}")
                self.assertEqual(response.status_code, 200)
                self.assertIn(f"/my/shortage_requests_approved/{request.id}", response.text)
                self._post(f"/my/shortage_requests_approved/{request.id}")
                request.invalidate_recordset()
                self.assertEqual(request.manager_approved_user_id, user)
                self.assertNotEqual(request.state, "employee_manager_approval")

    def test_reject_needs_reason_then_reset(self):
        request = self._create_request(self.employee, self.employee_user)
        self.authenticate("sp.manager", "sp.manager")
        url = f"/my/shortage_requests_rejected/{request.id}"
        self._post(url, reject_reason="   ")
        request.invalidate_recordset()
        self.assertEqual(request.state, "employee_manager_approval")
        self._post(url, reject_reason="Wrong time")
        request.invalidate_recordset()
        self.assertEqual(request.state, "rejected")
        self.assertEqual(request.rejected_stage, "manager")
        self.assertEqual(request.rejected_by_user_id, self.manager_user)
        response = self.url_open(f"/my/shortage_requests_approval/{request.id}")
        self.assertIn(f"/my/shortage_requests_reset_rejection/{request.id}", response.text)
        self._post(f"/my/shortage_requests_reset_rejection/{request.id}")
        request.invalidate_recordset()
        self.assertEqual(request.state, "employee_manager_approval")

    def test_other_users_cannot_decide(self):
        request = self._create_request(self.employee, self.employee_user)
        self.authenticate("sp.other.manager", "sp.other.manager")
        response = self.url_open(f"/my/shortage_requests_approval/{request.id}")
        self.assertNotIn(f"/my/shortage_requests_approved/{request.id}", response.text)
        self._post(f"/my/shortage_requests_approved/{request.id}")
        request.invalidate_recordset()
        self.assertEqual(request.state, "employee_manager_approval")

    def test_employee_list(self):
        own = self._create_request(self.portal_emp, day=2)
        other = self._create_request(self.employee, day=3)
        self.authenticate("sp.portal", "sp.portal")
        response = self.url_open("/my/shortage_requests")
        self.assertEqual(response.status_code, 200)
        self.assertIn(own.name, response.text)
        self.assertNotIn(other.name, response.text)
        self.assertEqual(self.url_open("/my/home").status_code, 200)
        visible = self.env["pr.hr.shortage.request"].with_user(self.portal_user).search([
            ("id", "in", (own | other).ids)])
        self.assertEqual(visible, own)

    def test_backend_views_per_role(self):
        request = self._create_request(self.employee, self.employee_user)
        action = self.env.ref("de_hr_workspace_attendance.action_my_shortage_request_approvals")
        internal = self.env.ref("base.group_user")
        for login, group, button in (
            ("sp.sup", "pr_hr.group_hr_supervisor", "action_hr_supervisor_approve"),
            ("sp.mgr", "pr_hr.group_hr_manager", "action_hr_manager_approve"),
            ("sp.md", "pr_hr.group_hr_md", "action_md_approve"),
            ("sp.manager", None, "action_manager_approve"),
        ):
            with self.subTest(login=login):
                if group:
                    self.env["res.users"].with_context(no_reset_password=True).create({
                        "name": login, "login": login, "password": login,
                        "email": f"{login}@example.com",
                        "company_id": self.company.id,
                        "company_ids": [Command.set(self.company.ids)],
                        "groups_id": [Command.set((internal | self.env.ref(group)).ids)],
                    })
                self.authenticate(login, login)
                views = self.make_jsonrpc_request("/web/dataset/call_kw", {
                    "model": request._name, "method": "get_views", "args": [], "kwargs": {
                        "views": [(v.view_id.id, v.view_mode) for v in action.view_ids] + [(False, "search")],
                        "context": {"from_approval_dashboard": True},
                    },
                })
                self.assertIn(button, views["views"]["form"]["arch"])
                names = [
                    name for name in views["models"][request._name]
                    if name.startswith("can_") or name in ("state", "payroll_finalized")
                ]
                values = self.make_jsonrpc_request("/web/dataset/call_kw", {
                    "model": request._name, "method": "web_read", "args": [[request.id]],
                    "kwargs": {
                        "specification": {
                            **{name: {} for name in names},
                            "employee_id": {"fields": {"display_name": {}}},
                        },
                        "context": {"from_approval_dashboard": True},
                    },
                })[0]
                # only the stage's own approver decides from the dashboard
                self.assertEqual(values["can_reject"], login == "sp.manager")

    def test_web_form_submits(self):
        self.authenticate("sp.employee", "sp.employee")
        vals = {
            "date": "2026-06-10", "checkin": "2026-06-10T08:00", "checkout": "2026-06-10T17:00",
            "message": "Forgot",
        }
        self._post("/shortage_request/create", **vals)
        request = self.env["pr.hr.shortage.request"].search([("employee_id", "=", self.employee.id)])
        self.assertEqual(len(request), 1)
        self.assertEqual(request.state, "employee_manager_approval")
        self.assertEqual(request.submitted_by_id, self.employee_user)
        # a duplicate shows its error instead of creating a second request
        response = self._post("/shortage_request/create", **vals)
        self.assertEqual(response.status_code, 200)
        self.assertIn("already exists", response.text)
        self.assertEqual(self.env["pr.hr.shortage.request"].search_count(
            [("employee_id", "=", self.employee.id)]), 1)
