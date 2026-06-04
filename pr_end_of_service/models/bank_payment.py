from odoo import fields, models


class AccountBankPayment(models.Model):
    _inherit = "pr.account.bank.payment"

    eos_id = fields.Many2one(
        "pr.end.of.service",
        string="End of Service",
        readonly=True,
        copy=False,
        tracking=True,
    )

    def action_post(self):
        res = super().action_post()
        for payment in self:
            if payment.eos_id and payment.state == "posted":
                payment.eos_id._mark_done_from_payment(payment)
        return res
