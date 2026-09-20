import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


class Record(SimpleNamespace):
    def ensure_one(self):
        pass

    def __getitem__(self, key):
        return getattr(self, key)


class TestPrDescriptions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parents[1] / "models" / "work_order.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        methods = [node for model in tree.body if isinstance(model, ast.ClassDef)
                   for node in model.body if isinstance(node, ast.FunctionDef)
                   and node.name in ("_get_purchase_requisition_description", "_onchange_product_internal_reference")]
        for method in methods:
            method.decorator_list = []
        namespace = {}
        exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec"), namespace)
        cls.describe = staticmethod(namespace["_get_purchase_requisition_description"])
        cls.onchange = staticmethod(namespace["_onchange_product_internal_reference"])

    def setUp(self):
        self.product = Record(name="Cable", display_name="[CBL] Cable")
        self.product.with_context = lambda **kwargs: Record(display_name="Cable")
        self.source = Record(product_id=self.product, name="Cable 4-core\nFor panel A")
        self.line = Record(product_id=self.product, name="[CBL] Cable",
                           sale_order_line_id=self.source, estimation_line_id=False,
                           _fields={"sale_order_line_id", "estimation_line_id"})

    def test_product_label_recovers_exact_so_description(self):
        self.assertEqual(self.describe(self.line), self.source.name)

    def test_custom_wo_description_wins(self):
        self.line.name = "WO specification\nFor panel B"
        self.assertEqual(self.describe(self.line), self.line.name)

    def test_estimation_fallback_and_missing_optional_links(self):
        self.line.sale_order_line_id = False
        self.line.estimation_line_id = self.source
        self.assertEqual(self.describe(self.line), self.source.name)
        self.line._fields = set()
        self.assertEqual(self.describe(self.line), "[CBL] Cable")

    def test_different_product_source_is_not_used(self):
        self.source.product_id = Record(name="Other product")
        self.assertEqual(self.describe(self.line), "[CBL] Cable")

    def test_same_product_lines_keep_their_own_specifications(self):
        other = Record(**vars(self.line))
        other.sale_order_line_id = Record(product_id=self.product, name="Cable for panel C")
        self.assertNotEqual(self.describe(self.line), self.describe(other))

    def test_same_product_code_does_not_reset_wo_text_or_cost(self):
        self.line.product_internal_reference = Record(product_id=self.product)
        self.line.name = "Imported SO specification"
        self.line.unit_cost = 250
        self.onchange([self.line])
        self.assertEqual(self.line.name, "Imported SO specification")
        self.assertEqual(self.line.unit_cost, 250)

    def test_changed_product_code_gets_new_defaults(self):
        product = Record(display_name="New product", uom_id=42, standard_price=75)
        self.line.product_internal_reference = Record(product_id=product)
        self.onchange([self.line])
        self.assertEqual(self.line.name, "New product")
        self.assertEqual(self.line.unit_cost, 75)
