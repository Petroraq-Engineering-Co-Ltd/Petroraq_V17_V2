# -*- coding: utf-8 -*-
"""Daily capacity / idle-hours tracking.

WHY THIS IS A STORED SNAPSHOT AND NOT A COMPUTED FIELD
------------------------------------------------------
The manager has to be able to LIST, GROUP, PIVOT and FILTER "who has
idle time on Tuesday". Odoo cannot generate one row per employee per
day out of a computed field on any existing model, so the day itself
has to become a record. Rows are refreshed idempotently by a cron.

SINGLE SOURCE OF TRUTH
----------------------
`_allocation_for_employee()` is the ONLY place that decides how many
hours a given day carries for a given employee. Both the idle report
AND the hard capacity block on employee.task.line call it, so the
number the employee is blocked on can never disagree with the number
the manager sees on screen.
"""
import logging
from collections import defaultdict
from datetime import datetime, time, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

from .task_states import UNALLOCATED_STATES

_logger = logging.getLogger(__name__)

# How many days ahead rows are maintained. The manager plans a week or
# two out, so building only "today" (the original behaviour) left the
# report empty for every future date he looked at.
HORIZON_DAYS = 14

# Local clock hours at which an employee with idle time is notified.
# Four slots inside the 08:00-17:00 working day, the last one early
# enough that there is still time to act on it.
NOTIFY_HOURS_LOCAL = (9, 11, 13, 15)


