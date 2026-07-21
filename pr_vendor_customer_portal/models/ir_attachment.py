# -*- coding: utf-8 -*-

from odoo import fields, models


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    pr_vendor_portal_upload = fields.Boolean(
        string="Vendor Portal Upload",
        index=True,
        copy=False,
    )
    pr_vendor_portal_document_type = fields.Selection(
        [
            ("po_acceptance", "PO Acceptance"),
            ("gdn", "Goods Delivery Note"),
            ("invoice", "Vendor Invoice"),
            ("delivery_note", "Delivery Note"),
            ("ses", "Service Entry Sheet"),
        ],
        string="Vendor Portal Document Type",
        index=True,
        copy=False,
    )
    pr_vendor_portal_visible = fields.Boolean(
        string="Visible in Vendor Portal",
        help="Expose this attachment to the vendor on the related portal document.",
        index=True,
        copy=False,
    )
    pr_vendor_id = fields.Many2one(
        "res.partner",
        string="Vendor",
        index=True,
        copy=False,
    )
    pr_vendor_invoice_number = fields.Char(
        string="Vendor Invoice Number",
        index=True,
        copy=False,
    )
    pr_vendor_invoice_date = fields.Date(
        string="Vendor Invoice Date",
        copy=False,
    )
    pr_vendor_invoice_amount = fields.Monetary(
        string="Vendor Invoice Amount",
        currency_field="pr_vendor_invoice_currency_id",
        copy=False,
    )
    pr_vendor_invoice_currency_id = fields.Many2one(
        "res.currency",
        string="Vendor Invoice Currency",
        copy=False,
    )
    pr_vendor_document_number = fields.Char(
        string="Vendor Document Number",
        index=True,
        copy=False,
    )
    pr_vendor_document_date = fields.Date(
        string="Vendor Document Date",
        copy=False,
    )
    pr_vendor_portal_user_id = fields.Many2one(
        "res.users",
        string="Uploaded By Portal User",
        copy=False,
    )
