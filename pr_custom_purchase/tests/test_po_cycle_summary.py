"""Isolated tests of reporting logic, without accounting journal fixtures."""
import ast
from pathlib import Path
from types import SimpleNamespace as Record
import unittest

from odoo.tools import float_compare


class Records(list):
    def filtered(self, predicate):
        return Records(record for record in self if predicate(record))


class TestPoCycleSummary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        model_dir = Path(__file__).parents[1] / "models"
        def method(filename, name):
            tree = ast.parse((model_dir / filename).read_text(encoding="utf-8-sig"))
            model = next(node for node in tree.body if isinstance(node, ast.ClassDef))
            node = next(node for node in model.body if isinstance(node, ast.FunctionDef) and node.name == name)
            node.decorator_list = []
            return node

        class Base(Records):
            def _compute_workflow_billing_status(self):
                for order in self:
                    order.workflow_payment_status = order.base_status

        namespace = {"float_compare": float_compare, "Base": Base}
        delivery = method("purchase_order_reporting.py", "_compute_workflow_delivery_status")
        payment = method("purchase_order_advance_payment.py", "_compute_workflow_billing_status")
        model = ast.ClassDef(name="Report", bases=[ast.Name(id="Base", ctx=ast.Load())],
                             keywords=[], body=[delivery, payment], decorator_list=[])
        exec(compile(ast.fix_missing_locations(ast.Module(body=[model], type_ignores=[])),
                     "production-reporting", "exec"), namespace)
        cls.Report = namespace["Report"]

    def setUp(self):
        self.currency = Record(rounding=0.01, _convert=lambda amount, *args: amount)
        self.order = Record(state="purchase", amount_total=100, currency_id=self.currency,
                            company_id=1, advance_payment_ids=Records(), base_status="no_bill")
        self.order.sudo = lambda: self.order
        self.report = self.Report([self.order])

    def test_delivery_quantities_and_states(self):
        line = Record(display_type=False, product_qty=10, qty_received=0,
                      product_uom=Record(rounding=0.01))
        self.order.order_line = Records([line])
        for quantity, expected in [(0, "pending"), (4, "partial"), (10, "done"), (0, "pending")]:
            line.qty_received = quantity
            self.report._compute_workflow_delivery_status()
            self.assertEqual(self.order.workflow_delivery_status, expected)
        for state, expected in [("draft", "not_ordered"), ("cancel", "cancel")]:
            self.order.state = state
            self.report._compute_workflow_delivery_status()
            self.assertEqual(self.order.workflow_delivery_status, expected)

    def test_only_posted_unreversed_advances_count(self):
        payment = Record(state="draft", payment_type="outbound", amount=30,
                         currency_id=self.currency, date="2026-09-15",
                         move_id=Record(reversal_move_id=Records()))
        self.order.advance_payment_ids.append(payment)
        for state, amount, expected in [("draft", 100, "no_bill"), ("posted", 30, "advance_partial"),
                                         ("posted", 100, "advance_paid"), ("cancel", 100, "no_bill")]:
            payment.state, payment.amount = state, amount
            self.report._compute_workflow_billing_status()
            self.assertEqual(self.order.workflow_payment_status, expected)
        payment.state = "posted"
        payment.move_id.reversal_move_id.append(Record(state="posted"))
        self.report._compute_workflow_billing_status()
        self.assertEqual(self.order.workflow_payment_status, "no_bill")

    def test_paid_bills_take_priority(self):
        self.order.base_status = "paid"
        self.report._compute_workflow_billing_status()
        self.assertEqual(self.order.workflow_payment_status, "paid")
