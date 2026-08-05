# -*- coding: utf-8 -*-
import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError, AccessError

_logger = logging.getLogger(__name__)

from .task_states import (  # noqa: F401,E402  (re-exported for convenience)
    EDITABLE_STATES, EXECUTION_STATES, PARTIAL_LOCK_STATES,
    FULL_LOCK_STATES, TERMINAL_STATES,
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

# Fallback working schedule, used only when the company has no Working
# Schedule configured. Client is in Saudi Arabia: Sunday-Thursday,
# 08:00-17:00, Asia/Riyadh.
# Python weekday(): Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
DEFAULT_WORK_DAYS = {6, 0, 1, 2, 3}
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
             'here (Sun-Thu, 08:00-17:00, Asia/Riyadh by default).')
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
    is_delayed = fields.Boolean(
        string='Delayed', compute='_compute_is_delayed',
        search='_search_is_delayed')
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
    # clock time on the next working day. Sunday-Thursday, 08:00-17:00,
    # Asia/Riyadh. The schedule is read from the company's Working
    # Schedule (Settings > Employees > Working Schedules) so the client
    # can change their hours, days or timezone without a code change;
    # the constants below are only the fallback if none is configured.
    # ==================================================================
    def _get_work_schedule(self):
        """Return (tz_name, {working weekdays}, hour_from, hour_to).

        resource.calendar.attendance.dayofweek is '0'=Monday..'6'=Sunday,
        which is exactly Python's datetime.weekday(), so no conversion
        is needed.
        """
        calendar = (self.company_id.resource_calendar_id
                    or self.env.company.resource_calendar_id)
        if calendar and calendar.attendance_ids:
            attendances = calendar.attendance_ids
            return (
                calendar.tz or DEFAULT_TZ,
                {int(a.dayofweek) for a in attendances},
                min(attendances.mapped('hour_from')),
                max(attendances.mapped('hour_to')),
            )
        return (DEFAULT_TZ, DEFAULT_WORK_DAYS,
                DEFAULT_HOUR_FROM, DEFAULT_HOUR_TO)

    def _get_hours_per_day(self):
        """How many hours of work fit in one working day. Read from the
        company's Working Schedule so the client can change it in
        Settings; falls back to 8."""
        calendar = (self.company_id.resource_calendar_id
                    or self.env.company.resource_calendar_id)
        if calendar and calendar.hours_per_day:
            return calendar.hours_per_day
        return DEFAULT_HOURS_PER_DAY

    def _working_days_between(self, start_date, end_date):
        """Number of working days from start to end, both inclusive."""
        self.ensure_one()
        if not start_date or not end_date or end_date < start_date:
            return 0
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
        a Friday/Saturday) it is first pulled forward to the start of the
        next working day, so the counterparty always gets a full working
        day of real availability.
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
        self.ensure_one()
        tz_name = self._get_work_schedule()[0]
        return pytz.utc.localize(
            fields.Datetime.now()).astimezone(pytz.timezone(tz_name)).date()

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

    @api.depends('task_line_ids.progress', 'task_line_ids.task_status')
    def _compute_progress(self):
        for rec in self:
            lines = rec.task_line_ids
            rec.progress = (
                sum(lines.mapped('progress')) / len(lines)) if lines else 0.0

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
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'employee.task.list') or _('New')
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
        return records

    def write(self, vals):
        # Validation 9: Closed task lists cannot be edited (TDD Section 14)
        protected_keys = set(vals.keys()) - {
            'message_follower_ids', 'activity_ids', 'message_ids',
            'message_main_attachment_id'}
        if protected_keys and not self.env.context.get('bypass_closed_lock'):
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
            self._check_employee_activities()
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

    def _set_state(self, new_state, extra_vals=None):
        """Single entry point for every status change. Also maintains
        `pending_since`, the clock used by the 24 working-hour rules."""
        vals = dict(extra_vals or {})
        vals['state'] = new_state
        if 'pending_since' not in vals:
            vals['pending_since'] = (
                fields.Datetime.now() if new_state in WAITING_STATES else False)
        self.with_context(etm_workflow=True).write(vals)

    # ==================================================================
    # CONSTRAINTS / VALIDATIONS (TDD Section 14)
    # ==================================================================
    def _is_plain_employee(self):
        """The acting user is a plain Task Employee (not Manager/Admin)."""
        return not (
            self.env.user.has_group(
                'employee_task_management.group_task_manager')
            or self.env.user.has_group(
                'employee_task_management.group_task_admin'))

    def _check_employee_activities(self):
        """Employee role: a task that is ALREADY stored must carry at
        least one activity, with hours.

        Why "already stored": the Activities pop-up can only open on a
        saved task line, so a line has to survive one save before its
        activities can be entered. The check therefore looks at the task
        lines as they exist in the database *before* the current save is
        applied - a line being created right now is given its one save,
        and from the next save onwards it must have activities.

        A Manager / Administrator is exempt (QA point 20) - he may hand
        over a bare task and let the employee plan the activities."""
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
                    'on the task line to add them.\n\nTasks without any '
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
            rec._set_state('submitted_manager')
            rec._log_approval_history('submitted')
            rec._notify_user(
                rec._get_manager_partner(),
                _('Task List Approval Required'),
                _('A new task list %s has been submitted by employee %s '
                  'and requires your approval.',
                  rec.name, rec.employee_id.name),
                'employee_task_management.mail_template_task_submitted')
        return True

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
            if rec.state != 'submitted_manager':
                raise UserError(_(
                    'Only task lists in "Submitted to Manager" state can '
                    'be approved.'))
            rec._check_approver_rights()
            rec._check_ready_for_execution()
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

    def _check_approver_rights(self):
        """Validations 5 & 10: manager approval cannot be done by the
        employee himself; only authorized users can approve/reject."""
        self.ensure_one()
        if self.employee_id.user_id and \
                self.employee_id.user_id == self.env.user and not \
                self.env.user.has_group(
                    'employee_task_management.group_task_admin'):
            raise AccessError(_(
                'You cannot approve or return your own task list. '
                'Manager approval cannot be done by the employee himself.'))
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

    def _check_is_the_employee(self):
        """Only the employee the list belongs to may accept it, request a
        modification, start the work or mark it completed."""
        self.ensure_one()
        if self.env.user.has_group(
                'employee_task_management.group_task_admin'):
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

    @api.model
    def _cron_flag_delayed(self):
        """Latch was_delayed on task lists that have gone past their date
        while still running. Without this, a list that ran late but was
        finished on the same day it slipped would never get flagged -
        _notify_late_execution only fires at Start Work and at Mark
        Completed."""
        running = self.search([
            ('state', 'in', ['manager_approved'] + list(EXECUTION_STATES)),
            ('was_delayed', '=', False),
        ])
        late = running.filtered('is_delayed')
        if late:
            late.sudo().with_context(etm_workflow=True).write(
                {'was_delayed': True})
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
        # Latch it before notifying: the flag matters more than the mail,
        # and it must survive the record being completed and closed.
        if not self.was_delayed:
            self.sudo().with_context(etm_workflow=True).write(
                {'was_delayed': True})
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
            rec._set_state('completed')
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
        if self.state != 'completed':
            raise UserError(_(
                'Only a task list the employee marked as Completed can be '
                'rejected.'))
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
            rec._set_state('closed', {'is_unlocked': False})
            rec.task_line_ids.with_context(etm_workflow=True).write(
                {'task_status': 'closed'})
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
        so record rules apply automatically."""
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
        return {key: self.search_count(domain)
                for key, domain in domains.items()}

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
