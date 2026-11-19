import ast
import calendar
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import unittest

try:  # Odoo test runner: collected through tests/__init__.py with tags.
    from odoo.tests import BaseCase as _TestCase, tagged
except ImportError:  # Standalone: python -I <this file>
    _TestCase = unittest.TestCase

    def tagged(*_tags):
        return lambda cls: cls


@tagged("post_install", "-at_install")
class TestSickLeaveAmount(_TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        source =Path(__file__).parents[1] / "models" / "hr_leave.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        model = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        method = next(node for node in model.body if isinstance(node, ast.FunctionDef)
                      and node.name == "_calculate_sick_leave_amount")
        namespace = {"date_utils": SimpleNamespace(
            start_of=lambda day, unit: day.replace(day=1),
            end_of=lambda day, unit: day.replace(day=calendar.monthrange(day.year, day.month)[1]),
        )}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
        cls.calculate = staticmethod(namespace["_calculate_sick_leave_amount"])

    def test_shahd_boundary_and_other_nonterminating_cases(self):
        days = {date(2026, 3, 1): {"from_date": date(2026, 3, 2), "to_date": date(2026, 3, 3)}}
        for consumed, expected in [(0, 200), (29, 175), (30, 150), (30.5, 150),
                                   (59, 75), (60, 0), (60.5, 0), (90, 0), (100, 0)]:
            with self.subTest(consumed=consumed):
                self.assertAlmostEqual(self.calculate([object()], days, consumed, 3100), expected)

    def test_month_boundary_carries_days_forward(self):
        days = {
            date(2026, 1, 1): {"from_date": date(2026, 1, 31), "to_date": date(2026, 1, 31)},
            date(2026, 2, 1): {"from_date": date(2026, 2, 1), "to_date": date(2026, 2, 1)},
        }
        self.assertAlmostEqual(self.calculate([object()], days, 29, 3100), 100 + 3100 / 28 * .75)

    def test_zero_salary_still_finishes(self):
        days = {date(2026, 3, 1): {"from_date": date(2026, 3, 2), "to_date": date(2026, 3, 3)}}
        self.assertEqual(self.calculate([object()], days, 30, 0), 0)

    def test_band_crossing_over_month_boundary_hand_computed(self):
        # Salary 9000, leave Jan 28 - Feb 10 2026, 25 prior sick days in the service year:
        # Jan 28-31: 4 days full pay            -> 4 * 9000 / 31            = 1161.29
        # Feb 1-10: day 30 full, days 31-39 75% -> (1 + 9 * 0.75) * 9000 / 28 = 2491.07
        days = {
            date(2026, 1, 1): {"from_date": date(2026, 1, 28), "to_date": date(2026, 1, 31)},
            date(2026, 2, 1): {"from_date": date(2026, 2, 1), "to_date": date(2026, 2, 10)},
        }
        self.assertAlmostEqual(self.calculate([object()], days, 25, 9000), 3652.36, places=2)
        # Prior-year sick days are not part of the count: with 0 prior days all 14 days are full pay.
        self.assertAlmostEqual(self.calculate([object()], days, 0, 9000), 4 * 9000 / 31 + 10 * 9000 / 28)


if __name__ == "__main__":
    unittest.main()
