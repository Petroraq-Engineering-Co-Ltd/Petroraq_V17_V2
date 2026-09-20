import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


class TestInvoiceProductCodePrecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).parents[1] / "models" / "account_move.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        model = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        methods = [node for node in model.body if isinstance(node, ast.FunctionDef)
                   and node.name in ("_inverse_product_internal_reference", "_onchange_product_internal_reference")]
        for method in methods:
            method.decorator_list = []
        namespace = {}
        exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), "exec"), namespace)
        cls.inverse = staticmethod(namespace["_inverse_product_internal_reference"])
        cls.onchange = staticmethod(namespace["_onchange_product_internal_reference"])

    def test_same_product_preserves_imported_invoice_and_bill_inputs(self):
        product = object()
        for move_type in ("out_invoice", "in_invoice"):
            calls = []
            line = SimpleNamespace(product_id=product, product_internal_reference=SimpleNamespace(product_id=product),
                                   quantity=.6113503115, price_unit=123.6571546354, name="Source order description",
                                   display_type="product", move_id=SimpleNamespace(is_invoice=lambda _: True))
            for method in ("_inverse_product_id", "_compute_account_id", "_compute_product_uom_id",
                           "_compute_name", "_compute_price_unit", "_compute_tax_ids"):
                setattr(line, method, lambda: calls.append("recomputed"))
            self.inverse([line])
            self.onchange([line])
            self.assertFalse(calls, move_type)
            self.assertEqual(line.quantity, .6113503115)
            self.assertEqual(line.price_unit, 123.6571546354)
            self.assertEqual(line.name, "Source order description")

    def test_changed_product_still_refreshes_defaults(self):
        replacement = object()
        calls = []
        line = SimpleNamespace(product_id=object(), product_internal_reference=SimpleNamespace(product_id=replacement),
                               display_type="product", move_id=SimpleNamespace(is_invoice=lambda _: True))
        for method in ("_inverse_product_id", "_compute_account_id", "_compute_product_uom_id",
                       "_compute_name", "_compute_price_unit", "_compute_tax_ids"):
            setattr(line, method, lambda name=method: calls.append(name))
        self.onchange([line])
        self.assertIs(line.product_id, replacement)
        self.assertIn("_compute_price_unit", calls)
        self.assertEqual(len(calls), 6)
