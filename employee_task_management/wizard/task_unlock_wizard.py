# -*- coding: utf-8 -*-
from odoo import models, fields, _


class EmployeeTaskUnlockWizard(models.TransientModel):
    _name = 'employee.task.unlock.wizard'
    _description = 'Unlock Closed Task List Wizard'

    task_list_id = fields.Many2one(
        'employee.task.list', string='Task List', required=True)
    unlock_reason = fields.Text(string='Unlock Reason', required=True)

    def action_confirm_unlock(self):
        """Move a closed task list back to Completed so a manager/admin can
        make exceptional edits (TDD Validation Rule 9 note)."""
        self.ensure_one()
        task = self.task_list_id
        task.with_context(bypass_closed_lock=True)._set_state(
            'completed', {'is_unlocked': True})
        task.task_line_ids.filtered(
            lambda l: l.task_status == 'closed').with_context(
            etm_workflow=True).write({'task_status': 'completed'})
        task._log_approval_history('unlocked', self.unlock_reason)
        task.message_post(body=_(
            'Task list unlocked for exceptional editing by %s. Reason: %s',
            self.env.user.name, self.unlock_reason))
        return {'type': 'ir.actions.act_window_close'}
