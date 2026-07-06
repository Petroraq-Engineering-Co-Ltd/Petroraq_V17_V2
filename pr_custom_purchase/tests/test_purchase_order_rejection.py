from odoo.tests.common import TransactionCase


class TestPurchaseOrderRejection(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create({
            "name": "Rejected PO Test Vendor",
            "supplier_rank": 1,
        })

    def _create_pending_po(self):
        return self.env["purchase.order"].create({
            "name": "PEC-PO-REJECTION-TEST",
            "partner_id": self.vendor.id,
            "state": "pending",
            "origin": "MISSING-RFQ-FOR-REJECTION-TEST",
            "pe_approved": True,
        })

    def test_rejection_keeps_document_as_rejected_po(self):
        order = self._create_pending_po()

        order.action_reject(reason="Commercial terms require revision.")

        self.assertEqual(order.state, "rejected")
        self.assertEqual(order.approval_status, "rejected")
        self.assertEqual(
            order.rejection_reason,
            "Commercial terms require revision.",
        )
        self.assertTrue(
            self.env["crossovered.budget"]._budget_order_is_po(order)
        )

    def test_reset_rejected_po_clears_reason_and_approvals(self):
        order = self._create_pending_po()
        order.action_reject(reason="Please revise the quotation.")

        order.action_reset_to_draft()

        self.assertEqual(order.state, "draft")
        self.assertFalse(order.rejection_reason)
        self.assertFalse(order.pe_approved)
        self.assertFalse(order.pm_approved)
        self.assertFalse(order.od_approved)
        self.assertFalse(order.md_approved)
