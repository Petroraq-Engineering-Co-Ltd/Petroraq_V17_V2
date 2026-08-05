# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools import float_compare

from .task_states import (
    EDITABLE_STATES, EXECUTION_STATES, PARTIAL_LOCK_STATES,
    LINE_PARTIAL_FIELDS, LINE_DELEGATED_FIELDS, MANAGER_HOURS_STATES,
)


class EmployeeTaskLine(models.Model):
    _name = 'employee.task.line'
    _description = 'Employee Task Line'
    _order = 'sequence, id'

    task_list_id = fields.Many2one(
        'employee.task.list', string='Task List',
        ondelete='cascade', required=True, index=True)
    sequence = fields.Integer(string='Sequence', default=1)
    sr_no = fields.Integer(
        string='Sr. No', compute='_compute_sr_no',
        help='Serial number of task line')
    description = fields.Text(string='Description', required=True)
    # Assign Date removed from the task lines - the header Assign Date
    # on the task list is the one that matters. Only Start / End remain.
    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')
    remarks = fields.Text(string='Remarks')
    progress = fields.Float(string='Progress %', group_operator='avg')
    task_status = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('closed', 'Closed'),
    ], string='Task Status', default='draft', required=True)

    # Related helpers used by views / record rules
    state = fields.Selection(
        related='task_list_id.state', string='List Status', store=True)
    employee_id = fields.Many2one(
        related='task_list_id.employee_id', store=True, string='Employee')
    department_id = fields.Many2one(
        related='task_list_id.department_id', store=True, string='Department')
    manager_id = fields.Many2one(
        related='task_list_id.manager_id', store=True, string='Manager')
    company_id = fields.Many2one(
        related='task_list_id.company_id', store=True, string='Company')
    can_edit_unlocked = fields.Boolean(
        related='task_list_id.can_edit_unlocked')
    activities_locked = fields.Boolean(
        string='Activities Fully Locked',
        compute='_compute_activities_locked',
        help='True when nothing at all can be touched in the activities '
             'grid. Drives the read-only state of the grid itself, which '
             'would otherwise override the per-column rules.')
    is_delayed = fields.Boolean(
        string='Delayed', compute='_compute_is_delayed', store=False)
    subtask_ids = fields.One2many(
        'employee.task.subtask', 'task_line_id', string='Activities')
    subtask_count = fields.Integer(
        string='Activities', compute='_compute_subtask_stats')
    subtask_done_count = fields.Integer(
        string='Completed Activities', compute='_compute_subtask_stats')
    has_subtasks = fields.Boolean(
        string='Has Activities', compute='_compute_subtask_stats')
    subtask_label = fields.Char(
        string='Activities Progress', compute='_compute_subtask_stats')
    total_hours = fields.Float(
        string='Hours', compute='_compute_total_hours', store=True,
        help='Sum of hours logged across this task\'s activities')

    @api.depends('subtask_ids.is_done')
    def _compute_subtask_stats(self):
        for line in self:
            line.subtask_count = len(line.subtask_ids)
            line.subtask_done_count = len(
                line.subtask_ids.filtered('is_done'))
            line.has_subtasks = bool(line.subtask_ids)
            line.subtask_label = (
                '%d / %d done' % (line.subtask_done_count, line.subtask_count)
                if line.subtask_ids else '-')

    @api.depends('task_list_id.state')
    def _compute_activities_locked(self):
        """The grid as a whole is read-only unless SOMETHING inside it is
        still editable. A field-level readonly cannot re-open a grid its
        container has already frozen, so this has to be decided here."""
        privileged = self._is_privileged_user()
        for line in self:
            state = line.task_list_id.state
            line.activities_locked = not (
                state in EDITABLE_STATES
                or state in PARTIAL_LOCK_STATES
                or (privileged and state in MANAGER_HOURS_STATES))

    @api.depends('subtask_ids.hours')
    def _compute_total_hours(self):
        for line in self:
            line.total_hours = sum(line.subtask_ids.mapped('hours'))

    # ------------------------------------------------------------------
    # Edit guards (QA point 7: a Closed task list must be fully locked,
    # including its tasks and activities - not only on screen)
    # ------------------------------------------------------------------
    def _is_privileged_user(self):
        return (
            self.env.user.has_group(
                'employee_task_management.group_task_manager')
            or self.env.user.has_group(
                'employee_task_management.group_task_admin'))

    def _check_list_editable(self, vals=None):
        """Once the task list is approved the plan is frozen: only the
        fields in LINE_PARTIAL_FIELDS (Remarks) may still change. Beyond
        that - Submitted, Completed, Closed, Rejected - nothing changes
        at all."""
        if self.env.context.get('etm_workflow'):
            return
        # Activity commands are policed by employee.task.subtask itself -
        # see LINE_DELEGATED_FIELDS. If that is all the write carried,
        # there is nothing for this guard to judge.
        touched = set(vals or {}) - LINE_DELEGATED_FIELDS
        if not touched:
            return
        for line in self:
            task_list = line.task_list_id
            if not task_list:
                continue
            state = task_list.state
            if state in EDITABLE_STATES:
                continue
            if state in PARTIAL_LOCK_STATES:
                blocked = touched - LINE_PARTIAL_FIELDS
                if blocked:
                    raise UserError(_(
                        'Task list "%s" has been approved, so the tasks '
                        'are frozen. Only Remarks can still be changed '
                        'here, and activities can only be ticked off as '
                        'Done.', task_list.name))
                continue
            raise UserError(_(
                'Task list "%s" is in "%s" status and can no longer be '
                'modified.', task_list.name,
                dict(task_list._fields['state'].selection).get(state)))

    def _check_structure_editable(self):
        """Adding or removing a task is only possible while the task list
        is still being written."""
        if self.env.context.get('etm_workflow'):
            return
        for line in self:
            task_list = line.task_list_id
            if not task_list:
                continue
            if task_list.state not in EDITABLE_STATES:
                raise UserError(_(
                    'Tasks can no longer be added to or removed from task '
                    'list "%s" - it is in "%s" status.', task_list.name,
                    dict(task_list._fields['state'].selection).get(
                        task_list.state)))

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._check_structure_editable()
        return lines

    def write(self, vals):
        self._check_list_editable(vals)
        return super().write(vals)

    def unlink(self):
        self._check_structure_editable()
        return super().unlink()

    # ------------------------------------------------------------------
    # Activities pop-up (restored - the task fields stay in the editable
    # list exactly as before; only the activities open in a dialog)
    # ------------------------------------------------------------------
    def action_close_subtask_dialog(self):
        """Footer button of the Activities dialog. Being a type="object"
        button (not special="cancel"), the web client saves the dirty
        form - including the edited activities - before calling this,
        then this just closes the dialog."""
        self.ensure_one()
        return {'type': 'ir.actions.act_window_close'}

    def action_open_subtasks(self):
        """Open this task's own form with the Activities grid
        (Activity, Hours, Done) in a dialog."""
        self.ensure_one()
        return {
            'name': _('Activities - %s', (self.description or '')[:60]),
            'type': 'ir.actions.act_window',
            'res_model': 'employee.task.line',
            'view_mode': 'form',
            'view_id': self.env.ref(
                'employee_task_management.'
                'view_employee_task_line_form_subtasks').id,
            'res_id': self.id,
            'target': 'new',
        }

    # ------------------------------------------------------------------
    # Progress roll-up from activities
    # ------------------------------------------------------------------
    def _recompute_progress_from_subtasks(self):
        """Progress % of a task is (done activities / total activities)
        and the Task Status follows it."""
        for line in self:
            if not line.subtask_ids:
                # Nothing to roll up yet - a task that still has no
                # activity keeps whatever status the workflow gave it.
                if line.progress:
                    line.with_context(etm_workflow=True).write(
                        {'progress': 0.0})
                continue
            total = len(line.subtask_ids)
            done = len(line.subtask_ids.filtered('is_done'))
            new_progress = round((done / total) * 100.0, 2) if total else 0.0
            vals = {'progress': new_progress}
            if line.task_status != 'closed':
                if new_progress >= 100:
                    vals['task_status'] = 'completed'
                    if not line.end_date:
                        vals['end_date'] = fields.Date.context_today(line)
                elif new_progress <= 0:
                    vals['task_status'] = (
                        'in_progress'
                        if line.task_list_id.state in EXECUTION_STATES
                        else 'draft')
                else:
                    vals['task_status'] = 'in_progress'
            line.with_context(etm_workflow=True).write(vals)

    @api.onchange('subtask_ids')
    def _onchange_subtasks(self):
        """Live UI mirror of _recompute_progress_from_subtasks so the
        form reflects the new progress/status before saving."""
        for line in self:
            total = len(line.subtask_ids)
            if not total:
                line.progress = 0.0
                if line.task_status != 'closed':
                    line.task_status = 'draft'
                continue
            done = len(line.subtask_ids.filtered('is_done'))
            line.progress = round((done / total) * 100.0, 2)
            if line.task_status != 'closed':
                if line.progress >= 100:
                    line.task_status = 'completed'
                elif line.progress <= 0:
                    line.task_status = 'draft'
                else:
                    line.task_status = 'in_progress'

    @api.depends('sequence', 'task_list_id.task_line_ids',
                 'task_list_id.task_line_ids.sequence')
    def _compute_sr_no(self):
        """Serial number of the task line inside its task list."""
        for task_list in self.mapped('task_list_id'):
            lines = task_list.task_line_ids.sorted(key=lambda l: l.sequence)
            for idx, line in enumerate(lines, start=1):
                line.sr_no = idx
        for line in self.filtered(lambda l: not l.task_list_id):
            line.sr_no = 0

    @api.depends('end_date', 'task_status')
    def _compute_is_delayed(self):
        today = fields.Date.context_today(self)
        for line in self:
            line.is_delayed = bool(
                line.end_date and line.end_date < today
                and line.task_status not in ('completed', 'closed'))

    # ------------------------------------------------------------------
    # Validations (TDD Section 14)
    # ------------------------------------------------------------------
    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        """Validation 4: End Date should not be earlier than Start Date.

        Only enforced while the dates can still be corrected. Beyond
        planning they are read-only, so raising here would leave the
        record permanently unsavable.
        """
        for line in self:
            if line.task_list_id and \
                    line.task_list_id.state not in EDITABLE_STATES:
                continue
            if line.start_date and line.end_date and \
                    line.end_date < line.start_date:
                raise ValidationError(_(
                    'End Date (%s) should not be earlier than Start Date '
                    '(%s) for task: %s',
                    line.end_date, line.start_date,
                    (line.description or '')[:60]))

    @api.model
    def _format_hours(self, value):
        """Render a float duration as HH:MM, matching the float_time
        widget the user sees on screen."""
        value = value or 0.0
        hours = int(value)
        minutes = int(round((value - hours) * 60))
        if minutes >= 60:
            hours, minutes = hours + 1, 0
        return '%02d:%02d' % (hours, minutes)

    def _get_capacity_hours(self):
        """How many hours of work this task's date range can hold.

        working days between Start and End (inclusive, Sun-Thu) x the
        hours in a working day. Returns None when it cannot be judged -
        no dates yet, or no task list.
        """
        self.ensure_one()
        task_list = self.task_list_id
        if not task_list or not self.start_date or not self.end_date:
            return None
        working_days = task_list._working_days_between(
            self.start_date, self.end_date)
        return working_days * task_list._get_hours_per_day()

    @api.constrains('total_hours', 'start_date', 'end_date')
    def _check_daily_capacity(self):
        """A task cannot hold more work than its own date range allows.

        A task planned to start and finish today has one working day of
        capacity - 08:00 by default - so activities of 04:30 and 05:00
        do not fit and the End Date has to move to tomorrow.
        """
        for line in self:
            if not line.subtask_ids:
                continue
            # Only while the task list is still being planned. Once it is
            # approved the dates are frozen, so re-checking capacity would
            # block work on a task nobody is allowed to re-date - and a
            # task that simply ran late is not a data error.
            if line.task_list_id.state not in EDITABLE_STATES:
                continue
            capacity = line._get_capacity_hours()
            if capacity is None:
                continue
            task_list = line.task_list_id
            # An End Date before the Start Date also yields zero working
            # days. Say so plainly instead of blaming the weekend - the
            # old wording sent people hunting for a calendar problem that
            # was really a reversed date pair.
            if line.end_date < line.start_date:
                raise ValidationError(_(
                    'Task "%(task)s" has an End Date (%(end)s) earlier '
                    'than its Start Date (%(start)s).',
                    task=(line.description or '')[:80],
                    start=line.start_date, end=line.end_date))
            working_days = task_list._working_days_between(
                line.start_date, line.end_date)
            if not working_days:
                raise ValidationError(_(
                    'Task "%(task)s" is planned from %(start)s to %(end)s, '
                    'which falls entirely on non-working days. Move the '
                    'dates onto working days.',
                    task=(line.description or '')[:80],
                    start=line.start_date, end=line.end_date))
            if float_compare(line.total_hours, capacity,
                             precision_digits=2) > 0:
                raise ValidationError(_(
                    'Task "%(task)s" does not fit in its own dates.\n\n'
                    'Planned: %(start)s to %(end)s '
                    '(%(days)s working day(s), %(capacity)s of capacity)\n'
                    'Activities add up to: %(total)s\n\n'
                    'Extend the End Date or reduce the activity hours.',
                    task=(line.description or '')[:80],
                    start=line.start_date, end=line.end_date,
                    days=working_days,
                    capacity=self._format_hours(capacity),
                    total=self._format_hours(line.total_hours)))

    @api.constrains('progress')
    def _check_progress(self):
        for line in self:
            if line.progress < 0 or line.progress > 100:
                raise ValidationError(_(
                    'Progress %% must be between 0 and 100.'))
