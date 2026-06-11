# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class ResPartner(models.Model):
    _inherit = "res.partner"

    pr_vendor_category_id = fields.Many2one(
        "pr.vendor.category",
        string="Primary Vendor Category",
        tracking=True,
        help="Main business nature of this vendor, such as manufacturer, wholesaler, distributor, or service provider.",
    )
    pr_vendor_category_ids = fields.Many2many(
        "pr.vendor.category",
        "res_partner_pr_vendor_category_rel",
        "partner_id",
        "category_id",
        string="Additional Vendor Categories",
        help="Additional business categories when the vendor operates in more than one role.",
    )
    pr_supplierinfo_ids = fields.One2many(
        "product.supplierinfo",
        "partner_id",
        string="Provided Products",
    )
    pr_supplied_product_count = fields.Integer(
        string="Provided Products",
        compute="_compute_pr_vendor_procurement_counts",
    )
    pr_purchase_line_count = fields.Integer(
        string="Purchased Lines",
        compute="_compute_pr_vendor_procurement_counts",
    )

    @api.depends("pr_supplierinfo_ids", "purchase_order_count")
    def _compute_pr_vendor_procurement_counts(self):
        SupplierInfo = self.env["product.supplierinfo"].sudo()
        PurchaseLine = self.env["purchase.order.line"].sudo()
        for partner in self:
            commercial_partner = partner.commercial_partner_id
            if not isinstance(commercial_partner.id, int):
                partner.pr_supplied_product_count = 0
                partner.pr_purchase_line_count = 0
                continue

            vendor_domain = [("partner_id", "child_of", commercial_partner.id)]
            purchase_line_domain = [
                ("order_id.partner_id", "child_of", commercial_partner.id),
                ("order_id.state", "in", ["purchase", "done"]),
                ("display_type", "=", False),
            ]
            partner.pr_supplied_product_count = SupplierInfo.search_count(vendor_domain)
            partner.pr_purchase_line_count = PurchaseLine.search_count(purchase_line_domain)

    def action_pr_open_supplierinfo(self):
        self.ensure_one()
        commercial_partner = self.commercial_partner_id
        action = self.env.ref("product.product_supplierinfo_type_action").read()[0]
        action.update({
            "name": _("Provided Products"),
            "domain": [("partner_id", "child_of", commercial_partner.id)],
            "context": {
                "default_partner_id": commercial_partner.id,
                "visible_product_tmpl_id": False,
                "search_default_active_products": True,
            },
        })
        return action

    def action_pr_open_purchase_history_lines(self):
        self.ensure_one()
        commercial_partner = self.commercial_partner_id
        return {
            "type": "ir.actions.act_window",
            "name": _("Purchase History"),
            "res_model": "purchase.order.line",
            "view_mode": "tree,form",
            "domain": [
                ("order_id.partner_id", "child_of", commercial_partner.id),
                ("order_id.state", "in", ["purchase", "done"]),
                ("display_type", "=", False),
            ],
            "context": {
                "search_default_order_id": 1,
                "create": False,
            },
            "target": "current",
        }
