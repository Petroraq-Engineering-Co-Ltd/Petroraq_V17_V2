from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestLeaveRequestCancellation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Create department manager user
        cls.manager_user = cls.env["res.users"].create({
            "name": "Dept Manager User",
            "login": "dept_manager_cancellation_test",
            "email": "dept_manager_cancellation_test@example.com",
            "groups_id": [(6, 0, [cls.env.ref("base.group_user").id])],
        })
        cls.manager_employee = cls.env["hr.employee"].create({
            "name": "Dept Manager Employee",
            "user_id": cls.manager_user.id,
        })

        # Create employee user
        cls.employee_user = cls.env["res.users"].create({
            "name": "Leave Test Employee User",
            "login": "leave_employee_cancellation_test",
            "email": "leave_employee_cancellation_test@example.com",
            "groups_id": [(6, 0, [cls.env.ref("base.group_user").id])],
        })
        cls.employee = cls.env["hr.employee"].create({
            "name": "Leave Test Employee",
            "user_id": cls.employee_user.id,
            "parent_id": cls.manager_employee.id,
            "work_email": "leave_employee_cancellation_test@example.com",
        })

        # Create HR Manager user
        cls.hr_manager_user = cls.env["res.users"].create({
            "name": "HR Manager Test User",
            "login": "hr_manager_cancellation_test",
            "email": "hr_manager_cancellation_test@example.com",
            "groups_id": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("pr_hr.group_hr_manager").id,
            ])],
        })

        # Create leave type
        cls.annual_leave_type = cls.env["hr.leave.type"].create({
            "name": "Annual Leave Cancellation Test",
            "time_type": "leave",
            "request_unit": "day",
            "requires_allocation": "no",
            "leave_type": "annual_leave",
        })

    def _create_approved_request(self, date_from, date_to):
        request = self.env["pr.hr.leave.request"].sudo().create({
            "name": "Test Leave Request",
            "employee_id": self.employee.id,
            "company_id": self.env.company.id,
            "leave_type_id": self.annual_leave_type.id,
            "date_from": date_from,
            "date_to": date_to,
        })
        request.write({
            "state": "hr_approve",
            "approval_state": "hr_approve",
        })
        leave = self.env["hr.leave"].sudo().create({
            "name": f"Test Leave {date_from}",
            "employee_id": self.employee.id,
            "holiday_status_id": self.annual_leave_type.id,
            "request_date_from": date_from,
            "request_date_to": date_to,
            "leave_request_id": request.id,
        })
        leave.sudo().state = "validate"
        request.leave_id = leave.id
        return request

    def test_request_cancellation_does_not_raise_allocation_error(self):
        today = fields.Date.context_today(self.env.user)
        start = today + timedelta(days=10)
        end = today + timedelta(days=39)  # 30 days
        request = self._create_approved_request(start, end)
        self.assertEqual(request.requested_days, 30.0)
        self.assertTrue(request.leave_id)
        self.assertEqual(request.state, "hr_approve")

        # When employee clicks "REQUEST CANCELLATION"
        request.with_user(self.employee_user).action_employee_cancel_request()

        self.assertEqual(request.state, "cancel_request")
        self.assertEqual(request.approval_state, "cancel_request")

    def test_hr_manager_approve_cancellation_refuses_leave(self):
        today = fields.Date.context_today(self.env.user)
        start = today + timedelta(days=10)
        end = today + timedelta(days=15)
        request = self._create_approved_request(start, end)

        # Move to cancel_request
        request.with_user(self.employee_user).action_employee_cancel_request()

        # HR manager approves cancellation
        request.with_user(self.hr_manager_user).action_hr_manager_cancel_approve()

        self.assertEqual(request.state, "cancelled")
        self.assertEqual(request.approval_state, "cancelled")
        self.assertEqual(request.leave_id.state, "refuse")

    def test_advance_allocation_override_cancellation(self):
        today = fields.Date.context_today(self.env.user)
        start = today + timedelta(days=10)
        end = today + timedelta(days=15)
        request = self._create_approved_request(start, end)
        request.allocation_override_applied = True

        # Regular employee without override group requests cancellation
        request.with_user(self.employee_user).action_employee_cancel_request()
        self.assertEqual(request.state, "cancel_request")
