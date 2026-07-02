from datetime import date

from odoo.tests.common import TransactionCase


class TestVendorPortalPurchaseOrderAttachment(TransactionCase):

    def test_portal_invoice_attachment_is_counted_on_purchase_order(self):
        vendor = self.env["res.partner"].create({
            "name": "Portal Attachment Test Vendor",
            "supplier_rank": 1,
        })
        order = self.env["purchase.order"].create({
            "partner_id": vendor.id,
        })
        attachment = self.env["ir.attachment"].create({
            "name": "INV-TEST-001.pdf",
            "type": "binary",
            "datas": "JVBERi0xLjQK",
            "mimetype": "application/pdf",
            "res_model": order._name,
            "res_id": order.id,
            "pr_vendor_portal_upload": True,
            "pr_vendor_id": vendor.id,
            "pr_vendor_invoice_number": "INV-TEST-001",
            "pr_vendor_invoice_date": date(2026, 6, 28),
            "pr_vendor_invoice_amount": 1000.0,
            "pr_vendor_invoice_currency_id": order.currency_id.id,
        })

        order._compute_pr_vendor_portal_invoice_count()
        self.assertEqual(order.pr_vendor_portal_invoice_count, 1)

        action = order.action_open_pr_vendor_portal_invoices()
        matching_attachments = self.env["ir.attachment"].search(action["domain"])
        self.assertEqual(matching_attachments, attachment)
