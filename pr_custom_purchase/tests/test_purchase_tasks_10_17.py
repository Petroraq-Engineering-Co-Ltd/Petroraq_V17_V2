from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestPurchaseTaskCommercialTerms(TransactionCase):
    def test_schedule_percentages_must_total_one_hundred(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env["account.payment.term"].create({
                "name": "Invalid Milestones", "purchase_milestone_schedule": True,
                "advance_percent": 20, "progressive_percent": 30, "completion_percent": 30,
            })

    def test_valid_payment_schedule_summary(self):
        term = self.env["account.payment.term"].create({
            "name": "20 / 60 / 20", "purchase_milestone_schedule": True,
            "advance_percent": 20, "progressive_percent": 60, "completion_percent": 20,
            "purchase_credit_days": 30,
        })
        self.assertIn("30 days", term.purchase_schedule_summary)
        self.assertIn("Progressive", term.purchase_schedule_summary)

    def test_ordinary_po_requires_vendor(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env["purchase.order"].create({"partner_id": False, "name": "PO-VENDOR-TEST"})

    def test_budgetary_rfq_allows_free_text_vendor(self):
        pr = self.env["purchase.requisition"].create({"pr_type": "budgetary"})
        before = self.env["res.partner"].search_count([("email", "=", "new-vendor@example.com")])
        order = self.env["purchase.order"].create({
            "name": "RFQ-BUDGETARY-TEST", "requisition_id": pr.id,
            "partner_id": False, "rfq_vendor_name": "Unregistered Vendor",
            "rfq_vendor_email": "new-vendor@example.com", "notes": "Budgetary enquiry only",
        })
        action = order.action_rfq_send()
        self.assertEqual(action["res_model"], "budgetary.rfq.email")
        self.assertFalse(order.partner_id)
        self.assertEqual(before, self.env["res.partner"].search_count([("email", "=", "new-vendor@example.com")]))
