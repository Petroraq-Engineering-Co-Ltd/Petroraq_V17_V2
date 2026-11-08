from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
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

    def test_request_creator_can_reset_rejection(self):
        request = self._request()
        request.with_user(self.requester).action_submit()
        request.with_user(self.approver_one).action_approve()
        approved_line = request.approver_line_ids.filtered(
            lambda line: line.approver_id == self.approver_one
        )
        original_approval_date = approved_line.action_date
        request.with_user(self.approver_two)._action_reject("Insufficient justification")
        self.assertEqual(request.state, "rejected")
        with self.assertRaises(AccessError):
            request.with_user(self.manager).action_reset_to_draft()
        request.with_user(self.requester).action_reset_to_draft()
        self.assertEqual(request.state, "draft")
        self.assertFalse(request.rejection_reason)
        self.assertEqual(approved_line.status, "approved")
        self.assertEqual(approved_line.action_date, original_approval_date)

        request.with_user(self.requester).action_submit()
        self.assertEqual(request.current_approver_ids, self.approver_two)
        self.assertEqual(approved_line.status, "approved")
        request.with_user(self.approver_two).action_approve()
        self.assertEqual(request.state, "approved")

    def test_reset_retains_approved_members_of_parallel_group(self):
        request = self.env["pr.it.service.request"].with_user(self.requester).create({
            "title": "Resume grouped deployment approval",
            "request_type_id": self.request_type.id,
            "employee_id": self.employee.id,
            "description": "Approved group members must not approve twice.",
            "approver_line_ids": [
                (0, 0, {"sequence": 10, "approver_id": self.approver_one.id}),
                (0, 0, {"sequence": 10, "approver_id": self.approver_two.id}),
                (0, 0, {"sequence": 10, "approver_id": self.approver_three.id}),
                (0, 0, {"sequence": 20, "approver_id": self.manager.id}),
            ],
        })
        request.with_user(self.requester).action_submit()
        request.with_user(self.approver_one).action_approve()
        request.with_user(self.approver_two)._action_reject("Deployment evidence missing")

        request.with_user(self.requester).action_reset_to_draft()
        request.with_user(self.requester).action_submit()
        self.assertEqual(
            set(request.current_approver_ids.ids),
            {self.approver_two.id, self.approver_three.id},
        )
        self.assertEqual(
            request.approver_line_ids.filtered(
                lambda line: line.approver_id == self.approver_one
            ).status,
            "approved",
        )

        request.with_user(self.approver_two).action_approve()
        request.with_user(self.approver_three).action_approve()
        self.assertEqual(request.current_approver_ids, self.manager)
        request.with_user(self.manager).action_approve()
        self.assertEqual(request.state, "approved")

    def test_rejection_via_wizard(self):
        """Test rejection flow through the dedicated wizard model."""
        request = self._request()
        request.with_user(self.requester).action_submit()

        # Approver opens wizard
        action = request.with_user(self.approver_one).action_open_reject_wizard()
        self.assertEqual(action.get("res_model"), "pr.it.service.request.reject.wizard")

        # Test empty reason validation
        wizard = self.env["pr.it.service.request.reject.wizard"].with_user(self.approver_one).create({
            "request_id": request.id,
            "reason": "   ",
        })
        with self.assertRaises(ValidationError):
            wizard.action_reject()

        # Reject with valid reason
        wizard.write({"reason": "Invalid business justification."})
        wizard.action_reject()
        self.assertEqual(request.state, "rejected")
        self.assertEqual(request.rejection_reason, "Invalid business justification.")
        self.assertEqual(request.rejected_by_id, self.approver_one)

    def test_cancellation_workflow(self):
        """Verify cancellation by requester and manager, and rejection of unauthorized cancellations."""
        request = self._request()

        # Unauthorized user cannot cancel
        with self.assertRaises(AccessError):
            request.with_user(self.approver_one).action_cancel()

        # Requester can cancel in draft
        request.with_user(self.requester).action_cancel()
        self.assertEqual(request.state, "cancelled")

        # Reset and submit, then manager can cancel
        request.with_user(self.requester).action_reset_to_draft()
        request.with_user(self.requester).action_submit()
        self.assertEqual(request.state, "pending")

        request.with_user(self.manager).action_cancel()
        self.assertEqual(request.state, "cancelled")

        # Approved request cannot be cancelled
        request.with_user(self.requester).action_reset_to_draft()
        request.with_user(self.requester).action_submit()
        request.with_user(self.approver_one).action_approve()
        request.with_user(self.approver_two).action_approve()
        self.assertEqual(request.state, "approved")
        with self.assertRaises(AccessError):
            request.with_user(self.requester).action_cancel()

    def test_security_impersonation_prevention(self):
        """Verify non-managers cannot create requests on behalf of other users."""
        with self.assertRaises(AccessError):
            self.env["pr.it.service.request"].with_user(self.requester).create({
                "title": "Unauthorized impersonation",
                "request_type_id": self.request_type.id,
                "requested_by_id": self.approver_one.id,
                "employee_id": self.employee.id,
                "description": "Attempt to create as someone else",
            })

        # IT Manager can create on behalf of other users
        manager_req = self.env["pr.it.service.request"].with_user(self.manager).create({
            "title": "Manager proxy request",
            "request_type_id": self.request_type.id,
            "requested_by_id": self.requester.id,
            "employee_id": self.employee.id,
            "description": "Authorized proxy submission",
        })
        self.assertEqual(manager_req.requested_by_id, self.requester)

    def test_draft_immutability_and_direct_write(self):
        """Verify locked fields and direct state modifications are forbidden outside draft."""
        request = self._request()
        request.with_user(self.requester).action_submit()

        # Direct state change without workflow context raises AccessError
        with self.assertRaises(AccessError):
            request.with_user(self.requester).write({"state": "approved"})

        # Modifying core request fields on pending request raises UserError
        with self.assertRaises(UserError):
            request.with_user(self.requester).write({"title": "Changed Title"})

        # Deleting non-draft request raises UserError
        with self.assertRaises(UserError):
            request.with_user(self.requester).unlink()

    def test_date_and_approval_chain_constraints(self):
        """Verify date validity and approval chain constraint rules."""
        # Required date cannot be earlier than request date
        with self.assertRaises(ValidationError):
            self.env["pr.it.service.request"].with_user(self.requester).create({
                "title": "Invalid dates",
                "request_type_id": self.request_type.id,
                "employee_id": self.employee.id,
                "description": "Past required date",
                "request_date": fields.Date.today(),
                "required_date": fields.Date.today() - timedelta(days=2),
            })

        # Duplicate approvers forbidden
        with self.assertRaises(ValidationError):
            self.env["pr.it.service.request"].with_user(self.requester).create({
                "title": "Duplicate approver",
                "request_type_id": self.request_type.id,
                "employee_id": self.employee.id,
                "description": "Same user twice",
                "approver_line_ids": [
                    (0, 0, {"sequence": 10, "approver_id": self.approver_one.id}),
                    (0, 0, {"sequence": 20, "approver_id": self.approver_one.id}),
                ],
            })

    def test_search_is_current_approver(self):
        """Verify the custom search method on computed is_current_approver."""
        request = self._request()
        request.with_user(self.requester).action_submit()

        # Approver one is current
        waiting_reqs = self.env["pr.it.service.request"].with_user(self.approver_one).search([
            ("is_current_approver", "=", True)
        ])
        self.assertIn(request, waiting_reqs)

        # Approver two is not current yet
        not_waiting = self.env["pr.it.service.request"].with_user(self.approver_two).search([
            ("is_current_approver", "=", True)
        ])
        self.assertNotIn(request, not_waiting)

    def test_resubmit_when_all_approvers_already_approved(self):
        """Verify immediate approval on resubmit when all approvers previously approved."""
        request = self._request()
        request.with_user(self.requester).action_submit()
        request.with_user(self.approver_one).action_approve()
        request.with_user(self.approver_two).action_approve()
        self.assertEqual(request.state, "approved")

        # Manually reset lines to simulate re-submission scenario
        request.approver_line_ids.with_context(it_request_workflow_write=True).write({"status": "approved"})
        request.with_context(it_request_workflow_write=True).write({"state": "draft"})
        request.with_user(self.requester).action_submit()
        self.assertEqual(request.state, "approved")
        self.assertTrue(request.approved_at)
