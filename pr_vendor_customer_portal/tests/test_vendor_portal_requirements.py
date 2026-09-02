# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestVendorPortalRequirements(TransactionCase):

    def test_cr_number_accepts_only_exactly_ten_digits(self):
        partner = self.env["res.partner"].create({
            "name": "Valid CR Vendor",
            "company_registry": "1234567890",
        })
        self.assertEqual(partner.company_registry, "1234567890")
        with self.assertRaises(ValidationError):
            partner.company_registry = "12345ABC90"
        with self.assertRaises(ValidationError):
            partner.company_registry = "123456789"

    def test_vendor_invoice_is_linked_to_one_receipt_and_payment_slips_exist(self):
        invoice_fields = self.env["pr.portal.vendor.invoice"]._fields
        self.assertIn("picking_id", invoice_fields)
        self.assertIn("service_receipt_id", invoice_fields)
        self.assertIn("grn_ses_id", invoice_fields)
        self.assertIn("pr_payment_slip_ids", self.env["account.move"]._fields)
        constraint_names = {
            constraint[0]
            for constraint in self.env["pr.portal.vendor.invoice"]._sql_constraints
        }
        self.assertTrue({
            "unique_portal_goods_receipt",
            "unique_portal_service_receipt",
            "unique_portal_legacy_receipt",
        }.issubset(constraint_names))

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
