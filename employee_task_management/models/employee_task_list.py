# -*- coding: utf-8 -*-
import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError, AccessError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)

from .task_states import (  # noqa: F401,E402  (re-exported for convenience)
    EDITABLE_STATES, EXECUTION_STATES, PARTIAL_LOCK_STATES,
    FULL_LOCK_STATES, TERMINAL_STATES, REPORTABLE_DELAY_STATES,
)

# A task list waiting in one of these states is auto-assigned to the
# employee as soon as the start date of one of its tasks arrives - the
# work is due, so it must not stay blocked on an approval or acceptance.
AUTO_ASSIGN_STATES = (
    'submitted_manager',
    'pending_acceptance',
    'modification_requested',
)

# Kanban columns that are always shown, in workflow order. Exception
# states (Returned, Modification Requested, Returned after Completion,
# Rejected) only get a column when they actually hold records, so the
# board stays readable.
KANBAN_CORE_STATES = (
    'draft',
    'submitted_manager',
    'pending_acceptance',
    'manager_approved',
    'in_progress',
    'completed',
    'closed',
)

# Python weekday(): Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
#
# TWO DIFFERENT WEEKS, deliberately. The client's PAYROLL is calculated
# from the company's Odoo Working Schedule, which is Sunday-Thursday and
# must NOT be changed. But Saturday is only a "soft" day off: an
# employee with pending work may come into the office and clear it, so
# task work may legitimately be PLANNED on a Saturday.
#
#   PAYROLL week  (Sun-Thu) - what the company officially works.
#                 Used for measuring LATENESS, so nobody is counted late
#                 over a day they were never obliged to work.
#   PLANNING week (payroll + Saturday) - days a task may be dated on and
#                 that carry capacity. A Saturday task holds a full day
#                 of hours like any other.
#
# Friday is the only genuinely blocked day.
DEFAULT_WORK_DAYS = {6, 0, 1, 2, 3}          # payroll: Sunday-Thursday

# Days that are officially off but may still be worked on request. Added
# to the payroll week to give the planning week.
OPTIONAL_WORK_DAYS = {5}                     # Saturday
DEFAULT_HOUR_FROM = 8.0
DEFAULT_HOUR_TO = 17.0
DEFAULT_HOURS_PER_DAY = 8.0
DEFAULT_TZ = 'Asia/Riyadh'

# States in which the record is waiting on somebody's action and the
# one-working-day auto-apply clock is running.
WAITING_STATES = ('submitted_manager', 'pending_acceptance',
                  'modification_requested')

# Keys that may appear in a write() without it being a real user edit of
# the task list content (chatter, workflow bookkeeping, stored computes).
INTERNAL_WRITE_KEYS = {
    'message_follower_ids', 'activity_ids', 'message_ids',
    'message_main_attachment_id', 'access_token',
    'state', 'pending_since', 'is_unlocked', 'progress', 'task_count',
}


