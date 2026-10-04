import base64
import unittest

from odoo.tests.common import TransactionCase


class TestPurchaseAdvancePaymentAttachments(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create({
            "name": "PO Advance Attachment Test Vendor",
            "supplier_rank": 1,
        })
        cls.order = cls.env["purchase.order"].create({
            "partner_id": cls.vendor.id,
        })
        cls.journal = cls.env["account.journal"].search([
            ("type", "in", ("bank", "cash")),
            ("company_id", "=", cls.env.company.id),
        ], limit=1)
        if not cls.journal:
            raise unittest.SkipTest("No bank/cash journal available for advance payment attachment tests.")

    def _create_payment(self):
        values = {
            "payment_type": "outbound",
            "partner_type": "supplier",
            "partner_id": self.vendor.id,
            "amount": 100.0,
            "journal_id": self.journal.id,
            "date": "2026-10-04",
            "purchase_order_id": self.order.id,
        }
        method_lines = self.journal.outbound_payment_method_line_ids
        if method_lines:
            values["payment_method_line_id"] = method_lines[0].id
        return self.env["account.payment"].create(values)

    def test_multiple_wizard_attachments_are_moved_to_payment_chatter(self):
        wizard = self.env["purchase.order.advance.payment.wizard"].create({
            "purchase_order_id": self.order.id,
            "amount": 100.0,
            "percentage": 100.0,
            "payment_date": "2026-10-04",
        })
        attachments = self.env["ir.attachment"]
        for filename in ("advance-request.pdf", "vendor-quotation.pdf"):
            attachments |= self.env["ir.attachment"].create({
                "name": filename,
                "type": "binary",
                "datas": base64.b64encode(filename.encode()),
                "mimetype": "application/pdf",
                "res_model": wizard._name,
                "res_id": wizard.id,
            })
        wizard.write({
            "attachment_ids": [(6, 0, attachments.ids)],
        })
        payment = self._create_payment()

        transferred = wizard._transfer_attachments_to_payment(payment)
        payment.message_post(
            body="Advance payment attachment test",
            attachment_ids=transferred.ids,
        )

        self.assertEqual(set(transferred.ids), set(attachments.ids))
        self.assertEqual(set(transferred.mapped("res_model")), {"account.payment"})
        self.assertEqual(set(transferred.mapped("res_id")), {payment.id})
        self.assertEqual(
            set(payment.message_ids.attachment_ids.ids),
            set(attachments.ids),
        )
