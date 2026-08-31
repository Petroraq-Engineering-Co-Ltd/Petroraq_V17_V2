# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import ValidationError


class EmployeeTaskRejectWizard(models.TransientModel):
    _name = 'employee.task.reject.wizard'
    _description = 'Reject Task List Wizard'

    task_list_id = fields.Many2one(
        'employee.task.list', string='Task List', required=True)
    reject_reason = fields.Text(
        string='Reject Reason', required=True,
        help='Mandatory. Explains to the employee why the completed work '
             'was not accepted.')

    def action_confirm_reject(self):
        """The manager refuses the completed work. The task list ends in
        the Rejected status - it is final, it does not go back to the
        employee and it cannot be reopened."""
        self.ensure_one()
        task = self.task_list_id
        if not self.reject_reason or not self.reject_reason.strip():
            raise ValidationError(_(
                'A reject reason is mandatory when rejecting a task list.'))
        # A list that started on its own start date can also be
        # rejected while still running - that is the manager's only
        # chance to refuse work he never approved in the first place.
        running_review = (
            task.state == 'in_progress' and task.started_without_approval)
        if task.state != 'completed' and not running_review:
            raise ValidationError(_(
                'Only a task list marked as Completed - or one that '
                'started without approval - can be rejected.'))
        task._check_approver_rights()
        task._set_state('rejected', {
            'reject_reason': self.reject_reason,
            'is_unlocked': False,
        })
        # Work already done is NOT wiped. Activities keep their done
        # ticks and the progress figures stand; the list simply ends in
        # Rejected so the record of what was actually worked survives.
        task.task_line_ids.with_context(etm_workflow=True).write(
            {'task_status': 'closed'})
        # Cascade the verdict down, exactly as rejecting a single TASK
        # already cascades to its activities. Without this the hours
        # would stay in the Pending column on a list the manager has
        # plainly refused, and the Rejected column would read zero.
        task.task_line_ids.subtask_ids.with_context(
            etm_workflow=True).write({
                'manager_verdict': 'rejected',
                'verdict_reason': self.reject_reason,
            })
        task.task_line_ids.with_context(etm_workflow=True).write({
            'manager_verdict': 'rejected',
            'verdict_reason': self.reject_reason,
        })
        if running_review:
            task.message_post(body=_(
                'Rejected while in progress. Work already recorded has '
                'been kept as-is.'))
        task._log_approval_history('rejected', self.reject_reason)
        task.activity_feedback(['mail.mail_activity_data_todo'])
        task._notify_user(
            task._get_employee_partner(),
            _('Task List Rejected'),
            _('Your completed task list %s has been REJECTED by your '
              'manager and is now closed.\n\nReject Reason: %s',
              task.name, self.reject_reason),
            'employee_task_management.mail_template_task_rejected')
        task._notify_user(
            task._get_manager_partner(),
            _('Task List Rejected'),
            _('Task list %s of %s has been rejected and closed.',
              task.name, task.employee_id.sudo().name))
        return {'type': 'ir.actions.act_window_close'}
