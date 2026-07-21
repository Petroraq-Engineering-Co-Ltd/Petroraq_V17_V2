# -*- coding: utf-8 -*-

from odoo import api, fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    pr_portal_delivered_quantity = fields.Float(
        string="Delivered Quantity",
        compute="_compute_pr_portal_delivery_summary",
    )
    pr_portal_pending_quantity = fields.Float(
        string="Pending Quantity",
        compute="_compute_pr_portal_delivery_summary",
    )
    pr_portal_delivery_status = fields.Selection(
        [
            ("pending", "Pending"),
            ("partial", "Partially Received"),
            ("received", "Received"),
            ("cancel", "Cancelled"),
        ],
        string="Delivery Status",
        compute="_compute_pr_portal_delivery_summary",
    )
    pr_vendor_portal_attachment_ids = fields.Many2many(
        "ir.attachment",
        string="Vendor Portal Documents",
        compute="_compute_pr_vendor_portal_attachment_ids",
    )

    def _compute_pr_vendor_portal_attachment_ids(self):
        Attachment = self.env["ir.attachment"].sudo()
        for picking in self:
            picking.pr_vendor_portal_attachment_ids = Attachment.search([
                ("res_model", "=", picking._name),
                ("res_id", "=", picking.id),
                "|",
                ("pr_vendor_portal_upload", "=", True),
                ("pr_vendor_portal_visible", "=", True),
            ])

    @api.model
    def _pr_portal_delivery_status_from_quantities(self, state, demanded, delivered):
        if state == "cancel":
            return "cancel"
        if state == "done" or (demanded and delivered >= demanded):
            return "received"
        if delivered:
            return "partial"
        return "pending"

    @api.depends("state", "move_ids_without_package.product_uom_qty", "move_ids_without_package.quantity")
    def _compute_pr_portal_delivery_summary(self):
        for picking in self:
            demanded = sum(picking.move_ids_without_package.mapped("product_uom_qty"))
            delivered = sum(picking.move_ids_without_package.mapped("quantity"))
            picking.pr_portal_delivered_quantity = delivered
            picking.pr_portal_pending_quantity = max(demanded - delivered, 0.0)
            picking.pr_portal_delivery_status = picking._pr_portal_delivery_status_from_quantities(
                picking.state, demanded, delivered
            )
