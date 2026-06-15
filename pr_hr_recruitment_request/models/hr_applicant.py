from odoo import fields, models


class Applicant(models.Model):
    _inherit = 'hr.applicant'

    partner_location = fields.Char(string='Location')
    will_relocate = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Willing to Relocate')
    notice_period = fields.Char(string='Notice Period')
    legally_required = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Has National ID / Iqama')
    national_id_iqama = fields.Char(string='National ID / Iqama Number')
    availability = fields.Char(string='Joining Availability')
    experience = fields.Char(string='Experience In Years')
    nationality_id = fields.Many2one('res.country', string='Nationality')


