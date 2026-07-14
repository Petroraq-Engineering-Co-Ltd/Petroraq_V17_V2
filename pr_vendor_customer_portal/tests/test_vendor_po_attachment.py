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
            "pr_vendor_portal_document_type": "invoice",
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

    def test_portal_dn_ses_attachments_are_counted_separately(self):
        vendor = self.env["res.partner"].create({
            "name": "Portal Document Test Vendor",
            "supplier_rank": 1,
        })
        order = self.env["purchase.order"].create({
            "partner_id": vendor.id,
        })
        invoice = self.env["ir.attachment"].create({
            "name": "INV-TEST-002.pdf",
            "type": "binary",
            "datas": "JVBERi0xLjQK",
            "mimetype": "application/pdf",
            "res_model": order._name,
            "res_id": order.id,
            "pr_vendor_portal_upload": True,
            "pr_vendor_portal_document_type": "invoice",
            "pr_vendor_id": vendor.id,
            "pr_vendor_invoice_number": "INV-TEST-002",
            "pr_vendor_invoice_date": date(2026, 6, 28),
            "pr_vendor_invoice_amount": 1000.0,
            "pr_vendor_invoice_currency_id": order.currency_id.id,
        })
        delivery_note = self.env["ir.attachment"].create({
            "name": "DN-TEST-001.pdf",
            "type": "binary",
            "datas": "JVBERi0xLjQK",
            "mimetype": "application/pdf",
            "res_model": order._name,
            "res_id": order.id,
            "pr_vendor_portal_upload": True,
            "pr_vendor_portal_document_type": "delivery_note",
            "pr_vendor_id": vendor.id,
            "pr_vendor_document_number": "DN-TEST-001",
            "pr_vendor_document_date": date(2026, 6, 29),
        })
        ses = self.env["ir.attachment"].create({
            "name": "SES-TEST-001.pdf",
            "type": "binary",
            "datas": "JVBERi0xLjQK",
            "mimetype": "application/pdf",
            "res_model": order._name,
            "res_id": order.id,
            "pr_vendor_portal_upload": True,
            "pr_vendor_portal_document_type": "ses",
            "pr_vendor_id": vendor.id,
            "pr_vendor_document_number": "SES-TEST-001",
            "pr_vendor_document_date": date(2026, 6, 30),
        })

        order._compute_pr_vendor_portal_invoice_count()
        order._compute_pr_vendor_portal_document_count()
        self.assertEqual(order.pr_vendor_portal_invoice_count, 1)
        self.assertEqual(order.pr_vendor_portal_document_count, 2)

        invoice_action = order.action_open_pr_vendor_portal_invoices()
        matching_invoices = self.env["ir.attachment"].search(invoice_action["domain"])
        self.assertEqual(matching_invoices, invoice)

        document_action = order.action_open_pr_vendor_portal_documents()
        matching_documents = self.env["ir.attachment"].search(document_action["domain"])
        self.assertEqual(set(matching_documents.ids), set((delivery_note | ses).ids))
