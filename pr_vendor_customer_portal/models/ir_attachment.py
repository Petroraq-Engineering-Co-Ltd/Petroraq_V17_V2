# -*- coding: utf-8 -*-

from odoo import fields, models


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    pr_vendor_portal_upload = fields.Boolean(
        string="Vendor Portal Invoice",
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
    pr_vendor_portal_user_id = fields.Many2one(
        "res.users",
        string="Uploaded By Portal User",
        copy=False,
    )
