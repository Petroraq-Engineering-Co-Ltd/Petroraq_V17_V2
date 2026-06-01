# -*- coding: utf-8 -*-

from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    pr_vendor_category_id = fields.Many2one(
        "pr.vendor.category",
        string="Vendor Category",
        related="partner_id.pr_vendor_category_id",
        store=True,
        readonly=True,
    )


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    pr_vendor_category_id = fields.Many2one(
        "pr.vendor.category",
        string="Vendor Category",
        related="order_id.pr_vendor_category_id",
        store=True,
        readonly=True,
    )
