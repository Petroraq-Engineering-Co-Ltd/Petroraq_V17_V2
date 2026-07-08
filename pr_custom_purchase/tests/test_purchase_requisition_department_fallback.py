from odoo.tests.common import TransactionCase


class TestPurchaseRequisitionDepartmentFallback(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.request_user = cls.env["res.users"].create({
            "name": "PR Request User Without Employee",
            "login": "pr.request.user.no.employee@example.test",
            "email": "pr.request.user.no.employee@example.test",
        })
        cls.manager_user = cls.env["res.users"].create({
            "name": "PR Department Manager User",
            "login": "pr.department.manager@example.test",
            "email": "pr.department.manager@example.test",
        })
        cls.manager_employee = cls.env["hr.employee"].create({
            "name": "PR Department Manager Employee",
            "user_id": cls.manager_user.id,
        })
        cls.department = cls.env["hr.department"].create({
            "name": "PR Fallback Department",
            "manager_id": cls.manager_employee.id,
        })
        cls.employee_without_user = cls.env["hr.employee"].create({
            "name": "PR Employee Without User",
            "department_id": cls.department.id,
        })
        cls.plan = cls.env["account.analytic.plan"].create({
            "name": "PR Fallback Test Plan",
        })
        cls.cost_center = cls.env["account.analytic.account"].create({
            "name": "PR Fallback Cost Center",
            "plan_id": cls.plan.id,
        })
        cls.product = cls.env["product.product"].create({
            "name": "PR Fallback Product",
            "standard_price": 10.0,
        })
        cls.budget = cls.env["crossovered.budget"].create({
            "name": "PR Department Fallback Budget",
            "date_from": "2026-07-01",
            "date_to": "2026-07-31",
            "state": "validate",
            "user_id": cls.env.user.id,
            "expense_type": "opex",
            "scope": "department",
            "department_id": cls.department.id,
        })
        cls.env["crossovered.budget.lines"].create({
            "crossovered_budget_id": cls.budget.id,
            "analytic_account_id": cls.cost_center.id,
            "date_from": cls.budget.date_from,
            "date_to": cls.budget.date_to,
            "planned_amount": 1000.0,
        })

    def _line_commands(self):
        return [(0, 0, {
            "description": self.product.id,
            "cost_center_id": self.cost_center.id,
            "quantity": 1.0,
            "unit_price": 10.0,
        })]

    def test_employee_name_without_user_sets_department_and_manager(self):
        requisition = self.env["purchase.requisition"].create({
            "requested_user_id": self.request_user.id,
            "requested_by": self.employee_without_user.name,
            "date_request": "2026-07-07",
            "expense_type": "opex",
            "expense_bucket_id": self.budget.id,
            "line_ids": self._line_commands(),
        })

        self.assertEqual(requisition.department, self.department.name)
        self.assertEqual(requisition.supervisor, self.manager_user.name)
        self.assertEqual(
            requisition.supervisor_partner_id,
            str(self.manager_user.partner_id.id),
        )

    def test_budget_department_is_used_when_no_employee_matches(self):
        requisition = self.env["purchase.requisition"].create({
            "requested_user_id": self.request_user.id,
            "requested_by": "No Matching Employee Name",
            "date_request": "2026-07-07",
            "expense_type": "opex",
            "expense_bucket_id": self.budget.id,
            "line_ids": self._line_commands(),
        })

        self.assertEqual(requisition.department, self.department.name)
        self.assertEqual(requisition.supervisor, self.manager_user.name)
