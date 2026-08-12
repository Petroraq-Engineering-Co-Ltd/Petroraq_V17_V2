# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import ValidationError


class EmployeeTaskLineRejectWizard(models.TransientModel):
    _name = 'employee.task.line.reject.wizard'
    _description = 'Reject an Individual Task'

    task_line_id = fields.Many2one(
        'employee.task.line', string='Task', required=True, readonly=True)
    reason = fields.Text(
        string='Rejection Reason', required=True,
        help='Explain what is wrong with this task. The employee sees '
             'this when the task is carried into their next task list.')

    def action_confirm_reject(self):
        """Mark the task rejected and queue it for carry-forward.

        The task is NOT copied anywhere yet - it is copied when the
        employee next creates a task list. Until then it simply waits,
        flagged, so nothing is lost if that takes a while.
        """
        self.ensure_one()
        if not self.reason or not self.reason.strip():
            raise ValidationError(_('A rejection reason is required.'))
        line = self.task_line_id
        line._check_reviewable()
        line.with_context(etm_workflow=True).write({
            'manager_verdict': 'rejected',
            'verdict_reason': self.reason,
            'carry_forward_pending': True,
        })
        line.task_list_id.message_post(body=_(
            'Task rejected by %(user)s: %(task)s<br/>'
            'Reason: %(reason)s<br/>'
            '<i>It will be added automatically to this employee\'s next '
            'task list.</i>',
            user=self.env.user.name,
            task=(line.description or '')[:80],
            reason=self.reason))
        return {'type': 'ir.actions.act_window_close'}
