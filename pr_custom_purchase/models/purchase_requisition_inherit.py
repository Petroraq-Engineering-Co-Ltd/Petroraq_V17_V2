from odoo import models, fields


class PurchaseRequisition(models.Model):
    _inherit = 'purchase.requisition'

    rejection_reason = fields.Text(string='Reason for Rejection')

    def write(self, vals):
        res = super().write(vals)
        if 'rejection_reason' in vals:
            for rec in self:
                custom_pr = rec.legacy_custom_pr_id or self.env['custom.pr'].sudo().search([('name', '=', rec.name)], limit=1)
                if custom_pr:
                    if not custom_pr.purchase_requisition_id:
                        custom_pr.sudo().purchase_requisition_id = rec.id
                    custom_pr.sudo().write({'rejection_reason': rec.rejection_reason})
        return res

