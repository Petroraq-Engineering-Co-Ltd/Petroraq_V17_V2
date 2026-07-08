from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestPurchaseRequisitionReset(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create({
            "name": "PR Reset Test Vendor",
            "supplier_rank": 1,
        })
        cls.plan = cls.env["account.analytic.plan"].create({
            "name": "PR Reset Test Plan",
        })
        cls.cost_center = cls.env["account.analytic.account"].create({
            "name": "PR Reset Test Cost Center",
            "plan_id": cls.plan.id,
        })
        cls.product = cls.env["product.product"].create({
            "name": "PR Reset Test Product",
            "standard_price": 10.0,
        })

    def _line_commands(self):
        return [(0, 0, {
            "description": self.product.id,
            "cost_center_id": self.cost_center.id,
            "quantity": 1.0,
            "unit_price": 10.0,
        })]

    def _create_pr(self, pr_type):
        return self.env["purchase.requisition"].create({
            "name": "RESET-%s-%s" % (pr_type.upper(), self.env["ir.sequence"].next_by_code("purchase.order") or "TEST"),
            "pr_type": pr_type,
            "approval": "approved",
            "line_ids": self._line_commands(),
        })

    def _confirm_reset(self, requisition):
        action = requisition.action_reset_to_draft()
        wizard = self.env["purchase.requisition.reset.wizard"].create({
            "requisition_id": requisition.id,
            "warning_message": action["context"]["default_warning_message"],
            "confirm_reset": True,
        })
        return wizard.action_confirm_reset()

    def test_cash_pr_without_payment_request_can_reset(self):
        requisition = self._create_pr("cash")

        self._confirm_reset(requisition)

        self.assertEqual(requisition.approval, "draft")
        self.assertEqual(requisition.status, "pr")

    def test_draft_payment_request_is_deleted_on_cash_pr_reset(self):
        requisition = self._create_pr("cash")
        payment_request = self.env[
            "purchase.requisition.payment.request"
        ].create({
            "purchase_requisition_id": requisition.id,
        })

        self._confirm_reset(requisition)

        self.assertFalse(payment_request.exists())
        self.assertEqual(requisition.approval, "draft")

    def test_advanced_payment_request_blocks_cash_pr_reset(self):
        requisition = self._create_pr("cash")
        payment_request = self.env[
            "purchase.requisition.payment.request"
        ].create({
            "purchase_requisition_id": requisition.id,
        })
        payment_request.state = "voucher_created"

        with self.assertRaises(UserError):
            requisition.action_reset_to_draft()

    def test_draft_rfqs_are_deleted_on_regular_pr_reset(self):
        requisition = self._create_pr("pr")
        rfq = self.env["purchase.order"].create({
            "partner_id": self.vendor.id,
            "requisition_id": requisition.id,
        })

        self._confirm_reset(requisition)

        self.assertFalse(rfq.exists())
        self.assertEqual(requisition.approval, "draft")

    def test_non_draft_rfq_blocks_regular_pr_reset(self):
        requisition = self._create_pr("pr")
        rfq = self.env["purchase.order"].create({
            "partner_id": self.vendor.id,
            "requisition_id": requisition.id,
        })
        rfq.state = "sent"

        with self.assertRaises(UserError):
            requisition.action_reset_to_draft()
