import ast
from collections import defaultdict
from datetime import date
from pathlib import Path
from types import SimpleNamespace as Record
import unittest


class Records(list):
    def __getattr__(self, name):
        values = [getattr(item, name) for item in self]
        return Records([child for value in values for child in value]) if values and isinstance(values[0], list) else Records(values)

    @property
    def ids(self):
        return [item.id for item in self]

    def filtered(self, predicate):
        return Records(item for item in self if predicate(item))

    def mapped(self, name):
        return [getattr(item, name) for item in self]


class TestSettlementReportLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).parents[1] / "models" / "settlement_report.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
        model = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        method = next(node for node in model.body if isinstance(node, ast.FunctionDef) and node.name == "_get_report_data")
        namespace = {"defaultdict": defaultdict, "_": lambda text: text,
                     "fields": Record(Date=Record(to_date=lambda value: value))}
        exec(compile(ast.Module(body=[helper, method], type_ignores=[]), str(source), "exec"), namespace)
        cls.report_data = staticmethod(namespace["_get_report_data"])
        cls.status = staticmethod(namespace["settlement_status"])

    def report(self, purchase=False, refund=False, cutoff=date(2026, 6, 30), balance_filter="all"):
        currency = Record(round=lambda value: round(value, 2), is_zero=lambda value: abs(value) < .005,
                          compare_amounts=lambda a, b: (a > b) - (a < b))
        direction = (-1 if purchase else 1) * (-1 if refund else 1)
        move = Record(id=1, invoice_date=date(2026, 6, 1), date=date(2026, 6, 1), name="TEST/001",
                      invoice_origin=False, commercial_partner_id=Record(display_name="Test Partner"),
                      invoice_line_ids=Record(purchase_line_id=Record(order_id=Records()),
                                              sale_line_ids=Record(order_id=Records())))
        term = Record(id=10, move_id=move, balance=100 * direction, date_maturity=date(2026, 6, 20),
                      account_id=Record(account_type="liability_payable" if purchase else "asset_receivable"))
        move.line_ids = Records([term])
        other = Record(id=11)
        partials = Records(Record(debit_move_id=term if direction > 0 else other,
                                 credit_move_id=other if direction > 0 else term, amount=amount, max_date=day)
                           for amount, day in [(30, date(2026, 6, 15)), (70, date(2026, 7, 15))])
        seen = {}
        def search_partials(domain):
            seen['cutoff'] = next(item[2] for item in domain if isinstance(item, tuple) and item[0] == 'max_date')
            return partials.filtered(lambda partial: partial.max_date <= seen['cutoff'])
        env = {"account.move": Record(search=lambda *args, **kwargs: Records([move])),
               "account.partial.reconcile": Record(search=search_partials)}
        wizard = Record(_check_report_access=lambda: None, report_type="purchase" if purchase else "sale",
                        company_id=Record(id=1, currency_id=currency), include_credit_notes=True,
                        date_as_of=cutoff, date_from=False, partner_ids=Records(), env=env,
                        balance_filter=balance_filter, _fields={"balance_filter": Record(selection=[(balance_filter, balance_filter)])})
        result = self.report_data(wizard)
        self.assertEqual(seen['cutoff'], cutoff)
        return result

    def test_cutoff_ignores_later_settlement_for_sales_and_purchases(self):
        for purchase in (False, True):
            row = self.report(purchase=purchase)['rows'][0]
            self.assertEqual((row['amount'], row['paid'], row['balance']), (100, 30, 70))
            self.assertEqual(row['received_date'], date(2026, 6, 15))
            self.assertEqual(row['overdue_days'], 10)
            later = self.report(purchase=purchase, cutoff=date(2026, 7, 31))['rows'][0]
            self.assertEqual(later['balance'], 0)

    def test_credit_signs_and_totals(self):
        for purchase in (False, True):
            report = self.report(purchase=purchase, refund=True)
            self.assertEqual(report['totals'], {'amount': -100, 'paid': -30, 'balance': -70})
            self.assertEqual(report['rows'][0]['status'], 'Credit Outstanding')

    def test_open_settled_and_overdue_filters(self):
        self.assertEqual(len(self.report(balance_filter='open')['rows']), 1)
        self.assertEqual(len(self.report(balance_filter='overdue')['rows']), 1)
        self.assertFalse(self.report(balance_filter='settled')['rows'])
        self.assertFalse(self.report(balance_filter='open', cutoff=date(2026, 7, 31))['rows'])

    def test_early_on_time_late_and_unpaid(self):
        due = date(2026, 6, 20)
        zero = lambda amount: abs(amount) < .005
        for day, expected in [(15, 'Early Received'), (20, 'Received'), (25, 'Late Received')]:
            self.assertEqual(self.status(100, 0, due, date(2026, 6, day), due, zero), expected)
        self.assertEqual(self.status(100, 100, due, False, due, zero), 'Pending')
        self.assertEqual(self.status(100, 100, due, False, date(2026, 6, 21), zero), 'Overdue')
