from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    zatca_warning_owner_id = fields.Many2one(
        "res.users",
        string="Default ZATCA Warning Owner",
        help="User assigned to new ZATCA warning cases for this company.",
    )


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    zatca_warning_owner_id = fields.Many2one(
        related="company_id.zatca_warning_owner_id",
        readonly=False,
    )
