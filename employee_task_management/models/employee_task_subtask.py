# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools import float_compare

from .task_states import (
    EDITABLE_STATES, EXECUTION_STATES, PARTIAL_LOCK_STATES,
    SUBTASK_PARTIAL_FIELDS, SUBTASK_MANAGER_FIELDS, MANAGER_HOURS_STATES,
)


class EmployeeTaskSubtask(models.Model):
    _name = 'employee.task.subtask'
    _description = 'Employee Task Activity'
    _order = 'sequence, id'

    task_line_id = fields.Many2one(
        'employee.task.line', string='Task',
        required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(string='Sequence', default=1)
    name = fields.Char(string='Activity', required=True)
    hours = fields.Float(
        string='Hours', tracking=True,
        help='Hours estimated / spent on this activity. Mandatory - '
             'enforced by _check_hours and by required="1" in the view. '
             'Deliberately NOT required at field level, so upgrading an '
             'existing database can never fail on a NOT NULL alter.')
    is_done = fields.Boolean(string='Done')

    # Related helpers used by record rules and view readonly logic
    task_list_id = fields.Many2one(
        related='task_line_id.task_list_id', store=True, string='Task List')
    state = fields.Selection(
        related='task_line_id.state', string='List Status')
    can_edit_unlocked = fields.Boolean(
        related='task_line_id.task_list_id.can_edit_unlocked')
    can_edit_hours = fields.Boolean(
        string='Hours Editable', compute='_compute_can_edit_hours',
        help='Hours stay editable for a Manager / Administrator while the '
             'task list is running, so an estimate can be corrected '
             'without unwinding the whole workflow.')

    def _is_privileged_user(self):
        return (
            self.env.user.has_group(
                'employee_task_management.group_task_manager')
            or self.env.user.has_group(
                'employee_task_management.group_task_admin'))

    @api.depends('task_line_id.task_list_id.state')
    def _compute_can_edit_hours(self):
        privileged = self._is_privileged_user()
        for rec in self:
            state = rec.task_line_id.task_list_id.state
            rec.can_edit_hours = bool(
                state in EDITABLE_STATES
                or (privileged and state in MANAGER_HOURS_STATES))

    # ------------------------------------------------------------------
    # Validations
    # ------------------------------------------------------------------
    @api.constrains('hours')
    def _check_hours(self):
        """QA point 12: mentioning the time is mandatory on every
        activity."""
        for rec in self:
            if not rec.hours or rec.hours <= 0:
                raise ValidationError(_(
                    'Hours are mandatory for every activity and must be '
                    'greater than 0.\n\nActivity: %s', rec.name or ''))

    def _check_done_allowed(self):
        """QA points 3, 4 & 5: an activity may only be ticked Done once
        the task list is actually being executed - i.e. after the manager
        approved it (or the employee accepted it) AND the employee
        pressed "Start Work"."""
        for rec in self.filtered('is_done'):
            task_list = rec.task_line_id.task_list_id
            if task_list and task_list.state not in EXECUTION_STATES:
                raise UserError(_(
                    'Activities cannot be marked as Done yet. Task list '
                    '"%s" is in "%s" state - the work has to be approved '
                    'and started ("Start Work") first.',
                    task_list.name,
                    dict(task_list._fields['state'].selection).get(
                        task_list.state)))

    def _check_activity_editable(self, vals=None):
        """Same freeze as the task lines: once the task list is approved
        no activity may be added, removed, renamed or re-costed - the
        only thing that still moves is the Done toggle."""
        if self.env.context.get('etm_workflow'):
            return
        # QA point 7: Manager / Administrator may work at any level, in
        # any state - including adding, renaming and re-costing
        # activities after approval.
        if self._is_privileged_user():
            return
        touched = set(vals or {})
        privileged = self._is_privileged_user()
        for rec in self:
            task_list = rec.task_line_id.task_list_id
            if not task_list:
                continue
            state = task_list.state
            if state in EDITABLE_STATES:
                continue
            allowed = set()
            if state in PARTIAL_LOCK_STATES:
                allowed |= SUBTASK_PARTIAL_FIELDS
            if privileged and state in MANAGER_HOURS_STATES:
                # A Manager / Administrator may still correct the hours,
                # including on a Completed task list awaiting review.
                allowed |= SUBTASK_MANAGER_FIELDS
            blocked = touched - allowed
            if blocked:
                raise UserError(_(
                    'Task list "%s" is in "%s" status - its activities '
                    'can no longer be modified this way.',
                    task_list.name,
                    dict(task_list._fields['state'].selection).get(state)))

    def _check_structure_editable(self):
        """Adding or removing an activity is only possible while the task
        list is still being written (Draft / Returned / Pending
        Acceptance / Modification Requested) - unless you are a
        Manager/Administrator, who may work at any level (QA point 7)."""
        if self.env.context.get('etm_workflow'):
            return
        if self._is_privileged_user():
            return
        for rec in self:
            task_list = rec.task_line_id.task_list_id
            if not task_list:
                continue
            if task_list.state not in EDITABLE_STATES:
                raise UserError(_(
                    'Activities can no longer be added to or removed from '
                    'task list "%s" - it is in "%s" status. Plan the '
                    'activities before accepting the task list.',
                    task_list.name,
                    dict(task_list._fields['state'].selection).get(
                        task_list.state)))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._check_structure_editable()
        records._check_done_allowed()
        records.mapped('task_line_id')._recompute_progress_from_subtasks()
        return records

    def _log_hours_change(self, previous_hours):
        """Post an audit note on the TASK LIST's chatter when hours are
        changed after the plan was frozen.

        The note goes on employee.task.list, not here: this model has no
        mail.thread, and even if it had, nobody ever opens an activity's
        own form - the task list chatter is where people actually look.
        Changes made while the list is still being planned are not
        logged; editing then is normal and would just be noise.
        """
        for rec in self:
            was = previous_hours.get(rec.id)
            if was is None:
                continue
            if float_compare(was, rec.hours, precision_digits=2) == 0:
                continue
            task_list = rec.task_line_id.task_list_id
            if not task_list or task_list.state in EDITABLE_STATES:
                continue
            task_list.message_post(body=_(
                'Hours changed on activity <b>%(activity)s</b> '
                '(task: %(task)s): %(old)s &rarr; %(new)s',
                activity=rec.name or '',
                task=(rec.task_line_id.description or '')[:60],
                old=rec.task_line_id._format_hours(was),
                new=rec.task_line_id._format_hours(rec.hours)))

    def write(self, vals):
        self._check_activity_editable(vals)
        previous_hours = (
            {rec.id: rec.hours for rec in self} if 'hours' in vals else {})
        res = super().write(vals)
        if vals.get('is_done'):
            self._check_done_allowed()
        if previous_hours:
            self._log_hours_change(previous_hours)
        if 'is_done' in vals or 'hours' in vals:
            self.mapped('task_line_id')._recompute_progress_from_subtasks()
        return res

    def unlink(self):
        lines = self.mapped('task_line_id')
        self._check_structure_editable()
        res = super().unlink()
        lines._recompute_progress_from_subtasks()
        return res
