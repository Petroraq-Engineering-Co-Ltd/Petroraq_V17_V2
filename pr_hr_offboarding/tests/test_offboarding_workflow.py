from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase


class TestOffboardingWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        users = cls.env["res.users"].with_context(no_reset_password=True)
        base_user_group = cls.env.ref("base.group_user")
        supervisor_group = cls.env.ref(
            "pr_hr_recruitment_request.group_onboarding_supervisor"
        )

        cls.supervisor_user = users.create(
            {
                "name": "Offboarding HR Supervisor",
                "login": "offboarding.hr.supervisor",
                "email": "offboarding.hr.supervisor@example.com",
                "groups_id": [(6, 0, [base_user_group.id, supervisor_group.id])],
            }
        )
        cls.manager_user = users.create(
            {
                "name": "Offboarding Department Manager",
                "login": "offboarding.department.manager",
                "email": "offboarding.department.manager@example.com",
                "groups_id": [(6, 0, [base_user_group.id])],
            }
        )
        cls.other_user = users.create(
            {
                "name": "Other Employee",
                "login": "offboarding.other.user",
                "email": "offboarding.other.user@example.com",
                "groups_id": [(6, 0, [base_user_group.id])],
            }
        )

        cls.department = cls.env["hr.department"].create(
            {"name": "Offboarding Test Department"}
        )
        cls.manager_employee = cls.env["hr.employee"].create(
            {
                "name": "Department Manager",
                "user_id": cls.manager_user.id,
                "department_id": cls.department.id,
                "company_id": cls.env.company.id,
            }
        )
        cls.department.manager_id = cls.manager_employee
        cls.employee = cls.env["hr.employee"].create(
            {
                "name": "Departing Employee",
                "department_id": cls.department.id,
                "company_id": cls.env.company.id,
            }
        )

    def _create_request(self):
        return self.env["pr.hr.offboarding.request"].with_user(
            self.supervisor_user
        ).create(
            {
                "request_type": "resignation",
                "employee_id": self.employee.id,
                "request_date": "2026-07-02",
                "last_working_date": "2026-07-31",
                "request_reason": "Employee submitted a resignation letter.",
            }
        )

    def test_submit_and_accept(self):
        request = self._create_request()
        request.action_submit()

        self.assertEqual(request.state, "submitted")
        self.assertEqual(
            request.department_manager_user_id, self.manager_user
        )

        request.with_user(self.manager_user).action_accept()
        self.assertEqual(request.state, "accepted")
        self.assertEqual(request.approved_by_id, self.manager_user)
        self.assertTrue(request.approved_date)

    def test_rejection_requires_reason_and_can_reset(self):
        request = self._create_request()
        request.action_submit()

        with self.assertRaises(UserError):
            request.with_user(self.manager_user)._action_reject(" ")

        request.with_user(self.manager_user)._action_reject(
            "The proposed last working date must be reviewed."
        )
        self.assertEqual(request.state, "rejected")
        self.assertEqual(request.rejected_by_id, self.manager_user)
        self.assertTrue(request.rejection_reason)

        request.with_user(self.supervisor_user).action_reset_to_draft()
        self.assertEqual(request.state, "draft")
        self.assertFalse(request.rejection_reason)
        self.assertFalse(request.rejected_by_id)

    def test_only_assigned_manager_can_decide(self):
        request = self._create_request()
        request.action_submit()

        with self.assertRaises((AccessError, UserError)):
            request.with_user(self.other_user).action_accept()

    def test_regular_user_cannot_create_request(self):
        with self.assertRaises(AccessError):
            self.env["pr.hr.offboarding.request"].with_user(
                self.other_user
            ).create(
                {
                    "request_type": "termination",
                    "employee_id": self.employee.id,
                    "last_working_date": "2026-07-31",
                    "request_reason": "Test",
                }
            )

    def test_status_cannot_be_changed_directly(self):
        request = self._create_request()

        with self.assertRaises(AccessError):
            request.write({"state": "accepted"})

    def test_submit_requires_manager_user(self):
        department = self.env["hr.department"].create(
            {"name": "Department Without Manager User"}
        )
        manager = self.env["hr.employee"].create(
            {
                "name": "Manager Without User",
                "department_id": department.id,
                "company_id": self.env.company.id,
            }
        )
        department.manager_id = manager
        employee = self.env["hr.employee"].create(
            {
                "name": "Employee Without Manager User",
                "department_id": department.id,
                "company_id": self.env.company.id,
            }
        )
        request = self.env["pr.hr.offboarding.request"].with_user(
            self.supervisor_user
        ).create(
            {
                "request_type": "termination",
                "employee_id": employee.id,
                "last_working_date": "2026-07-31",
                "request_reason": "Position eliminated.",
            }
        )

        with self.assertRaises(UserError):
            request.action_submit()
