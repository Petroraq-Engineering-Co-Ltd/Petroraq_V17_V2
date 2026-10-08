from datetime import date

from odoo.tests.common import TransactionCase

from ..models.eos_calculation import get_service_duration
from ..models.pr_end_of_service import _classify_contract_salary_rule


class TestEOSCalculation(TransactionCase):
    def test_service_duration_is_inclusive(self):
        duration = get_service_duration(date(2025, 1, 1), date(2025, 12, 31))

        self.assertEqual(duration["years"], 1)
        self.assertEqual(duration["months"], 0)
        self.assertEqual(duration["days"], 0)

    def test_accommodation_salary_rule_is_housing(self):
        self.assertEqual(
            _classify_contract_salary_rule("ACCOMMODATION", "Accommodation"),
            "housing",
        )

    def test_transport_and_other_salary_rule_buckets(self):
        self.assertEqual(
            _classify_contract_salary_rule("TRANSPORTATION", "Transportation"),
            "transport",
        )
        self.assertEqual(
            _classify_contract_salary_rule("FOOD", "Food"),
            "other",
        )