class EmployeeTaskList(models.Model):
    _name = 'employee.task.list'
    _description = 'Employee Task List'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'assign_date desc, id desc'
    _rec_name = 'name'

    # ------------------------------------------------------------------
    # Header Fields (TDD Section 3.1)
    # ------------------------------------------------------------------
    name = fields.Char(
        string='Task List Reference', required=True, copy=False,
        readonly=True, index=True, default=lambda self: _('New'),
        help='Auto-generated reference number (PEC-TL-YEAR-00000)')
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, tracking=True,
        default=lambda self: self.env.user.employee_id,
        help='Employee the task list belongs to')
    # precompute=True is REQUIRED here. Both fields are
    # required + computed + stored: without precompute Odoo runs the
    # compute AFTER the INSERT, so the INSERT goes out without the
    # column and PostgreSQL rejects it on the NOT NULL constraint. This
    # only surfaced once the fields became read-only for employees,
    # because until then the browser was sending the values itself.
    department_id = fields.Many2one(
        'hr.department', string='Department', required=True, tracking=True,
        compute='_compute_employee_details', store=True, readonly=False,
        precompute=True,
        help='Auto-filled from employee profile')
    manager_id = fields.Many2one(
        'hr.employee', string='Manager', required=True, tracking=True,
        compute='_compute_employee_details', store=True, readonly=False,
        precompute=True,
        help='Immediate manager of employee')
    assign_date = fields.Date(
        string='Assign Date', required=True, tracking=True, readonly=True,
        default=fields.Date.context_today,
        help='Date on which the task list is raised. Filled in '
             'automatically when the record is created and not editable - '
             'the working dates of each task are its Start Date and End '
             'Date on the task lines.')
    completion_date = fields.Date(
        string='Completion Date', readonly=True, copy=False, tracking=True,
        help='Date the task list was actually marked Completed. Stamped '
             'automatically - this is when the work genuinely finished, '
             'not the planned End Date on any task line.')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted_manager', 'Submitted to Manager'),
        ('returned_manager', 'Returned by Manager'),
        ('pending_acceptance', 'Pending Employee Acceptance'),
        ('modification_requested', 'Modification Requested'),
        ('manager_approved', 'Manager Approved'),
        ('in_progress', 'In Progress'),
        ('returned_after_completion', 'Returned by Manager after Completion'),
        ('completed', 'Completed'),
        ('closed', 'Closed'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', required=True, tracking=True,
        copy=False, index=True, group_expand='_group_expand_state')
    # Stamped at the EVENT (in action_submit_to_manager), never
    # recomputed from current data: it records HOW this list reached
    # In Progress. A live compute would go stale the moment the manager
    # ruled on it, and the review buttons would vanish or reappear on
    # their own - the same trap that broke needs_employee_planning.
    started_without_approval = fields.Boolean(
        string='Started Without Approval', readonly=True, copy=False,
        help='This task list started on its own start date, so the '
             'employee began work immediately. It still needs the '
             'manager to accept or reject it.')
    manager_remarks = fields.Text(
        string='Manager Remarks', tracking=True,
        help='Remarks from manager')
    return_reason = fields.Text(
        string='Return Reason', tracking=True, copy=False,
        help='Reason provided by the manager when returning the task list')
    modification_reason = fields.Text(
        string='Modification Request', tracking=True, copy=False,
        help='Reason given by the employee when requesting a modification '
             'to an assigned task list')
    reject_reason = fields.Text(
        string='Reject Reason', tracking=True, copy=False,
        help='Reason given by the manager when rejecting a completed '
             'task list. A rejected task list is final.')
    pending_since = fields.Datetime(
        string='Waiting Since', copy=False, readonly=True,
        help='Moment the task list entered its current waiting state. '
             'The auto-apply rules measure one full working day from '
             'here (Sat-Thu, 08:00-17:00, Asia/Riyadh by default).')
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)

    # ------------------------------------------------------------------
    # Lines / progress / helpers
    # ------------------------------------------------------------------
    task_line_ids = fields.One2many(
        'employee.task.line', 'task_list_id', string='Task Lines', copy=True)
    task_count = fields.Integer(
        string='Number of Tasks', compute='_compute_task_count', store=True)
    progress = fields.Float(
        string='Progress %', compute='_compute_progress', store=True,
        group_operator='avg', tracking=True)
    completion_notes = fields.Text(string='Completion Notes')
    approval_history_ids = fields.One2many(
        'employee.task.approval.history', 'task_list_id',
        string='Approval History', readonly=True, copy=False)
    attachment_ids = fields.Many2many(
        'ir.attachment', 'employee_task_list_attachment_rel',
        'task_list_id', 'attachment_id', string='Attachments', copy=False,
        help='Supporting files, site photos, drawings, work progress documents')
    was_delayed = fields.Boolean(
        string='Was Delayed', readonly=True, copy=False, tracking=True,
        help='Latched. Set once the task list actually ran late and never '
             'cleared, so the delay is still visible after the work is '
             'completed and closed. is_delayed only reflects the live '
             'situation and goes False the moment the work finishes.')
    was_delayed_days = fields.Integer(
        string='Worst Delay (Days)', readonly=True, copy=False,
        tracking=True, default=0,
        help="Worst-line rollup of employee.task.line.was_delayed_days. "
             "Latched - never decreases, even after the work is "
             "completed and closed.")
    is_delayed = fields.Boolean(
        string='Delayed', compute='_compute_is_delayed',
        search='_search_is_delayed')
    delayed_days = fields.Integer(
        string='Delayed (Days)', compute='_compute_delayed_days',
        help='Worst-line rollup of employee.task.line.delayed_days - how '
             'many working days late the most-delayed task is (or '
             'finished). 0 while waiting on approval/acceptance; that '
             'wait is tracked separately by is_delayed/pending_since.')
    is_unlocked = fields.Boolean(
        string='Unlocked for Editing', default=False, copy=False, tracking=True,
        help='Set when a manager/admin unlocks a closed task list for '
             'exceptional edits. Cleared when the record is closed again.')
    can_edit_unlocked = fields.Boolean(
        compute='_compute_user_flags', string='Can Edit While Unlocked')
    can_select_employee = fields.Boolean(
        compute='_compute_user_flags', string='Can Choose Another Employee')
    can_edit_department = fields.Boolean(
        compute='_compute_user_flags', string='Can Choose Department')
    can_edit_manager = fields.Boolean(
        compute='_compute_user_flags', string='Can Choose Manager')
    color = fields.Integer(string='Color Index', compute='_compute_color')
    is_current_user_manager = fields.Boolean(
        compute='_compute_user_flags', string='Is Current User The Manager')
    is_current_user_employee = fields.Boolean(
        compute='_compute_user_flags', string='Is Current User The Employee')
    needs_employee_planning = fields.Boolean(
        string='Employee Must Plan This',
        readonly=True, copy=False,
        help="True when the manager assigned this task list WITHOUT "
             "activities, so the employee has to plan it himself. Drives "
             "which buttons he gets: nothing to agree to yet, so Accept "
             "and Request Modification are replaced by Submit Activities "
             "for Review.")
    can_act_for_employee = fields.Boolean(
        compute='_compute_user_flags', string='Can Act For The Employee',
        help="The employee himself, OR the manager this task list reports "
             "to (or an Administrator). A manager may drive his own "
             "people's Accept / Start Work / Mark Completed when they are "
             "away - and only his own people, never another team's.")
    activity_update_log = fields.Html(
        string='Activities Update Log',
        compute='_compute_activity_update_log',
        help='Consolidated log of activities updated against task lines')
    allowed_employee_ids = fields.Many2many(
        'hr.employee', compute='_compute_allowed_selection',
        string='Selectable Employees')
    allowed_department_ids = fields.Many2many(
        'hr.department', compute='_compute_allowed_selection',
        string='Selectable Departments')
    has_task_without_activity = fields.Boolean(
        compute='_compute_has_task_without_activity',
        string='Some Task Has No Activity')

    # ==================================================================
    # WORKING-TIME HELPERS
    #
    # Agreed rule: "24 working hours" means ONE WORKING DAY - the same
    # clock time on the next working day. Saturday-Thursday (Friday only
    # is the weekend), 08:00-17:00, Asia/Riyadh. The schedule is read
    # from the company's Working
    # Schedule (Settings > Employees > Working Schedules) so the client
    # can change their hours, days or timezone without a code change;
    # the constants below are only the fallback if none is configured.
    # ==================================================================
    def _get_work_schedule(self):
        """Return (tz_name, {working weekdays}, hour_from, hour_to).

        THE WORKING WEEK IS FIXED IN CODE. It is deliberately NOT read
        from the Working Schedule any more.

        Why: the calendar used to win, and it caused three separate
        production problems.
          1. A stock Odoo database ships a Mon-Fri calendar, so Friday
             became a working day and generated idle rows for a day
             nobody works.
          2. The same calendar made SUNDAY a non-working day, so Sunday
             carried no capacity at all and a task spanning a Sunday
             silently dumped its hours onto the neighbouring days.
          3. Worst of all, the answer depended on WHO was asking. The
             cron runs as OdooBot and resolved `self.env.company` from
             OdooBot's company; a manual run resolved it from the
             user's. Two different calendars meant two different working
             weeks, so the scheduled run kept deleting rows the manual
             run had just created - exactly the "30 August appears then
             vanishes" behaviour that was reported.

        The client's week is set by the country and their contract, not
        by a settings field: Sunday-Thursday, Saturday optional, Friday
        off. Hard-coding it makes the answer identical for every caller
        and removes an entire class of misconfiguration.

        Hours and timezone ARE still read from the calendar - those are
        genuinely tunable, and neither can change which days exist.
        """
        calendar = (self.company_id.resource_calendar_id
                    or self.env.company.resource_calendar_id)
        tz_name = DEFAULT_TZ
        hour_from, hour_to = DEFAULT_HOUR_FROM, DEFAULT_HOUR_TO
        if calendar:
            tz_name = calendar.tz or DEFAULT_TZ
            if calendar.attendance_ids:
                hour_from = min(calendar.attendance_ids.mapped('hour_from'))
                hour_to = max(calendar.attendance_ids.mapped('hour_to'))
                configured_days = {
                    int(a.dayofweek) for a in calendar.attendance_ids}
                if configured_days != DEFAULT_WORK_DAYS:
                    # Informational only now - it no longer changes any
                    # behaviour, but a calendar that disagrees with the
                    # real work week is still a payroll problem worth
                    # surfacing.
                    _logger.info(
                        "Working Schedule '%s' lists working days %s, "
                        "which differs from this module's fixed week "
                        "%s. The fixed week is used; the calendar only "
                        "supplies hours and timezone.",
                        calendar.display_name,
                        sorted(configured_days), sorted(DEFAULT_WORK_DAYS))
        return (tz_name, DEFAULT_WORK_DAYS, hour_from, hour_to)

    def _get_hours_per_day(self):
        """How many hours of work fit in one working day. Read from the
        company's Working Schedule so the client can change it in
        Settings; falls back to 8."""
        calendar = (self.company_id.resource_calendar_id
                    or self.env.company.resource_calendar_id)
        if calendar and calendar.hours_per_day:
            return calendar.hours_per_day
        return DEFAULT_HOURS_PER_DAY

    def _get_planning_work_days(self):
        """Days a task may be DATED on and that carry capacity.

        The payroll week plus the optional days (Saturday). Read this -
        never the raw payroll week - for date validation and capacity,
        or an employee coming in on a Saturday to clear pending work
        cannot record it.
        """
        # NO ensure_one() - same reason as _today_local() above.
        payroll = self._get_work_schedule()[1] or DEFAULT_WORK_DAYS
        return set(payroll) | OPTIONAL_WORK_DAYS

    def _working_days_between(self, start_date, end_date, work_days=None):
        """Number of working days from start to end, both inclusive.

        Defaults to the PAYROLL week - the safe default, because being
        counted late over an official day off is the harm worth avoiding.
        Callers doing planning/capacity maths pass
        _get_planning_work_days() explicitly.
        """
        self.ensure_one()
        if not start_date or not end_date or end_date < start_date:
            return 0
        if work_days is None:
            work_days = self._get_work_schedule()[1] or DEFAULT_WORK_DAYS
        days, cursor, guard = 0, start_date, 0
        while cursor <= end_date and guard < 3650:
            if cursor.weekday() in work_days:
                days += 1
            cursor += timedelta(days=1)
            guard += 1
        return days

    @api.model
    def _float_to_time_parts(self, float_hour):
        hours = int(float_hour)
        minutes = int(round((float_hour - hours) * 60))
        if minutes >= 60:
            hours, minutes = hours + 1, 0
        return min(hours, 23), minutes

    @api.model
    def _shift_to_next_working_day(self, dt_local, work_days):
        """Same clock time, next working day."""
        nxt = dt_local + timedelta(days=1)
        guard = 0
        while nxt.weekday() not in work_days and guard < 14:
            nxt += timedelta(days=1)
            guard += 1
        return nxt

    def _working_deadline(self, start_dt_utc):
        """Deadline = same clock time on the next working day.

        If the clock started outside the working window (evening, or on
        a Friday) it is first pulled forward to the start of the next
        working day, so the counterparty always gets a full working day
        of real availability.
        """
        self.ensure_one()
        if not start_dt_utc:
            return False
        tz_name, work_days, hour_from, hour_to = self._get_work_schedule()
        if not work_days:
            work_days = DEFAULT_WORK_DAYS
        tz = pytz.timezone(tz_name)
        local = pytz.utc.localize(start_dt_utc).astimezone(tz)

        start_h, start_m = self._float_to_time_parts(hour_from)
        clock = local.hour + local.minute / 60.0

        if local.weekday() not in work_days or clock >= hour_to:
            # Outside the working window - restart at the next working
            # day's opening time.
            local = self._shift_to_next_working_day(local, work_days)
            local = local.replace(hour=start_h, minute=start_m,
                                  second=0, microsecond=0)
        elif clock < hour_from:
            # Same day, but before opening time.
            local = local.replace(hour=start_h, minute=start_m,
                                  second=0, microsecond=0)

        deadline_local = self._shift_to_next_working_day(local, work_days)
        return deadline_local.astimezone(pytz.utc).replace(tzinfo=None)

    def _today_local(self):
        """Today's date in the working schedule's timezone (Asia/Riyadh
        by default). A cron runs as OdooBot, whose timezone is usually
        UTC, so fields.Date.context_today would roll over at the wrong
        moment for the client."""
        # NO ensure_one() - the idle-hours cron legitimately calls this
        # on an EMPTY recordset (it needs "what is today" before it has
        # any record in hand), and ensure_one() crashed it with
        # "Expected singleton". Nothing here reads record data:
        # _get_work_schedule() already falls back to self.env.company.
        return self._now_local().date()

    def _now_local(self):
        """Right now, in the working schedule's timezone."""
        tz_name = self._get_work_schedule()[0]
        return pytz.utc.localize(
            fields.Datetime.now()).astimezone(pytz.timezone(tz_name))

    def _has_task_due_to_start(self):
        """True when at least one task was due to start today or earlier.

        The manager's note that most tasks carry the same start and end
        date is why the START date is the trigger: waiting for the end
        date would mean the work is already late before it is released.
        """
        self.ensure_one()
        today = self._today_local()
        return any(line.start_date and line.start_date <= today
                   for line in self.task_line_ids)

    def _waiting_grace_expired(self):
        """True when this record has been waiting longer than one full
        working day in its current waiting state."""
        self.ensure_one()
        # Records created before pending_since existed fall back to their
        # last write date.
        started = self.pending_since or self.write_date
        if not started:
            return False
        deadline = self._working_deadline(started)
        return bool(deadline) and fields.Datetime.now() > deadline

    def _waiting_deadline_display(self):
        """Deadline as a plain datetime, for messages and debugging."""
        self.ensure_one()
        started = self.pending_since or self.write_date
        return self._working_deadline(started) if started else False

    # ==================================================================
    # COMPUTES
    # ==================================================================
    @api.depends('employee_id')
    def _compute_employee_details(self):
        """System auto-fills department, manager and company (TDD 6.1)."""
        for rec in self:
            if rec.employee_id:
                rec.department_id = rec.employee_id.department_id
                rec.manager_id = rec.employee_id.parent_id
            else:
                rec.department_id = False
                rec.manager_id = False

    @api.depends('task_line_ids')
    def _compute_task_count(self):
        for rec in self:
            rec.task_count = len(rec.task_line_ids)

    @api.depends('task_line_ids.progress', 'task_line_ids.task_status',
                 'task_line_ids.total_hours')
    def _compute_progress(self):
        """Roll the task lines up, weighted by each task's HOURS.

        Same rule the activities now follow (Feedback #5 point 3): a
        plain average made a one-hour task count as much as an
        eight-hour one, so a list could read 50% with nearly all the
        real work still outstanding. Falls back to a plain average when
        no task carries hours, so a list still being planned never
        divides by zero.
        """
        for rec in self:
            lines = rec.task_line_ids
            if not lines:
                rec.progress = 0.0
                continue
            total_hours = sum(lines.mapped('total_hours'))
            if total_hours <= 0:
                rec.progress = round(
                    sum(lines.mapped('progress')) / len(lines), 2)
            else:
                rec.progress = round(sum(
                    line.progress * line.total_hours for line in lines
                ) / total_hours, 2)

    @api.depends('task_line_ids.end_date', 'task_line_ids.task_status',
                 'state', 'pending_since')
    def _compute_is_delayed(self):
        """QA point 16: a task list that is simply waiting for the
        manager is NOT delayed - it only becomes delayed once it has sat
        in that waiting state for more than one working day. Draft,
        Returned, Completed and Closed lists are never delayed."""
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.state in WAITING_STATES:
                rec.is_delayed = rec._waiting_grace_expired()
            elif rec.state in ('manager_approved',) + EXECUTION_STATES:
                rec.is_delayed = any(
                    line.end_date and line.end_date < today
                    and line.task_status not in ('completed', 'closed')
                    for line in rec.task_line_ids)
            else:
                # draft, returned_manager, completed, closed, rejected
                rec.is_delayed = False

    def _search_is_delayed(self, operator, value):
        candidates = self.search([
            ('state', 'in', list(WAITING_STATES) + ['manager_approved']
             + list(EXECUTION_STATES)),
        ])
        delayed_ids = candidates.filtered('is_delayed').ids
        if (operator == '=' and value) or (operator == '!=' and not value):
            return [('id', 'in', delayed_ids)]
        return [('id', 'not in', delayed_ids)]

    @api.depends('task_line_ids.delayed_days', 'state')
    def _compute_delayed_days(self):
        """Worst-line rollup of employee.task.line.delayed_days - the
        numeric counterpart of is_delayed's ANY-based rollup. Scoped to
        the execution states, same as is_delayed's execution branch;
        the waiting-for-approval delay (pending_since /
        _waiting_grace_expired) is a different concept and stays
        boolean-only for now."""
        for rec in self:
            # Draft / Submitted / Pending Acceptance / Modification
            # Requested: execution has not begun, so an end-date delay
            # is not meaningful yet (that wait is tracked separately by
            # is_delayed + pending_since).
            #
            # Completed, Closed and Rejected DO keep their figure: the
            # lines settle on End Date -> Completion Date, and a task
            # list that finished a day late is still a day late once the
            # manager closes it. Excluding them here reset the number to
            # 0 on close, which is what the manager reported.
            if rec.state not in REPORTABLE_DELAY_STATES:
                rec.delayed_days = 0
                continue
            rec.delayed_days = max(
                rec.task_line_ids.mapped('delayed_days') or [0])

    @api.depends('state')
    def _compute_color(self):
        """Kanban card color indicators (TDD Section 11)."""
        color_map = {
            'draft': 0,                        # grey
            'submitted_manager': 2,            # orange
            'pending_acceptance': 2,           # orange
            'modification_requested': 2,       # orange
            'manager_approved': 4,             # blue
            'in_progress': 6,                  # purple-ish
            'completed': 10,                   # green
            'returned_manager': 1,             # red
            'returned_after_completion': 1,    # red
            'closed': 8,                       # dark grey
            'rejected': 1,                     # red
        }
        for rec in self:
            rec.color = color_map.get(rec.state, 0)

    @api.depends('is_unlocked', 'manager_id', 'employee_id',
                 'employee_id.department_id', 'employee_id.parent_id')
    def _compute_user_flags(self):
        is_manager_group = self.env.user.has_group(
            'employee_task_management.group_task_manager')
        is_admin_group = self.env.user.has_group(
            'employee_task_management.group_task_admin')
        privileged = is_manager_group or is_admin_group
        for rec in self:
            rec.is_current_user_manager = (
                rec.manager_id and rec.manager_id.user_id == self.env.user)
            rec.is_current_user_employee = (
                rec.employee_id and rec.employee_id.user_id == self.env.user)
            # "Only HIS employees": the manager named on THIS task list,
            # not any manager. An Administrator is included as the usual
            # escape hatch.
            rec.can_act_for_employee = (
                rec.is_current_user_employee
                or rec.is_current_user_manager
                or self.env.user.has_group(
                    'employee_task_management.group_task_admin'))
            rec.can_edit_unlocked = rec.is_unlocked and privileged
            # QA point 24: a plain employee may not pick another person.
            rec.can_select_employee = privileged
            # Department / Manager are locked for a plain employee, BUT
            # only when the HR record actually supplies them. If the
            # hr.employee has no Department (or no Manager) the field
            # stays editable, otherwise the employee would face a
            # required-but-read-only field and could never save at all.
            rec.can_edit_department = (
                privileged or not rec.employee_id.department_id)
            rec.can_edit_manager = (
                privileged or not rec.employee_id.parent_id)

    @api.depends('task_line_ids.subtask_ids')
    def _compute_has_task_without_activity(self):
        for rec in self:
            rec.has_task_without_activity = any(
                not line.subtask_ids for line in rec.task_line_ids)

    @api.depends('employee_id')
    def _compute_allowed_selection(self):
        """Bug 6: a Manager must only be able to pick employees and
        departments of his own team / department - not the whole company.
        A Task Administrator keeps the full choice; a plain Employee is
        limited to himself (the fields are read-only for him anyway).

        Same pattern Odoo core uses for account.move.suitable_journal_ids:
        a non-stored computed m2m consumed by domain="[('id','in',...)]".
        """
        user = self.env.user
        employee_model = self.env['hr.employee']
        department_model = self.env['hr.department']
        is_admin = user.has_group(
            'employee_task_management.group_task_admin')
        is_manager = user.has_group(
            'employee_task_management.group_task_manager')
        own_employee = user.employee_id
        if is_admin:
            employees = employee_model.search([])
            departments = department_model.search([])
        elif is_manager:
            employees = employee_model.search([
                '|',
                ('parent_id.user_id', '=', user.id),
                ('department_id.manager_id.user_id', '=', user.id),
            ]) | own_employee
            departments = department_model.search([
                '|',
                ('manager_id.user_id', '=', user.id),
                ('id', 'in', employees.mapped('department_id').ids),
            ]) | own_employee.department_id
        else:
            employees = own_employee
            departments = own_employee.department_id
        for rec in self:
            # Never hide the value already stored on the record, otherwise
            # an existing task list would look empty to its reader.
            rec.allowed_employee_ids = employees | rec.employee_id
            rec.allowed_department_ids = (
                departments | rec.department_id)

    @api.depends('task_line_ids.subtask_ids.name',
                 'task_line_ids.subtask_ids.is_done',
                 'task_line_ids.subtask_ids.hours',
                 'task_line_ids.description')
    def _compute_activity_update_log(self):
        for rec in self:
            rows = []
            for line in rec.task_line_ids:
                for act in line.subtask_ids:
                    mark = '\u2713' if act.is_done else '\u25cb'
                    rows.append(
                        '<li>%s <b>%s</b> - %s (%.1fh)</li>' % (
                            mark, act.name,
                            (line.description or '')[:40],
                            act.hours or 0.0))
            rec.activity_update_log = (
                '<ul>%s</ul>' % ''.join(rows)) if rows else (
                '<p class="text-muted">%s</p>' % _('No activities logged yet.'))

    # ==================================================================
    # KANBAN COLUMN ORDER
    # ==================================================================
    @api.model
    def _group_expand_state(self, states, domain=None, order=None):
        """Decide which status columns appear, and in which order.

        Without this Odoo groups by the raw database value, so the
        Kanban columns come out alphabetically by technical key -
        Closed, Completed, Draft, In Progress... - which is meaningless
        to a user. Returning an explicit list here fixes both the order
        and the set of columns.

        The seven core workflow columns are always present, even when
        empty, so the board reads as the process itself. The exception
        states only appear when they actually hold records.
        """
        all_states = [key for key, _label in self._fields['state'].selection]
        populated = set(states or [])
        return [state for state in all_states
                if state in KANBAN_CORE_STATES or state in populated]

    # ==================================================================
    # VIEW POST-PROCESSING
    # ==================================================================
    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        """QA points 13/14/15: the Kanban board is read-only - cards may
        not be dragged from one column to another, because that silently
        changes the workflow status. Only a Task Administrator keeps the
        ability to drag."""
        arch, view = super()._get_view(
            view_id=view_id, view_type=view_type, **options)
        if view_type == 'kanban':
            is_admin = self.env.user.has_group(
                'employee_task_management.group_task_admin')
            for node in arch.iter('kanban'):
                node.set('records_draggable', '1' if is_admin else '0')
        return arch, view

    # ==================================================================
    # CREATE / WRITE / UNLINK
    # ==================================================================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # The reference is NO LONGER drawn here. A draft is a
            # private scratchpad that may never go anywhere, and every
            # abandoned one used to burn a sequence number permanently,
            # leaving gaps in the client's numbering. The number is now
            # drawn on the way OUT of Draft - see _assign_reference().
            vals.setdefault('name', _('New'))
            # Safety net next to precompute=True above: whatever the
            # client did or did not send, derive Department and Manager
            # from the employee before the row is inserted.
            if vals.get('employee_id') and not (
                    vals.get('department_id') and vals.get('manager_id')):
                employee = self.env['hr.employee'].sudo().browse(
                    vals['employee_id'])
                if not vals.get('department_id'):
                    vals['department_id'] = employee.department_id.id or False
                if not vals.get('manager_id'):
                    vals['manager_id'] = employee.parent_id.id or False
        records = super().create(vals_list)
        records._check_assign_date()
        records._pull_carried_forward_tasks()
        return records

    @api.model
    def _activities_to_carry(self, source_line):
        """Which of a rejected task's activities come back for redoing.

        Agreed rule: only the ones that were NOT completed - if a task
        had 5 activities, 3 done and was rejected over the other 2, the
        employee redoes just those 2.

        Fallback: if EVERY activity was already ticked done (the manager
        rejected the task on quality, not on unfinished work) there is
        nothing left to carry, and a task with no activities cannot be
        saved by an employee at all. In that case the whole set comes
        back reset, so the task is always actionable.
        """
        refused = source_line.subtask_ids.filtered(
            lambda a: a.manager_verdict == 'rejected')
        if refused:
            return refused
        # Fallback for tasks rejected BEFORE activity-level review
        # existed (every activity still Pending), and for a task
        # rejected as a whole while it was still running, where some
        # activities may genuinely be unfinished.
        unfinished = source_line.subtask_ids.filtered(lambda a: not a.is_done)
        return unfinished or source_line.subtask_ids

    @api.model
    def _carry_forward_default_date(self):
        """The date a carried-forward task lands on.

        Start / End Date became REQUIRED in 1.16.0, so the old
        behaviour of copying rejected tasks across with the dates left
        blank now hits a NOT NULL violation the moment the record is
        flushed - the employee saw a raw "a mandatory field is not set"
        error on Start Date and could not save at all.

        The intent behind blanking them was that the employee re-plans,
        and that still holds: he can change these freely. They just have
        to start from a value that is legal, which means a WORKING day -
        dropping a carried task onto a Friday would be rejected on save
        by _check_working_date_range, trading one blocked save for
        another.

        The next working day AFTER today, not today itself. Today's
        capacity was already spent on the work that got rejected - those
        hours still count, because the employee really did work them -
        so seeding the redo onto today would collide with the original
        and could not be saved. Tomorrow is the first day that has room.
        """
        day = self._today_local() + timedelta(days=1)
        work_days = self._get_planning_work_days()
        for _offset in range(14):
            if day.weekday() in work_days:
                return day
            day += timedelta(days=1)
        return self._today_local() + timedelta(days=1)

    def _carry_forward_commands(self, employee_id):
        """One2many CREATE commands for every task this employee still
        owes, ready to drop straight into task_line_ids.

        Used by default_get and by the employee_id onchange so the tasks
        show up THE MOMENT the form opens - previously they only
        appeared after the first save, which made them look like they
        had been added by something the employee did.
        """
        if not employee_id:
            return []
        pending = self.env['employee.task.line'].sudo().search([
            ('carry_forward_pending', '=', True),
            ('task_list_id.employee_id', '=', employee_id),
        ])
        commands = []
        replan_date = self._carry_forward_default_date()
        for source in pending:
            commands.append((0, 0, {
                'description': source.description,
                'remarks': source.remarks,
                # Seeded with the next working day, NOT blank: the dates
                # are required since 1.16.0 and a blank one cannot be
                # saved. The employee still re-plans - he just edits a
                # valid value instead of filling an empty one.
                'start_date': replan_date,
                'end_date': replan_date,
                'is_carried_forward': True,
                'carried_from_line_id': source.id,
                'subtask_ids': [
                    (0, 0, {
                        'name': a.name,
                        'hours': a.hours,
                        'sequence': a.sequence,
                        'is_done': False,
                    }) for a in self._activities_to_carry(source)
                ],
            }))
        return commands

    @api.model
    def default_get(self, fields_list):
        """Pre-load rejected tasks onto a brand-new form straight away."""
        res = super().default_get(fields_list)
        if 'task_line_ids' in fields_list and not res.get('task_line_ids'):
            employee_id = res.get('employee_id')
            if not employee_id:
                employee = self.env.user.employee_id
                employee_id = employee.id if employee else False
            commands = self._carry_forward_commands(employee_id)
            if commands:
                res['task_line_ids'] = commands
        return res

    @api.onchange('employee_id')
    def _onchange_employee_carry_forward(self):
        """A manager picking a different employee should immediately see
        that employee's outstanding rejected tasks instead of the
        previous one's."""
        if self._origin.id:
            # Only ever pre-fills a brand-new, unsaved record.
            return
        keep = self.task_line_ids.filtered(lambda l: not l.is_carried_forward)
        self.task_line_ids = keep
        commands = self._carry_forward_commands(
            self.employee_id.id if self.employee_id else False)
        for command in commands:
            self.task_line_ids = [(0, 0, command[2])]

    def _pull_carried_forward_tasks(self):
        """Copy any tasks the manager rejected on an earlier task list
        into this brand-new one.

        Agreed behaviour: the whole task comes across, with every
        activity reset to not-done and the dates seeded with the next
        working day so the employee re-plans them. The source task is un-flagged so it can
        never be pulled twice.
        """
        for rec in self:
            if not rec.employee_id or rec.state != 'draft':
                continue
            # Lines the form already pre-loaded (see _carry_forward_commands,
            # which fills them in the moment the form opens) must not be
            # copied a second time when the record is finally saved.
            already_here = rec.task_line_ids.mapped('carried_from_line_id').ids
            pending = self.env['employee.task.line'].sudo().search([
                ('carry_forward_pending', '=', True),
                ('task_list_id.employee_id', '=', rec.employee_id.id),
                ('task_list_id', '!=', rec.id),
                ('id', 'not in', already_here),
            ])
            # Whether they arrived via the form or are being copied right
            # now, every source this list carries is settled.
            self.env['employee.task.line'].sudo().browse(
                already_here).with_context(etm_workflow=True).write(
                    {'carry_forward_pending': False})
            if not pending:
                continue
            replan_date = rec._carry_forward_default_date()
            for source in pending:
                new_line = self.env['employee.task.line'].sudo().with_context(
                    etm_workflow=True).create({
                        'task_list_id': rec.id,
                        'description': source.description,
                        # Same as _carry_forward_commands: seeded with a
                        # valid working day rather than left blank.
                        'start_date': replan_date,
                        'end_date': replan_date,
                        'remarks': source.remarks,
                        'is_carried_forward': True,
                        'carried_from_line_id': source.id,
                    })
                # Only the unfinished activities come back - see
                # _activities_to_carry for the all-done fallback.
                for activity in self._activities_to_carry(source):
                    self.env['employee.task.subtask'].sudo().with_context(
                        etm_workflow=True).create({
                            'task_line_id': new_line.id,
                            'name': activity.name,
                            'hours': activity.hours,
                            'sequence': activity.sequence,
                            'is_done': False,
                        })
            pending.sudo().with_context(etm_workflow=True).write(
                {'carry_forward_pending': False})
            rec.message_post(body=_(
                '%(count)s task(s) rejected on an earlier task list were '
                'added here automatically and must be redone. Only the '
                'activities that were not completed have come across, '
                'dated %(day)s - change the dates to suit your plan.',
                day=replan_date,
                count=len(pending)))
            _logger.info(
                "Carried %s rejected task(s) forward into %s",
                len(pending), rec.name)

    def _task_line_commands_are_remarks_only(self, commands):
        """True when every command in a task_line_ids write is purely an
        UPDATE of the Remarks field on an existing line - lets Remarks
        stay editable on a Closed/Rejected task list without opening up
        anything else (adding/removing a line, or any other field)."""
        if not commands:
            return False
        for cmd in commands:
            if not isinstance(cmd, (list, tuple)) or not cmd:
                return False
            if cmd[0] != 1:  # only (1, id, {vals}) UPDATE commands allowed
                return False
            if len(cmd) < 3 or not isinstance(cmd[2], dict):
                return False
            if set(cmd[2].keys()) - {'remarks'}:
                return False
        return True

    def write(self, vals):
        # Validation 9: Closed task lists cannot be edited (TDD Section 14)
        protected_keys = set(vals.keys()) - {
            'message_follower_ids', 'activity_ids', 'message_ids',
            'message_main_attachment_id'}
        # Remarks stays editable on a task line in EVERY state, including
        # Closed/Rejected - if every command inside task_line_ids is
        # purely a Remarks update on an existing line, this guard has
        # nothing to say about it.
        if 'task_line_ids' in protected_keys and \
                self._task_line_commands_are_remarks_only(
                    vals.get('task_line_ids')):
            protected_keys.discard('task_line_ids')
        if protected_keys and not self.env.context.get('bypass_closed_lock') \
                and not self._is_privileged_user():
            for rec in self:
                if rec.state in TERMINAL_STATES and 'state' not in vals:
                    raise UserError(_(
                        '%s task list "%s" is final and cannot be edited.',
                        dict(rec._fields['state'].selection).get(rec.state),
                        rec.name))
        # QA points 13/14: the status may only move through the workflow
        # buttons - never by dragging a Kanban card or by a raw write.
        if 'state' in vals and not self.env.context.get('etm_workflow') \
                and not self.env.user.has_group(
                    'employee_task_management.group_task_admin'):
            # A plain form save re-sends the unchanged value - that is
            # harmless. Only a real status CHANGE outside the workflow
            # buttons (e.g. dragging a Kanban card) is refused.
            for rec in self:
                if rec.state != vals['state']:
                    raise UserError(_(
                        'The status of a task list can only be changed '
                        'with the workflow buttons on the form (Submit, '
                        'Approve, Accept, Start Work, Mark Completed, '
                        'Close...).'))
        # Checked against the task lines as they currently stand in the
        # database, i.e. before this save adds anything new. Skipped for
        # purely technical writes (chatter, workflow, stored computes) so
        # that posting a message never trips the validation.
        if set(vals.keys()) - INTERNAL_WRITE_KEYS \
                and not self.env.context.get('etm_workflow'):
            self._check_employee_activities('task_line_ids' in vals)
        res = super().write(vals)
        if 'assign_date' in vals:
            self._check_assign_date()
        return res

    def unlink(self):
        for rec in self:
            if rec.state != 'draft' and not self.env.user.has_group(
                    'employee_task_management.group_task_admin'):
                raise UserError(_(
                    'Only Draft task lists can be deleted. '
                    '"%s" is in %s state.', rec.name,
                    dict(rec._fields['state'].selection).get(rec.state)))
        return super().unlink()

    def _assign_reference(self):
        """Draw the task list reference, once and once only.

        THE GUARD IS THE WHOLE POINT: a number is only drawn for a
        record still sitting at the placeholder. A list returned for
        correction drops back to Draft and is submitted again - without
        this check it would take a SECOND number, and every reference
        already written into the chatter, into emails and into the
        approval history would point at a number the record no longer
        carries.

        So the rule is: a task list gets exactly one reference for its
        entire life, at the moment it first leaves Draft, and nothing
        afterwards can change it.
        """
        for rec in self:
            if rec.name and rec.name != _('New'):
                continue  # already numbered - never renumber
            reference = rec.env['ir.sequence'].next_by_code(
                'employee.task.list')
            if not reference:
                # No sequence configured. Leave the placeholder rather
                # than blocking the employee's submission over a
                # numbering problem - the record is still perfectly
                # usable and the reference can be repaired later.
                _logger.warning(
                    "No 'employee.task.list' sequence found - task list "
                    "%s left without a reference", rec.id)
                continue
            rec.with_context(etm_workflow=True).write({'name': reference})

    def _set_state(self, new_state, extra_vals=None):
        """Single entry point for every status change. Also maintains
        `pending_since`, the clock used by the 24 working-hour rules."""
        # Every route out of Draft passes through here - the employee
        # submitting, the manager assigning, the auto-assign cron, the
        # same-day auto-start, and anything added in future. Putting the
        # reference here rather than in each action means a new
        # transition can never be added that forgets to number the
        # record.
        if new_state != 'draft':
            self._assign_reference()
        vals = dict(extra_vals or {})
        vals['state'] = new_state
        # `needs_employee_planning` records HOW THE LIST WAS HANDED OVER,
        # not what it looks like right now. It was originally computed
        # live from "does any task lack activities", which meant the
        # moment the employee added them the flag flipped and the Accept
        # / Request Modification buttons came back before he had ever
        # accepted anything. Stamped once on the way IN to Pending
        # Acceptance, cleared on the way OUT, so the button set stays
        # stable for the whole episode.
        if 'pending_since' not in vals:
            vals['pending_since'] = (
                fields.Datetime.now() if new_state in WAITING_STATES else False)
        if 'needs_employee_planning' in vals or new_state != 'pending_acceptance':
            vals.setdefault('needs_employee_planning', False)
            self.with_context(etm_workflow=True).write(vals)
            return
        # Entering Pending Acceptance: the answer differs per record, so
        # each one is stamped with its OWN state at hand-over.
        for rec in self:
            rec.with_context(etm_workflow=True).write(dict(
                vals, needs_employee_planning=rec._plan_is_incomplete()))

    # ==================================================================
    # CONSTRAINTS / VALIDATIONS (TDD Section 14)
    # ==================================================================
    def _is_privileged_user(self):
        """Manager or Administrator. Mirrors the identically-named
        helper on employee.task.line / employee.task.subtask so the
        three models agree on who counts as privileged."""
        return (
            self.env.user.has_group(
                'employee_task_management.group_task_manager')
            or self.env.user.has_group(
                'employee_task_management.group_task_admin'))

    def _is_plain_employee(self):
        """The acting user is a plain Task Employee (not Manager/Admin)."""
        return not (
            self.env.user.has_group(
                'employee_task_management.group_task_manager')
            or self.env.user.has_group(
                'employee_task_management.group_task_admin'))

    @api.model
    def _check_employee_activities(self, touches_task_lines=False):
        """Employee role: a stored task must carry at least one activity.

        DELIBERATELY SKIPPED whenever the save touches task_line_ids at
        all. Rationale, learned from three separate deadlocks:

          * Activities can only be added through a dialog on an
            ALREADY-SAVED task line, so a new line must survive one save
            with no activities.
          * The capacity rule rejects activities that do not fit the
            line's dates, so the ONLY way to fit 11:00 of work is to
            widen the End Date first - which is itself a save.

        If this check fired on those saves, the employee would be left
        with no legal move in either direction. Previous versions tried
        to work this out by parsing the task_line_ids command payload;
        that was fragile and still let a deadlock through. The rule is
        now simply: if you are working on the tasks, you are not blocked.

        Nothing is waved through - action_submit_to_manager still calls
        _check_activities_before_submit(), so a task list can never
        REACH the manager carrying a task with no activities. This is a
        tidiness check on idle saves, not the real gate.

        A Manager / Administrator is exempt entirely (QA point 20) - he
        may hand over a bare task and let the employee plan it.
        """
        if touches_task_lines:
            return
        if not self._is_plain_employee():
            return
        for rec in self:
            # Only meaningful while the employee can still act on it -
            # from Manager Approved onwards the plan is frozen anyway.
            if rec.state not in EDITABLE_STATES:
                continue
            offenders = [
                line for line in rec.task_line_ids if not line.subtask_ids]
            if offenders:
                raise UserError(_(
                    'Every task must have at least one activity before the '
                    'task list can be saved.\n\nUse the Activities button '
                    'on the task line to add them - or remove the task if '
                    'you no longer need it.\n\nTasks without any '
                    'activity:\n%s',
                    '\n'.join('- %s' % (l.description or _('(no description)'))[:80]
                               for l in offenders)))

    def _check_assign_date(self):
        """Validation 3: Assign Date cannot be empty & before today's date."""
        for rec in self:
            if rec.state == 'draft' and rec.assign_date:
                create_date = fields.Date.context_today(rec)
                if rec.create_date:
                    create_date = fields.Date.to_date(rec.create_date)
                if rec.assign_date < create_date:
                    raise ValidationError(_(
                        'Assign Date cannot be before today\'s date.'))

    @api.constrains('employee_id', 'manager_id')
    def _check_manager_not_employee(self):
        for rec in self:
            if rec.employee_id and rec.manager_id and \
                    rec.employee_id == rec.manager_id:
                raise ValidationError(_(
                    'Employee and Manager cannot be the same person.'))

    # ==================================================================
    # HELPERS
    # ==================================================================
    def _log_approval_history(self, action, remarks=False):
        """Maintain approval history for audit purposes (TDD Section 23)."""
        self.ensure_one()
        self.env['employee.task.approval.history'].sudo().create({
            'task_list_id': self.id,
            'user_id': self.env.user.id,
            'action': action,
            'approval_level': 'manager' if action in (
                'approved', 'returned', 'closed', 'assigned',
                'returned_completed', 'rejected', 'resent') else 'employee',
            'state': self.state,
            'remarks': remarks or False,
        })

    def _notify_user(self, partner, subject, body, template_xmlid=False):
        """Send notification via inbox message, activity and email
        (TDD Section 15)."""
        self.ensure_one()
        if not partner:
            return
        # 1. System inbox (chatter notification)
        self.message_post(
            body=body, subject=subject,
            partner_ids=partner.ids,
            message_type='notification',
            subtype_xmlid='mail.mt_comment')
        # 2. Activity scheduling
        user = partner.user_ids[:1]
        if user:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=subject,
                note=body,
                user_id=user.id)
        # 3. Email through template
        if template_xmlid:
            template = self.env.ref(template_xmlid, raise_if_not_found=False)
            if template:
                template.send_mail(self.id, force_send=True)

    def _get_manager_partner(self):
        self.ensure_one()
        return self.manager_id.user_id.partner_id or \
            self.manager_id.work_contact_id

    def _get_employee_partner(self):
        self.ensure_one()
        return self.employee_id.user_id.partner_id or \
            self.employee_id.work_contact_id

    def _plan_is_incomplete(self):
        """True when any task is missing its activities or their hours.

        The same bar `_check_ready_for_execution` enforces, expressed as
        a question rather than an exception.
        """
        self.ensure_one()
        return (
            not self.task_line_ids
            or any(not line.subtask_ids
                   or any(a.hours <= 0 for a in line.subtask_ids)
                   for line in self.task_line_ids))

    def action_submit_activities_for_review(self):
        """Employee sends HIS OWN plan back to the manager for review.

        Replaces Accept / Request Modification when the manager handed
        over a bare task list. Deliberately lands in `submitted_manager`
        rather than a new state: that already means "waiting on the
        manager", already notifies him, already offers Approve and
        Return for Correction, and is already picked up by the start-date
        auto-assign - so if the manager never looks, the plan applies on
        the start date exactly like every other waiting list.
        """
        for rec in self:
            if rec.state != 'pending_acceptance':
                raise UserError(_(
                    'Activities can only be submitted for review while '
                    'the task list is pending your acceptance.'))
            rec._check_is_the_employee()
            rec._log_acted_on_behalf(_('Submit Activities for Review'))
            # Same completeness bar as Accept - a half-planned list is
            # no more reviewable than it is acceptable.
            rec._check_ready_for_execution()
            rec._set_state('submitted_manager')
            rec._log_approval_history('submitted')
            rec.message_post(body=_(
                '%(who)s planned the activities for this task list and '
                'submitted them for review.',
                who=rec.employee_id.name or self.env.user.name))
            rec._notify_user(
                rec._get_manager_partner(),
                _('Activities Submitted for Review'),
                _('%(who)s has planned the activities for task list '
                  '%(ref)s and submitted them for your review. You can '
                  'approve them, adjust the hours, or return the list.',
                  who=rec.employee_id.name or '', ref=rec.name))
        return True

    def _check_ready_for_execution(self):
        """Called right before the task list becomes applicable (Manager
        Approve, or Employee Accept). From that moment on nothing can be
        added any more, so the plan has to be complete NOW - regardless
        of who is acting."""
        self.ensure_one()
        if not self.task_line_ids:
            raise ValidationError(_(
                'Task list %s has no task. Add the tasks and their '
                'activities before it becomes applicable - once approved, '
                'tasks and activities are frozen.', self.name))
        for line in self.task_line_ids:
            if not line.subtask_ids:
                raise ValidationError(_(
                    'Task "%s" has no activity. Add the activities before '
                    'the task list becomes applicable - once approved, '
                    'activities can only be ticked off, not added.',
                    (line.description or '')[:80]))
            if any(a.hours <= 0 for a in line.subtask_ids):
                raise ValidationError(_(
                    'Hours are mandatory on every activity of task "%s".',
                    (line.description or '')[:80]))

    def _check_lines_content(self):
        """Shared content checks used before a list leaves Draft."""
        self.ensure_one()
        if not self.task_line_ids:
            raise ValidationError(_(
                'Task list cannot be submitted/assigned without at least '
                'one task line.'))
        if any(not line.description for line in self.task_line_ids):
            raise ValidationError(_(
                'Description is mandatory for every task line.'))

    # ==================================================================
    # WORKFLOW ACTIONS (TDD Section 6 & 19)
    # ==================================================================
    def action_submit_to_manager(self):
        """Employee submits the task list to the immediate manager (TDD 6.2)."""
        for rec in self:
            if rec.state not in ('draft', 'returned_manager'):
                raise UserError(_(
                    'Task list can only be submitted from Draft or '
                    'Returned state.'))
            rec._check_lines_content()
            # Validation: required fields are filled
            missing = []
            if not rec.employee_id:
                missing.append(_('Employee'))
            if not rec.department_id:
                missing.append(_('Department'))
            if not rec.manager_id:
                missing.append(_('Manager'))
            if not rec.assign_date:
                missing.append(_('Assign Date'))
            if missing:
                raise ValidationError(_(
                    'Please fill the required fields before submitting: %s',
                    ', '.join(missing)))
            # QA points 11 & 12: no submission without activities + hours
            rec._check_activities_before_submit()
            # The day's total across EVERY task list, not just this one.
            rec._check_daily_capacity_across_lists()
            rec._log_approval_history('submitted')
            if rec._starts_today_or_earlier():
                rec._start_without_waiting()
            else:
                # Future-dated work: the existing approval flow is
                # unchanged, deliberately. There is no urgency, so the
                # manager gets to look at it before anything happens.
                rec._set_state('submitted_manager')
                rec._notify_user(
                    rec._get_manager_partner(),
                    _('Task List Approval Required'),
                    _('A new task list %s has been submitted by employee %s '
                      'and requires your approval.',
                      rec.name, rec.employee_id.name),
                    'employee_task_management.mail_template_task_submitted')
        return True

    def _starts_today_or_earlier(self):
        """True when at least one task on this list is due to start now.

        This is the trigger for skipping the approval wait. The client's
        rule is stated as "Assignment Date = today AND Start Date =
        today", but assign_date has been auto-stamped and readonly since
        1.2.4 - it IS today at creation, always - so the only half that
        can actually vary is the start date. `<= today` rather than
        `== today` so a list submitted a day late still starts rather
        than silently falling back into the approval queue.
        """
        self.ensure_one()
        today = self._today_local()
        return any(line.start_date and line.start_date <= today
                   for line in self.task_line_ids)

    def _start_without_waiting(self):
        """Same-day work goes straight to In Progress.

        Only the tasks actually dated today start. A task on the same
        list that begins next week stays in Draft with its manager
        verdict still Pending - the manager rules on those individually,
        which is how the future-dated approval requirement survives a
        list that is already running.

        The list still needs the manager's Accept / Reject; that is what
        `started_without_approval` records, and it is stamped here at
        the event rather than computed later.
        """
        self.ensure_one()
        today = self._today_local()
        self._set_state('in_progress', {'started_without_approval': True})
        starting = self.task_line_ids.filtered(
            lambda l: l.task_status == 'draft'
            and l.start_date and l.start_date <= today)
        if starting:
            starting.with_context(etm_workflow=True).write(
                {'task_status': 'in_progress'})
        self.task_line_ids.with_context(
            etm_workflow=True)._recompute_progress_from_subtasks()
        later = self.task_line_ids - starting
        self._log_approval_history(
            'started',
            _('Start date had already arrived, so work began '
              'immediately without waiting for approval.'))
        self.message_post(body=_(
            '<b>Work started immediately</b> - %(now)s task(s) were due '
            'today. %(later)s task(s) dated later are still waiting for '
            'the manager\'s decision.',
            now=len(starting), later=len(later)))
        self._notify_user(
            self._get_manager_partner(),
            _('Task List Started - Review Required'),
            _('Employee %(emp)s submitted task list %(name)s for work '
              'due today, so it has gone straight to In Progress. '
              'Please accept or reject it.',
              emp=self.employee_id.name, name=self.name))
        self._notify_late_execution('started')

    def _accept_running_list(self):
        """Manager accepts a list that is already being worked on.

        The status deliberately STAYS at In Progress - the employee is
        mid-task and moving him backwards to Manager Approved would make
        him press Start Work again on work he has already begun. What
        changes is that the list is no longer awaiting a decision, and
        every task on it (including the future-dated ones that never
        started) is now formally approved.
        """
        self.ensure_one()
        pending = self.task_line_ids.filtered(
            lambda l: l.manager_verdict == 'pending')
        if pending:
            pending.with_context(etm_workflow=True).write(
                {'manager_verdict': 'approved'})
        self.with_context(etm_workflow=True).write(
            {'started_without_approval': False})
        self._log_approval_history('approved', self.manager_remarks)
        self.message_post(body=_(
            'Task list accepted by %s while already in progress. '
            '%s task(s) approved.', self.env.user.name, len(pending)))
        self._notify_user(
            self._get_employee_partner(),
            _('Task List Accepted'),
            _('Your task list %s has been accepted by %s. Carry on with '
              'the work.', self.name, self.env.user.name))

    def _check_daily_capacity_across_lists(self):
        """Submit-time gate for the whole list.

        The live constraint on employee.task.line catches the ordinary
        case as the employee types, but two lists can each sit in Draft
        at 8 hours: Draft does not consume capacity, so neither one
        blocks the other while both are still being written. Submitting
        is the moment one of them becomes real, so the totals are
        re-checked here against everything else already committed.
        """
        self.ensure_one()
        if self._is_privileged_user():
            return
        dated = self.task_line_ids.filtered(
            lambda l: l.start_date and l.end_date)
        if not dated or not self.employee_id:
            return
        Idle = self.env['employee.task.idle.day']
        Line = self.env['employee.task.line']
        date_from = min(dated.mapped('start_date'))
        date_to = max(dated.mapped('end_date'))
        per_day = Idle._allocation_for_employee(
            self.employee_id, date_from, date_to,
            include_list_ids=self.ids)
        capacity = self._get_hours_per_day()
        for day in sorted(per_day):
            if float_compare(per_day[day], capacity,
                             precision_digits=2) > 0:
                raise ValidationError(_(
                    'This task list cannot be submitted - not enough '
                    'capacity on %(day)s.\n\n'
                    'Employee: %(emp)s\n'
                    'Task list: %(name)s\n\n'
                    'Daily capacity: %(cap)s\n'
                    'Total once this list counts: %(total)s\n'
                    'Over by: %(over)s\n\n'
                    'What you can do:\n'
                    '  - reduce the activity hours on this list\n'
                    '  - move some tasks to a day with free capacity\n'
                    '  - extend a task\'s End Date so its hours spread '
                    'across more days\n\n'
                    'Note: hours already spent that day count even if '
                    'the manager rejected the work. Rejected work is '
                    'redone on a LATER day, not on the day it failed.',
                    day=day,
                    emp=self.employee_id.name or '',
                    name=self.name or '',
                    cap=Line._format_hours(capacity),
                    total=Line._format_hours(per_day[day]),
                    over=Line._format_hours(per_day[day] - capacity)))

    def _check_activities_before_submit(self):
        """QA point 11: a task list may not be submitted to the manager
        with tasks that carry no activity. Applies to the Employee role;
        a Manager submitting on behalf of somebody else is exempt
        (QA point 20)."""
        self.ensure_one()
        if not self._is_plain_employee():
            return
        for line in self.task_line_ids:
            if not line.subtask_ids:
                raise ValidationError(_(
                    'Task list cannot be submitted: task "%s" has no '
                    'activity. Add at least one activity with hours.',
                    (line.description or '')[:80]))
            if any(a.hours <= 0 for a in line.subtask_ids):
                raise ValidationError(_(
                    'Task list cannot be submitted: hours are mandatory '
                    'for every activity of task "%s".',
                    (line.description or '')[:80]))

    def action_manager_approve(self):
        """Manager approves a task list the employee submitted (TDD 6.3).
        The employee wrote it himself, so no acceptance step is needed -
        it becomes applicable straight away."""
        for rec in self:
            # A list that started on its own start date is already In
            # Progress but has never been ruled on. The manager still
            # has to accept it - he just must not knock it BACK to
            # Manager Approved, because the employee is working on it.
            running_review = (
                rec.state == 'in_progress' and rec.started_without_approval)
            if rec.state != 'submitted_manager' and not running_review:
                raise UserError(_(
                    'Only task lists in "Submitted to Manager" state can '
                    'be approved.'))
            rec._check_approver_rights()
            rec._check_ready_for_execution()
            if running_review:
                rec._accept_running_list()
                continue
            rec._set_state('manager_approved')
            rec._log_approval_history('approved', rec.manager_remarks)
            rec.activity_feedback(['mail.mail_activity_data_todo'])
            rec._notify_user(
                rec._get_employee_partner(),
                _('Task List Approved'),
                _('Your task list %s has been approved by manager %s and '
                  'is now applicable.', rec.name, rec.manager_id.name),
                'employee_task_management.mail_template_task_approved')
        return True

    def action_manager_return(self):
        """Manager returns the task list for correction (TDD 6.3), or
        sends a completed task list back to the employee. Opens a wizard
        that makes return remarks mandatory (Validation 7)."""
        self.ensure_one()
        if self.state != 'submitted_manager':
            raise UserError(_(
                'Return for Correction is only available for task lists '
                'in "Submitted to Manager" state. A completed task list '
                'is either Closed or Rejected.'))
        self._check_approver_rights()
        return {
            'name': _('Return Task List for Correction'),
            'type': 'ir.actions.act_window',
            'res_model': 'employee.task.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_task_list_id': self.id},
        }

    def _is_own_task_list(self):
        """True when the current user is the employee this task list
        belongs to.

        A department manager has a task list of his own, and reports to
        his own manager. He may run his subordinates' lists, but his own
        must go to HIS manager - so this is the single test every
        approver action shares.
        """
        self.ensure_one()
        return bool(
            self.employee_id.user_id
            and self.employee_id.user_id == self.env.user)

    def _check_approver_rights(self):
        """Validations 5 & 10: manager approval cannot be done by the
        employee himself; only authorized users can approve/reject.

        NO EXCEPTIONS, Administrator included: nobody signs off their
        own work. An admin who needs to unstick their own list has it
        approved by their own manager, exactly like everyone else.
        """
        self.ensure_one()
        if self._is_own_task_list():
            raise AccessError(_(
                'You cannot approve, return, close or reject your own '
                'task list (%s). It has to be actioned by your own '
                'manager%s.',
                self.name,
                _(' (%s)', self.manager_id.name) if self.manager_id else ''))
        if not (self.env.user.has_group(
                'employee_task_management.group_task_manager') or
                self.env.user.has_group(
                'employee_task_management.group_task_admin')):
            raise AccessError(_(
                'Only authorized users (Manager / Administrator) can '
                'approve or reject task lists.'))
        if self.env.user.has_group(
                'employee_task_management.group_task_manager') and not \
                self.env.user.has_group(
                'employee_task_management.group_task_admin'):
            if self.manager_id.user_id and \
                    self.manager_id.user_id != self.env.user:
                raise AccessError(_(
                    'Only the immediate manager (%s) can approve or '
                    'return this task list.', self.manager_id.name))

    def _log_acted_on_behalf(self, what):
        """Chatter note whenever somebody other than the employee drives
        one of the employee's own actions, so the record never implies
        the employee did something he did not."""
        self.ensure_one()
        if self.is_current_user_employee:
            return
        self.message_post(body=_(
            '<b>%(what)s</b> was done by %(actor)s on behalf of '
            '%(employee)s.',
            what=what, actor=self.env.user.name,
            employee=self.employee_id.name or _('the employee')))

    def _check_is_the_employee(self):
        """ONLY the employee the list belongs to may accept it, request a
        modification, start the work or mark it completed.

        NO EXCEPTIONS - Manager and Administrator included. Feedback #4
        points 3 and 4: the client saw managers being offered "Submit to
        Manager" and "Accept" on lists belonging to somebody else and
        called it a bug. These are the employee's own acts of
        commitment; a manager doing them on his behalf would put words
        in his mouth.

        This REVERSES the 1.6.0 reading of QA point 7. The manager's
        override on EDITING content (dates, hours, tasks, activities in
        any state) is deliberately untouched - see the privileged
        early-returns in _check_list_editable / _check_structure_editable
        / _check_activity_editable. Only the workflow buttons are his
        employee's alone.
        """
        self.ensure_one()
        if self.is_current_user_manager or self.env.user.has_group(
                'employee_task_management.group_task_admin'):
            # The manager THIS list reports to may act for his employee
            # (e.g. the employee is on leave). Recorded on the record so
            # it is never mistaken for the employee's own action.
            return
        if not (self.employee_id.user_id
                and self.employee_id.user_id == self.env.user):
            raise AccessError(_(
                'Only %s can perform this action on task list %s.',
                self.employee_id.name, self.name))

    # ---------------- Acceptance branch (QA points 17, 18, 22) --------
    def action_employee_accept(self):
        """QA point 17 / 22: a task list assigned by the manager is NOT
        applicable until the employee accepts it. Accepting makes it
        applicable and the employee can then start work."""
        for rec in self:
            if rec.state != 'pending_acceptance':
                raise UserError(_(
                    'Only a task list waiting for your acceptance can be '
                    'accepted.'))
            rec._check_is_the_employee()
            rec._log_acted_on_behalf(_('Accept'))
            rec._check_ready_for_execution()
            rec._set_state('manager_approved')
            rec._log_approval_history(
                'accepted', _('Accepted by %s', self.env.user.name))
            rec.activity_feedback(['mail.mail_activity_data_todo'])
            rec._notify_user(
                rec._get_manager_partner(),
                _('Task List Accepted'),
                _('Employee %s has accepted task list %s. It is now '
                  'applicable.', rec.employee_id.name, rec.name),
                'employee_task_management.mail_template_task_accepted')
        return True

    def action_request_modification(self):
        """QA point 18: employee asks the manager to change something
        (dates, hours, scope) before accepting the assigned task list."""
        self.ensure_one()
        if self.state != 'pending_acceptance':
            raise UserError(_(
                'A modification can only be requested while the task list '
                'is waiting for your acceptance.'))
        self._check_is_the_employee()
        self._log_acted_on_behalf(_('Request Modification'))
        return {
            'name': _('Request Modification'),
            'type': 'ir.actions.act_window',
            'res_model': 'employee.task.modification.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_task_list_id': self.id},
        }

    def action_resend_to_employee(self):
        """Manager has looked at the modification request, adjusted the
        task list and sends it back to the employee for acceptance."""
        for rec in self:
            if rec.state != 'modification_requested':
                raise UserError(_(
                    'Only a task list with a pending modification request '
                    'can be re-sent to the employee.'))
            rec._check_approver_rights()
            rec._set_state('pending_acceptance')
            rec._log_approval_history(
                'resent', _('Modified and re-sent by %s', self.env.user.name))
            rec._notify_user(
                rec._get_employee_partner(),
                _('Task List Updated - Please Accept'),
                _('Your modification request on task list %s has been '
                  'handled by %s. Please review and accept it.',
                  rec.name, self.env.user.name),
                'employee_task_management.mail_template_task_modified')
        return True

    @api.model
    def _cron_auto_apply(self):
        """Release a waiting task list once its work is due to start.

        A task list stuck in Submitted to Manager, Pending Employee
        Acceptance or Modification Requested is assigned to the employee
        automatically as soon as the START DATE of one of its tasks
        arrives. The work is due, so it must not stay blocked behind an
        approval or an acceptance that nobody actioned.

        It moves to Manager Approved - the employee still presses Start
        Work himself.

        NOTE: this replaced the earlier rule, which released a task list
        one working day after the manager ignored a modification request.
        `pending_since` and `_working_deadline()` are still maintained,
        but now only feed the Delayed calculation (QA point 16).

        A task list whose plan is incomplete is skipped on purpose: from
        Manager Approved onwards nothing can be added any more, so
        auto-applying it would create a record nobody could ever finish.
        """
        waiting = self.search([('state', 'in', list(AUTO_ASSIGN_STATES))])
        for rec in waiting:
            if not rec._has_task_due_to_start():
                continue
            try:
                rec._check_ready_for_execution()
            except ValidationError as err:
                _logger.info(
                    "Auto-assign skipped for %s - plan incomplete: %s",
                    rec.name, err)
                continue

            previous_state = dict(
                rec._fields['state'].selection).get(rec.state)
            reason = _(
                'Start date reached while the task list was still in '
                '"%s" - assigned to the employee automatically.',
                previous_state)

            # The status change gets its own savepoint. A notification
            # problem (SMTP down, no mail server) must never roll it back.
            try:
                with self.env.cr.savepoint():
                    rec.sudo()._set_state('manager_approved')
                    rec.sudo()._log_approval_history('auto_applied', reason)
            except Exception:
                _logger.exception(
                    "Auto-assign failed for task list %s", rec.name)
                continue

            _logger.info(
                "Auto-assigned task list %s (was %s, start date reached)",
                rec.name, previous_state)

            employee_body = _(
                'The start date of task list %s has arrived while it was '
                'still waiting in "%s", so it has been assigned to you '
                'automatically. You may start work.',
                rec.name, previous_state)
            manager_body = _(
                'Task list %s was assigned to %s automatically - its start '
                'date arrived while the task list was still in "%s".',
                rec.name, rec.employee_id.name, previous_state)

            try:
                with self.env.cr.savepoint():
                    rec.sudo()._notify_user(
                        rec._get_employee_partner(),
                        _('Task List Auto-Assigned'), employee_body,
                        'employee_task_management.'
                        'mail_template_task_auto_applied')
                    rec.sudo()._notify_user(
                        rec._get_manager_partner(),
                        _('Task List Auto-Assigned'), manager_body)
            except Exception:
                _logger.exception(
                    "Auto-assign notification failed for task list %s",
                    rec.name)
        try:
            with self.env.cr.savepoint():
                self._cron_flag_delayed()
        except Exception:
            _logger.exception("Delayed flagging pass failed")
        return True

    def _latch_delays(self):
        """Single entry point for latching delay history - both the
        boolean (was_delayed) and the day-count (was_delayed_days), at
        both the task-line and the task-list level. Never decreases
        anything; only raises the latched values when the live ones
        exceed them. Called from _notify_late_execution (Start Work /
        Mark Completed) and _cron_flag_delayed (hourly sweep) so both
        triggers stay consistent with each other."""
        self.ensure_one()
        for line in self.task_line_ids.filtered(
                lambda l: l.delayed_days > l.was_delayed_days):
            line.with_context(etm_workflow=True).write(
                {'was_delayed_days': line.delayed_days})
        worst = max(self.task_line_ids.mapped('was_delayed_days') or [0])
        vals = {}
        if not self.was_delayed and worst > 0:
            vals['was_delayed'] = True
        if worst > self.was_delayed_days:
            vals['was_delayed_days'] = worst
        if vals:
            self.sudo().with_context(etm_workflow=True).write(vals)

    @api.model
    def _cron_flag_delayed(self):
        """Latch delay history (was_delayed / was_delayed_days) on task
        lists that have gone past their date while still running.
        Without this, a list that ran late but was finished on the
        same day it slipped would never get flagged -
        _notify_late_execution only fires at Start Work and at Mark
        Completed.

        Re-evaluates every currently-late running record on each pass,
        not just ones not yet flagged - was_delayed_days needs to keep
        climbing while a task stays late, rather than freezing at
        whatever it was the first time was_delayed flipped True.
        """
        running = self.search([
            ('state', 'in', ['manager_approved'] + list(EXECUTION_STATES)),
        ])
        late = running.filtered('is_delayed')
        for rec in late:
            rec._latch_delays()
        if late:
            _logger.info(
                "Flagged %s task list(s) as delayed", len(late))
        return True

    @api.model
    def _cron_auto_apply_modification_requests(self):
        """Kept so an existing ir.cron record pointing at the old method
        name keeps working after the upgrade."""
        return self._cron_auto_apply()

    # ---------------- Execution branch -------------------------------
    def action_start_work(self):
        """Employee starts work after the task list is applicable
        (TDD 6.4). Only from Manager Approved."""
        for rec in self:
            if rec.state != 'manager_approved':
                raise UserError(_(
                    'Work can only be started once the task list is '
                    'approved and applicable.'))
            rec._check_is_the_employee()
            rec._log_acted_on_behalf(_('Start Work'))
            rec._set_state('in_progress')
            starting = rec.task_line_ids.filtered(
                lambda l: l.task_status == 'draft')
            # NEVER overwrite a planned start date. Stamping today over it
            # destroyed the plan and, on a task whose dates had already
            # passed, produced an End Date earlier than the Start Date.
            # Only tasks left without a start date get one - and it is
            # clamped to the End Date, so filling a blank can never
            # produce a range that ends before it begins.
            today = fields.Date.context_today(rec)
            for line in starting.filtered(lambda l: not l.start_date):
                stamp = min(today, line.end_date) if line.end_date else today
                line.with_context(etm_workflow=True).write(
                    {'start_date': stamp})
            starting.with_context(etm_workflow=True).write(
                {'task_status': 'in_progress'})
            # Re-sync any status left stale by an earlier close/unlock
            rec.task_line_ids.with_context(
                etm_workflow=True)._recompute_progress_from_subtasks()
            rec._log_approval_history('started')
            rec._notify_late_execution('started')
        return True

    def _notify_late_execution(self, moment):
        """Work is allowed to run late - it is not blocked - but it must
        not run late silently. Posts a note on the chatter and pings the
        manager when work starts, or is completed, after the date it was
        planned for.

        `moment` is 'started' or 'completed'.
        """
        self.ensure_one()
        today = self._today_local()
        if moment == 'started':
            late = self.task_line_ids.filtered(
                lambda l: l.start_date and l.start_date < today)
            if not late:
                return
            worst = min(late.mapped('start_date'))
            days = self._working_days_between(worst, today) - 1
            subject = _('Work Started Late')
            body = _(
                'Work on task list %(name)s started on %(today)s, '
                '%(days)s working day(s) after the planned start date '
                '(%(planned)s). %(count)s task(s) affected.',
                name=self.name, today=today, days=max(days, 0),
                planned=worst, count=len(late))
        else:
            late = self.task_line_ids.filtered(
                lambda l: l.end_date and l.end_date < today)
            if not late:
                return
            worst = min(late.mapped('end_date'))
            days = self._working_days_between(worst, today) - 1
            subject = _('Completed After the Planned Date')
            body = _(
                'Task list %(name)s was completed on %(today)s, '
                '%(days)s working day(s) after the planned end date '
                '(%(planned)s). %(count)s task(s) finished late.',
                name=self.name, today=today, days=max(days, 0),
                planned=worst, count=len(late))
        # Latch delay history before notifying: the flag matters more
        # than the mail, and it must survive the record being
        # completed and closed. Runs regardless of which moment
        # triggered this - it recomputes independently from the
        # current end-date-based delayed_days on each line.
        self._latch_delays()
        try:
            with self.env.cr.savepoint():
                self.message_post(body=body, subject=subject)
                self._notify_user(self._get_manager_partner(), subject, body)
        except Exception:
            # A notification must never block the employee's work.
            _logger.exception(
                "Late-execution notice failed for task list %s", self.name)

    def action_mark_completed(self):
        """Employee marks the task list as completed (TDD 6.5).

        QA final point: completion is refused unless the real progress of
        every task is 100% - the status label alone is not trusted."""
        for rec in self:
            if rec.state not in EXECUTION_STATES:
                raise UserError(_(
                    'Only a task list that is In Progress (or returned '
                    'after completion) can be marked as completed.'))
            rec._check_is_the_employee()
            rec._log_acted_on_behalf(_('Mark Completed'))
            if not rec.task_line_ids:
                raise ValidationError(_(
                    'Task list cannot be completed without any task.'))
            no_activity = rec.task_line_ids.filtered(
                lambda l: not l.subtask_ids)
            if no_activity:
                raise ValidationError(_(
                    'Task list cannot be completed - the following tasks '
                    'have no activity:\n%s',
                    '\n'.join('- %s' % (l.description or '')[:80]
                              for l in no_activity)))
            not_done = rec.task_line_ids.filtered(
                lambda l: l.progress < 100.0)
            if not_done:
                raise ValidationError(_(
                    'Task list cannot be marked as Completed while its '
                    'progress is below 100%%.\n\nPending tasks:\n%s',
                    '\n'.join('- %s (%.0f%%)' % (
                        (l.description or '')[:70], l.progress)
                        for l in not_done)))
            rec._set_state(
                'completed', {'completion_date': fields.Date.context_today(rec)})
            rec._log_approval_history('completed')
            rec._notify_late_execution('completed')
            rec._notify_user(
                rec._get_manager_partner(),
                _('Task List Completed - Review Required'),
                _('Employee %s has marked task list %s as completed. '
                  'Please review and close it.',
                  rec.employee_id.name, rec.name),
                'employee_task_management.mail_template_task_completed')
            rec._notify_user(
                rec._get_employee_partner(),
                _('Task List Marked Completed'),
                _('Your task list %s has been marked as completed and '
                  'sent to your manager for final review.', rec.name))
        return True

    def action_reject(self):
        """Manager rejects a completed task list. Opens a wizard that
        makes the Reject Reason mandatory. Rejection is final - the task
        list ends there, it does not go back to the employee."""
        self.ensure_one()
        running_review = (
            self.state == 'in_progress' and self.started_without_approval)
        if self.state != 'completed' and not running_review:
            raise UserError(_(
                'Only a task list the employee marked as Completed - or '
                'one that started without approval - can be rejected.'))
        self._check_approver_rights()
        return {
            'name': _('Reject Task List'),
            'type': 'ir.actions.act_window',
            'res_model': 'employee.task.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_task_list_id': self.id},
        }

    def action_close(self):
        """Manager closes the task list after review (TDD 6.6)."""
        for rec in self:
            if rec.state != 'completed':
                raise UserError(_(
                    'Only completed task lists can be closed.'))
            rec._check_approver_rights()
            # Any task the manager did not explicitly rule on counts as
            # approved - closing the list IS the approval. This keeps
            # the old whole-list behaviour intact for anyone who never
            # touches the per-task buttons.
            untouched = rec.task_line_ids.filtered(
                lambda l: l.manager_verdict == 'pending')
            if untouched:
                untouched.with_context(etm_workflow=True).write(
                    {'manager_verdict': 'approved'})
            rec._set_state('closed', {'is_unlocked': False})
            rec.task_line_ids.with_context(etm_workflow=True).write(
                {'task_status': 'closed'})
            rejected = rec.task_line_ids.filtered(
                lambda l: l.manager_verdict == 'rejected')
            if rejected:
                rec.message_post(body=_(
                    'Task list closed with %(count)s rejected task(s). '
                    'They will be added automatically to this '
                    'employee\'s next task list.', count=len(rejected)))
            rec._log_approval_history('closed', rec.manager_remarks)
            rec.activity_feedback(['mail.mail_activity_data_todo'])
            rec._notify_user(
                rec._get_employee_partner(),
                _('Task List Closed'),
                _('Your task list %s has been reviewed and closed by '
                  'your manager.', rec.name),
                'employee_task_management.mail_template_task_closed')
        return True

    def action_assign_to_employee(self):
        """Manager creates a task list for an employee and assigns it
        (TDD 2.2). QA point 22: it is NOT applicable yet - it waits for
        the employee to accept it."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_(
                    'Only Draft task lists can be assigned to an employee.'))
            if rec.employee_id.user_id and \
                    rec.employee_id.user_id == self.env.user:
                raise UserError(_(
                    'This task list belongs to you. Use "Submit to '
                    'Manager" instead so your manager can approve it.'))
            if not (self.env.user.has_group(
                    'employee_task_management.group_task_manager') or
                    self.env.user.has_group(
                    'employee_task_management.group_task_admin')):
                raise AccessError(_(
                    'Only a Manager or Administrator can assign a task '
                    'list to an employee.'))
            rec._set_state('pending_acceptance')
            rec._log_approval_history(
                'assigned', _('Created and assigned by manager %s',
                              self.env.user.name))
            rec._notify_user(
                rec._get_employee_partner(),
                _('New Task List Assigned - Acceptance Required'),
                _('Task list %s has been created and assigned to you by '
                  '%s. Please review it and click "Accept" - or "Request '
                  'Modification" if something needs to change.',
                  rec.name, self.env.user.name),
                'employee_task_management.mail_template_task_assigned')
        return True

    def action_submit_to_employee(self):
        """After a manager/admin unlocks a closed task list and makes
        corrections, this pushes it back to the employee."""
        for rec in self:
            if not rec.is_unlocked or rec.state != 'completed':
                raise UserError(_(
                    'Submit to Employee is only available right after '
                    'unlocking a closed task list.'))
            if not (self.env.user.has_group(
                    'employee_task_management.group_task_manager') or
                    self.env.user.has_group(
                    'employee_task_management.group_task_admin')):
                raise AccessError(_(
                    'Only a Manager or Administrator can submit an '
                    'unlocked task list back to the employee.'))
            rec._set_state('manager_approved', {'is_unlocked': False})
            rec._log_approval_history(
                'resubmitted',
                _('Updated and resubmitted to employee by %s',
                  self.env.user.name))
            rec._notify_user(
                rec._get_employee_partner(),
                _('Task List Updated - Start Working'),
                _('Task list %s has been updated by %s and is ready for '
                  'you to work on. Please review the changes and click '
                  '"Start Work".', rec.name, self.env.user.name),
                'employee_task_management.mail_template_task_resubmitted')
        return True

    # ==================================================================
    # DASHBOARD
    # ==================================================================
    @api.model
    def get_dashboard_data(self):
        """Counts for the custom dashboard's KPI cards. Uses search_count
        so record rules apply automatically. Also carries today's
        capacity figures so the employee sees his own idle hours without
        having to open a report."""
        domains = {
            'total': [],
            'pending_approval': [('state', '=', 'submitted_manager')],
            'in_progress': [('state', 'in', list(EXECUTION_STATES))],
            'completed': [('state', '=', 'completed')],
            'delayed': [('is_delayed', '=', True)],
            # Rejected is a closed outcome too, so it stays visible on
            # the dashboard instead of vanishing from every card.
            'closed': [('state', 'in', list(TERMINAL_STATES))],
        }
        data = {key: self.search_count(domain)
                for key, domain in domains.items()}
        # Today's capacity for the logged-in employee. Kept flat (plain
        # numbers and one pre-formatted string) because the client-side
        # Object.assign() merges this straight into the KPI state.
        Line = self.env['employee.task.line']
        idle = self.env['employee.task.idle.day']._idle_summary_for_user()
        data.update({
            'idle_has_row': idle['has_row'],
            'idle_capacity_display': Line._format_hours(idle['capacity']),
            'idle_allocated_display': Line._format_hours(idle['allocated']),
            'idle_display': Line._format_hours(idle['idle']),
            'idle_raw': idle['idle'],
        })
        return data

    def action_unlock(self):
        """Manager/Admin unlock of a closed record.

        DISABLED for now: the Unlock button has been removed from every
        view on the client's instruction - a Closed task list is final.
        The method and its wizard are kept so the feature can be switched
        back on later by simply putting the button back in the form.
        """
        self.ensure_one()
        raise UserError(_(
            'Closed task lists cannot be unlocked.'))
