"""Isolated payment eligibility regressions; runnable without an Odoo database."""
import ast
from pathlib import Path
from types import SimpleNamespace as Record
import unittest


class Records(list):
    def filtered(self, predicate):
        return Records(record for record in self if predicate(record))

    def mapped(self, field):
        return Records(getattr(record, field) for record in self)


class TestInvoicePaymentFilter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).parents[1] / "controllers" / "portal.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        controller = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        method = next(node for node in controller.body
                      if isinstance(node, ast.FunctionDef) and node.name == "_vendor_receipt_fully_paid")
        namespace = {"float_compare": lambda a, b, precision_rounding: round(
            (a - b) / precision_rounding)}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
        cls.check = namespace["_vendor_receipt_fully_paid"]

    def setUp(self):
        self.currency = Record(
            compare_amounts=lambda a, b: round((a - b) * 100),
            _convert=lambda amount, *args: amount,
        )
        self.po = Record(advance_payment_ids=Records(), amount_total=100,
                         currency_id=self.currency, company_id=1)
        self.bill = Record(state="posted", payment_state="paid", move_type="in_invoice",
                           amount_total=100, currency_id=self.currency, date="2026-09-13")
        self.uom = Record(rounding=0.01, _compute_quantity=lambda qty, target: qty)
        self.line = Record(invoice_lines=Records([Record(
            move_id=self.bill, quantity=10, product_uom_id=self.uom)]),
            qty_received=10, product_uom=self.uom)

    def receipt(self, kind):
        return Record(_name=kind, purchase_id=self.po, purchase_order_id=self.po,
                      bill_ids=Records([self.bill]), grand_total=100,
                      move_ids_without_package=Records([Record(quantity=10, purchase_line_id=self.line)]),
                      line_ids=Records([Record(done_qty=10, purchase_line_id=self.line)]))

    def test_payment_states_for_all_receipt_types(self):
        for kind in ("stock.picking", "service.receipt.note", "grn.ses"):
            for state in ("paid", "partial", "not_paid", "in_payment", "reversed"):
                with self.subTest(kind=kind, state=state):
                    self.bill.payment_state = state
                    self.assertEqual(self.check(self.receipt(kind)), state == "paid")

    def test_unbilled_and_cancelled_bills_remain_available(self):
        for kind in ("stock.picking", "service.receipt.note", "grn.ses"):
            self.bill.state = "cancel"
            self.assertFalse(self.check(self.receipt(kind)))
        self.line.invoice_lines = Records()
        self.assertFalse(self.check(self.receipt("stock.picking")))

    def test_paid_earlier_delivery_does_not_hide_unpaid_backorder(self):
        self.line.qty_received = 20
        for kind in ("stock.picking", "service.receipt.note"):
            self.assertFalse(self.check(self.receipt(kind)))

    def test_legacy_bill_must_cover_receipt_amount(self):
        self.bill.amount_total = 50
        self.assertFalse(self.check(self.receipt("grn.ses")))

    def test_only_posted_full_advances_hide_receipts(self):
        self.line.invoice_lines = Records()
        payment = Record(state="draft", payment_type="outbound", currency_id=self.currency,
                         amount=100, date="2026-09-13")
        self.po.advance_payment_ids.append(payment)
        self.assertFalse(self.check(self.receipt("stock.picking")))
        payment.state = "posted"
        self.assertTrue(self.check(self.receipt("stock.picking")))
        payment.amount = 50
        self.assertFalse(self.check(self.receipt("stock.picking")))


if __name__ == "__main__":
    unittest.main()
