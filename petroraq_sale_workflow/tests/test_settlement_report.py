from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestSettlementReport(AccountTestInvoicingCommon):
    def _wizard(self, purchase=False, **values):
        return self.env["pr.settlement.report.wizard"].create({
            "report_type": "purchase" if purchase else "sale",
            "company_id": self.env.company.id, "date_as_of": "2026-06-30",
            "partner_ids": [Command.set(self.partner_a.ids)], **values,
        })

    def _invoice(self, purchase=False, refund=False):
        move_type = ("in_" if purchase else "out_") + ("refund" if refund else "invoice")
        return self.init_invoice(move_type, partner=self.partner_a, invoice_date="2026-06-01",
                                 amounts=[100], taxes=[], post=True)

    def _settle(self, invoice, amount, date):
        term = invoice.line_ids.filtered(lambda line: line.account_id.account_type in
                                        ("asset_receivable", "liability_payable"))
        sign = 1 if invoice.move_type == "out_invoice" else -1
        payment = self.env["account.move"].create({
            "date": date, "journal_id": self.company_data["default_journal_misc"].id,
            "line_ids": [Command.create({
                "name": "Settlement", "partner_id": self.partner_a.id, "account_id": term.account_id.id,
                "debit": amount if sign < 0 else 0, "credit": amount if sign > 0 else 0,
            }), Command.create({
                "name": "Counterpart", "account_id": self.company_data["default_account_revenue"].id,
                "debit": amount if sign > 0 else 0, "credit": amount if sign < 0 else 0,
            })],
        })
        payment.action_post()
        (term | payment.line_ids.filtered(lambda line: line.account_id == term.account_id)).reconcile()

    def test_historical_partial_balance_excludes_later_payment(self):
        invoice = self._invoice()
        self._settle(invoice, 30, "2026-06-15")
        self._settle(invoice, 70, "2026-07-15")
        rows = self._wizard()._get_report_data()["rows"]
        row = next(row for row in rows if row["invoice"] == invoice.name)
        self.assertEqual((row["amount"], row["paid"], row["balance"]), (100, 30, 70))
        self.assertEqual(row["status"], "Partially Received")
        later = self._wizard(date_as_of="2026-07-31")._get_report_data()["rows"]
        self.assertEqual(next(row for row in later if row["invoice"] == invoice.name)["balance"], 0)

    def test_vendor_sign_and_credit_note(self):
        bill = self._invoice(purchase=True)
        self._settle(bill, 25, "2026-06-15")
        credit = self._invoice(purchase=True, refund=True)
        rows = self._wizard(purchase=True)._get_report_data()["rows"]
        row = next(row for row in rows if row["invoice"] == bill.name)
        self.assertEqual((row["paid"], row["balance"]), (25, 75))
        self.assertEqual(next(row for row in rows if row["invoice"] == credit.name)["amount"], -100)

    def test_partner_filter_and_date_validation(self):
        invoice = self._invoice()
        wizard = self._wizard(partner_ids=[Command.set(self.partner_b.ids)])
        self.assertNotIn(invoice.name, [row["invoice"] for row in wizard._get_report_data()["rows"]])
        with self.assertRaises(ValidationError):
            self._wizard(date_from="2026-07-01")._get_report_data()
