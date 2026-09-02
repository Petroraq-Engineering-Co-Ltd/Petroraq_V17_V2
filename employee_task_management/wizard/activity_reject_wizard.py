# -*- coding: utf-8 -*-
from odoo import models, fields, _


class EmployeeTaskActivityRejectWizard(models.TransientModel):
    _name = 'employee.task.activity.reject.wizard'
    _description = 'Reject an Individual Activity'

    subtask_id = fields.Many2one(
        'employee.task.subtask', string='Activity',
        required=True, readonly=True)
    reason = fields.Text(
        string='Rejection Reason',
        help='Optional. If given, the employee sees it when the '
             'activity is carried into their next task list.')

    def action_confirm_reject(self):
        """Refuse one activity and roll the result up to its task.

        Unlike the whole-task rejection the reason is OPTIONAL here -
        agreed with the client. Rejecting a single activity is a
        lighter-weight action and forcing a justification on each one
        would make reviewing a long list tedious enough that managers
        stop doing it properly.
        """
        self.ensure_one()
        activity = self.subtask_id
        activity._check_activity_reviewable()
        activity.with_context(etm_workflow=True).write({
            'manager_verdict': 'rejected',
            'verdict_reason': self.reason or False,
        })
        # The roll-up decides whether the task is now Rejected outright
        # or Partially Rejected, and flags it for carry-forward either
        # way. It is the only place that decision is made.
        activity.task_line_id._sync_verdict_from_activities()
        activity.task_line_id.task_list_id.message_post(body=_(
            'Activity rejected by %(user)s: %(activity)s '
            '(task: %(task)s)%(reason)s',
            user=self.env.user.name,
            activity=(activity.name or '')[:80],
            task=(activity.task_line_id.description or '')[:80],
            reason=(_('<br/>Reason: %s') % self.reason
                    if self.reason else '')))
        # Same reasoning as action_approve_activity: closing the wizard
        # would drop the manager out of the Activities dialog entirely.
        # Hand him back the activity list he was working through.
        return activity.task_line_id.action_open_subtasks()