class EmployeeTaskIdleDay(models.Model):
    _name = 'employee.task.idle.day'
    _description = 'Employee Daily Capacity / Idle Hours'
    _order = 'date desc, employee_id'

    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        ondelete='cascade', index=True)
    department_id = fields.Many2one(
        'hr.department', string='Department',
        related='employee_id.department_id', store=True)
    manager_id = fields.Many2one(
        'hr.employee', string='Manager',
        related='employee_id.parent_id', store=True)
    date = fields.Date(string='Date', required=True, index=True)

    capacity_hours = fields.Float(
        string='Total Working Hours', digits=(16, 2),
        help='Hours this employee is expected to work on this day.')
    allocated_hours = fields.Float(
        string='Allocated Hours', digits=(16, 2),
        help='Hours committed to tasks across ALL of this employee\'s '
             'task lists for this day. Equals Approved + Pending; '
             'rejected hours are excluded.')
    idle_hours = fields.Float(
        string='Idle Hours', digits=(16, 2),
        help='Working hours not yet covered by any task.')

    # Allocated split by verdict. Approved + Pending = Allocated;
    # REJECTED SITS OUTSIDE IT, because refused work has to be redone
    # and must not keep occupying the day it failed on.
    approved_hours = fields.Float(
        string='Approved Hours', digits=(16, 2),
        help='Allocated hours the manager has accepted. Includes tasks '
             'left at Pending Review on a Closed list, which count as '
             'approved.')
    rejected_hours = fields.Float(
        string='Rejected Hours', digits=(16, 2),
        help='Hours the manager refused. NOT counted in Allocated - '
             'the work has to be done again, so the capacity is '
             'released and shows up in Idle Hours, leaving room for '
             'the redo.')
    pending_hours = fields.Float(
        string='Pending Hours', digits=(16, 2),
        help='Allocated hours not yet reviewed. Falls to zero as the '
             'manager works through his approvals.')
    has_idle = fields.Boolean(
        string='Has Idle Time', index=True,
        help='Stored so the manager can filter on it directly.')

    # ------------------------------------------------------------------
    # Notification bookkeeping. The manager asked to see WHETHER the
    # employee was told, so this is reported, not just used internally.
    # ------------------------------------------------------------------
    notify_count = fields.Integer(
        string='Reminders Sent', default=0,
        help='How many idle-hour reminders the employee has been sent '
             'for this day.')
    last_notified_on = fields.Datetime(
        string='Last Reminder', readonly=True)
    notified_slots = fields.Char(
        string='Reminder Slots Done', readonly=True, copy=False,
        help='Technical: which of the daily reminder slots have already '
             'fired, so a cron re-run cannot send the same one twice.')
    notified = fields.Boolean(
        string='Reminder Sent', compute='_compute_notified', store=True)

    _sql_constraints = [
        ('employee_date_uniq', 'unique(employee_id, date)',
         'There can only be one capacity row per employee per day.'),
    ]

    @api.depends('notify_count')
    def _compute_notified(self):
        for rec in self:
            rec.notified = rec.notify_count > 0

    @api.depends('employee_id', 'date')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s - %s' % (
                rec.employee_id.name or '', rec.date or '')

    # ==================================================================
    # ALLOCATION - the single source of truth
    # ==================================================================
    @api.model
    def _spread_days(self, line, work_days):
        """The working days a task line's hours are spread over.

        A task that runs three days holds its activities across those
        three days, not all on day one - so 12 hours over three days
        consumes 4 hours of each day's capacity. Non-working days inside
        the range carry nothing.
        """
        if not line.start_date or not line.end_date:
            return []
        days, cursor, guard = [], line.start_date, 0
        while cursor <= line.end_date and guard < 3650:
            if cursor.weekday() in work_days:
                days.append(cursor)
            cursor += timedelta(days=1)
            guard += 1
        return days

    @api.model
    def _line_fallback_bucket(self, line):
        """Where a task's hours land when its activities say nothing.

        A task left at Pending Review counts as APPROVED once the
        manager closes the whole list - that is the module's existing
        rule (see manager_verdict's help text), and honouring it here is
        what stops finished work from sitting in Pending forever.
        """
        if line.manager_verdict == 'rejected':
            return 'rejected'
        if line.manager_verdict == 'approved':
            return 'approved'
        # 'partial' means the activities carry the real answer, so it
        # never reaches here for an activity that has been ruled on.
        if line.task_list_id.state == 'closed':
            return 'approved'
        return 'pending'

    @api.model
    def _activity_buckets(self, line):
        """{bucket: hours} for one task, split by ACTIVITY verdict.

        An activity still at Pending inherits its TASK's verdict. That
        fallback is what keeps every figure recorded before
        activity-level review existed exactly as it was: those
        activities are all Pending, so they follow the task and nothing
        moves. Only activities a manager has actually ruled on
        individually pull away from their task.

        A task with no activities at all falls back wholesale, so its
        hours are never silently dropped.
        """
        buckets = {'approved': 0.0, 'rejected': 0.0, 'pending': 0.0}
        fallback = self._line_fallback_bucket(line)
        if not line.subtask_ids:
            buckets[fallback] = line.total_hours or 0.0
            return buckets
        for activity in line.subtask_ids:
            verdict = activity.manager_verdict
            if verdict == 'pending':
                verdict = fallback
            buckets[verdict] += activity.hours or 0.0
        return buckets

    @api.model
    def _allocation_breakdown(self, employee, date_from, date_to,
                              include_list_ids=()):
        """{date: {'total','approved','rejected','pending'}}.

        Same lines, same even spread, same states as the plain total
        below - only split by the manager's verdict. The three buckets
        always sum back to the total, which is the property that lets a
        manager check any row's arithmetic by eye.
        """
        if not employee or not date_from or not date_to:
            return {}
        Line = self.env['employee.task.line'].sudo()
        TaskList = self.env['employee.task.list'].sudo()
        domain = [
            ('task_list_id.employee_id', '=', employee.id),
            ('start_date', '!=', False),
            ('end_date', '!=', False),
            ('start_date', '<=', date_to),
            ('end_date', '>=', date_from),
            '|',
            ('task_list_id.state', 'not in', list(UNALLOCATED_STATES)),
            ('task_list_id', 'in', list(include_list_ids or [])),
        ]
        work_days = TaskList._get_planning_work_days()
        result = defaultdict(
            lambda: {'total': 0.0, 'approved': 0.0,
                     'rejected': 0.0, 'pending': 0.0})
        for line in Line.search(domain):
            days = self._spread_days(line, work_days)
            if not days:
                continue
            # Hours spread evenly across the task's working days; each
            # bucket is spread by the same factor.
            #
            # REJECTED HOURS ARE NOT IN THE TOTAL. Refused work has to
            # be done again, so leaving it in the day's allocation
            # double-books the employee: the rejected original and its
            # replacement would both consume the same capacity and he
            # could not fit the redo in. Releasing them also matches
            # what rejecting a WHOLE list has always done.
            #   allocated = approved + pending
            #   rejected  = reported alongside, outside the total
            spread = 1.0 / len(days)
            buckets = self._activity_buckets(line)
            countable = buckets['approved'] + buckets['pending']
            for day in days:
                if date_from <= day <= date_to:
                    result[day]['total'] += countable * spread
                    for bucket, hours in buckets.items():
                        result[day][bucket] += hours * spread
        return dict(result)

    @api.model
    def _allocation_for_employee(self, employee, date_from, date_to,
                                 include_list_ids=()):
        """{date: allocated hours} for ONE employee over a date window.

        Counts every task line of the employee whose task list is in an
        allocating state - that is, everything EXCEPT Draft and
        Rejected. A task still waiting on the manager therefore already
        consumes capacity (the employee is committed to it), while a
        rejected list releases its hours again.

        `include_list_ids` forces particular task lists to be counted
        even if they are still Draft. That is what makes the live
        capacity block work: the list the employee is editing right now
        is by definition a draft, and it obviously has to count against
        his own day, or he would only discover the clash at submit time.
        """
        # Delegates to _allocation_breakdown so there is still exactly
        # ONE place that decides what a day carries. The capacity block
        # and the report cannot drift apart.
        return {day: figures['total'] for day, figures
                in self._allocation_breakdown(
                    employee, date_from, date_to, include_list_ids).items()}

    # ==================================================================
    # LEAVE / HOLIDAY AWARENESS
    # ==================================================================
    @api.model
    def _is_public_holiday(self, day):
        """True when the company calendar marks this whole day off.

        Reads resource.calendar.leaves, which ships with base `resource`
        - no extra module dependency, so this cannot break an upgrade on
        a database that does not have hr_holidays installed.
        """
        calendar = self.env.company.resource_calendar_id
        domain = [
            ('resource_id', '=', False),
            ('date_from', '<=', datetime.combine(day, time.max)),
            ('date_to', '>=', datetime.combine(day, time.min)),
        ]
        if calendar:
            domain += ['|', ('calendar_id', '=', calendar.id),
                       ('calendar_id', '=', False)]
        else:
            domain += [('calendar_id', '=', False)]
        return bool(self.env['resource.calendar.leaves'].sudo().search_count(
            domain))

    @api.model
    def _employees_on_leave(self, employees, day):
        """Employee ids on approved leave on `day`.

        hr_holidays is deliberately NOT added to the manifest's
        `depends`: adding a dependency that turned out not to be
        installed has broken an upgrade on this client's system before.
        The model is looked up at runtime instead, so on a database
        without hr_holidays this simply returns nothing and the rest of
        the feature carries on working.
        """
        if 'hr.leave' not in self.env:
            return set()
        try:
            leaves = self.env['hr.leave'].sudo().search([
                ('employee_id', 'in', employees.ids),
                ('state', '=', 'validate'),
                ('date_from', '<=', datetime.combine(day, time.max)),
                ('date_to', '>=', datetime.combine(day, time.min)),
            ])
            return set(leaves.mapped('employee_id').ids)
        except Exception:
            _logger.exception(
                "Idle hours: could not read leaves for %s - treating "
                "everybody as present", day)
            return set()

    # ==================================================================
    # REFRESH
    # ==================================================================
    @api.model
    def _tracked_employees(self):
        """Employees the capacity report covers.

        Anyone who has ever had a task list, plus anyone holding the
        Task Employee group. The second half matters on day one: a new
        joiner with no task list yet is exactly the person the manager
        needs to see sitting at 8 idle hours.
        """
        Employee = self.env['hr.employee'].sudo()
        with_lists = self.env['employee.task.list'].sudo().search(
            []).mapped('employee_id')
        group = self.env.ref(
            'employee_task_management.group_task_employee',
            raise_if_not_found=False)
        by_group = Employee.browse()
        if group:
            by_group = Employee.search(
                [('user_id', 'in', group.users.ids)])
        return (with_lists | by_group).filtered('active')

    @api.model
    def _refresh_for_day(self, day, employees=None):
        """Idempotent upsert of every employee's row for one day.

        Safe to run as often as you like - it never duplicates, and it
        DELETES rows that should no longer exist (a day that turned out
        to be a holiday, an employee who went on leave). Notification
        bookkeeping is preserved across refreshes.
        """
        TaskList = self.env['employee.task.list'].sudo()
        work_days = TaskList._get_planning_work_days()
        payroll_days = TaskList._get_work_schedule()[1]
        if employees is None:
            employees = self._tracked_employees()
        if not employees:
            return self.browse()

        existing = self.sudo().search([
            ('date', '=', day), ('employee_id', 'in', employees.ids)])
        by_employee = {r.employee_id.id: r for r in existing}

        # Friday (and any non-working weekday) carries no capacity at
        # all, and a public holiday is nobody's idle time.
        if day.weekday() not in work_days or self._is_public_holiday(day):
            existing.unlink()
            return self.browse()

        on_leave = self._employees_on_leave(employees, day)
        capacity = TaskList._get_hours_per_day()
        # Saturday is an OPTIONAL working day: the employee may come in
        # to clear pending work, but he is not expected to. Generating a
        # row for a Saturday nobody planned anything on would show the
        # whole company sitting at 8 idle hours every weekend.
        optional_day = day.weekday() not in payroll_days

        kept = self.browse()
        for employee in employees:
            figures = self._allocation_breakdown(
                employee, day, day).get(day, {})
            allocated = figures.get('total', 0.0)
            row = by_employee.get(employee.id)

            # A day the employee cannot work is not idle time.
            if employee.id in on_leave or (optional_day and not allocated):
                if row:
                    row.unlink()
                continue

            idle = max(capacity - allocated, 0.0)
            vals = {
                'capacity_hours': capacity,
                'allocated_hours': allocated,
                'approved_hours': figures.get('approved', 0.0),
                'rejected_hours': figures.get('rejected', 0.0),
                'pending_hours': figures.get('pending', 0.0),
                'idle_hours': idle,
                'has_idle': idle > 0.0,
            }
            if row:
                row.write(vals)
            else:
                row = self.sudo().create(dict(
                    vals, employee_id=employee.id, date=day))
            kept |= row
        return kept

    # ==================================================================
    # CRON
    # ==================================================================
    @api.model
    def _cron_refresh_idle_hours(self):
        """Hourly refresh of the rolling horizon + the daily reminders.

        Hourly rather than daily on purpose: the numbers move whenever
        anybody saves a task, and the manager needs the report to be
        true when he opens it, not true as of midnight.
        """
        TaskList = self.env['employee.task.list'].sudo()
        today = TaskList._today_local()
        employees = self._tracked_employees()
        for offset in range(HORIZON_DAYS):
            day = today + timedelta(days=offset)
            try:
                with self.env.cr.savepoint():
                    self._refresh_for_day(day, employees)
            except Exception:
                # One bad day must not abort the whole horizon.
                _logger.exception("Idle hours refresh failed for %s", day)
        try:
            with self.env.cr.savepoint():
                self._notify_idle_employees(today)
        except Exception:
            _logger.exception("Idle hours notification pass failed")
        return True

    @api.model
    def _due_notify_slots(self, local_hour, done):
        """Reminder slots that have come round but not yet been sent."""
        return [h for h in NOTIFY_HOURS_LOCAL
                if h <= local_hour and str(h) not in done]

    @api.model
    def _notify_idle_employees(self, day):
        """Send today's idle reminders, at most one per slot per day.

        The slots already sent are recorded ON THE ROW rather than
        recomputed from the clock, so re-running the cron - or running
        it manually - can never send the same reminder twice.
        """
        TaskList = self.env['employee.task.list'].sudo()
        if day != TaskList._today_local():
            return  # only ever nag about today
        local_hour = TaskList._now_local().hour
        rows = self.sudo().search([
            ('date', '=', day), ('has_idle', '=', True)])
        for row in rows:
            done = set((row.notified_slots or '').split(','))
            due = self._due_notify_slots(local_hour, done)
            if not due:
                continue
            partner = row.employee_id.user_id.partner_id
            if not partner:
                continue
            hours = self.env['employee.task.line']._format_hours(
                row.idle_hours)
            body = _(
                'You have %(hours)s idle hours remaining for today. '
                'Please create tasks/activities for the available time.',
                hours=hours)
            try:
                with self.env.cr.savepoint():
                    row._send_reminder(
                        _('Idle Hours Remaining Today'), body)
            except Exception:
                # A mail problem must never stop the bookkeeping or the
                # rest of the run - cron errors are swallowed into the
                # log, so this would otherwise be invisible.
                _logger.exception(
                    "Idle reminder failed for %s", row.employee_id.name)
                continue
            done |= {str(h) for h in due}
            row.sudo().write({
                'notified_slots': ','.join(
                    sorted(x for x in done if x)),
                'notify_count': row.notify_count + 1,
                'last_notified_on': fields.Datetime.now(),
            })

    def _send_reminder(self, subject, body):
        """Deliver one idle reminder.

        Posted on the EMPLOYEE record rather than through the task
        list's `_notify_user`. That helper calls `ensure_one()` and
        posts to a task list's chatter - there is no task list here (the
        whole point is that the employee has not created one), and
        calling it from a cron on an empty recordset is exactly the
        "Expected singleton" crash this module has already been bitten
        by once. hr.employee inherits mail.thread, so the message lands
        in the employee's inbox and reaches his email through the
        normal follower channel.
        """
        self.ensure_one()
        partner = self.employee_id.user_id.partner_id
        if not partner:
            return
        self.employee_id.sudo().message_post(
            body=body, subject=subject,
            partner_ids=partner.ids,
            message_type='notification',
            subtype_xmlid='mail.mt_comment')

    # ==================================================================
    # UI HELPERS
    # ==================================================================
    def action_refresh_today(self):
        """Manual "Refresh" button - rows only exist once something has
        built them, and on a fresh install nobody wants to wait an hour
        to see the feature work."""
        self.env['employee.task.idle.day'].sudo()._cron_refresh_idle_hours()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.model
    def _idle_summary_for_user(self):
        """Today's capacity figures for the logged-in employee, for the
        dashboard card."""
        employee = self.env['hr.employee'].sudo().search(
            [('user_id', '=', self.env.uid)], limit=1)
        blank = {'capacity': 0.0, 'allocated': 0.0, 'idle': 0.0,
                 'has_row': False}
        if not employee:
            return blank
        today = self.env['employee.task.list'].sudo()._today_local()
        row = self.sudo().search(
            [('employee_id', '=', employee.id), ('date', '=', today)],
            limit=1)
        if not row:
            return blank
        return {
            'capacity': row.capacity_hours,
            'allocated': row.allocated_hours,
            'idle': row.idle_hours,
            'has_row': True,
        }
