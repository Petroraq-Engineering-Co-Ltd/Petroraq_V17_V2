from odoo import fields
from odoo.tests.common import TransactionCase
from types import SimpleNamespace


class TestVatSummaryDetailedLines(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        today = fields.Date.context_today(cls.env.user)
        cls.wizard = cls.env["vat.summary.wizard"].create(
            {
                "company_id": cls.env.company.id,
                "date_filter": "custom",
                "date_start": today,
                "date_end": today,
                "is_detailed": True,
                "merge_invoice_lines": True,
            }
        )

    @staticmethod
    def _line(group_key, entry, amount, vat_amount):
        return {
            "_move_id": group_key[1],
            "_group_key": group_key,
            "date": "01/01/2026",
            "entry": entry,
            "reference": "",
            "account": "4000 Revenue",
            "partner": "Customer",
            "label": "Invoice item",
            "amount": amount,
            "vat_amount": vat_amount,
            "total_amount": amount + vat_amount,
        }

    def test_invoice_lines_are_merged(self):
        lines = [
            self._line(("invoice", 10), "INV/0010", 100.0, 15.0),
            self._line(("invoice", 10), "INV/0010", 50.0, 7.5),
            self._line(("invoice", 11), "INV/0011", 80.0, 12.0),
        ]

        result = self.wizard._merge_detailed_invoice_lines(lines)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["amount"], 150.0)
        self.assertEqual(result[0]["vat_amount"], 22.5)
        self.assertEqual(result[0]["total_amount"], 172.5)

    def test_journal_lines_remain_separate(self):
        lines = [
            self._line(("line", 21), "MISC/0021", 100.0, 0.0),
            self._line(("line", 22), "MISC/0021", 50.0, 0.0),
        ]

        result = self.wizard._merge_detailed_invoice_lines(lines)

        self.assertEqual(len(result), 2)

    def test_credit_note_lines_keep_negative_totals(self):
        lines = [
            self._line(("invoice", 30), "RINV/0030", -100.0, -15.0),
            self._line(("invoice", 30), "RINV/0030", -50.0, -7.5),
        ]

        result = self.wizard._merge_detailed_invoice_lines(lines)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["amount"], -150.0)
        self.assertEqual(result[0]["vat_amount"], -22.5)
        self.assertEqual(result[0]["total_amount"], -172.5)

    def test_unmerged_option_keeps_invoice_lines(self):
        self.wizard.merge_invoice_lines = False
        lines = [
            self._line(("invoice", 10), "INV/0010", 100.0, 15.0),
            self._line(("invoice", 10), "INV/0010", 50.0, 7.5),
        ]

        result = self.wizard._merge_detailed_invoice_lines(lines)

        self.assertEqual(len(result), 2)
        self.assertNotIn("_group_key", result[0])

    def test_purchase_tax_is_included_for_non_expense_account(self):
        purchase_tax = SimpleNamespace(type_tax_use="purchase")
        asset_account = SimpleNamespace(account_type="asset_current")
        line = SimpleNamespace(
            balance=1250.0,
            tax_ids=[purchase_tax],
            account_id=asset_account,
        )

        amounts = self.wizard._get_vated_detail_amounts(line)

        self.assertEqual(amounts["vated_purchases"], 1250.0)
        self.assertEqual(amounts["vated_sales"], 0.0)

    def test_actual_posted_vat_is_allocated_without_rounding_difference(self):
        lines = [
            self._line(("invoice", 40), "BILL/0040", 100.0, 0.0),
            self._line(("invoice", 40), "BILL/0040", 33.33, 0.0),
        ]

        self.wizard._allocate_actual_vat(lines, {40: 20.0})

        self.assertAlmostEqual(sum(line["vat_amount"] for line in lines), 20.0)
        self.assertAlmostEqual(
            sum(line["total_amount"] for line in lines),
            153.33,
        )
