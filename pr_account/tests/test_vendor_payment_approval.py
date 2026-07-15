import unittest

from odoo.tests.common import TransactionCase


class TestVendorPaymentApproval(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create({
            "name": "Approval Test Vendor",
            "supplier_rank": 1,
        })
        cls.customer = cls.env["res.partner"].create({
            "name": "Approval Test Customer",
            "customer_rank": 1,
        })
        cls.journal = cls.env["account.journal"].search([
            ("type", "in", ("bank", "cash")),
            ("company_id", "=", cls.env.company.id),
        ], limit=1)
        if not cls.journal:
            raise unittest.SkipTest("No bank/cash journal available for payment approval tests.")

    def _payment_vals(self, **extra):
        vals = {
            "payment_type": "outbound",
            "partner_type": "supplier",
            "partner_id": self.vendor.id,
            "amount": 100.0,
            "journal_id": self.journal.id,
            "date": "2026-07-14",
        }
        vals.update(extra)
        if "payment_method_line_id" not in vals:
            method_lines = (
                self.journal.outbound_payment_method_line_ids
                if vals["payment_type"] == "outbound"
                else self.journal.inbound_payment_method_line_ids
            )
            if method_lines:
                vals["payment_method_line_id"] = method_lines[0].id
        return vals

    def test_direct_vendor_payment_requires_approval_on_create(self):
        payment = self.env["account.payment"].create(self._payment_vals())

        self.assertTrue(payment.pr_requires_vendor_payment_approval)
        self.assertEqual(payment.pr_payment_approval_state, "draft")
        self.assertFalse(payment.pr_vendor_payment_source_line_ids)

    def test_direct_vendor_payment_post_submits_instead_of_posting(self):
        payment = self.env["account.payment"].create(self._payment_vals())

        payment.action_post()

        self.assertEqual(payment.state, "draft")
        self.assertTrue(payment.pr_requires_vendor_payment_approval)
        self.assertEqual(payment.pr_payment_approval_state, "submit")

    def test_customer_payment_does_not_require_vendor_approval(self):
        payment = self.env["account.payment"].create(self._payment_vals(
            payment_type="inbound",
            partner_type="customer",
            partner_id=self.customer.id,
        ))

        self.assertFalse(payment.pr_requires_vendor_payment_approval)