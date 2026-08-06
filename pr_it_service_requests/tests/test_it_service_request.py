from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase


class TestItServiceRequest(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        internal_group = cls.env.ref("base.group_user")
        manager_group = cls.env.ref("pr_it_service_requests.group_it_service_manager")
        cls.requester = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "IT Requester", "login": "it.requester.test", "email": "requester@example.com",
            "groups_id": [(6, 0, [internal_group.id])],
        })
        cls.approver_one = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "IT Approver One", "login": "it.approver.one.test", "email": "approver1@example.com",
            "groups_id": [(6, 0, [internal_group.id])],
        })
        cls.approver_two = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "IT Approver Two", "login": "it.approver.two.test", "email": "approver2@example.com",
            "groups_id": [(6, 0, [internal_group.id])],
        })
        cls.approver_three = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "IT Approver Three", "login": "it.approver.three.test", "email": "approver3@example.com",
            "groups_id": [(6, 0, [internal_group.id])],
        })
        cls.manager = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "IT Manager", "login": "it.manager.test", "email": "manager@example.com",
            "groups_id": [(6, 0, [internal_group.id, manager_group.id])],
        })
        cls.employee = cls.env["hr.employee"].create({"name": "IT Requester", "user_id": cls.requester.id})
        cls.request_type = cls.env["pr.it.request.type"].create({"name": "Test Access", "code": "TEST_ACCESS"})

    def _request(self):
        return self.env["pr.it.service.request"].with_user(self.requester).create({
            "title": "Grant repository access", "request_type_id": self.request_type.id,
            "employee_id": self.employee.id, "description": "Access is required for project work.",
            "approver_line_ids": [
                (0, 0, {"sequence": 10, "approver_id": self.approver_one.id}),
                (0, 0, {"sequence": 20, "approver_id": self.approver_two.id}),
            ],
        })

    def test_sequential_approval(self):
        request = self._request()
        request.with_user(self.requester).action_submit()
        self.assertEqual(request.current_approver_id, self.approver_one)
        with self.assertRaises(AccessError):
            request.with_user(self.approver_two).action_approve()
        request.with_user(self.approver_one).action_approve()
        self.assertEqual(request.current_approver_id, self.approver_two)
        request.with_user(self.approver_two).action_approve()
        self.assertEqual(request.state, "approved")

    def test_requester_cannot_self_approve(self):
        with self.assertRaises(ValidationError):
            self.env["pr.it.service.request"].with_user(self.requester).create({
                "title": "Self approval", "request_type_id": self.request_type.id,
                "employee_id": self.employee.id, "description": "Invalid chain",
                "approver_line_ids": [(0, 0, {"sequence": 10, "approver_id": self.requester.id})],
            })

    def test_parallel_approval_group_completes_before_next_sequence(self):
        request = self.env["pr.it.service.request"].with_user(self.requester).create({
            "title": "Deploy shared application",
            "request_type_id": self.request_type.id,
            "employee_id": self.employee.id,
            "description": "Requires three department approvals before management.",
            "approver_line_ids": [
                (0, 0, {"sequence": 10, "approver_id": self.approver_one.id}),
                (0, 0, {"sequence": 10, "approver_id": self.approver_two.id}),
                (0, 0, {"sequence": 10, "approver_id": self.approver_three.id}),
                (0, 0, {"sequence": 20, "approver_id": self.manager.id}),
            ],
        })
        request.with_user(self.requester).action_submit()
        self.assertEqual(
            set(request.current_approver_ids.ids),
            {self.approver_one.id, self.approver_two.id, self.approver_three.id},
        )
        with self.assertRaises(AccessError):
            request.with_user(self.manager).action_approve()

        request.with_user(self.approver_two).action_approve()
        self.assertEqual(
            set(request.current_approver_ids.ids),
            {self.approver_one.id, self.approver_three.id},
        )
        request.with_user(self.approver_one).action_approve()
        self.assertEqual(request.current_approver_ids, self.approver_three)
        request.with_user(self.approver_three).action_approve()
        self.assertEqual(request.current_approver_ids, self.manager)
        request.with_user(self.manager).action_approve()
        self.assertEqual(request.state, "approved")

    def test_parallel_unsaved_lines_do_not_compare_new_ids(self):
        request = self.env["pr.it.service.request"].new({
            "title": "Parallel draft",
            "request_type_id": self.request_type.id,
            "employee_id": self.employee.id,
            "description": "Draft with equal sequence values.",
            "approver_line_ids": [
                (0, 0, {"sequence": 10, "approver_id": self.approver_one.id}),
                (0, 0, {"sequence": 10, "approver_id": self.approver_two.id}),
            ],
        })
        request._compute_approval_summary()
        self.assertFalse(request.current_approver_ids)
        self.assertEqual(request.approval_progress, "0 of 2 approved")

    def test_manager_can_reset_rejection(self):
        request = self._request()
        request.with_user(self.requester).action_submit()
        request.with_user(self.approver_one)._action_reject("Insufficient justification")
        self.assertEqual(request.state, "rejected")
        request.with_user(self.manager).action_reset_to_draft()
        self.assertEqual(request.state, "draft")
        self.assertFalse(request.rejection_reason)
