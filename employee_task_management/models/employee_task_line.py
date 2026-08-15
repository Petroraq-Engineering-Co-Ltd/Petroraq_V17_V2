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

    # ------------------------------------------------------------------
    # Manager verdict, per task (line-level approve / reject).
    # Deliberately SEPARATE from task_status: task_status is the
    # employee's execution progress, auto-computed from the activities.
    # This is the manager's opinion of that work, which is a different
    # fact and must be able to disagree with it.
    # ------------------------------------------------------------------
    manager_verdict = fields.Selection([
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Manager Verdict', default='pending', required=True,
        readonly=True, copy=False, tracking=True,
        help='Set by the manager while reviewing a Completed task list, '
             'one task at a time. Left at Pending Review, a task counts '
             'as approved when the manager closes the whole list.')
    verdict_reason = fields.Text(
        string='Rejection Reason', readonly=True, copy=False,
        help='Why the manager rejected this task. Mandatory on rejection.')
    carry_forward_pending = fields.Boolean(
        string='Awaiting Carry-Forward', readonly=True, copy=False,
        help='A rejected task waits here until the employee creates '
             'their next task list, at which point it is copied into it '
             'automatically and this flag is cleared.')
    carried_from_line_id = fields.Many2one(
        'employee.task.line', string='Redo Of', readonly=True, copy=False,
        ondelete='set null',
        help='The rejected task this one was carried forward from.')
    is_carried_forward = fields.Boolean(
        string='Carried Forward', readonly=True, copy=False,
        help='This task was auto-added because a manager rejected it on '
             'an earlier task list. The employee cannot remove it.')

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
    completion_date = fields.Date(
        string='Completion Date', readonly=True, copy=False, tracking=True,
        help="Date this task's activities reached 100%% and it was "
             "marked Completed. Cleared automatically if it drops back "
             "below 100%% (e.g. an activity gets un-ticked). Used to "
             "measure how many working days late it finished.")
    delayed_days = fields.Integer(
        string='Delayed (Days)', compute='_compute_delayed_days',
        help='Working days past the planned End Date. 0 if on time or '
             'not yet due. Keeps counting while still running late, '
             'and settles at the final figure once Completed.')
    was_delayed_days = fields.Integer(
        string='Worst Delay (Days)', readonly=True, copy=False,
        tracking=True, default=0,
        help='The worst delayed_days this task has ever recorded. '
             'Latched - never decreases, even if the task is later '
             'corrected or re-completed on time.')
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
        """Once the task list is approved the plan is frozen - only
        Remarks may still change, and it may change in ANY state, for
        both employee and manager. Beyond Remarks: Submitted, Completed,
        Closed, Rejected allow nothing at all; the partial-lock states
        (Manager Approved, In Progress, Returned After Completion) also
        allow nothing else here (activities are policed separately by
        employee.task.subtask)."""
        if self.env.context.get('etm_workflow'):
            return
        # QA point 7: a Manager / Administrator may edit at any level, in
        # any state. Employees stay bound by the rules below.
        if self._is_privileged_user():
            return
        # Activity commands are policed by employee.task.subtask itself -
        # see LINE_DELEGATED_FIELDS. If that is all the write carried,
        # there is nothing for this guard to judge.
        touched = set(vals or {}) - LINE_DELEGATED_FIELDS
        if not touched:
            return
        # Remarks is exempt from this guard in every state - drop it
        # before checking anything else.
        touched = touched - LINE_PARTIAL_FIELDS
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
                # Anything left in `touched` here is not Remarks (already
                # subtracted above), so it is still blocked.
                raise UserError(_(
                    'Task list "%s" has been approved, so the tasks '
                    'are frozen. Only Remarks can still be changed '
                    'here, and activities can only be ticked off as '
                    'Done.', task_list.name))
            raise UserError(_(
                'Task list "%s" is in "%s" status and can no longer be '
                'modified.', task_list.name,
                dict(task_list._fields['state'].selection).get(state)))

    def _check_structure_editable(self):
        """Adding or removing a task is only possible while the task list
        is still being written - unless you are a Manager/Administrator,
        who may restructure at any level (QA point 7)."""
        if self.env.context.get('etm_workflow'):
            return
        if self._is_privileged_user():
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
        # A carried-forward task is mandatory rework - the employee may
        # not drop it. A manager/administrator still can, in case the
        # task genuinely became irrelevant.
        carried = self.filtered('is_carried_forward')
        if carried and not self._is_privileged_user():
            raise UserError(_(
                'These tasks were carried forward because they were '
                'rejected on an earlier task list, so they have to be '
                'done:\n%s',
                '\n'.join('- %s' % (l.description or '')[:80]
                           for l in carried)))
        self._check_structure_editable()
        return super().unlink()

    # ------------------------------------------------------------------
    # Line-level manager review (Completed state)
    # ------------------------------------------------------------------
    def _check_reviewable(self):
        """A verdict may only be set by a manager/admin, and only while
        the task list is sitting at Completed waiting for review."""
        self.ensure_one()
        if not self._is_privileged_user():
            raise UserError(_(
                'Only a Manager or Administrator can approve or reject '
                'a task.'))
        # Same rule as the whole-list actions: nobody rules on their own
        # work. Without this a department manager could approve or
        # reject the individual tasks on his OWN completed task list,
        # which is the exact hole the whole-list guard already closes.
        if self.task_list_id._is_own_task_list():
            raise UserError(_(
                'You cannot approve or reject tasks on your own task '
                'list (%s). It has to be reviewed by your own manager.',
                self.task_list_id.name))
        if self.task_list_id.state != 'completed':
            raise UserError(_(
                'Tasks can only be approved or rejected while the task '
                'list is Completed and awaiting your review.'))

    def action_approve_task(self):
        """Manager accepts this individual task."""
        for line in self:
            line._check_reviewable()
            line.with_context(etm_workflow=True).write({
                'manager_verdict': 'approved',
                'verdict_reason': False,
            })
            line.task_list_id.message_post(body=_(
                'Task approved by %(user)s: %(task)s',
                user=line.env.user.name,
                task=(line.description or '')[:80]))
        return True

    def action_reject_task(self):
        """Manager rejects this individual task. Opens a wizard so the
        reason is mandatory, consistent with the whole-list Reject."""
        self.ensure_one()
        self._check_reviewable()
        return {
            'name': _('Reject Task'),
            'type': 'ir.actions.act_window',
            'res_model': 'employee.task.line.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_task_line_id': self.id},
        }

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
    def _weighted_progress(self):
        """Progress % of this task, weighted by each activity's HOURS.

        Client rule (Feedback #5 point 3): an activity worth 5:00 out of
        a 6:00 task carries 83.33% of that task, not 50% just because it
        is one of two rows. Equal-share counting made a five-hour job and
        a one-hour job look identical, which is what they objected to.

        Two deliberate guards:
          * ALL done returns exactly 100.0, never 99.99 - Mark Completed
            hard-checks progress == 100, so a float rounding error there
            would block completion outright.
          * If the activities carry no hours at all (possible while
            planning, before the hours-mandatory gate at submit), fall
            back to equal share rather than dividing by zero.
        """
        self.ensure_one()
        activities = self.subtask_ids
        if not activities:
            return 0.0
        done = activities.filtered('is_done')
        if not done:
            return 0.0
        if len(done) == len(activities):
            return 100.0
        total_hours = sum(activities.mapped('hours'))
        if total_hours <= 0:
            return round(len(done) / len(activities) * 100.0, 2)
        return round(sum(done.mapped('hours')) / total_hours * 100.0, 2)

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
            new_progress = line._weighted_progress()
            vals = {'progress': new_progress}
            if line.task_status != 'closed':
                if new_progress >= 100:
                    vals['task_status'] = 'completed'
                    if line.task_status != 'completed':
                        # Genuine transition into Completed - stamp when
                        # it actually happened, not on every later
                        # recompute while it stays at 100%.
                        vals['completion_date'] = fields.Date.context_today(
                            line)
                elif new_progress <= 0:
                    vals['task_status'] = (
                        'in_progress'
                        if line.task_list_id.state in EXECUTION_STATES
                        else 'draft')
                    if line.completion_date:
                        vals['completion_date'] = False
                else:
                    vals['task_status'] = 'in_progress'
                    if line.completion_date:
                        vals['completion_date'] = False
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
            line.progress = line._weighted_progress()
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

    @api.depends('end_date', 'task_status', 'completion_date')
    def _compute_delayed_days(self):
        """How many working days past the planned End Date this task
        is (still running) or finished (Completed) - 0 if on time.

        Deliberately different from is_delayed: is_delayed goes False
        the moment a task is marked Completed, because its job is to
        drive a "needs attention now" ribbon. This field keeps showing
        the final figure once Completed instead of resetting to 0, so
        it settles on the answer to "how late did this finish" rather
        than "does this need attention right now".
        """
        for line in self:
            task_list = line.task_list_id
            if not line.end_date or not task_list:
                line.delayed_days = 0
                continue
            if line.task_status in ('completed', 'closed'):
                # A task that finished a day late is STILL a day late
                # once the manager closes the list. Closed used to
                # return 0 here, so the figure silently reset the moment
                # action_close set every line to 'closed' - the manager
                # then saw Worst Delay 1 next to Delayed (Days) 0 on the
                # same record (Feedback #5 point 2).
                reference = line.completion_date or line.end_date
            else:
                reference = task_list._today_local()
            if reference <= line.end_date:
                line.delayed_days = 0
            else:
                line.delayed_days = max(
                    task_list._working_days_between(
                        line.end_date, reference) - 1, 0)

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

        working days between Start and End (inclusive, Sat-Thu) x the
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

    @api.constrains('start_date', 'end_date')
    def _check_working_date_range(self):
        """A task's own date range must contain at least one working
        day, and the End Date cannot be before the Start Date.

        Checked the moment the task is saved - independent of whether
        it has any activities yet. Previously this only fired once
        activities existed (as part of the capacity check below), so a
        task dated entirely on a Friday could be created and even
        submitted as long as nobody had added an activity to it yet.
        """
        for line in self:
            task_list = line.task_list_id
            if not task_list or task_list.state not in EDITABLE_STATES:
                continue
            # A line with only ONE date set still has to sit on a working
            # day. Previously this whole check was skipped unless BOTH
            # dates were filled, so a task dated on a Friday saved
            # silently as long as the other date was left blank - neither
            # date field is required, so that is easy to hit.
            if not line.start_date or not line.end_date:
                single = line.start_date or line.end_date
                if single and not task_list._working_days_between(
                        single, single):
                    raise ValidationError(_(
                        'Task "%(task)s" is planned on %(day)s, which is '
                        'not a working day. Move it onto a working day.',
                        task=(line.description or '')[:80], day=single))
                continue
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

    @api.constrains('total_hours', 'start_date', 'end_date')
    def _check_daily_capacity(self):
        """A task cannot hold more work than its own date range allows.

        A task planned to start and finish today has one working day of
        capacity - 08:00 by default - so activities of 04:30 and 05:00
        do not fit and the End Date has to move to tomorrow.

        The date range itself (off-day / inverted dates) is already
        checked by _check_working_date_range above, regardless of
        whether activities exist yet - by the time we get here on a
        line that HAS activities, the range is known to be sane.
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
            if float_compare(line.total_hours, capacity,
                             precision_digits=2) > 0:
                # Safe to recompute here - _check_working_date_range
                # already guarantees this range holds at least one
                # working day by the time a write reaches this point.
                working_days = line.task_list_id._working_days_between(
                    line.start_date, line.end_date)
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
