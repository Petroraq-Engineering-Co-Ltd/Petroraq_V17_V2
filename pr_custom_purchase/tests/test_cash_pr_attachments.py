import base64

from odoo.tests.common import TransactionCase


class TestCashPrAttachmentFlow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.requisition = cls.env["purchase.requisition"].create({
            "name": "CASH-PR-ATTACHMENT-TEST",
            "pr_type": "cash",
        })
        cls.explicit_pr_attachment = cls.env["ir.attachment"].create({
            "name": "pr-explicit.pdf",
            "type": "binary",
            "datas": base64.b64encode(b"Explicit PR attachment"),
            "mimetype": "application/pdf",
        })
        cls.requisition.write({
            "attachment_ids": [(4, cls.explicit_pr_attachment.id)],
        })
        cls.chatter_pr_attachment = cls.env["ir.attachment"].create({
            "name": "pr-chatter.pdf",
            "type": "binary",
            "datas": base64.b64encode(b"PR chatter attachment"),
            "mimetype": "application/pdf",
            "res_model": cls.requisition._name,
            "res_id": cls.requisition.id,
        })
        cls.payment_request = cls.env[
            "purchase.requisition.payment.request"
        ].create({
            "purchase_requisition_id": cls.requisition.id,
        })

    def test_pr_and_payment_request_attachments_reach_voucher(self):
        self.payment_request._copy_attachments_from_record(self.requisition)
        self.payment_request._copy_attachments_from_record(self.requisition)

        self.assertEqual(
            set(self.payment_request.attachment_ids.mapped("name")),
            {"pr-explicit.pdf", "pr-chatter.pdf"},
        )
        self.assertEqual(len(self.payment_request.attachment_ids), 2)

        payment_request_attachment = self.env["ir.attachment"].create({
            "name": "payment-request-extra.pdf",
            "type": "binary",
            "datas": base64.b64encode(b"Payment request attachment"),
            "mimetype": "application/pdf",
        })
        self.payment_request.write({
            "attachment_ids": [(4, payment_request_attachment.id)],
        })

        voucher_target = self.env["purchase.requisition"].create({
            "name": "CASH-PR-ATTACHMENT-VOUCHER-TARGET",
            "pr_type": "cash",
        })
        self.payment_request._copy_attachments_to_record(voucher_target)

        voucher_attachments = self.env["ir.attachment"].search([
            ("res_model", "=", voucher_target._name),
            ("res_id", "=", voucher_target.id),
        ])
        self.assertEqual(
            set(voucher_attachments.mapped("name")),
            {
                "pr-explicit.pdf",
                "pr-chatter.pdf",
                "payment-request-extra.pdf",
            },
        )
