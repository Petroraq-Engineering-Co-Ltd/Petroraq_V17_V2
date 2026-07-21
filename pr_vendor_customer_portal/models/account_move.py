# -*- coding: utf-8 -*-

from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    pr_portal_amount_paid = fields.Monetary(
        string="Amount Paid",
        currency_field="currency_id",
        compute="_compute_pr_portal_payment_summary",
        compute_sudo=True,
    )
    pr_portal_payment_date = fields.Date(
        string="Payment Date",
        compute="_compute_pr_portal_payment_summary",
        compute_sudo=True,
    )

    @api.depends("amount_total", "amount_residual", "payment_state")
    def _compute_pr_portal_payment_summary(self):
        for move in self:
            accounting_move = move.sudo()
            move.pr_portal_amount_paid = max(
                accounting_move.amount_total - accounting_move.amount_residual,
                0.0,
            )
            payments = (
                accounting_move._get_reconciled_payments()
                if accounting_move.state == "posted"
                else self.env["account.payment"].sudo()
            )
            move.pr_portal_payment_date = max(payments.mapped("date"), default=False)
