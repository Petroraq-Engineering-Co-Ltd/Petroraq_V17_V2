from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestSaleConfirmationApproval(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Confirmation Test Customer"})
        cls.product = cls.env["product.product"].create({
            "name": "Confirmation Test Product",
            "type": "consu",
            "list_price": 100.0,
        })
        cls.approver_group = cls.env.ref(
            "petroraq_sale_workflow.group_sale_confirmation_approver"
        )
        cls.approver_group.write({"users": [(4, cls.env.user.id)]})

    def _create_order(self, with_attachment=True):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "approval_state": "approved",
            "po_number": "PO-TEST-001",
            "po_date": date(2099, 1, 1),
            "order_line": [(0, 0, {
                "product_id": self.product.id,
                "product_uom_qty": 1.0,
                "price_unit": 100.0,
            })],
        })
        if with_attachment:
            attachment = self.env["ir.attachment"].create({
                "name": "customer-po.pdf",
                "type": "binary",
                "datas": "VGVzdCBDdXN0b21lciBQTw==",
                "res_model": "sale.order",
                "res_id": order.id,
            })
            order.customer_po_attachment_ids = [(6, 0, attachment.ids)]
        return order

    def test_request_keeps_quotation_approval_and_waits_for_confirmation(self):
        order = self._create_order()
        order.action_request_confirmation_approval()
        self.assertEqual(order.approval_state, "approved")
        self.assertEqual(order.confirmation_approval_state, "pending")
        self.assertEqual(order.confirmation_requested_by_id, self.env.user)

    def test_po_attachment_is_mandatory(self):
        order = self._create_order(with_attachment=False)
        with self.assertRaises(ValidationError):
            order.action_request_confirmation_approval()

    def test_direct_confirmation_is_blocked_before_second_approval(self):
        order = self._create_order()
        with self.assertRaises(UserError):
            order.action_confirm()

    def test_approval_then_po_change_resets_confirmation_approval(self):
        order = self._create_order()
        order.action_request_confirmation_approval()
        order.action_approve_confirmation()
        self.assertEqual(order.confirmation_approval_state, "approved")

        order.po_number = "PO-TEST-CHANGED"
        self.assertEqual(order.confirmation_approval_state, "not_requested")
        self.assertFalse(order.confirmation_approved_by_id)

