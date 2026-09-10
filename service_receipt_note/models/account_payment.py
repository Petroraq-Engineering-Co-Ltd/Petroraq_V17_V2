# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class AccountPayment(models.Model):
    _inherit = "account.payment"

    pr_related_grn_ids = fields.Many2many(
        "stock.picking",
        string="Related GRNs",
        compute="_compute_pr_related_purchase_receipts",
        compute_sudo=True,
    )
    pr_related_grn_count = fields.Integer(
        string="GRN Count",
        compute="_compute_pr_related_purchase_receipts",
        compute_sudo=True,
    )
    pr_related_srn_ids = fields.Many2many(
        "service.receipt.note",
        string="Related SRNs",
        compute="_compute_pr_related_purchase_receipts",
        compute_sudo=True,
    )
    pr_related_srn_count = fields.Integer(
        string="SRN Count",
        compute="_compute_pr_related_purchase_receipts",
        compute_sudo=True,
    )

    @api.depends(
        "pr_vendor_payment_source_line_ids.move_id.invoice_line_ids.purchase_line_id.order_id",
    )
    def _compute_pr_related_purchase_receipts(self):
        Picking = self.env["stock.picking"].sudo()
        ServiceReceipt = self.env["service.receipt.note"].sudo()
        for payment in self:
            bills = payment.pr_vendor_payment_source_line_ids.mapped("move_id").filtered(
                lambda move: move.move_type in ("in_invoice", "in_refund")
            )
            purchase_orders = bills.invoice_line_ids.mapped("purchase_line_id.order_id")
            if purchase_orders:
                grns = Picking.search([
                    ("purchase_id", "in", purchase_orders.ids),
                    ("picking_type_code", "=", "incoming"),
                    ("state", "=", "done"),
                ]).filtered(
                    lambda picking: not hasattr(picking, "_get_receipt_approval_state")
                    or picking._get_receipt_approval_state() == "approved"
                )
                srns = ServiceReceipt.search([
                    ("purchase_id", "in", purchase_orders.ids),
                    ("state", "=", "done"),
                    ("approval_state", "=", "approved"),
                ])
            else:
                grns = Picking.browse()
                srns = ServiceReceipt.browse()
            payment.pr_related_grn_ids = grns
            payment.pr_related_grn_count = len(grns)
            payment.pr_related_srn_ids = srns
            payment.pr_related_srn_count = len(srns)

    def action_open_pr_related_grns(self):
        self.ensure_one()
        action = {
            "name": _("Related GRNs"),
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "view_mode": "tree,form",
            "domain": [("id", "in", self.pr_related_grn_ids.ids)],
            "context": {"create": False},
        }
        if self.pr_related_grn_count == 1:
            action.update({"view_mode": "form", "res_id": self.pr_related_grn_ids.id})
        return action

    def action_open_pr_related_srns(self):
        self.ensure_one()
        action = {
            "name": _("Related SRNs"),
            "type": "ir.actions.act_window",
            "res_model": "service.receipt.note",
            "view_mode": "tree,form",
            "domain": [("id", "in", self.pr_related_srn_ids.ids)],
            "context": {"create": False},
        }
        if self.pr_related_srn_count == 1:
            action.update({"view_mode": "form", "res_id": self.pr_related_srn_ids.id})
        return action
