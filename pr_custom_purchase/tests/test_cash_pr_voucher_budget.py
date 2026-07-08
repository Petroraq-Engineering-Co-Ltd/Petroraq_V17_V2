from types import SimpleNamespace

from odoo.tests.common import TransactionCase


class TestCashPrVoucherBudget(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plan = cls.env["account.analytic.plan"].create({
            "name": "Cash PR Voucher Budget Test",
        })
        cls.budget_cost_center = cls.env["account.analytic.account"].create({
            "name": "Budget Cost Center",
            "plan_id": cls.plan.id,
        })
        cls.project_cost_center = cls.env["account.analytic.account"].create({
            "name": "Project Cost Center",
            "plan_id": cls.plan.id,
        })
        cls.employee_cost_center = cls.env["account.analytic.account"].create({
            "name": "Employee Cost Center",
            "plan_id": cls.plan.id,
        })
        cls.product = cls.env["product.product"].create({
            "name": "Cash PR Voucher Budget Product",
            "standard_price": 90.0,
        })
        cls.requisition = cls.env["purchase.requisition"].create({
            "name": "CASH-PR-BUDGET-DIMENSION-TEST",
            "pr_type": "cash",
            "line_ids": [(0, 0, {
                "description": cls.product.id,
                "cost_center_id": cls.budget_cost_center.id,
                "quantity": 1.0,
                "unit_price": 90.0,
            })],
        })

    def test_only_originating_cost_center_is_checked(self):
        voucher_line = SimpleNamespace(
            _fields={"budget_cost_center_id": True},
            budget_cost_center_id=self.budget_cost_center,
            description="Test voucher line",
            amount=90.0,
            analytic_distribution={
                str(self.budget_cost_center.id): 100.0,
                str(self.project_cost_center.id): 100.0,
                str(self.employee_cost_center.id): 100.0,
            },
        )

        amounts = self.requisition._get_voucher_budget_amounts([voucher_line])

        self.assertEqual(set(amounts), {self.budget_cost_center.id})
        self.assertEqual(amounts[self.budget_cost_center.id]["amount"], 90.0)
