# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    pr_vendor_portal_invoice_count = fields.Integer(
        string="Vendor Invoices",
        compute="_compute_pr_vendor_portal_invoice_count",
    )

    @api.depends("message_ids.attachment_ids")
    def _compute_pr_vendor_portal_invoice_count(self):
        Attachment = self.env["ir.attachment"].sudo()
        for order in self:
            order.pr_vendor_portal_invoice_count = Attachment.search_count([
                ("res_model", "=", order._name),
                ("res_id", "=", order.id),
                ("pr_vendor_portal_upload", "=", True),
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
            ],
            "context": {
                "create": False,
                "delete": False,
            },
        }
