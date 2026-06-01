# -*- coding: utf-8 -*-

from odoo import fields, models


class PrVendorCategory(models.Model):
    _name = "pr.vendor.category"
    _description = "Vendor Category"
    _order = "sequence, name"

    name = fields.Char(required=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text()

    _sql_constraints = [
        ("name_unique", "unique(name)", "Vendor category name must be unique."),
    ]
