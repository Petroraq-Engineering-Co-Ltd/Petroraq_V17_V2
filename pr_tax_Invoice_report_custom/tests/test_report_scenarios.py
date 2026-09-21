"""Report classification tests runnable without an Odoo database."""
import ast
from pathlib import Path
from types import SimpleNamespace as Record
import unittest


class Lines(list):
    def filtered(self, predicate):
        return Lines(line for line in self if predicate(line))

    def mapped(self, field):
        return [getattr(line, field) for line in self]


class TestInvoiceReportScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).parents[1] / "models" / "models.py"
        method = next(node for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
                      if isinstance(node, ast.FunctionDef) and node.name == "_get_custom_invoice_report_values")
        namespace = {}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
        cls.report = namespace["_get_custom_invoice_report_values"]

    def line(self, amount=100, **values):
        return Record(**dict(dict(display_type="product", is_downpayment=False,
                                  dp_source_sale_line_id=False, price_subtotal=amount, discount=0), **values))

    def values(self, lines, state="posted", move_type="out_invoice", tax=15):
        invoice = Record(ensure_one=lambda: None, invoice_line_ids=Lines(lines), state=state,
                         move_type=move_type, amount_tax=tax,
                         amount_untaxed=sum(line.price_subtotal for line in lines),
                         currency_id=Record(is_zero=lambda value: abs(value) < 0.005))
        return self.report.__func__(invoice)

    def test_titles_for_draft_posted_cancelled_invoices_and_credit_notes(self):
        for state in ("draft", "posted", "cancel"):
            for kind in ("out_invoice", "out_refund", "in_refund"):
                for dp in (False, True):
                    values = self.values([self.line(is_downpayment=dp)], state, kind)
                    self.assertEqual("Draft" in values["title"], state == "draft")
                    self.assertEqual("Cancelled" in values["title"], state == "cancel")
                    self.assertEqual("Credit Note" in values["title"], kind.endswith("refund"))
                    self.assertNotIn("Proforma", values["title"])

    def test_progressive_deductions_support_native_and_custom_links(self):
        for link in ("is_downpayment", "dp_source_sale_line_id"):
            result = self.values([self.line(1000), self.line(-150, **{link: True})])
            self.assertEqual(result["deduction"], -150)
            self.assertEqual(result["before_deduction"], 1000)

    def test_notes_do_not_change_downpayment_classification_or_discount(self):
        result = self.values([self.line(is_downpayment=True, discount=5),
                              self.line(0, display_type="line_note"),
                              self.line(0, display_type="line_section")])
        self.assertIn("Down Payment", result["title"])
        self.assertTrue(result["has_discount"])
        self.assertEqual(result["deduction"], 0)

    def test_zero_tax_invoice_has_no_hardcoded_rate(self):
        self.assertEqual(self.values([self.line()], tax=0)["title"], "Invoice / فاتورة")


if __name__ == "__main__":
    unittest.main()
