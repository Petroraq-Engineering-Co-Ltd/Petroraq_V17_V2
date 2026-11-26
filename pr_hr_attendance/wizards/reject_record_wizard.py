from odoo import _, models
from odoo.exceptions import UserError


class PrRejectRecordWizard(models.TransientModel):
    _inherit = 'pr.reject.record.wizard'

    def action_reject(self):
        self.ensure_one()
        record = self.record_id
        if not record or record._name != 'pr.hr.shortage.request':
            return super().action_reject()
        stage = self.env.context.get('pr_shortage_rejection_stage')
        if stage not in ('manager', 'hr_supervisor', 'hr_manager', 'md'):
            raise UserError(_('Invalid shortage-request rejection stage.'))
        record._apply_stage_rejection(stage, self.reject_reason)
        return {
            'effect': {
                'fadeout': 'slow',
                'message': _('Rejected Successfully'),
                'type': 'rainbow_man',
            }
        }
