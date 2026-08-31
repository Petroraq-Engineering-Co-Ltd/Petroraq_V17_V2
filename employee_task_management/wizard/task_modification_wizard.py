# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import ValidationError


class EmployeeTaskModificationWizard(models.TransientModel):
    _name = 'employee.task.modification.wizard'
    _description = 'Request Modification Wizard'

    task_list_id = fields.Many2one(
        'employee.task.list', string='Task List', required=True)
    modification_reason = fields.Text(
        string='What needs to be modified?', required=True,
        help='Explain what has to change - dates, hours, scope - so the '
             'manager can adjust the task list.')

    def action_confirm_request(self):
        """QA point 18: the employee asks his manager to modify an
        assigned task list instead of accepting it as it is. QA point 23:
        if the manager does not act within one working day, the task
        list becomes applicable automatically (handled by the cron)."""
        self.ensure_one()
        task = self.task_list_id
        if not self.modification_reason or not self.modification_reason.strip():
            raise ValidationError(_(
                'Please describe the modification you are requesting.'))
        task._check_is_the_employee()
        task._set_state('modification_requested', {
            'modification_reason': self.modification_reason,
        })
        task._log_approval_history(
            'modification_requested', self.modification_reason)
        task._notify_user(
            task._get_manager_partner(),
            _('Modification Requested on Task List'),
            _('Employee %s has requested a modification on task list %s.'
              '\n\nRequest: %s\n\nIf this request is not handled before '
              'the task start date, the task list will be assigned to the '
              'employee automatically.',
              task.employee_id.sudo().name, task.name, self.modification_reason),
            'employee_task_management.mail_template_task_modification_request')
        task._notify_user(
            task._get_employee_partner(),
            _('Modification Request Sent'),
            _('Your modification request on task list %s has been sent to '
              '%s.', task.name, task.manager_id.sudo().name))
        return {'type': 'ir.actions.act_window_close'}
