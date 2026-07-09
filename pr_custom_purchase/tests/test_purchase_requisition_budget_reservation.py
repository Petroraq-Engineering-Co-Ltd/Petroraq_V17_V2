from odoo.tests.common import TransactionCase


class TestPurchaseRequisitionBudgetReservation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create({
            "name": "Budget Reservation Vendor",
            "supplier_rank": 1,
        })
        cls.uom = cls.env.ref("uom.product_uom_unit")
        cls.cost_center_plan = cls.env["account.analytic.plan"].create({
            "name": "Budget Reservation Cost Centers",
        })
        cls.project_plan = cls.env["account.analytic.plan"].create({
            "name": "Budget Reservation Projects",
        })
        cls.cost_center = cls.env["account.analytic.account"].create({
            "name": "Budget Reservation Cost Center",
            "plan_id": cls.cost_center_plan.id,
        })
        cls.second_cost_center = cls.env["account.analytic.account"].create({
            "name": "Budget Reservation Second Cost Center",
            "plan_id": cls.cost_center_plan.id,
        })
        cls.project_analytic = cls.env["account.analytic.account"].create({
            "name": "Budget Reservation Project",
            "plan_id": cls.project_plan.id,
        })
        cls.product = cls.env["product.product"].create({
            "name": "Budget Reservation Product",
            "detailed_type": "consu",
            "uom_id": cls.uom.id,
            "uom_po_id": cls.uom.id,
            "standard_price": 10.0,
        })

    def _create_requisition(self, line_commands):
        return self.env["purchase.requisition"].create({
            "name": "BUDGET-RESERVATION-PR",
            "approval": "approved",
            "line_ids": line_commands,
        })

    def _create_po(self, requisition, line_vals):
        return self.env["purchase.order"].create({
            "name": "BUDGET-RESERVATION-PO",
            "partner_id": self.vendor.id,
            "state": "pending",
            "requisition_id": requisition.id,
            "order_line": [(0, 0, line_vals)],
        })

    def _po_line_vals(self, quantity, unit_price, cost_center, requisition_line=False, analytic=True):
        vals = {
            "product_id": self.product.id,
            "name": self.product.display_name,
            "product_qty": quantity,
            "product_uom": self.uom.id,
            "price_unit": unit_price,
            "date_planned": "2026-07-09 00:00:00",
        }
        if analytic:
            vals["analytic_distribution"] = {str(cost_center.id): 100.0}
        if requisition_line:
            vals["custom_requisition_line_id"] = requisition_line.id
        return vals

    def test_downstream_po_value_clears_stale_pr_reservation(self):
        requisition = self._create_requisition([(0, 0, {
            "description": self.product.id,
            "cost_center_id": self.cost_center.id,
            "quantity": 10.0,
            "unit_price": 10.0,
        })])
        requisition_line = requisition.line_ids

        self._create_po(
            requisition,
            self._po_line_vals(
                quantity=5.0,
                unit_price=25.0,
                cost_center=self.cost_center,
                requisition_line=requisition_line,
            ),
        )

        self.assertEqual(requisition._current_budget_reservation_by_cost_center(), {})

    def test_approved_pr_without_po_keeps_budget_reservation(self):
        requisition = self._create_requisition([(0, 0, {
            "description": self.product.id,
            "cost_center_id": self.cost_center.id,
            "quantity": 10.0,
            "unit_price": 10.0,
        })])

        reservation = requisition._current_budget_reservation_by_cost_center()
        self.assertEqual(reservation[self.cost_center.id]["amount"], 100.0)

    def test_partial_po_replaces_pr_reservation(self):
        requisition = self._create_requisition([(0, 0, {
            "description": self.product.id,
            "cost_center_id": self.cost_center.id,
            "quantity": 10.0,
            "unit_price": 10.0,
        })])
        requisition_line = requisition.line_ids

        self._create_po(
            requisition,
            self._po_line_vals(
                quantity=5.0,
                unit_price=5.0,
                cost_center=self.cost_center,
                requisition_line=requisition_line,
            ),
        )

        self.assertEqual(requisition._current_budget_reservation_by_cost_center(), {})

    def test_po_without_analytic_counts_by_linked_pr_cost_center(self):
        requisition = self._create_requisition([(0, 0, {
            "description": self.product.id,
            "cost_center_id": self.cost_center.id,
            "quantity": 10.0,
            "unit_price": 10.0,
        })])
        requisition_line = requisition.line_ids

        self._create_po(
            requisition,
            self._po_line_vals(
                quantity=5.0,
                unit_price=10.0,
                cost_center=self.cost_center,
                requisition_line=requisition_line,
                analytic=False,
            ),
        )

        spent = self.cost_center._get_po_budget_spent_map()
        self.assertEqual(spent[self.cost_center.id], 50.0)

    def test_comma_analytic_distribution_matches_same_product_pr_line(self):
        requisition = self._create_requisition([
            (0, 0, {
                "description": self.product.id,
                "cost_center_id": self.cost_center.id,
                "quantity": 10.0,
                "unit_price": 10.0,
            }),
            (0, 0, {
                "description": self.product.id,
                "cost_center_id": self.second_cost_center.id,
                "quantity": 10.0,
                "unit_price": 10.0,
            }),
        ])
        first_line, second_line = requisition.line_ids.sorted("id")
        po_vals = self._po_line_vals(
            quantity=10.0,
            unit_price=10.0,
            cost_center=self.second_cost_center,
        )
        po_vals["analytic_distribution"] = {
            "%s,%s" % (self.second_cost_center.id, self.project_analytic.id): 100.0
        }

        self._create_po(requisition, po_vals)

        purchased_quantities = requisition._get_purchased_requisition_line_quantities()
        self.assertEqual(purchased_quantities[first_line.id], 0.0)
        self.assertEqual(purchased_quantities[second_line.id], 10.0)
