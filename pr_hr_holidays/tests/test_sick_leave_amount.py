import ast
import calendar
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import unittest


class TestSickLeaveAmount(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).parents[1] / "models" / "hr_leave.py"
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
