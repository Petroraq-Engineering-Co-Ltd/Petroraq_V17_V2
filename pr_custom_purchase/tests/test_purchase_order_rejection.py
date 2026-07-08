from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError


class TestPurchaseOrderRejection(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create({
            "name": "Rejected PO Test Vendor",
            "supplier_rank": 1,
        })
        cls.uom = cls.env.ref("uom.product_uom_unit")
        cls.product = cls.env["product.product"].create({
            "name": "Rejected PO Test Service",
            "detailed_type": "service",
            "uom_id": cls.uom.id,
            "uom_po_id": cls.uom.id,
            "standard_price": 5000.0,
        })

    def _create_pending_po(self):
        return self.env["purchase.order"].create({
            "name": "PEC-PO-REJECTION-TEST",
            "partner_id": self.vendor.id,
            "state": "pending",
            "origin": "MISSING-RFQ-FOR-REJECTION-TEST",
            "pe_approved": True,
            "order_line": [(0, 0, {
                "product_id": self.product.id,
                "name": self.product.display_name,
                "product_qty": 1.0,
                "product_uom": self.product.uom_po_id.id,
                "price_unit": 5000.0,
                "date_planned": "2026-07-07 00:00:00",
            })],
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

    def test_reset_then_confirm_resubmits_for_approval(self):
        order = self._create_pending_po()
        order.action_reject(reason="Please revise the quotation.")
        order.action_reset_to_draft()

        order.button_confirm()

        self.assertEqual(order.state, "pending")
        self.assertEqual(order.approval_status, "pending_pe")
        self.assertFalse(order.pe_approved)
        self.assertFalse(order.pm_approved)
        self.assertFalse(order.od_approved)
        self.assertFalse(order.md_approved)

    def test_submit_button_moves_draft_po_to_pending_approval(self):
        order = self._create_pending_po()
        order.action_reject(reason="Please revise the quotation.")
        order.action_reset_to_draft()

        order.action_submit_for_approval()

        self.assertEqual(order.state, "pending")
        self.assertEqual(order.approval_status, "pending_pe")
        self.assertFalse(order.pe_approved)
        self.assertFalse(order.rejection_reason)

    def test_rfq_cannot_be_submitted_for_po_approval(self):
        rfq = self.env["purchase.order"].create({
            "name": "PEC-RFQ-SUBMIT-GUARD-TEST",
            "partner_id": self.vendor.id,
            "state": "draft",
            "order_line": [(0, 0, {
                "product_id": self.product.id,
                "name": self.product.display_name,
                "product_qty": 1.0,
                "product_uom": self.product.uom_po_id.id,
                "price_unit": 5000.0,
                "date_planned": "2026-07-07 00:00:00",
            })],
        })

        with self.assertRaises(UserError):
            rfq.action_submit_for_approval()

    def test_fully_approved_pending_order_uses_native_confirmation(self):
        order = self._create_pending_po()

        order.button_confirm()

        self.assertEqual(order.state, "done")
        self.assertEqual(order.approval_status, "approved")
