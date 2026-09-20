from odoo import Command
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestDownpaymentTax(AccountTestInvoicingCommon):
    def _create_advance(self, method, included=False, fixed_amount=82800):
        tax = self.env["account.tax"].create({
            "name": "Advance VAT 15%", "amount": 15,
            "amount_type": "percent", "type_tax_use": "sale",
            "price_include": included,
        })
        product = self.env["product.product"].create({
            "name": "Advance tax test service", "type": "service",
            "invoice_policy": "order",
            "property_account_income_id": self.company_data["default_account_revenue"].id,
        })
        order = self.env["sale.order"].create({
            "partner_id": self.partner_a.id,
            "order_line": [Command.create({
                "product_id": product.id, "product_uom_qty": 1,
                "price_unit": 552000 if included else 480000,
                "tax_id": [Command.set(tax.ids)],
            })],
        })
        wizard = self.env["sale.advance.payment.inv"].with_context(
            active_model="sale.order", active_ids=order.ids,
        ).create({
            "sale_order_ids": [Command.set(order.ids)],
            "advance_payment_method": method, "amount": 15,
            "fixed_amount": fixed_amount, "product_id": product.id,
        })
        # Exercise native invoice creation including its fixed-total adjustment.
        return wizard._create_invoices(order)

    def _assert_vat(self, invoice):
        self.assertAlmostEqual(invoice.amount_untaxed, 72000, places=2)
        self.assertAlmostEqual(invoice.amount_tax, 10800, places=2)
        self.assertAlmostEqual(invoice.amount_total, 82800, places=2)
        self.assertTrue(invoice.line_ids.filtered("tax_line_id"))

    def test_percentage_advance_retains_vat(self):
        self._assert_vat(self._create_advance("percentage"))

    def test_fixed_advance_does_not_adjust_vat_to_zero(self):
        self._assert_vat(self._create_advance("fixed"))

    def test_tax_included_fixed_advance(self):
        self._assert_vat(self._create_advance("fixed", included=True))

    def test_fixed_amount_includes_vat(self):
        invoice = self._create_advance("fixed", fixed_amount=72000)
        self.assertAlmostEqual(invoice.amount_untaxed, 62608.70, places=2)
        self.assertAlmostEqual(invoice.amount_tax, 9391.30, places=2)
        self.assertAlmostEqual(invoice.amount_total, 72000, places=2)
