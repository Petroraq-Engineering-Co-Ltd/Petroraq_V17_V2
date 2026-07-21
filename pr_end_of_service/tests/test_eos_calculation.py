from datetime import date

from odoo.tests.common import TransactionCase

from ..models.eos_calculation import get_service_duration


class TestEOSCalculation(TransactionCase):
    def test_service_duration_is_inclusive(self):
        duration = get_service_duration(date(2025, 1, 1), date(2025, 12, 31))

        self.assertEqual(duration["years"], 1)
        self.assertEqual(duration["months"], 0)
        self.assertEqual(duration["days"], 0)
