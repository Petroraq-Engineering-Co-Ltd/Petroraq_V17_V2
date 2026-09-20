"""Run delivery summary regressions without an Odoo server."""
import ast
from pathlib import Path
from types import SimpleNamespace as Record
import unittest


class Records(list):
    def mapped(self, field):
        return [getattr(record, field) for record in self]

    def filtered(self, predicate):
        return Records(record for record in self if predicate(record))


class TestDeliverySummary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).parents[1] / "models" / "stock_picking.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        methods = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                   and node.name in ("_pr_portal_delivery_status_from_quantities",
                                     "_compute_pr_portal_delivery_summary")]
        for method in methods:
            method.decorator_list = []
        namespace = {}
        exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), "exec"), namespace)
        cls.methods = namespace

    def summary(self, state, quantity, move_state=None, demand=65):
        picking = Record(state=state, move_ids_without_package=Records([
            Record(state=move_state or state, product_uom_qty=demand, quantity=quantity)]))
        picking._pr_portal_delivery_status_from_quantities = lambda *args: self.methods[
            "_pr_portal_delivery_status_from_quantities"](None, *args)
        self.methods["_compute_pr_portal_delivery_summary"]([picking])
        return (picking.pr_portal_delivery_status, picking.pr_portal_delivered_quantity,
                picking.pr_portal_pending_quantity)

    def test_ready_full_quantity_is_not_delivered(self):
        for state in ("draft", "confirmed", "waiting", "assigned"):
            self.assertEqual(self.summary(state, 65), ("pending", 0, 65))

    def test_validated_receipt_and_pending_backorder(self):
        self.assertEqual(self.summary("done", 40, demand=40), ("received", 40, 0))
        self.assertEqual(self.summary("assigned", 25, demand=25), ("pending", 0, 25))
        self.assertEqual(self.summary("done", 25, demand=25), ("received", 25, 0))

    def test_partial_and_cancelled_moves(self):
        self.assertEqual(self.summary("done", 40), ("partial", 40, 25))
        self.assertEqual(self.summary("cancel", 65), ("cancel", 0, 65))
        self.assertEqual(self.summary("done", 65, move_state="cancel"), ("pending", 0, 65))


if __name__ == "__main__":
    unittest.main()
