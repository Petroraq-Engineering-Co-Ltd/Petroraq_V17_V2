from datetime import date

from odoo.tests.common import TransactionCase


class TestJoiningArrearsPeriod(TransactionCase):

    def test_unpaid_new_joiner_starts_on_joining_date(self):
        date_from, date_to, paid_through = self.env[
            "payroll.joining.arrears"
        ]._get_arrears_period(date(2099, 6, 26), date(2099, 7, 1), cutoff_day=26)
        self.assertEqual(paid_through, date(2099, 6, 25))
        self.assertEqual(date_from, date(2099, 6, 26))
        self.assertEqual(date_to, date(2099, 6, 30))
        self.assertEqual((date_to - date_from).days + 1, 5)

    def test_explicit_paid_through_can_include_joining_day(self):
        date_from, date_to, _paid_through = self.env[
            "payroll.joining.arrears"
        ]._get_arrears_period(
            date(2099, 6, 26),
            date(2099, 7, 1),
            cutoff_day=26,
            paid_through=date(2099, 6, 25),
        )
        self.assertEqual(date_from, date(2099, 6, 26))
        self.assertEqual(date_to, date(2099, 6, 30))
        self.assertEqual((date_to - date_from).days + 1, 5)

    def test_joining_after_cutoff_starts_on_joining_date(self):
        date_from, date_to, _paid_through = self.env[
            "payroll.joining.arrears"
        ]._get_arrears_period(date(2099, 6, 28), date(2099, 7, 1), cutoff_day=26)
        self.assertEqual(date_from, date(2099, 6, 28))
        self.assertEqual(date_to, date(2099, 6, 30))
