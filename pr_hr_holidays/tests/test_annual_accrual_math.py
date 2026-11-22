"""Run directly with Python; does not require an Odoo database."""
import importlib.util
from datetime import date, timedelta
from pathlib import Path
import unittest

try:  # Odoo test runner: collected through tests/__init__.py with tags.
    from odoo.tests import BaseCase as _TestCase, tagged
except ImportError:  # Standalone: python -I <this file>
    _TestCase = unittest.TestCase

    def tagged(*_tags):
        return lambda cls: cls

spec = importlib.util.spec_from_file_location(
    "annual_accrual", Path(__file__).parents[1] / "models" / "annual_accrual.py",
)
math = importlib.util.module_from_spec(spec)
spec.loader.exec_module(math)


@tagged("post_install", "-at_install")
class TestCalendarEntitlement(_TestCase):
    def test_ongoing_daily_credits_over_many_years(self):
        for entitlement in (21, 26):
            for gain in ("start", "end"):
                start = date(2020, 6, 6)
                for year in range(2020, 2031):
                    anniversary = date(year, 6, 6)
                    for elapsed in (0, 1, 165, 329, 330, 350, 364):
                        expected = (year - 2020) * entitlement + entitlement * min(elapsed + (gain == "start"), 330) / 330
                        self.assertAlmostEqual(math.lifetime_entitlement(
                            start, False, anniversary + timedelta(days=elapsed), entitlement, 330, gain,
                        ), expected)

    def test_ongoing_february_29_and_cutoff(self):
        start = date(2024, 2, 29)
        self.assertEqual(math.lifetime_entitlement(start, False, date(2028, 2, 29), 21, 330, "end"), 84)
        self.assertAlmostEqual(math.lifetime_entitlement(start, False, date(2028, 3, 1), 21, 330, "end"), 84 + 21 / 330)
        cutoff = date(2025, 3, 9)
        expected = 21 + 21 * 10 / 330
        for gain in ("start", "end"):
            self.assertAlmostEqual(math.lifetime_entitlement(start, cutoff, date(2030, 1, 1), 21, 330, gain), expected)

    def test_every_day_of_normal_and_leap_years(self):
        for year in (2023, 2024):
            start, end = date(year, 1, 1), date(year, 12, 31)
            for entitlement in (21, 26):
                for elapsed in range(-1, 400):
                    for gain in ("start", "end"):
                        target = start + timedelta(days=elapsed)
                        expected_days = min(330, max(0, elapsed + (gain == "start")))
                        self.assertAlmostEqual(
                            math.earned_entitlement(start, end, target, entitlement, 330, gain),
                            entitlement * expected_days / 330,
                        )

    def test_final_day_with_365_day_earning_period(self):
        start, end = date(2023, 1, 1), date(2023, 12, 31)
        self.assertAlmostEqual(math.earned_entitlement(start, end, end, 21, 365, "end"), 21 * 364 / 365)
        self.assertEqual(math.earned_entitlement(start, end, date(2024, 1, 1), 21, 365, "end"), 21)

    def test_anniversary_preserves_february_29(self):
        anchor = date(2024, 2, 29)
        start = anchor
        for year in (2025, 2026, 2027, 2028):
            following = math.next_anniversary(start, anchor)
            self.assertEqual(following, date(year, 2, 29 if year == 2028 else 28))
            self.assertIn((following - start).days, (365, 366))
            start = following

    def test_next_year_restarts_with_separate_balance(self):
        for entitlement in (21, 26):
            for year in (2023, 2024, 2025):
                start, end = date(year, 7, 1), date(year + 1, 6, 30)
                self.assertEqual(math.earned_entitlement(start, end, start, entitlement, 330, "end"), 0)
                self.assertEqual(math.earned_entitlement(start, end, end, entitlement, 330, "end"), entitlement)

    def test_service_year_bounds_follow_contract_anniversary(self):
        anchor = date(2023, 6, 15)
        self.assertEqual(math.service_year_bounds(anchor, date(2026, 2, 1)), (date(2025, 6, 15), date(2026, 6, 15)))
        self.assertEqual(math.service_year_bounds(anchor, date(2026, 6, 15)), (date(2026, 6, 15), date(2027, 6, 15)))
        self.assertEqual(math.service_year_bounds(anchor, date(2026, 6, 14)), (date(2025, 6, 15), date(2026, 6, 15)))
        self.assertEqual(math.service_year_bounds(anchor, anchor), (anchor, date(2024, 6, 15)))

    def test_service_year_bounds_february_29_anchor(self):
        anchor = date(2024, 2, 29)
        self.assertEqual(math.service_year_bounds(anchor, date(2027, 2, 27)), (date(2026, 2, 28), date(2027, 2, 28)))
        self.assertEqual(math.service_year_bounds(anchor, date(2027, 2, 28)), (date(2027, 2, 28), date(2028, 2, 29)))
        self.assertEqual(math.service_year_bounds(anchor, date(2028, 2, 29)), (date(2028, 2, 29), date(2029, 2, 28)))

    def test_overlap_days_is_inclusive(self):
        window = (date(2025, 9, 1), date(2026, 1, 27))
        self.assertEqual(math.overlap_days(date(2025, 10, 1), date(2025, 10, 25), *window), 25)
        self.assertEqual(math.overlap_days(date(2025, 8, 25), date(2025, 9, 3), *window), 3)
        self.assertEqual(math.overlap_days(date(2025, 1, 1), date(2025, 1, 31), *window), 0)
        self.assertEqual(math.overlap_days(date(2026, 1, 27), date(2026, 2, 5), *window), 1)


if __name__ == "__main__":
    unittest.main()
