from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pr_eos_expense_account_id = fields.Many2one(
        "account.account",
        string="EOS Expense Account",
        config_parameter="pr_end_of_service.expense_account_id",
        domain="[('deprecated', '=', False)]",
    )
    pr_eos_payment_account_id = fields.Many2one(
        "account.account",
        string="EOS Payment Account",
        config_parameter="pr_end_of_service.payment_account_id",
        domain="[('deprecated', '=', False)]",
        help="Credit account used on the generated Petroraq bank payment voucher.",
    )
