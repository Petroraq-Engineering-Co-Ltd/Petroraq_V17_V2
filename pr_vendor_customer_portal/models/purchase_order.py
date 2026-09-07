# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    pr_vendor_portal_invoice_count = fields.Integer(
        string="Vendor Invoices",
        compute="_compute_pr_vendor_portal_invoice_count",
    )
    pr_vendor_portal_document_count = fields.Integer(
        string="Vendor Documents",
        compute="_compute_pr_vendor_portal_document_count",
    )
    pr_vendor_portal_attachment_ids = fields.Many2many(
        "ir.attachment",
        string="Vendor Portal Documents",
        compute="_compute_pr_vendor_portal_attachment_ids",
    )
    pr_vendor_has_invoiceable_receipt = fields.Boolean(
        string="Has Approved GRN/SES Available for Invoicing",
        compute="_compute_pr_vendor_has_invoiceable_receipt",
    )

    def _compute_pr_vendor_has_invoiceable_receipt(self):
        """Allow a portal invoice only for an approved, unused GRN/SES."""
        Invoice = self.env["pr.portal.vendor.invoice"].sudo()
        Picking = self.env["stock.picking"].sudo()
        ServiceReceipt = self.env["service.receipt.note"].sudo()
        LegacyReceipt = self.env["grn.ses"].sudo()

        for order in self:
            used_picking_ids = Invoice.search([
                ("po_id", "=", order.id),
                ("picking_id", "!=", False),
            ]).mapped("picking_id").ids
            goods_receipts = Picking.search([
                ("purchase_id", "=", order.id),
                ("picking_type_id.code", "=", "incoming"),
                ("state", "=", "done"),
                ("id", "not in", used_picking_ids),
            ])
            has_goods_receipt = any(
                receipt._get_receipt_approval_state() == "approved"
                for receipt in goods_receipts
            )

            used_service_ids = Invoice.search([
                ("po_id", "=", order.id),
                ("service_receipt_id", "!=", False),
            ]).mapped("service_receipt_id").ids
            has_service_receipt = bool(ServiceReceipt.search_count([
                ("purchase_id", "=", order.id),
                ("state", "=", "done"),
                ("approval_state", "=", "approved"),
                ("id", "not in", used_service_ids),
            ]))

            used_legacy_ids = Invoice.search([
                ("po_id", "=", order.id),
                ("grn_ses_id", "!=", False),
            ]).mapped("grn_ses_id").ids
            has_legacy_receipt = bool(LegacyReceipt.search_count([
                ("purchase_order_id", "=", order.id),
                ("stage", "=", "approved"),
                ("is_approved", "=", True),
                ("id", "not in", used_legacy_ids),
            ]))

            order.pr_vendor_has_invoiceable_receipt = (
                has_goods_receipt or has_service_receipt or has_legacy_receipt
            )

    def _compute_pr_vendor_portal_attachment_ids(self):
        Attachment = self.env["ir.attachment"].sudo()
        for order in self:
            order.pr_vendor_portal_attachment_ids = Attachment.search([
                ("res_model", "=", order._name),
                ("res_id", "=", order.id),
                ("res_field", "=", False),
            ])

    @api.depends("message_ids.attachment_ids")
    def _compute_pr_vendor_portal_invoice_count(self):
        Attachment = self.env["ir.attachment"].sudo()
        for order in self:
            order.pr_vendor_portal_invoice_count = Attachment.search_count([
                ("res_model", "=", order._name),
                ("res_id", "=", order.id),
                ("pr_vendor_portal_upload", "=", True),
                "|",
                ("pr_vendor_portal_document_type", "=", False),
                ("pr_vendor_portal_document_type", "=", "invoice"),
            ])

    @api.depends("message_ids.attachment_ids")
    def _compute_pr_vendor_portal_document_count(self):
        Attachment = self.env["ir.attachment"].sudo()
        for order in self:
            order.pr_vendor_portal_document_count = Attachment.search_count([
                ("res_model", "=", order._name),
                ("res_id", "=", order.id),
                ("pr_vendor_portal_upload", "=", True),
                ("pr_vendor_portal_document_type", "in", ("po_acceptance", "gdn", "delivery_note", "ses")),
            ])

    def action_open_pr_vendor_portal_invoices(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Vendor Invoices - %s", self.name),
            "res_model": "ir.attachment",
            "view_mode": "tree,form",
            "views": [
                (
                    self.env.ref(
                        "pr_vendor_customer_portal.view_pr_po_vendor_invoice_attachment_tree"
                    ).id,
                    "tree",
                ),
                (False, "form"),
            ],
            "domain": [
                ("res_model", "=", self._name),
                ("res_id", "=", self.id),
                ("pr_vendor_portal_upload", "=", True),
                "|",
                ("pr_vendor_portal_document_type", "=", False),
                ("pr_vendor_portal_document_type", "=", "invoice"),
            ],
            "context": {
                "create": False,
                "delete": False,
            },
        }

    def action_open_pr_vendor_portal_documents(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Vendor Documents - %s", self.name),
            "res_model": "ir.attachment",
            "view_mode": "tree,form",
            "views": [
                (
                    self.env.ref(
                        "pr_vendor_customer_portal.view_pr_po_vendor_document_attachment_tree"
                    ).id,
                    "tree",
                ),
                (False, "form"),
            ],
            "domain": [
                ("res_model", "=", self._name),
                ("res_id", "=", self.id),
                ("pr_vendor_portal_upload", "=", True),
                ("pr_vendor_portal_document_type", "in", ("po_acceptance", "gdn", "delivery_note", "ses")),
            ],
            "context": {
                "create": False,
                "delete": False,
            },
        }
