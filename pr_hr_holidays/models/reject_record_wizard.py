from odoo import _
from odoo.exceptions import UserError
from odoo import models


class PrRejectRecordWizard(models.TransientModel):
    _inherit = 'pr.reject.record.wizard'

    def action_reject(self):
        self.ensure_one()
        record = self.record_id
        rejection_stage = self.env.context.get('pr_leave_rejection_stage')
        if record and record._name == 'pr.hr.leave.request' and rejection_stage:
            if rejection_stage not in ('manager', 'hr_supervisor', 'hr_manager'):
                raise UserError(_('Invalid leave-request rejection stage.'))
            record._apply_stage_rejection(rejection_stage, self.reject_reason)
            return {
                'effect': {
                    'fadeout': 'slow',
                    'message': _('Rejected Successfully'),
                    'type': 'rainbow_man',
                }
            }
        return super().action_reject()
