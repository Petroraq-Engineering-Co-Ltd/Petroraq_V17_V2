# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ProductSupplierInfo(models.Model):
    _inherit = "product.supplierinfo"

    pr_vendor_category_id = fields.Many2one(
        "pr.vendor.category",
        string="Vendor Category",
        related="partner_id.pr_vendor_category_id",
        store=True,
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._pr_mark_partners_as_vendors()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "partner_id" in vals:
            self._pr_mark_partners_as_vendors()
        return res

    def _pr_mark_partners_as_vendors(self):
        partners = self.mapped("partner_id").filtered(lambda partner: partner.supplier_rank <= 0)
        if partners:
            partners.write({"supplier_rank": 1})
