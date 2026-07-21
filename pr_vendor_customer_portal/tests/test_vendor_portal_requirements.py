# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase


class TestVendorPortalRequirements(TransactionCase):

    def test_purchase_quotation_model_is_registered_for_rfq_portal(self):
        self.assertIn("purchase.quotation", self.env.registry.models)

    def test_delivery_status_labels_cover_requested_workflow(self):
        status = self.env["stock.picking"]._pr_portal_delivery_status_from_quantities
        self.assertEqual(status("assigned", 10.0, 0.0), "pending")
        self.assertEqual(status("assigned", 10.0, 4.0), "partial")
        self.assertEqual(status("done", 10.0, 10.0), "received")
        self.assertEqual(status("cancel", 10.0, 0.0), "cancel")

    def test_po_portal_documents_only_include_vendor_safe_attachments(self):
        vendor = self.env["res.partner"].create({
            "name": "Portal Requirements Vendor",
            "supplier_rank": 1,
        })
        order = self.env["purchase.order"].create({"partner_id": vendor.id})
        base_values = {
            "type": "binary",
            "datas": "JVBERi0xLjQK",
            "res_model": order._name,
            "res_id": order.id,
        }
        internal = self.env["ir.attachment"].create({
            **base_values,
            "name": "internal.pdf",
        })
        petroraq_shared = self.env["ir.attachment"].create({
            **base_values,
            "name": "po-acceptance.pdf",
            "pr_vendor_portal_visible": True,
            "pr_vendor_portal_document_type": "po_acceptance",
        })
        vendor_upload = self.env["ir.attachment"].create({
            **base_values,
            "name": "vendor-invoice.pdf",
            "pr_vendor_portal_upload": True,
            "pr_vendor_portal_document_type": "invoice",
        })

        order._compute_pr_vendor_portal_attachment_ids()

        self.assertEqual(
            set(order.pr_vendor_portal_attachment_ids.ids),
            {petroraq_shared.id, vendor_upload.id},
        )
        self.assertNotIn(internal, order.pr_vendor_portal_attachment_ids)
