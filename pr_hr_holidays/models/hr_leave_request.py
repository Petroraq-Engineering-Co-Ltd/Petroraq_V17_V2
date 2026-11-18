from odoo import models, fields, api, _
from odoo.tools import date_utils, format_date
from odoo.osv import expression
from dateutil.relativedelta import relativedelta
from odoo.exceptions import AccessError, ValidationError, UserError
import re
import json
import math
from random import randint
import logging
from datetime import datetime, timedelta
import pandas as pd

_logger = logging.getLogger(__name__)

HR_SUPERVISOR_GROUP = "pr_hr.group_hr_supervisor"
HR_MANAGER_GROUP = "pr_hr.group_hr_manager"
APPROVAL_STATES = ("draft", "manager_approve", "hr_supervisor")


class HrLeaveRequest(models.Model):
    """
    """
    # region [Initial]
    _name = 'pr.hr.leave.request'
    _description = 'Hr Leave Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = "id"
    # endregion [Initial]

    # region [Fields]

    name = fields.Char(string="Name")
    leave_type_id = fields.Many2one("hr.leave.type", string="Leave Type", required=True)
    date_from = fields.Date(string="Date From", required=True)
    date_to = fields.Date(string="Date To", required=True)
    requested_days = fields.Float(
        string="Requested Days",
        compute="_compute_requested_days",
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one('res.company', string='Company', tracking=True, required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', tracking=True, required=True)
    employee_manager_id = fields.Many2one('hr.employee', string='Manager', tracking=True, readonly=True)
    hr_supervisor_ids = fields.Many2many('res.users', 'leave_request_hr_supervisor_users', 'hr_supervisor_id',
                                         'leave_request_id', string='HR Supervisors', tracking=True, readonly=True)
    hr_manager_ids = fields.Many2many('res.users', 'leave_request_hr_manager_users', 'hr_manager_id',
                                      'leave_request_id', string='HR Managers', tracking=True, readonly=True)
    manager_approved_user_id = fields.Many2one('res.users', string='Manager Approved By', readonly=True, copy=False)
    manager_approved_date = fields.Datetime(string='Manager Approved On', readonly=True, copy=False)
    hr_supervisor_approved_user_id = fields.Many2one('res.users', string='HR Supervisor Approved By', readonly=True,
                                                     copy=False)
    hr_supervisor_approved_date = fields.Datetime(string='HR Supervisor Approved On', readonly=True, copy=False)
    hr_manager_approved_user_id = fields.Many2one('res.users', string='HR Manager Approved By', readonly=True,
                                                  copy=False)
    hr_manager_approved_date = fields.Datetime(string='HR Manager Approved On', readonly=True, copy=False)
    reject_reason = fields.Text(string="Rejection Reason", readonly=True, tracking=True)
    rejected_stage = fields.Selection([
        ('manager', 'Department Manager'),
        ('hr_supervisor', 'HR Supervisor'),
        ('hr_manager', 'HR Manager'),
    ], string='Rejected At', readonly=True, copy=False, tracking=True)
    rejected_from_state = fields.Selection([
        ('draft', 'Submitted'),
        ('manager_approve', 'Manager Approved'),
        ('hr_supervisor', 'HR Supervisor Approved'),
    ], string='Rejected From State', readonly=True, copy=False)
    rejected_by_user_id = fields.Many2one(
        'res.users', string='Rejected By', readonly=True, copy=False, tracking=True
    )
    can_reset_rejection = fields.Boolean(compute='_compute_can_reset_rejection')
    note = fields.Text(string="Note")
    state = fields.Selection([
        ('draft', 'Submitted'),
        ('manager_approve', 'Manager Approved'),
        ('hr_supervisor', 'HR Supervisor Approved'),
        ('hr_approve', 'HR Manager Approved'),
        ('reject', 'Rejected'),
        ('cancel_request', 'Cancellation Requested'),
        ('cancelled', 'Cancelled'),
    ], default='draft', track_visibility='always',
        string='Status', required=True, index=True)
    approval_state = fields.Selection([
        ('draft', 'Pending Approval'),
        ('manager_approve', 'Pending Approval'),
        ('hr_supervisor', 'Pending Approval'),
        ('hr_approve', 'Approved'),
        ('reject', 'Rejected'),
        ('cancel_request', 'Pending Cancellation Approval'),
        ('cancelled', 'Cancelled'),
    ], default='draft', track_visibility='always',
        string='Approval Status')
    employee_manager_check = fields.Boolean(compute="_compute_employee_manager_check")
    employee_user_check = fields.Boolean(compute="_compute_employee_user_check")
    hr_supervisor_check = fields.Boolean(compute="_compute_hr_supervisor_check")
    hr_manager_check = fields.Boolean(compute="_compute_hr_manager_check")
    can_manager_approve = fields.Boolean(compute="_compute_approval_button_visibility")
    can_hr_supervisor_approve = fields.Boolean(compute="_compute_approval_button_visibility")
    can_hr_manager_approve = fields.Boolean(compute="_compute_approval_button_visibility")
    can_reject = fields.Boolean(compute="_compute_approval_button_visibility")
    can_approve_cancellation = fields.Boolean(compute="_compute_approval_button_visibility")
    leave_id = fields.Many2one("hr.leave", string="Leave", readonly=True)
    allocation_override_applied = fields.Boolean(
        string="Allocation Override Applied",
        default=False,
        readonly=True,
        copy=False,
    )
    allocation_override_note = fields.Text(
        string="Allocation Override Note",
        readonly=True,
        copy=False,
    )
    allocation_bypassed = fields.Boolean(
        string="Allocation Bypassed",
        compute="_compute_allocation_bypassed",
        readonly=True,
    )

    # endregion [Fields]

    def init(self):
        """Backfill rejection stage metadata for rejections created before stage tracking existed."""
        self.env.cr.execute("""
            UPDATE pr_hr_leave_request
               SET rejected_stage = CASE
                   WHEN hr_supervisor_approved_user_id IS NOT NULL THEN 'hr_manager'
                   WHEN manager_approved_user_id IS NOT NULL THEN 'hr_supervisor'
                   ELSE 'manager'
               END
             WHERE state = 'reject'
               AND rejected_stage IS NULL
        """)
        self.env.cr.execute("""
            UPDATE pr_hr_leave_request
               SET rejected_from_state = CASE rejected_stage
                   WHEN 'hr_manager' THEN 'hr_supervisor'
                   WHEN 'hr_supervisor' THEN 'manager_approve'
                   ELSE 'draft'
               END
             WHERE state = 'reject'
               AND rejected_from_state IS NULL
        """)

    # region [Role Helpers]

    @api.model
    def _user_is_hr_supervisor(self, user=None):
        user = user or self.env.user
        return bool(user and user.has_group(HR_SUPERVISOR_GROUP))

    @api.model
    def _user_is_hr_manager(self, user=None):
        user = user or self.env.user
        return bool(user and user.has_group(HR_MANAGER_GROUP))

    def _user_is_dept_manager(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        if not user:
            return False
        return bool(
            (self.employee_id.parent_id.user_id and self.employee_id.parent_id.user_id == user)
            or (self.employee_manager_id.user_id and self.employee_manager_id.user_id == user)
        )

    @api.model
    def _get_group_users_for_company(self, group_xmlid, company=None):
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        if not group:
            return self.env["res.users"]
        users = (
            self.env["res.users"]
            .sudo()
            .browse(group.sudo().users.ids)
            .filtered(lambda u: u.active)
        )
        if company:
            users = users.filtered(lambda u: company in u.company_ids)
        return users

    def _should_forward_escalate_hr_supervisor_to_hr_manager(self):
        """Return True if there is at least one active HR Supervisor
        (pr_hr.group_hr_supervisor) for this request's company and every such
        approver also holds HR Manager rights (pr_hr.group_hr_manager)."""
        self.ensure_one()
        candidates = self._get_group_users_for_company(HR_SUPERVISOR_GROUP, self.company_id)
        return bool(candidates) and all(
            candidate.has_group(HR_MANAGER_GROUP) for candidate in candidates
        )

    @api.model
    def _get_pending_approval_domain(self, user=None):
        user = user or self.env.user
        role_domains = [
            [
                ("state", "=", "draft"),
                "|",
                ("employee_manager_id.user_id", "=", user.id),
                ("employee_id.parent_id.user_id", "=", user.id),
            ],
        ]
        if self._user_is_hr_supervisor(user):
            role_domains.append([("state", "=", "manager_approve")])
        if self._user_is_hr_manager(user):
            role_domains.append([("state", "in", ["hr_supervisor", "cancel_request"])])
        return expression.OR(role_domains) if len(role_domains) > 1 else role_domains[0]

    # endregion [Role Helpers]

    # region [Compute Methods]

    @api.depends("employee_id", "employee_id.parent_id", "employee_id.parent_id.user_id", "employee_manager_id",
                 "employee_manager_id.user_id")
    @api.depends_context("uid")
    def _compute_employee_manager_check(self):
        user = self.env.user
        for rec in self:
            rec.employee_manager_check = rec._user_is_dept_manager(user)

    @api.depends("employee_id", "employee_id.user_id")
    @api.depends_context("uid")
    def _compute_employee_user_check(self):
        for rec in self:
            if rec.employee_id.user_id and rec.employee_id.user_id.id == self.env.user.id:
                rec.employee_user_check = True
            else:
                rec.employee_user_check = False

    @api.depends_context("uid")
    def _compute_hr_supervisor_check(self):
        is_hr_sup = self._user_is_hr_supervisor()
        for rec in self:
            rec.hr_supervisor_check = is_hr_sup

    @api.depends_context("uid")
    def _compute_hr_manager_check(self):
        is_hr_mgr = self._user_is_hr_manager()
        for rec in self:
            rec.hr_manager_check = is_hr_mgr

    @api.depends("state", "employee_id", "employee_id.parent_id.user_id", "employee_manager_id",
                 "employee_manager_id.user_id")
    @api.depends_context("uid")
    def _compute_approval_button_visibility(self):
        user = self.env.user
        is_hr_sup = self._user_is_hr_supervisor(user)
        is_hr_mgr = self._user_is_hr_manager(user)
        for rec in self:
            has_id = bool(rec.id)
            is_dept_mgr = rec._user_is_dept_manager(user)
            rec.can_manager_approve = (
                has_id
                and rec.state == "draft"
                and is_dept_mgr
                and not is_hr_mgr
            )
            rec.can_hr_supervisor_approve = (
                has_id
                and rec.state == "manager_approve"
                and is_hr_sup
                and not is_hr_mgr
            )
            rec.can_hr_manager_approve = (
                has_id
                and rec.state in APPROVAL_STATES
                and is_hr_mgr
            )
            rec.can_reject = has_id and (
                (rec.state in APPROVAL_STATES and is_hr_mgr)
                or (rec.state == "manager_approve" and is_hr_sup)
                or (rec.state == "draft" and is_dept_mgr)
            )
            rec.can_approve_cancellation = (
                has_id
                and rec.state == "cancel_request"
                and is_hr_mgr
            )

    @api.depends('state', 'rejected_stage', 'rejected_by_user_id', 'employee_id.parent_id.user_id',
                 'employee_manager_id', 'employee_manager_id.user_id',
                 'hr_supervisor_ids', 'hr_manager_ids')
    @api.depends_context('uid')
    def _compute_can_reset_rejection(self):
        user = self.env.user
        for rec in self:
            rec.can_reset_rejection = (
                rec.state == 'reject'
                and rec._user_can_decide_rejected_stage(user)
            )

    def _user_can_decide_rejected_stage(self, user):
        self.ensure_one()
        # The person who made the rejection must always be able to reopen their
        # own decision. This also covers hierarchy/group changes after rejection.
        if self.rejected_stage and self.rejected_by_user_id == user:
            return True
        if self.rejected_stage == 'manager':
            return self._user_is_dept_manager(user)
        if self.rejected_stage == 'hr_supervisor':
            return self._user_is_hr_supervisor(user)
        if self.rejected_stage == 'hr_manager':
            return self._user_is_hr_manager(user)
        return False

    def _user_can_reject_stage(self, stage, user):
        self.ensure_one()
        if stage == 'manager':
            return self.state == 'draft' and self._user_is_dept_manager(user)
        if stage == 'hr_supervisor':
            return self.state == 'manager_approve' and self._user_is_hr_supervisor(user)
        if stage == 'hr_manager':
            return self.state in APPROVAL_STATES and self._user_is_hr_manager(user)
        return False

    def _apply_stage_rejection(self, stage, reason):
        actor = self.env.user
        for rec in self:
            if rec.state not in APPROVAL_STATES:
                raise UserError(_('This leave request cannot be rejected in its current state.'))
            if not rec._user_can_reject_stage(stage, actor):
                raise AccessError(_('You are not allowed to reject this leave request at the current stage.'))
            previous_state = rec.state
            rec.sudo().write({
                'reject_reason': reason,
                'rejected_stage': stage,
                'rejected_from_state': previous_state,
                'rejected_by_user_id': actor.id,
                'state': 'reject',
                'approval_state': 'reject',
            })
            if stage == 'hr_manager' and previous_state in ('draft', 'manager_approve'):
                rec.sudo().message_post(
                    body=_('Rejected by HR Manager via skip-level decision.')
                )

    def action_reset_rejection(self):
        stage_to_state = {
            'manager': 'draft',
            'hr_supervisor': 'manager_approve',
            'hr_manager': 'hr_supervisor',
        }
        actor = self.env.user
        for rec in self:
            if rec.state != 'reject' or not rec._user_can_decide_rejected_stage(actor):
                raise UserError(_('Only an authorized approver from the rejecting stage can reset this decision.'))

            rejected_stage = rec.rejected_stage
            target_state = rec.rejected_from_state or stage_to_state[rejected_stage]
            reset_vals = {
                'state': target_state,
                'approval_state': target_state,
                'reject_reason': False,
                'rejected_stage': False,
                'rejected_from_state': False,
                'rejected_by_user_id': False,
                'allocation_override_applied': False,
                'allocation_override_note': False,
            }
            if target_state == 'draft':
                reset_vals.update({
                    'manager_approved_user_id': False,
                    'manager_approved_date': False,
                    'hr_supervisor_approved_user_id': False,
                    'hr_supervisor_approved_date': False,
                    'hr_manager_approved_user_id': False,
                    'hr_manager_approved_date': False,
                })
            elif target_state == 'manager_approve':
                reset_vals.update({
                    'hr_supervisor_approved_user_id': False,
                    'hr_supervisor_approved_date': False,
                    'hr_manager_approved_user_id': False,
                    'hr_manager_approved_date': False,
                })
            elif target_state == 'hr_supervisor':
                reset_vals.update({
                    'hr_manager_approved_user_id': False,
                    'hr_manager_approved_date': False,
                })

            rec.sudo().write(reset_vals)
            rec.sudo().message_post(
                body=_('%(user)s reset the rejection and reopened the %(stage)s decision.') % {
                    'user': actor.display_name,
                    'stage': dict(rec._fields['rejected_stage'].selection).get(rejected_stage, rejected_stage),
                }
            )
        return True

    @api.depends("date_from", "date_to", "leave_type_id", "leave_type_id.leave_type")
    def _compute_requested_days(self):
        for rec in self:
            if not rec.date_from or not rec.date_to or rec.date_to < rec.date_from:
                rec.requested_days = 0.0
                continue
            if rec.leave_type_id.leave_type == "annual_leave":
                # Annual leave consumes every calendar date in the inclusive
                # period, including weekends and public holidays.
                rec.requested_days = (rec.date_to - rec.date_from).days + 1
                continue
            working_days = rec._get_working_days_in_period()
            rec.requested_days = len(working_days)

    def _get_working_days_in_period(self):
        """Working days excluding weekends + public holidays (hr.public.holiday)"""
        self.ensure_one()
        if not self.date_from or not self.date_to or self.date_to < self.date_from:
            return []

        # 1. Weekends from work calendar
        calendar_id = self._get_request_calendar()
        if calendar_id and calendar_id.attendance_ids:
            working_weekdays = {int(attendance.dayofweek) for attendance in calendar_id.attendance_ids}
        else:
            working_weekdays = set(range(5))  # Mon-Fri

        # 2. Public holidays (CORRECT MODEL: hr.public.holiday)
        holiday_dates = set()
        public_holidays = self.env['hr.public.holiday'].sudo().search([
            ('date_from', '<=', self.date_to),
            ('date_to', '>=', self.date_from),
            ('state', '=', 'active')
            # Removed company_id - not all instances have it
        ])

        for holiday in public_holidays:
            # Handle single-day and multi-day holidays
            start_date = max(self.date_from, holiday.date_from)
            end_date = min(self.date_to, holiday.date_to)
            current_date = start_date
            while current_date <= end_date:
                holiday_dates.add(current_date)
                current_date += timedelta(days=1)

        # 3. Count only working days (exclude weekends + holidays)
        working_days = []
        current_date = self.date_from
        while current_date <= self.date_to:
            is_weekend = current_date.weekday() not in working_weekdays
            is_public_holiday = current_date in holiday_dates
            if not is_weekend and not is_public_holiday:
                working_days.append(current_date)
            current_date += timedelta(days=1)

        return working_days

    def _get_non_working_dates_in_period(self):
        """Get ALL non-working dates (weekends + public holidays) for validation"""
        self.ensure_one()
        if not self.date_from or not self.date_to or self.date_to < self.date_from:
            return []

        # Weekends
        calendar_id = self._get_request_calendar()
        if calendar_id and calendar_id.attendance_ids:
            working_weekdays = {int(attendance.dayofweek) for attendance in calendar_id.attendance_ids}
        else:
            working_weekdays = set(range(5))

        # Public holidays
        holiday_domain = [
            ('date_from', '<=', self.date_to),
            ('date_to', '>=', self.date_from),
            # ('company_id', 'in', [self.company_id.id, False]),
            ('state', '=', 'active')
        ]
        public_holidays = self.env['hr.public.holiday'].sudo().search(holiday_domain)

        non_working_dates = set()

        # Add weekends
        current_date = self.date_from
        while current_date <= self.date_to:
            if current_date.weekday() not in working_weekdays:
                non_working_dates.add(current_date)
            current_date += timedelta(days=1)

        # Add public holidays
        for holiday in public_holidays:
            current_holiday_date = max(self.date_from, holiday.date_from)
            end_holiday_date = min(self.date_to, holiday.date_to)
            while current_holiday_date <= end_holiday_date:
                non_working_dates.add(current_holiday_date)
                current_holiday_date += timedelta(days=1)

        return sorted(list(non_working_dates))

    @api.depends("requested_days", "leave_type_id", "employee_id", "date_from", "date_to", "state")
    def _compute_allocation_bypassed(self):
        for rec in self:
            if not rec.employee_id or not rec.leave_type_id:
                rec.allocation_bypassed = False
                continue
            available_days = rec._get_available_days_for_request()
            rec.allocation_bypassed = (
                    available_days != float("inf")
                    and rec._get_requested_days_count() > (available_days + 1e-6)
            )

    def _get_request_calendar(self):
        self.ensure_one()
        return (
                self.employee_id.resource_calendar_id
                or self.company_id.resource_calendar_id
                or self.env.company.resource_calendar_id
        )

    def _get_weekend_dates_in_period(self):
        self.ensure_one()
        if not self.date_from or not self.date_to or self.date_to < self.date_from:
            return []

        calendar_id = self._get_request_calendar()
        if calendar_id and calendar_id.attendance_ids:
            working_weekdays = {int(attendance.dayofweek) for attendance in calendar_id.attendance_ids}
        else:
            working_weekdays = set(range(5))  # Default Mon-Fri

        weekend_dates = []
        current_date = self.date_from
        while current_date <= self.date_to:
            if current_date.weekday() not in working_weekdays:
                weekend_dates.append(current_date)
            current_date += timedelta(days=1)
        return weekend_dates

    def _check_leave_request_weekend_dates(self):
        """Block single-day non-working requests, allow multi-day"""
        for rec in self:
            non_working_dates = rec._get_non_working_dates_in_period()
            total_days = (rec.date_to - rec.date_from).days + 1

            if total_days > 1:
                continue  # ✅ Multi-day OK

            if non_working_dates:
                formatted_dates = ", ".join(format_date(rec.env, date) for date in non_working_dates)
                raise ValidationError(_(
                    "Cannot request leave on non-working date(s) (weekend/public holiday): %(dates)s"
                ) % {"dates": formatted_dates})

    @api.constrains("employee_id", "company_id", "date_from", "date_to")
    def _check_weekend_dates(self):
        self._check_leave_request_weekend_dates()

    def _is_request_for_current_user_employee(self):
        self.ensure_one()
        return bool(
            self.employee_id
            and self.employee_id.user_id
            and self.employee_id.user_id == self.env.user
        )

    def _can_bypass_annual_leave_start_date(self):
        self.ensure_one()
        return (
            self.env.user.has_group('pr_hr_holidays.group_leave_allocation_limit_override')
            and not self._is_request_for_current_user_employee()
        )

    @api.constrains("leave_type_id", "date_from", "employee_id")
    def _check_annual_leave_start_date(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.leave_type_id or not rec.date_from:
                continue
            if rec._can_bypass_annual_leave_start_date():
                continue

            if rec.leave_type_id.leave_type == "annual_leave" and rec.date_from <= today:
                raise ValidationError(_("Annual Leave requests must start from tomorrow onward."))

    # endregion [Compute Methods]

    # region [Onchange Methods]

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        self.ensure_one()
        if self.employee_id.company_id:
            self.company_id = self.employee_id.company_id.id

    @api.onchange("employee_id", "company_id", "date_from", "date_to")
    def _onchange_leave_request_dates(self):
        for rec in self:
            weekend_dates = rec._get_weekend_dates_in_period()
            total_days = (rec.date_to - rec.date_from).days + 1 if rec.date_from and rec.date_to else 0

            # Only show warning for single-day weekend requests
            if total_days == 1 and weekend_dates:
                formatted_dates = ", ".join(format_date(rec.env, date) for date in weekend_dates)
                return {
                    "warning": {
                        "title": _("Weekend Date Selected"),
                        "message": _(
                            "You cannot request leave on weekend/non-working date(s): %(dates)s."
                        ) % {"dates": formatted_dates},
                    }
                }

    def _send_hr_manager_cancellation_email(self):
        for rec in self:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            record_url = base_url + "/web#id=" + str(
                rec.id) + "&view_type=form&model=pr.hr.leave.request&view_type=form"

            user_ids = rec._get_group_users_for_company(HR_MANAGER_GROUP, rec.company_id)
            if user_ids:
                for user in user_ids:
                    employee_id = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
                    if employee_id and employee_id.work_email:
                        body_message = f"""Dear Mr/Mrs. {employee_id.name},<br/><br/>

                            We wish to inform you that employee {rec.employee_id.name} has requested a <strong>Cancellation for Leave Request {rec.name}</strong>.<br/><br/>
                            You can check the request to take a decision by clicking this button <a class="btn btn-primary" href="{record_url}" role="button">Leave Request</a><br/><br/><br/>
                            Thank you for your attention to this matter.<br/><br/>
                            Best regards,<br/>
                            <strong>HR Department</strong><br/>
                            Petroraq Engineering
                            """
                        receiver = employee_id.work_email
                        mail = self.env["mail.mail"]
                        mail_id = mail.sudo().create(
                            rec._prepare_email_vals(body_message=body_message, receiver=receiver))
                        if mail_id:
                            mail_id.sudo().send()

    # endregion [Onchange Methods]

    # region [Emails]

    def _prepare_email_vals(self, body_message, receiver):
        for rec in self:
            message = {
                "email_from": "noreply@petroraq.com",
                "subject": f"{rec.employee_id.code} - Leave Request From {rec.date_from} To {rec.date_to}",
                "body_html": body_message,
                "email_to": receiver,
            }
            return message

    def _send_manager_email(self):
        for rec in self:
            manager = rec.employee_id.parent_id or rec.employee_manager_id
            receiver = manager.work_email if manager else False
            if not receiver:
                continue
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            record_url = base_url + "/web#id=" + str(
                rec.id) + "&view_type=form&model=pr.hr.leave.request&view_type=form"

            body_message = f"""Dear Mr/Mrs. {manager.name},<br/><br/>

                We wish to inform you that your employee {rec.employee_id.name} has been asked for <strong>Leave Request From {rec.date_from} To {rec.date_to}</strong>.<br/><br/>
                You can check the request to take a decision by clicking this button <a class="btn btn-primary" href="{record_url}" role="button">Leave Request</a><br/><br/><br/>
                Thank you for your attention to this matter.<br/><br/>
                Best regards,<br/>
                <strong>HR Department</strong><br/>
                Petroraq Engineering
                """
            mail = self.env["mail.mail"]
            mail_id = mail.sudo().create(rec._prepare_email_vals(body_message=body_message, receiver=receiver))
            if mail_id:
                mail_id.sudo().send()

    def _send_hr_supervisor_email(self):
        for rec in self:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            record_url = base_url + "/web#id=" + str(
                rec.id) + "&view_type=form&model=pr.hr.leave.request&view_type=form"

            user_ids = rec._get_group_users_for_company(HR_SUPERVISOR_GROUP, rec.company_id)
            if user_ids:
                for user in user_ids:
                    employee_id = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
                    if employee_id and employee_id.work_email:
                        body_message = f"""Dear Mr/Mrs. {employee_id.name},<br/><br/>

                            We wish to inform you that your employee {rec.employee_id.name} has been asked for <strong>Leave Request From {rec.date_from} To {rec.date_to}</strong>.<br/><br/>
                            You can check the request to take a decision by clicking this button <a class="btn btn-primary" href="{record_url}" role="button">Leave Request</a><br/><br/><br/>
                            Thank you for your attention to this matter.<br/><br/>
                            Best regards,<br/>
                            <strong>HR Department</strong><br/>
                            Petroraq Engineering
                            """
                        receiver = employee_id.work_email
                        mail = self.env["mail.mail"]
                        mail_id = mail.sudo().create(
                            rec._prepare_email_vals(body_message=body_message, receiver=receiver))
                        if mail_id:
                            mail_id.sudo().send()

    def _send_hr_manager_email(self):
        for rec in self:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            record_url = base_url + "/web#id=" + str(
                rec.id) + "&view_type=form&model=pr.hr.leave.request&view_type=form"

            user_ids = rec._get_group_users_for_company(HR_MANAGER_GROUP, rec.company_id)
            if user_ids:
                for user in user_ids:
                    employee_id = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
                    if employee_id and employee_id.work_email:
                        body_message = f"""Dear Mr/Mrs. {employee_id.name},<br/><br/>

                            We wish to inform you that your employee {rec.employee_id.name} has been asked for <strong>Leave Request From {rec.date_from} To {rec.date_to}</strong>.<br/><br/>
                            You can check the request to take a decision by clicking this button <a class="btn btn-primary" href="{record_url}" role="button">Leave Request</a><br/><br/><br/>
                            Thank you for your attention to this matter.<br/><br/>
                            Best regards,<br/>
                            <strong>HR Department</strong><br/>
                            Petroraq Engineering
                            """
                        receiver = employee_id.work_email
                        mail = self.env["mail.mail"]
                        mail_id = mail.sudo().create(
                            rec._prepare_email_vals(body_message=body_message, receiver=receiver))
                        if mail_id:
                            mail_id.sudo().send()

    def _send_result_to_employee(self, result):
        for rec in self:
            receiver = rec.employee_id.work_email
            if not receiver:
                continue
            body_message = f"""Dear Mr/Mrs. {rec.employee_id.name},<br/><br/>

                We wish to inform you that your Leave Request {rec.name} has been <strong>{result}</strong>.<br/><br/>
                Thank you for your attention to this matter.<br/><br/>
                Best regards,<br/>
                <strong>HR Department</strong><br/>
                Petroraq Engineering
                """
            mail = self.env["mail.mail"]
            mail_id = mail.sudo().create(rec._prepare_email_vals(body_message=body_message, receiver=receiver))
            if mail_id:
                mail_id.sudo().send()

    # endregion [Emails]

    # region [Actions]

    def _get_requested_days_count(self):
        self.ensure_one()
        if self.date_from and self.date_to and self.date_to < self.date_from:
            raise ValidationError(_("Date To must be greater than or equal to Date From."))
        return self.requested_days  # Now correctly reflects working days only

    def _get_available_days_for_request(self):
        self.ensure_one()
        if not self.employee_id or not self.leave_type_id:
            return 0.0

        leave_type = self.leave_type_id
        employee = self.employee_id

        target_date = self.date_to or self.date_from or fields.Date.context_today(self)
        allocation_data = leave_type.get_allocation_data(employee, target_date).get(employee, [])
        leave_type_data = next(
            (
                data
                for _name, data, _requires_allocation, leave_type_id in allocation_data
                if leave_type_id == leave_type.id
            ),
            {},
        )
        virtual_remaining = float(leave_type_data.get("virtual_remaining_leaves", 0.0) or 0.0)
        if leave_type.allows_negative:
            virtual_remaining += float(leave_type.max_allowed_negative or 0.0)

        # Fallback for custom leave types where dashboard-like computed balances are not available.
        if abs(virtual_remaining) < 1e-6 and leave_type.requires_allocation != "yes":
            virtual_remaining = 30.0 if getattr(leave_type, "leave_type", False) == "sick_leave" else 0.0

        # Do not count "draft" requests here to avoid showing misleading "0 available"
        # on initial portal submission; drafts are not yet manager-confirmed commitments.
        pending_states = ["manager_approve", "hr_supervisor"]
        domain = [
            ("employee_id", "=", employee.id),
            ("leave_type_id", "=", leave_type.id),
            ("state", "in", pending_states),
        ]
        if isinstance(self.id, int):
            domain.insert(0, ("id", "!=", self.id))
        pending_requests = self.search(domain)
        pending_days = sum(req._get_requested_days_count() for req in pending_requests)
        return virtual_remaining - pending_days

    def _check_requested_days_with_allocation(self):
        for rec in self:
            if self.env.user.has_group('pr_hr_holidays.group_leave_allocation_limit_override'):
                continue
            if rec.allocation_override_applied:
                continue
            if rec.state in ('hr_approve', 'cancel_request', 'cancelled', 'reject'):
                continue
            if rec.leave_id:
                continue

            requested_days = rec._get_requested_days_count()
            if requested_days <= 0:
                continue

            available_days = rec._get_available_days_for_request()
            if available_days != float("inf") and requested_days > (available_days + 1e-6):
                raise ValidationError(_(
                    "You cannot request %(requested).2f day(s) for %(leave_type)s. "
                    "Only %(available).2f day(s) are available."
                ) % {
                                          "requested": requested_days,
                                          "leave_type": rec.leave_type_id.display_name,
                                          "available": max(0.0, available_days),
                                      })

    def _get_user_identity_key(self, user):
        employee = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
        if employee:
            return ("emp", employee.id)
        return ("user", user.id)

    def _finalize_hr_manager_approval(self, actor, approval_date, chatter_body=None):
        self.ensure_one()
        actor = actor or self.env.user
        actor_has_allocation_override = bool(
            actor and actor.has_group("pr_hr_holidays.group_leave_allocation_limit_override")
        )
        rec = self.sudo()
        available_days = rec._get_available_days_for_request()
        bypassed_allocation_limit = (
            actor_has_allocation_override
            and available_days != float("inf")
            and rec._get_requested_days_count() > (available_days + 1e-6)
        )
        rec.write({
            "allocation_override_applied": bypassed_allocation_limit,
            "allocation_override_note": _(
                "Advance allocation: this leave was approved without available allocation."
            ) if bypassed_allocation_limit else False,
        })
        rec.with_user(actor)._check_requested_days_with_allocation()
        rec.write({
            "state": "hr_approve",
            "approval_state": "hr_approve",
            "hr_manager_approved_user_id": actor.id if actor else False,
            "hr_manager_approved_date": approval_date,
        })
        rec._create_employee_leave(allocation_override=actor_has_allocation_override)
        if chatter_body:
            rec.message_post(body=chatter_body)
        rec._send_result_to_employee(result="Approved")
        return True

    def _route_at_hr_supervisor_stage(self, actor=None, include_submitter=True):
        self.ensure_one()
        actor = actor or self.env.user
        now = fields.Datetime.now()
        actor_is_hr_sup = self._user_is_hr_supervisor(actor)
        actor_is_hr_mgr = self._user_is_hr_manager(actor)

        if actor_is_hr_sup and actor_is_hr_mgr:
            self.sudo().write({
                "hr_supervisor_approved_user_id": actor.id,
                "hr_supervisor_approved_date": now,
            })
            self._finalize_hr_manager_approval(
                actor=actor,
                approval_date=now,
                chatter_body=_("Approved by HR Supervisor and HR Manager."),
            )
            return

        if actor_is_hr_sup:
            self.sudo().write({
                "state": "hr_supervisor",
                "approval_state": "hr_supervisor",
                "hr_supervisor_approved_user_id": actor.id,
                "hr_supervisor_approved_date": now,
            })
            if actor == self.create_uid:
                body = _("Submitted and auto-advanced to HR Manager Approval based on submitter access rights.")
            else:
                body = _("Auto-advanced to HR Manager Approval based on approver access rights.")
            self.sudo().message_post(body=body)
            self.sudo()._send_hr_manager_email()
            return

        if include_submitter and self.create_uid and self.create_uid != actor:
            submitter = self.create_uid
            if self._user_is_hr_supervisor(submitter) and not self._user_is_hr_manager(submitter):
                self.sudo().write({
                    "state": "hr_supervisor",
                    "approval_state": "hr_supervisor",
                    "hr_supervisor_approved_user_id": submitter.id,
                    "hr_supervisor_approved_date": now,
                })
                self.sudo().message_post(
                    body=_("Auto-advanced to HR Manager Approval based on submitter access rights.")
                )
                self.sudo()._send_hr_manager_email()
                return

        if self._should_forward_escalate_hr_supervisor_to_hr_manager():
            self.sudo().write({
                "state": "hr_supervisor",
                "approval_state": "hr_supervisor",
            })
            self.sudo().message_post(
                body=_("Routed directly to HR Manager Approval based on HR Supervisor approver access rights.")
            )
            self.sudo()._send_hr_manager_email()
            return

        self.sudo().write({
            "state": "manager_approve",
            "approval_state": "manager_approve",
        })
        self.sudo()._send_hr_supervisor_email()

    def _route_after_create(self):
        self.ensure_one()
        submitter = self.env.user
        now = fields.Datetime.now()
        submitter_is_hr_sup = self._user_is_hr_supervisor(submitter)
        submitter_is_hr_mgr = self._user_is_hr_manager(submitter)

        if submitter_is_hr_sup and submitter_is_hr_mgr:
            vals = {
                "hr_supervisor_approved_user_id": submitter.id,
                "hr_supervisor_approved_date": now,
            }
            if self._user_is_dept_manager(submitter):
                vals.update({
                    "manager_approved_user_id": submitter.id,
                    "manager_approved_date": now,
                })
            self.sudo().write(vals)
            self._finalize_hr_manager_approval(
                actor=submitter,
                approval_date=now,
                chatter_body=_("Auto-approved on submission by HR Supervisor and HR Manager."),
            )
            return

        manager_user = self.employee_manager_id.user_id.filtered(lambda u: u.active)
        has_distinct_manager = bool(
            manager_user
            and self._get_user_identity_key(manager_user) != self._get_user_identity_key(submitter)
        )
        if has_distinct_manager:
            self.sudo()._send_manager_email()
            return

        advance_vals = {
            "state": "manager_approve",
            "approval_state": "manager_approve",
        }
        if self._user_is_dept_manager(submitter) or (
            manager_user
            and self._get_user_identity_key(manager_user) == self._get_user_identity_key(submitter)
        ):
            advance_vals.update({
                "manager_approved_user_id": submitter.id,
                "manager_approved_date": now,
            })
        self.sudo().write(advance_vals)
        self._route_at_hr_supervisor_stage(actor=submitter, include_submitter=True)

    def action_manager_approve(self):
        actor = self.env.user
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("This leave request is not awaiting Department Manager approval."))
            if rec._user_is_hr_manager(actor):
                rec.action_hr_manager_approve()
                continue
            if not rec._user_is_dept_manager(actor):
                raise AccessError(_("Only the Department Manager can approve this stage."))
            now = fields.Datetime.now()
            rec.sudo().write({
                "state": "manager_approve",
                "approval_state": "manager_approve",
                "manager_approved_user_id": actor.id,
                "manager_approved_date": now,
            })
            rec._route_at_hr_supervisor_stage(actor=actor, include_submitter=True)
        return True

    def action_employee_cancel_request(self):
        for rec in self:
            rec = rec.sudo()
            rec.state = "cancel_request"
            rec.approval_state = "cancel_request"
            rec._send_hr_manager_cancellation_email()

    def action_hr_manager_cancel_approve(self):
        if not self._user_is_hr_manager():
            raise AccessError(_("Only an HR Manager can approve leave request cancellations."))
        for rec in self:
            if rec.state != "cancel_request":
                raise UserError(_("This leave request is not awaiting cancellation approval."))
            rec = rec.sudo()
            rec.state = "cancelled"
            rec.approval_state = "cancelled"
            if rec.leave_id:
                if hasattr(rec.leave_id.sudo(), "action_refuse"):
                    try:
                        rec.leave_id.sudo().action_refuse()
                    except Exception:
                        rec.leave_id.sudo().state = "refuse"
                else:
                    rec.leave_id.sudo().state = "refuse"
            rec._send_result_to_employee(result="Cancelled")
        return True

    def _open_reject_wizard(self, stage):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reject Reason',
            'res_model': 'pr.reject.record.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_record_id': '%s,%s' % (self._name, self.id),
                'pr_leave_rejection_stage': stage,
            },
            'views': [(self.env.ref('pr_base.pr_reject_record_wizard_view_form').id, 'form')],
        }

    def action_reject(self):
        actor = self.env.user
        for rec in self:
            if rec.state not in APPROVAL_STATES:
                raise UserError(_("This leave request cannot be rejected in its current state."))
            if rec._user_is_hr_manager(actor):
                return rec._open_reject_wizard("hr_manager")
            if rec.state == "manager_approve" and rec._user_is_hr_supervisor(actor):
                return rec._open_reject_wizard("hr_supervisor")
            if rec.state == "draft" and rec._user_is_dept_manager(actor):
                return rec._open_reject_wizard("manager")
            raise AccessError(_("You are not allowed to reject this leave request at the current stage."))

    def action_manager_reject(self):
        actor = self.env.user
        for rec in self:
            if not rec._user_can_reject_stage("manager", actor):
                raise AccessError(_("You are not allowed to reject this leave request at the current stage."))
            return rec._open_reject_wizard("manager")

    def action_hr_supervisor_approve(self):
        actor = self.env.user
        if not self._user_is_hr_supervisor(actor):
            raise AccessError(_("Only an HR Supervisor can approve this stage."))
        for rec in self:
            if rec.state != "manager_approve":
                raise UserError(_("This leave request is not awaiting HR Supervisor approval."))
            now = fields.Datetime.now()
            rec.sudo().write({
                "hr_supervisor_approved_user_id": actor.id,
                "hr_supervisor_approved_date": now,
            })
            if rec._user_is_hr_manager(actor):
                rec._finalize_hr_manager_approval(
                    actor=actor,
                    approval_date=now,
                    chatter_body=_("Approved by HR Supervisor and HR Manager."),
                )
                continue
            rec.sudo().write({
                "state": "hr_supervisor",
                "approval_state": "hr_supervisor",
            })
            rec.sudo()._send_hr_manager_email()
        return True

    def action_hr_supervisor_reject(self):
        actor = self.env.user
        for rec in self:
            if not rec._user_can_reject_stage("hr_supervisor", actor):
                raise AccessError(_("You are not allowed to reject this leave request at the current stage."))
            return rec._open_reject_wizard("hr_supervisor")

    def action_hr_manager_approve(self):
        actor = self.env.user
        if not self._user_is_hr_manager(actor):
            raise AccessError(_("Only an HR Manager can approve this stage."))
        for rec in self:
            if rec.state not in APPROVAL_STATES:
                raise UserError(_("This leave request cannot be approved in its current state."))
            previous_state = rec.state
            now = fields.Datetime.now()
            is_dept_mgr = rec._user_is_dept_manager(actor)
            is_hr_sup = rec._user_is_hr_supervisor(actor)
            extra_vals = {}
            chatter_body = None

            if previous_state == "draft":
                if is_dept_mgr:
                    extra_vals["manager_approved_user_id"] = actor.id
                    extra_vals["manager_approved_date"] = now
                if is_hr_sup:
                    extra_vals["hr_supervisor_approved_user_id"] = actor.id
                    extra_vals["hr_supervisor_approved_date"] = now
                if is_dept_mgr and is_hr_sup:
                    chatter_body = _("Approved by Department Manager, HR Supervisor, and HR Manager.")
                else:
                    chatter_body = _("Approved by HR Manager via skip-level approval.")
            elif previous_state == "manager_approve":
                if is_hr_sup:
                    extra_vals["hr_supervisor_approved_user_id"] = actor.id
                    extra_vals["hr_supervisor_approved_date"] = now
                    chatter_body = _("Approved by HR Supervisor and HR Manager.")
                else:
                    chatter_body = _("Approved by HR Manager via skip-level approval.")

            if extra_vals:
                rec.sudo().write(extra_vals)
            rec._finalize_hr_manager_approval(
                actor=actor,
                approval_date=now,
                chatter_body=chatter_body,
            )
        return True

    def action_hr_manager_reject(self):
        actor = self.env.user
        for rec in self:
            if not rec._user_can_reject_stage("hr_manager", actor):
                raise AccessError(_("You are not allowed to reject this leave request at the current stage."))
            return rec._open_reject_wizard("hr_manager")

    def _create_employee_leave(self, allocation_override=False):
        for rec in self:
            leave_context = {
                "tracking_disable": True,
                "mail_activity_automation_skip": True,
                "leave_fast_create": True,
                "leave_skip_state_check": True,
                "pr_leave_request_allocation_checked": True,
            }
            if allocation_override:
                leave_context["pr_leave_allocation_override"] = True

            leave_vals = {
                'name': f"{rec.employee_id.name} Leave From {rec.date_from} To {rec.date_to}",
                "employee_id": rec.employee_id.id,
                "holiday_status_id": rec.leave_type_id.id,
                "request_date_from": rec.date_from,
                "request_date_to": rec.date_to,
                "leave_request_id": rec.id,
                "allocation_override_applied": bool(rec.allocation_override_applied),
                "allocation_override_note": rec.allocation_override_note or False,
            }
            leave_id = self.env["hr.leave"].with_context(**leave_context).sudo().create(leave_vals)
            if leave_id:
                rec.leave_id = leave_id.id
                leave_id.with_context(**leave_context).sudo().state = "validate"
                return leave_id
            else:
                return False

    def action_open_leave(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "hr.leave",
            "res_id": self.leave_id.id,
            "views": [[self.env.ref('hr_holidays.hr_leave_view_form').id, "form"]],
            "target": "current",
            "name": self.leave_id.name
        }

    # endregion [Actions]

    # region [Constrains]

    @api.constrains("state")
    def _check_reject_state(self):
        for rec in self:
            if rec.state == "reject":
                rec.approval_state = "reject"
                rec._send_result_to_employee(result="Rejected")

    # region [Constrains]

    # region [Crud]

    @api.model
    def _validate_leave_request_create_vals(self, vals):
        validation_record = self.new(dict(vals))
        validation_record._compute_requested_days()
        validation_record._check_leave_request_weekend_dates()
        validation_record._check_annual_leave_start_date()
        validation_record._check_requested_days_with_allocation()

    @api.model_create_multi
    def create(self, vals_list):
        '''
        We Inherit Create Method To Pass Sequence Fo Field Name
        '''
        for vals in vals_list:
            if not vals.get("name"):
                vals["name"] = self.env['ir.sequence'].next_by_code('hr.holidays.leave.request.seq.code') or '/'
            self._validate_leave_request_create_vals(vals)

        records = super().create(vals_list)
        for rec in records:
            hr_supervisor_ids = self._get_group_users_for_company(HR_SUPERVISOR_GROUP, rec.company_id)
            hr_manager_ids = self._get_group_users_for_company(HR_MANAGER_GROUP, rec.company_id)
            setup_vals = {}
            employee_manager_id = rec.employee_id.parent_id
            if employee_manager_id:
                setup_vals["employee_manager_id"] = employee_manager_id.id
            if hr_supervisor_ids:
                setup_vals["hr_supervisor_ids"] = [(6, 0, hr_supervisor_ids.ids)]
            if hr_manager_ids:
                setup_vals["hr_manager_ids"] = [(6, 0, hr_manager_ids.ids)]
            if setup_vals:
                rec.sudo().write(setup_vals)

            rec._route_after_create()
        return records

    def write(self, vals):
        res = super().write(vals)
        date_employee_fields = {"employee_id", "leave_type_id", "date_from", "date_to"}
        if date_employee_fields.intersection(vals.keys()):
            self._check_leave_request_weekend_dates()
            self._check_requested_days_with_allocation()
        elif "state" in vals:
            target_state = vals.get("state")
            if target_state not in ("cancel_request", "cancelled", "reject", "hr_approve"):
                self._check_requested_days_with_allocation()
        return res

    def unlink(self):
        for rec in self:
            if rec.state != 'draft':
                raise ValidationError("This Leave Request Should Be Draft To Can Delete !!")
        return super().unlink()

    # endregion [Crud]
