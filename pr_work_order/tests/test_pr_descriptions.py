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
                   and node.name in (
                       "_get_purchase_requisition_description",
                       "_onchange_product_internal_reference",
                       "_get_source_budget_ceilings",
                   )]
        for method in methods:
            method.decorator_list = []
        namespace = {"_": lambda value: value}
        exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec"), namespace)
        cls.describe = staticmethod(namespace["_get_purchase_requisition_description"])
        cls.onchange = staticmethod(namespace["_onchange_product_internal_reference"])
        cls.get_ceilings = staticmethod(namespace["_get_source_budget_ceilings"])

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

    def test_work_order_creation_keeps_the_source_description_link(self):
        models_dir = Path(__file__).parents[1] / "models"
        work_order_source = (models_dir / "work_order.py").read_text(encoding="utf-8-sig")
        sale_source = (models_dir / "sale_order_inherit.py").read_text(encoding="utf-8-sig")
        self.assertIn("sale_order_line_id = fields.Many2one", work_order_source)
        self.assertIn('"sale_order_line_id": line.id', sale_source)

    def test_work_order_revision_revalidates_sale_order_ceiling(self):
        source = (Path(__file__).parents[1] / "models" / "work_order.py").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("def _validate_budget_within_source_documents", source)
        self.assertIn("work_orders._validate_budget_within_source_documents()", source)

    def test_work_order_budget_uses_so_and_estimation_ceilings(self):
        estimation = Record(
            display_name="EST/2026/001",
            total_with_profit=900.0,
        )
        sale_order = Record(
            display_name="SO/2026/001",
            amount_total=1000.0,
            estimation_id=estimation,
            _fields={"estimation_id"},
        )
        work_order = Record(sale_order_id=sale_order)

        self.assertEqual(
            self.get_ceilings(work_order),
            [
                ("Sales Order", "SO/2026/001", 1000.0),
                ("Estimation", "EST/2026/001", 900.0),
            ],
        )

    def test_work_order_budget_ceiling_supports_sales_without_estimation_module(self):
        sale_order = Record(
            display_name="SO/2026/002",
            amount_total=750.0,
            _fields=set(),
        )
        work_order = Record(sale_order_id=sale_order)

        self.assertEqual(
            self.get_ceilings(work_order),
            [("Sales Order", "SO/2026/002", 750.0)],
        )

    def test_create_pr_reloads_live_boq_description(self):
        source = (
            Path(__file__).parents[1] / "models" / "work_order_pr_wizard.py"
        ).read_text(encoding="utf-8-sig")
        self.assertIn(
            "line_description = boq_line._get_purchase_requisition_description()",
            source,
        )
        self.assertIn('"boq_line_id": source_boq_line.id', source)

    def test_readonly_wizard_description_is_force_saved(self):
        source = (
            Path(__file__).parents[1] / "views" / "work_order_pr_wizard_views.xml"
        ).read_text(encoding="utf-8-sig")
        self.assertIn(
            '<field name="line_description" readonly="1" force_save="1"/>',
            source,
        )
