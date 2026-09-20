"""Receipt upload eligibility regressions, runnable without an Odoo server."""
import ast
from pathlib import Path
from types import SimpleNamespace as Record
import unittest


class TestInvoicePaymentFilter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).parents[1] / "controllers" / "portal.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        method = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef) and node.name == "_get_vendor_invoice_receipt")
        cls.namespace = {"_": lambda text: text}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), cls.namespace)
        cls.check = cls.namespace["_get_vendor_invoice_receipt"]

    def setUp(self):
        self.vendor = Record(id=7)
        self.po = Record(state="purchase", payment_state="paid", advance_payment_amount=1000)
        self.receipt = Record(
            id=8, name="Receipt", state="done", approval_state="approved",
            stage="approved", is_approved=True, purchase_id=self.po,
            purchase_order_id=self.po, grand_total=1000,
            partner_id=Record(commercial_partner_id=self.vendor),
        )
        self.receipt._get_receipt_approval_state = lambda: self.receipt.approval_state
        model = Record()
        model.sudo = lambda: model
        model.browse = lambda ident: Record(exists=lambda: self.receipt if ident == 8 else False)
        self.namespace["request"] = Record(env={key: model for key in
            ("stock.picking", "service.receipt.note", "grn.ses")})
        self._get_accessible_vendor_delivery = lambda ident: True
        self._get_accessible_srn = lambda ident: True
        self._commercial_partner = lambda: self.vendor
        self._receipt_invoice_amount = lambda receipt: 1000
        # Any payment-based eligibility check must fail the test.
        self._vendor_receipt_fully_paid = lambda receipt: self.fail("Payment must not block submission")

    def test_fully_paid_po_allows_invoice_for_each_receipt_type(self):
        for kind in ("picking", "service", "legacy"):
            with self.subTest(kind=kind):
                self.assertTrue(self.check(kind + ":8", self.po))

    def test_pending_or_unapproved_receipts_are_rejected(self):
        for kind in ("picking", "service"):
            self.receipt.state = "assigned"
            self.assertFalse(self.check(kind + ":8", self.po))
            self.receipt.state = "done"
            self.receipt.approval_state = "pending"
            self.assertFalse(self.check(kind + ":8", self.po))
            self.receipt.approval_state = "approved"
        self.receipt.is_approved = False
        self.assertFalse(self.check("legacy:8", self.po))

    def test_wrong_po_cancelled_po_and_inaccessible_receipt_are_rejected(self):
        self.assertFalse(self.check("picking:8", Record(state="purchase")))
        self.po.state = "cancel"
        self.assertFalse(self.check("picking:8", self.po))
        self.po.state = "purchase"
        self._get_accessible_vendor_delivery = lambda ident: False
        self.assertFalse(self.check("picking:8", self.po))
        self._get_accessible_srn = lambda ident: False
        self.assertFalse(self.check("service:8", self.po))

    def test_invalid_or_missing_receipt_is_rejected(self):
        for token in (None, "invalid", "picking:abc", "picking:999", "other:8"):
            self.assertFalse(self.check(token, self.po))


if __name__ == "__main__":
    unittest.main()
