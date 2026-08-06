# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import ValidationError


class EmployeeTaskReturnWizard(models.TransientModel):
    _name = 'employee.task.return.wizard'
    _description = 'Return Task List Wizard'

    task_list_id = fields.Many2one(
        'employee.task.list', string='Task List', required=True)
    return_reason = fields.Text(
        string='Return Reason', required=True,
        help='Return remarks are mandatory when a manager returns a '
             'task list (Validation Rule 7).')

    def action_confirm_return(self):
        """Send the task list back to the employee for correction.

        Only reachable from "Submitted to Manager" (TDD 6.3): the manager
        reviewed the plan and wants it changed before any work starts.
        A COMPLETED task list is no longer returned - the manager either
        Closes it or Rejects it.
        """
        self.ensure_one()
        task = self.task_list_id
        if not self.return_reason or not self.return_reason.strip():
            raise ValidationError(_(
                'Return remarks are mandatory when returning a task list.'))
        if task.state != 'submitted_manager':
            raise ValidationError(_(
                'Only a task list in "Submitted to Manager" status can be '
                'returned for correction.'))
        task._set_state('returned_manager', {
            'return_reason': self.return_reason,
            'manager_remarks': (
                (task.manager_remarks + '\n') if task.manager_remarks else ''
            ) + self.return_reason,
        })
        task._log_approval_history('returned', self.return_reason)
        task.activity_feedback(['mail.mail_activity_data_todo'])
        task._notify_user(
            task._get_employee_partner(),
            _('Task List Returned for Correction'),
            _('Your task list %s has been returned by your manager. '
              'Please review the remarks, make corrections and resubmit.'
              '\n\nReturn Reason: %s', task.name, self.return_reason),
            'employee_task_management.mail_template_task_returned')
        task._notify_user(
            task._get_manager_partner(),
            _('Task List Returned for Correction'),
            _('Task list %s has been returned to %s for correction.',
              task.name, task.employee_id.name))
        return {'type': 'ir.actions.act_window_close'}
