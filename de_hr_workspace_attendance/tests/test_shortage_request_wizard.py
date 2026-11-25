from datetime import date, datetime, timedelta

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestShortageRequestWizard(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # pr_base requires a unique VAT on companies and ID on employees
        cls.company = cls.env["res.company"].create({
            "name": "Shortage Wizard Test Company", "vat": "PRSHORTAGEWIZARD01"})
        cls.calendar = cls.env["resource.calendar"].create({
            "name": "08:00 - 17:00",
            "tz": "Asia/Riyadh",
            "company_id": cls.company.id,
            "attendance_ids": [Command.clear()] + [Command.create({
                "name": str(day), "dayofweek": str(day), "day_period": "morning",
                "hour_from": 8, "hour_to": 17,
            }) for day in range(7)],
        })
        cls.employee_user, cls.manager_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create([{
            "name": login,
            "login": login,
            "password": login,
            "email": f"{login}@example.com",
            "tz": "Asia/Riyadh",
            "company_id": cls.company.id,
            "company_ids": [Command.set(cls.company.ids)],
            "groups_id": [Command.set((
                cls.env.ref("base.group_user")
                | cls.env.ref("de_hr_workspace.group_hr_employee_workspace")
            ).ids)],
        } for login in ("sw.employee", "sw.manager")])
        cls.manager = cls._create_employee("SW Manager", cls.manager_user)
        cls.employee = cls._create_employee("SW Employee", cls.employee_user, cls.manager)

    @classmethod
    def _create_employee(cls, name, user, manager=None):
        return cls.env["hr.employee"].create({
            "name": name,
            "identification_id": name,
            "user_id": user.id,
            "parent_id": manager.id if manager else False,
            "company_id": cls.company.id,
            "resource_calendar_id": cls.calendar.id,
            "tz": "Asia/Riyadh",
            "compute_attendance": True,
        })

    def _punch(self, check_in, check_out, employee=None):
        """Biometric punch, in UTC (Riyadh is UTC+3)."""
        attendance = self.env["hr.attendance"].sudo().with_context(
            attendance_policy_source="biometric", allow_late_attendance=True, sync_from_device=True,
        ).create({
            "employee_id": (employee or self.employee).id,
            "check_in": check_in,
            "check_out": check_out,
        })
        return attendance.with_user(self.employee_user).with_context({})

    def _short_punch(self, day=1):
        return self._punch(datetime(2026, 6, day, 5, 0), datetime(2026, 6, day, 12, 0))

    def _wizard(self, attendance, user=None, **vals):
        return self.env["pr.hr.shortage.request.wizard"].with_user(user or self.employee_user).create({
            "attendance_id": attendance.id,
            "employee_reason": "Doctor appointment",
            **vals,
        })

    def _attachment(self, user, **vals):
        return self.env["ir.attachment"].with_user(user).create({
            "name": "proof.txt", "raw": b"proof", "res_model": "pr.hr.shortage.request.wizard",
            "res_id": 0, **vals,
        })

    def _requests(self):
        return self.env["pr.hr.shortage.request"].search([("employee_id", "=", self.employee.id)])

    def test_button_opens_editable_popup(self):
        attendance = self._short_punch()
        self.assertTrue(attendance.can_request_shortage)
        action = attendance.action_open_shortage_request()
        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(action["res_model"], "pr.hr.shortage.request.wizard")
        self.assertEqual(action["target"], "new")
        # overrides the create/edit restrictions of the My Attendance action
        self.assertTrue(action["context"]["edit"])
        self.assertTrue(action["context"]["create"])
        wizard = self._wizard(attendance)
        self.assertEqual(wizard.date, date(2026, 6, 1))
        self.assertEqual(wizard.check_out, datetime(2026, 6, 1, 12, 0))
        self.assertEqual(wizard.shortage_time, "2 hours")
        self.assertEqual(wizard.scheduled_check_in, datetime(2026, 6, 1, 5, 0))
        self.assertEqual(wizard.scheduled_check_out, datetime(2026, 6, 1, 14, 0))
        self.assertFalse(wizard.payroll_finalized)

    def test_popup_default_values(self):
        """What the web client requests before the wizard is saved."""
        attendance = self._short_punch()
        Wizard = self.env["pr.hr.shortage.request.wizard"].with_user(self.employee_user).with_context(
            **attendance.action_open_shortage_request()["context"])
        names = ["attendance_id", "date", "check_in", "check_out", "shortage_time",
                 "scheduled_check_in", "scheduled_check_out", "payroll_finalized",
                 "employee_reason"]
        values = Wizard.onchange({}, [], {name: {} for name in names})["value"]
        self.assertEqual(values["attendance_id"], attendance.id)
        self.assertEqual(str(values["date"]), "2026-06-01")
        self.assertEqual(str(values["scheduled_check_out"]), "2026-06-01 14:00:00")

    def test_submit(self):
        attendance = self._short_punch()
        attachment = self._attachment(self.employee_user)
        result = self._wizard(attendance, attachment_ids=[Command.set(attachment.ids)]).action_submit()
        request = self._requests()
        self.assertEqual(len(request), 1)
        self.assertIn(request.name, result["params"]["message"])
        self.assertEqual(result["params"]["next"]["type"], "ir.actions.act_window_close")
        self.assertEqual(request.state, "employee_manager_approval")
        self.assertEqual(request.submitted_by_id, self.employee_user)
        self.assertEqual(request.request_type, "shortage")
        self.assertTrue(request.apply_scheduled_shift)
        self.assertEqual(request.company_id, self.company)
        self.assertEqual(request.date, date(2026, 6, 1))
        self.assertEqual(request.check_in, attendance.check_in)
        self.assertEqual(request.check_out, datetime(2026, 6, 1, 12, 0))
        self.assertEqual(request.shortage_time, "2 hours")
        self.assertEqual(request.employee_reason, "Doctor appointment")
        self.assertEqual((attachment.res_model, attachment.res_id), (request._name, request.id))
        # the approver can open the file
        attachment.with_user(self.manager_user).check("read")
        # nothing changes on the attendance until the final approval
        self.assertEqual(attendance.check_out, datetime(2026, 6, 1, 12, 0))

    def test_web_client_flow(self):
        """Same calls as the web client, from the button to the submission."""
        attendance = self._short_punch()
        self.authenticate("sw.employee", "sw.employee")

        def call(model, method, *args, **kwargs):
            return self.make_jsonrpc_request("/web/dataset/call_kw", {
                "model": model, "method": method, "args": args, "kwargs": kwargs,
            })

        form = self.env.ref("de_hr_workspace_attendance.hr_attendance_workspace_form_view")
        arch = call("hr.attendance", "get_views", views=[(form.id, "form")])["views"]["form"]["arch"]
        self.assertIn("can_request_shortage", arch)
        action = call("hr.attendance", "action_open_shortage_request", [attendance.id])
        context = {"create": False, "edit": False, **action["context"]}
        views = call(action["res_model"], "get_views", views=action["views"], context=context)
        arch = views["views"]["form"]["arch"]
        self.assertIn("many2many_binary", arch)
        self.assertIn("action_submit", arch)
        wizard = call(
            action["res_model"], "web_save", [],
            {"attendance_id": attendance.id, "employee_reason": "Web"},
            specification={"date": {}}, context=context,
        )[0]
        self.assertEqual(wizard["date"], "2026-06-01")
        result = call(action["res_model"], "action_submit", [wizard["id"]], context=context)
        self.assertEqual(result["tag"], "display_notification")
        self.assertEqual(self._requests().state, "employee_manager_approval")

    def test_submit_uses_local_date(self):
        # 00:30 in Riyadh is still the previous day in UTC
        attendance = self._punch(datetime(2026, 6, 2, 21, 30), datetime(2026, 6, 3, 2, 0))
        self._wizard(attendance).action_submit()
        self.assertEqual(self._requests().date, date(2026, 6, 3))

    def test_blank_reason(self):
        wizard = self._wizard(self._short_punch(), employee_reason="   ")
        with self.assertRaises(UserError):
            wizard.action_submit()
        self.assertFalse(self._requests())

    def test_second_pending_request(self):
        attendance = self._short_punch()
        self._wizard(attendance).action_submit()
        wizard = self._wizard(attendance)
        # assertRaises rolls back, as the web client request would
        with self.assertRaises(ValidationError):
            wizard.action_submit()
        self.assertEqual(len(self._requests()), 1)

    def test_old_date_is_allowed(self):
        day = date.today() - timedelta(days=90)
        attendance = self._punch(
            datetime(day.year, day.month, day.day, 5, 0), datetime(day.year, day.month, day.day, 12, 0))
        self.assertFalse(attendance.show_shortage_button)
        self.assertTrue(attendance.can_request_shortage)

    def test_no_request_without_shortage_or_check_out(self):
        for attendance in (
            self._punch(datetime(2026, 6, 4, 5, 0), datetime(2026, 6, 4, 14, 0)),
            self._punch(datetime(2026, 6, 5, 5, 0), False),
        ):
            self.assertFalse(attendance.can_request_shortage)
            with self.assertRaises(UserError):
                attendance.action_open_shortage_request()
            with self.assertRaises(UserError):
                self._wizard(attendance).action_submit()

    def test_only_own_attendance(self):
        attendance = self._short_punch().with_user(self.manager_user)
        self.assertFalse(attendance.can_request_shortage)
        with self.assertRaises(UserError):
            attendance.action_open_shortage_request()
        with self.assertRaises(UserError):
            self._wizard(attendance, user=self.manager_user).action_submit()
        self.assertFalse(self._requests())

    def test_foreign_attachment(self):
        foreign = self._attachment(self.manager_user)
        with self.assertRaises(AccessError):
            self._wizard(
                self._short_punch(), attachment_ids=[Command.set(foreign.ids)],
            ).action_submit()
        self.assertFalse(foreign.res_id)
