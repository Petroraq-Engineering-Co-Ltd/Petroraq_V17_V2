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


class _LeaveDryRunDone(Exception):
    """Raised to roll back the savepoint of a successful hr.leave dry run."""

HR_SUPERVISOR_GROUP = "pr_hr.group_hr_supervisor"
HR_MANAGER_GROUP = "pr_hr.group_hr_manager"
MD_GROUP = "pr_hr.group_hr_md"
ALLOCATION_OVERRIDE_GROUP = "pr_hr_holidays.group_leave_allocation_limit_override"
APPROVAL_STATES = (
    "employee_manager_approval",
    "hr_supervisor_approval",
    "hr_manager_approval",
    "md_approval",
)
WORKFLOW_PROTECTED_FIELDS = frozenset({
    "state",
    "approval_state",
    "manager_approved_user_id",
    "manager_approved_date",
    "hr_supervisor_approved_user_id",
    "hr_supervisor_approved_date",
    "hr_manager_approved_user_id",
    "hr_manager_approved_date",
    "md_approved_user_id",
    "md_approved_date",
    "rejected_stage",
    "rejected_from_state",
    "rejected_by_user_id",
    "reject_reason",
    "allocation_override_applied",
    "allocation_override_note",
    "leave_id",
})
APPROVAL_STAGE_CHAIN = (
    ("employee_manager_approval", "employee_manager", "Dept. Manager"),
    ("hr_supervisor_approval", "hr_supervisor", "HR Supervisor"),
    ("hr_manager_approval", "hr_manager", "HR Manager"),
    ("md_approval", "md", "MD"),
)
# Approver audit fields of each stage, in chain order.
STAGE_APPROVAL_FIELDS = (
    ("employee_manager_approval", "manager_approved_user_id", "manager_approved_date"),
    ("hr_supervisor_approval", "hr_supervisor_approved_user_id", "hr_supervisor_approved_date"),
    ("hr_manager_approval", "hr_manager_approved_user_id", "hr_manager_approved_date"),
    ("md_approval", "md_approved_user_id", "md_approved_date"),
)


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

    @api.model
    def _default_employee_id(self):
        employee = self.env["hr.employee"].sudo().search([
            ("user_id", "=", self.env.uid),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        return employee.id if employee else False

    @api.model
    def _default_company_id(self):
        employee_id = self._default_employee_id()
        if employee_id:
            employee = self.env["hr.employee"].sudo().browse(employee_id)
            if employee.company_id:
                return employee.company_id.id
        return self.env.company.id

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
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self._default_company_id(),
        tracking=True,
        required=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        default=lambda self: self._default_employee_id(),
        tracking=True,
        required=True,
    )
    employee_manager_id = fields.Many2one('hr.employee', string='Manager', tracking=True, readonly=True)
    hr_supervisor_ids = fields.Many2many('res.users', 'leave_request_hr_supervisor_users', 'hr_supervisor_id',
                                         'leave_request_id', string='HR Supervisors', tracking=True, readonly=True)
    hr_manager_ids = fields.Many2many('res.users', 'leave_request_hr_manager_users', 'hr_manager_id',
                                      'leave_request_id', string='HR Managers', tracking=True, readonly=True)
    submitted_by_id = fields.Many2one('res.users', string='Submitted By', readonly=True, copy=False)
    manager_approved_user_id = fields.Many2one('res.users', string='Manager Approved By', readonly=True, copy=False)
    manager_approved_date = fields.Datetime(string='Manager Approved On', readonly=True, copy=False)
    hr_supervisor_approved_user_id = fields.Many2one('res.users', string='HR Supervisor Approved By', readonly=True,
                                                     copy=False)
    hr_supervisor_approved_date = fields.Datetime(string='HR Supervisor Approved On', readonly=True, copy=False)
    hr_manager_approved_user_id = fields.Many2one('res.users', string='HR Manager Approved By', readonly=True,
                                                  copy=False)
    hr_manager_approved_date = fields.Datetime(string='HR Manager Approved On', readonly=True, copy=False)
    md_approved_user_id = fields.Many2one('res.users', string='MD Approved By', readonly=True, copy=False)
    md_approved_date = fields.Datetime(string='MD Approved On', readonly=True, copy=False)
    reject_reason = fields.Text(string="Rejection Reason", readonly=True, tracking=True)
    rejected_stage = fields.Selection([
        ('manager', 'Dept. Manager'),
        ('hr_supervisor', 'HR Supervisor'),
        ('hr_manager', 'HR Manager'),
        ('md', 'MD'),
    ], string='Rejected At', readonly=True, copy=False, tracking=True)
    rejected_from_state = fields.Selection([
        ('employee_manager_approval', 'Dept. Manager'),
        ('hr_supervisor_approval', 'HR Supervisor'),
        ('hr_manager_approval', 'HR Manager'),
        ('md_approval', 'MD'),
    ], string='Rejected From State', readonly=True, copy=False)
    rejected_by_user_id = fields.Many2one(
        'res.users', string='Rejected By', readonly=True, copy=False, tracking=True
    )
    can_reset_rejection = fields.Boolean(compute='_compute_can_reset_rejection')
    can_reset_to_draft = fields.Boolean(compute='_compute_can_reset_to_draft')
    note = fields.Text(string="Note")
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "pr_hr_leave_request_attachment_rel",
        "request_id",
        "attachment_id",
        string="Attachments",
        copy=False,
        help="Supporting documents, e.g. the medical certificate. Required for sick leave.",
    )
    is_sick_leave = fields.Boolean(compute="_compute_is_sick_leave")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('employee_manager_approval', 'Dept. Manager'),
        ('hr_supervisor_approval', 'HR Supervisor'),
        ('hr_manager_approval', 'HR Manager'),
        ('md_approval', 'MD'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancel_request', 'Cancellation Requested'),
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True, copy=False,
        string='Status', required=True, index=True)
    approval_state = fields.Selection([
        ('draft', 'Draft'),
        ('employee_manager_approval', 'Pending Dept. Manager'),
        ('hr_supervisor_approval', 'Pending HR Supervisor'),
        ('hr_manager_approval', 'Pending HR Manager'),
        ('md_approval', 'Pending MD'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancel_request', 'Pending Cancellation Approval'),
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True, copy=False,
        string='Approval Status')
    employee_manager_check = fields.Boolean(compute="_compute_employee_manager_check")
    employee_user_check = fields.Boolean(compute="_compute_employee_user_check")
    hr_supervisor_check = fields.Boolean(compute="_compute_hr_supervisor_check")
    hr_manager_check = fields.Boolean(compute="_compute_hr_manager_check")
    can_select_employee = fields.Boolean(compute="_compute_can_select_employee")
    can_submit = fields.Boolean(compute="_compute_approval_button_visibility")
    can_manager_approve = fields.Boolean(compute="_compute_approval_button_visibility")
    can_hr_supervisor_approve = fields.Boolean(compute="_compute_approval_button_visibility")
    can_hr_manager_approve = fields.Boolean(compute="_compute_approval_button_visibility")
    can_md_approve = fields.Boolean(compute="_compute_approval_button_visibility")
    dashboard_approve_role = fields.Selection([
        ('md', 'MD'),
        ('hr_manager', 'HR Manager'),
        ('hr_supervisor', 'HR Supervisor'),
        ('employee_manager', 'Dept. Manager'),
        ('none', 'None'),
    ], string="Dashboard Approve Role", compute="_compute_approval_button_visibility")
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
             WHERE state = 'rejected'
               AND rejected_stage IS NULL
        """)
        self.env.cr.execute("""
            UPDATE pr_hr_leave_request
               SET rejected_from_state = CASE rejected_stage
                   WHEN 'md' THEN 'md_approval'
                   WHEN 'hr_manager' THEN 'hr_manager_approval'
                   WHEN 'hr_supervisor' THEN 'hr_supervisor_approval'
                   ELSE 'employee_manager_approval'
               END
             WHERE state = 'rejected'
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

    @api.model
    def _user_is_md(self, user=None):
        user = user or self.env.user
        return bool(user and user.has_group(MD_GROUP))

    def _user_is_dept_manager(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        if not user:
            return False
        return bool(
            (self.employee_id.parent_id.user_id and self.employee_id.parent_id.user_id == user)
            or (self.employee_manager_id.user_id and self.employee_manager_id.user_id == user)
        )

    def _get_user_leave_request_roles(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        roles = set()
        if not user:
            return roles
        if self._user_is_dept_manager(user):
            roles.add("employee_manager")
        if self._user_is_hr_supervisor(user):
            roles.add("hr_supervisor")
        if self._user_is_hr_manager(user):
            roles.add("hr_manager")
        if self._user_is_md(user):
            roles.add("md")
        return roles

    def _get_highest_consecutive_role(self, user, from_state):
        """Walk APPROVAL_STAGE_CHAIN from `from_state` and return the role of the
        last stage the user can cover without a gap (False if the user does
        not hold the role of `from_state` itself)."""
        self.ensure_one()
        state_keys = [stage[0] for stage in APPROVAL_STAGE_CHAIN]
        if from_state not in state_keys:
            return False
        roles = self._get_user_leave_request_roles(user)
        highest = False
        for _state, role, _label in APPROVAL_STAGE_CHAIN[state_keys.index(from_state):]:
            if role not in roles:
                break
            highest = role
        return highest

    def _user_can_submit(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        if not user:
            return False
        return bool(
            user._is_admin()
            or (self.employee_id.user_id and self.employee_id.user_id == user)
            or (self.create_uid and self.create_uid == user)
            or self._user_is_dept_manager(user)
            or self._user_is_hr_supervisor(user)
            or self._user_is_hr_manager(user)
            or user.has_group("hr_holidays.group_hr_holidays_user")
            or user.has_group("hr_holidays.group_hr_holidays_manager")
        )

    def _user_can_reset_to_draft(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        if not user:
            return False
        return bool(
            user._is_admin()
            or (self.employee_id.user_id and self.employee_id.user_id == user)
            or (self.create_uid and self.create_uid == user)
            or (self.submitted_by_id and self.submitted_by_id == user)
            or self._user_is_hr_supervisor(user)
            or self._user_is_hr_manager(user)
            or self._user_is_md(user)
        )

    @api.model
    def _get_stage_label(self, state_key):
        return dict(self._fields["state"].selection).get(state_key, state_key)

    def _validate_dashboard_intermediate_approvals(self, target_role):
        """When approving/rejecting from the Approval Dashboard, verify that the
        current user holds every intermediate role between the record's current
        state and target_role. Raises UserError if any intermediate role is missing."""
        self.ensure_one()
        if not self.env.context.get("from_approval_dashboard"):
            return
        missing_label = self._get_missing_intermediate_role_label(target_role, self.env.user)
        if missing_label:
            raise UserError(
                _("You cannot approve this request until %s approval is completed.")
                % _(missing_label)
            )

    def _get_missing_intermediate_role_label(self, target_role, user):
        """Label of the first stage between the current state and target_role
        whose role the user does not hold, or False when they hold them all."""
        self.ensure_one()
        state_keys = [stage[0] for stage in APPROVAL_STAGE_CHAIN]
        role_keys = [stage[1] for stage in APPROVAL_STAGE_CHAIN]
        if self.state not in state_keys or target_role not in role_keys:
            return False

        current_idx = state_keys.index(self.state)
        target_idx = role_keys.index(target_role)
        if target_idx <= current_idx:
            return False

        user_roles = self._get_user_leave_request_roles(user)
        for idx in range(current_idx, target_idx):
            _st, intermediate_role, role_label = APPROVAL_STAGE_CHAIN[idx]
            if intermediate_role not in user_roles:
                return role_label
        return False

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

    def _get_hr_supervisor_forward_state(self):
        """State a request entering the HR Supervisor stage is forwarded to,
        based on the later roles held by EVERY active HR Supervisor of the
        request's company (False: stay at HR Supervisor).

        - all supervisors hold HR Manager and MD -> md_approval
        - all hold HR Manager, or all hold MD but not HR Manager (gap: the
          request comes back to them at MD) -> hr_manager_approval
        """
        self.ensure_one()
        supervisors = self._get_group_users_for_company(HR_SUPERVISOR_GROUP, self.company_id)
        if not supervisors:
            return False
        all_hr_manager = all(user.has_group(HR_MANAGER_GROUP) for user in supervisors)
        all_md = all(user.has_group(MD_GROUP) for user in supervisors)
        if all_hr_manager and all_md:
            return "md_approval"
        if all_hr_manager or all_md:
            return "hr_manager_approval"
        return False

    def _record_skipped_stage_approvals(self, actor, approval_date, before_state):
        """Record `actor` on every earlier stage that was skipped (no approver
        recorded) and whose role `actor` holds. Stages the actor does not hold
        stay empty."""
        self.ensure_one()
        stage_states = [stage[0] for stage in STAGE_APPROVAL_FIELDS]
        role_by_state = {stage[0]: stage[1] for stage in APPROVAL_STAGE_CHAIN}
        roles = self._get_user_leave_request_roles(actor)
        vals = {}
        for state, user_field, date_field in STAGE_APPROVAL_FIELDS[:stage_states.index(before_state)]:
            if not self[user_field] and role_by_state[state] in roles:
                vals.update({user_field: actor.id, date_field: approval_date})
        if vals:
            self.sudo().write(vals)

    @api.model
    def _get_pending_approval_domain(self, user=None):
        user = user or self.env.user
        role_domains = [
            [
                ("state", "=", "employee_manager_approval"),
                "|",
                ("employee_manager_id.user_id", "=", user.id),
                ("employee_id.parent_id.user_id", "=", user.id),
            ],
        ]
        if self._user_is_hr_supervisor(user):
            role_domains.append([("state", "=", "hr_supervisor_approval")])
        if self._user_is_hr_manager(user):
            role_domains.append([("state", "in", ["hr_manager_approval", "cancel_request"])])
        if self._user_is_md(user):
            role_domains.append([("state", "=", "md_approval")])
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

    @api.model
    def _user_can_select_any_employee(self, user=None):
        user = user or self.env.user
        return bool(
            user
            and (
                user._is_admin()
                or user.has_group(HR_SUPERVISOR_GROUP)
                or user.has_group(HR_MANAGER_GROUP)
                or user.has_group("hr_holidays.group_hr_holidays_manager")
            )
        )

    @api.depends_context("uid")
    def _compute_hr_manager_check(self):
        is_hr_mgr = self._user_is_hr_manager()
        for rec in self:
            rec.hr_manager_check = is_hr_mgr

    # "state" is a dependency only so the onchange of a new (unsaved) record
    # computes this field; without a field dependency it stays False there.
    @api.depends("state")
    @api.depends_context("uid")
    def _compute_can_select_employee(self):
        can_select = self._user_can_select_any_employee()
        for rec in self:
            rec.can_select_employee = can_select

    @api.depends("state", "employee_id", "employee_id.user_id", "employee_id.parent_id.user_id",
                 "employee_manager_id", "employee_manager_id.user_id", "create_uid")
    @api.depends_context("uid", "from_approval_dashboard")
    def _compute_approval_button_visibility(self):
        user = self.env.user
        is_hr_sup = self._user_is_hr_supervisor(user)
        is_hr_mgr = self._user_is_hr_manager(user)
        is_md = self._user_is_md(user)
        from_dashboard = bool(self.env.context.get("from_approval_dashboard"))
        for rec in self:
            has_id = bool(rec.id)
            is_dept_mgr = rec._user_is_dept_manager(user)
            rec.can_submit = rec.state == "draft" and (not has_id or rec._user_can_submit(user))

            selected_role = False
            if has_id and rec.state in APPROVAL_STATES:
                if from_dashboard:
                    # Dashboard: the user's own stage, extended to every
                    # following stage they also hold without a gap.
                    selected_role = rec._get_highest_consecutive_role(user, rec.state)
                else:
                    # Backend: highest role wins, with skip-level from any
                    # earlier pending stage.
                    if is_md:
                        selected_role = "md"
                    elif is_hr_mgr and rec.state != "md_approval":
                        selected_role = "hr_manager"
                    elif is_hr_sup and rec.state in ("employee_manager_approval", "hr_supervisor_approval"):
                        selected_role = "hr_supervisor"
                    elif is_dept_mgr and rec.state == "employee_manager_approval":
                        selected_role = "employee_manager"

            rec.dashboard_approve_role = (
                (selected_role or "none") if from_dashboard else False
            )
            rec.can_manager_approve = selected_role == "employee_manager"
            rec.can_hr_supervisor_approve = selected_role == "hr_supervisor"
            rec.can_hr_manager_approve = selected_role == "hr_manager"
            rec.can_md_approve = selected_role == "md"
            rec.can_reject = bool(selected_role)
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
                rec.state == 'rejected'
                and rec._user_can_decide_rejected_stage(user)
            )

    @api.depends('state', 'leave_id', 'employee_id.user_id', 'create_uid', 'submitted_by_id')
    @api.depends_context('uid')
    def _compute_can_reset_to_draft(self):
        user = self.env.user
        for rec in self:
            rec.can_reset_to_draft = (
                bool(rec.id)
                and rec.state == 'rejected'
                and not rec.leave_id
                and rec._user_can_reset_to_draft(user)
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
        if self.rejected_stage == 'md':
            return self._user_is_md(user)
        return False

    def _user_can_reject_stage(self, stage, user):
        self.ensure_one()
        from_dashboard = bool(self.env.context.get("from_approval_dashboard"))
        if stage == 'manager':
            return self.state == 'employee_manager_approval' and self._user_is_dept_manager(user)
        if stage == 'hr_supervisor':
            if not (
                self.state in ('employee_manager_approval', 'hr_supervisor_approval')
                and self._user_is_hr_supervisor(user)
            ):
                return False
            if from_dashboard and self.state == 'employee_manager_approval':
                return self._user_is_dept_manager(user)
            return True
        if stage == 'hr_manager':
            if not (
                self.state in ('employee_manager_approval', 'hr_supervisor_approval', 'hr_manager_approval')
                and self._user_is_hr_manager(user)
            ):
                return False
            if from_dashboard:
                return not self._get_missing_intermediate_role_label('hr_manager', user)
            return True
        if stage == 'md':
            if not (self.state in APPROVAL_STATES and self._user_is_md(user)):
                return False
            if from_dashboard:
                return not self._get_missing_intermediate_role_label('md', user)
            return True
        return False

    def _apply_stage_rejection(self, stage, reason):
        actor = self.env.user
        if not (reason or "").strip():
            raise UserError(_("Please provide a reason for rejecting this leave request."))
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
                'state': 'rejected',
                'approval_state': 'rejected',
            })
            if stage == 'md' and previous_state != 'md_approval':
                rec.sudo().message_post(
                    body=_('Rejected by MD via skip-level decision.')
                )
            elif stage == 'hr_manager' and previous_state in ('employee_manager_approval', 'hr_supervisor_approval'):
                rec.sudo().message_post(
                    body=_('Rejected by HR Manager via skip-level decision.')
                )
            elif stage == 'hr_supervisor' and previous_state == 'employee_manager_approval':
                rec.sudo().message_post(
                    body=_('Rejected by HR Supervisor via skip-level decision.')
                )

    def action_reset_rejection(self):
        stage_to_state = {
            'manager': 'employee_manager_approval',
            'hr_supervisor': 'hr_supervisor_approval',
            'hr_manager': 'hr_manager_approval',
            'md': 'md_approval',
        }
        stage_states = [stage[0] for stage in STAGE_APPROVAL_FIELDS]
        actor = self.env.user
        for rec in self:
            if rec.state != 'rejected' or not rec._user_can_decide_rejected_stage(actor):
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
            # Clear the approvals of the reopened stage and every later one.
            if target_state in stage_states:
                for _state, user_field, date_field in STAGE_APPROVAL_FIELDS[stage_states.index(target_state):]:
                    reset_vals.update({user_field: False, date_field: False})

            rec.sudo().write(reset_vals)
            rec.sudo().message_post(
                body=_('%(user)s reset the rejection and reopened the %(stage)s decision.') % {
                    'user': actor.display_name,
                    'stage': dict(rec._fields['rejected_stage'].selection).get(rejected_stage, rejected_stage),
                }
            )
        return True

    def action_reset_to_draft(self):
        actor = self.env.user
        for rec in self:
            if rec.state != 'rejected' or rec.leave_id:
                raise UserError(_('Only rejected leave requests without a validated leave can be reset to draft.'))
            if not rec._user_can_reset_to_draft(actor):
                raise AccessError(_('You are not allowed to reset this leave request to draft.'))
            rec.sudo().write({
                'state': 'draft',
                'approval_state': 'draft',
                'submitted_by_id': False,
                'manager_approved_user_id': False,
                'manager_approved_date': False,
                'hr_supervisor_approved_user_id': False,
                'hr_supervisor_approved_date': False,
                'hr_manager_approved_user_id': False,
                'hr_manager_approved_date': False,
                'md_approved_user_id': False,
                'md_approved_date': False,
                'reject_reason': False,
                'rejected_stage': False,
                'rejected_from_state': False,
                'rejected_by_user_id': False,
                'allocation_override_applied': False,
                'allocation_override_note': False,
            })
            rec.sudo().message_post(
                body=_('%(user)s reset this leave request to Draft.') % {'user': actor.display_name}
            )
        return True

    @api.depends("date_from", "date_to", "leave_type_id", "leave_type_id.leave_type", "employee_id")
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

        # 2. Public holidays (hr.public.holiday) scoped to this employee
        holiday_dates = self.employee_id._pr_get_public_holiday_dates(self.date_from, self.date_to)

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

        non_working_dates = set()

        # Add weekends
        current_date = self.date_from
        while current_date <= self.date_to:
            if current_date.weekday() not in working_weekdays:
                non_working_dates.add(current_date)
            current_date += timedelta(days=1)

        # Add public holidays scoped to this employee
        non_working_dates |= self.employee_id._pr_get_public_holiday_dates(self.date_from, self.date_to)

        return sorted(non_working_dates)

    @api.depends("requested_days", "leave_type_id", "employee_id", "date_from", "date_to", "state", "leave_id")
    def _compute_allocation_bypassed(self):
        for rec in self:
            if (
                not rec.employee_id
                or not rec.leave_type_id
                or rec.leave_id
                or rec.state in ("approved", "cancel_request", "cancelled")
            ):
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

    @api.constrains("employee_id", "date_to")
    def _check_last_working_day(self):
        for rec in self:
            if rec.state in ("rejected", "cancelled"):
                continue
            cutoff = rec.employee_id.sudo().last_working_date
            if cutoff and rec.date_to and rec.date_to > cutoff:
                raise ValidationError(_(
                    "Time off for %(employee)s cannot extend beyond the Last Working Day (%(date)s).",
                    employee=rec.employee_id.display_name,
                    date=cutoff,
                ))

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
        self._send_approver_group_email(HR_MANAGER_GROUP)

    def _send_md_email(self):
        self._send_approver_group_email(MD_GROUP)

    def _send_approver_group_email(self, group_xmlid):
        """Notify every active user of `group_xmlid` in the request's company
        that the request awaits their decision."""
        for rec in self:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            record_url = base_url + "/web#id=" + str(
                rec.id) + "&view_type=form&model=pr.hr.leave.request&view_type=form"

            user_ids = rec._get_group_users_for_company(group_xmlid, rec.company_id)
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
        # Balance check only: read allocations with sudo, otherwise approvers who
        # hold only the pr_hr HR groups (no hr_holidays group) are not allowed to
        # read the employee's allocations by record rules and always get 0 days.
        allocation_data = leave_type.sudo().get_allocation_data(employee.sudo(), target_date).get(employee, [])
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

        # Do not count "draft" or "employee_manager_approval" requests here to avoid
        # showing misleading "0 available" on initial submission before Dept. Manager
        # confirmation.
        pending_states = ["hr_supervisor_approval", "hr_manager_approval", "md_approval"]
        domain = [
            ("employee_id", "=", employee.id),
            ("leave_type_id", "=", leave_type.id),
            ("state", "in", pending_states),
        ]
        if isinstance(self.id, int):
            domain.insert(0, ("id", "!=", self.id))
        # Neutralise the approver-queue filter that de_hr_workspace_timeoff
        # applies in search_fetch (context key or approvals menu action params),
        # otherwise pending requests outside the user's queue are not counted.
        pending_requests = self.sudo().with_context(approvals_of_leave_request=False, params=None).search(domain)
        pending_days = sum(req._get_requested_days_count() for req in pending_requests)
        return virtual_remaining - pending_days

    def _check_requested_days_with_allocation(self):
        for rec in self:
            if self.env.user.has_group('pr_hr_holidays.group_leave_allocation_limit_override'):
                continue
            if rec.allocation_override_applied:
                continue
            if rec.state in ('approved', 'cancel_request', 'cancelled', 'rejected'):
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

    def _apply_approver_allocation_check(self, actor):
        """Check the allocation balance on behalf of `actor`, whose approval is
        about to move the request on. An actor in the allocation override
        group may approve beyond the balance: the request is then flagged. A
        flag set by an earlier approver is kept, so a later approver without
        the override group is not blocked by the same shortfall."""
        self.ensure_one()
        rec = self.sudo()
        available_days = rec._get_available_days_for_request()
        exceeds = (
            available_days != float("inf")
            and rec._get_requested_days_count() > (available_days + 1e-6)
        )
        actor_has_override = bool(actor and actor.has_group(ALLOCATION_OVERRIDE_GROUP))
        override = exceeds and (actor_has_override or rec.allocation_override_applied)
        rec.write({
            "allocation_override_applied": override,
            "allocation_override_note": _(
                "Advance allocation: this leave was approved without available allocation."
            ) if override else False,
        })
        rec.with_user(actor)._check_requested_days_with_allocation()

    def _finalize_approval(self, actor, approval_date, chatter_body=None):
        """Final (MD) approval: record the MD approver, approve the request and
        create its validated hr.leave."""
        self.ensure_one()
        actor = actor or self.env.user
        rec = self.sudo()
        rec._apply_approver_allocation_check(actor)
        rec.write({
            "state": "approved",
            "approval_state": "approved",
            "md_approved_user_id": actor.id,
            "md_approved_date": approval_date,
        })
        rec._create_employee_leave(
            allocation_override=bool(
                actor.has_group(ALLOCATION_OVERRIDE_GROUP) or rec.allocation_override_applied
            )
        )
        if chatter_body:
            rec.message_post(body=chatter_body)
        rec._send_result_to_employee(result="Approved")
        return True

    def _complete_hr_manager_stage(self, actor, approval_date, chatter_body=None):
        """Record `actor`'s HR Manager approval. An actor who is also MD covers
        the final MD stage in the same click; otherwise the request moves on to
        MD approval."""
        self.ensure_one()
        actor = actor or self.env.user
        self.sudo().write({
            "hr_manager_approved_user_id": actor.id,
            "hr_manager_approved_date": approval_date,
        })
        if self._user_is_md(actor):
            if chatter_body:
                self.sudo().message_post(body=chatter_body)
            return self._finalize_approval(
                actor=actor,
                approval_date=approval_date,
                chatter_body=_("MD approval given by %s, who also holds the MD role.") % actor.name,
            )
        self._apply_approver_allocation_check(actor)
        self.sudo().write({
            "state": "md_approval",
            "approval_state": "md_approval",
        })
        if chatter_body:
            self.sudo().message_post(body=chatter_body)
        self.sudo()._send_md_email()
        return True

    def _finalize_if_submitter_holds_hr_roles(self, actor, now):
        """A request submitted by a user holding both HR Supervisor and HR Manager
        only waits for the employee's direct manager. Once that approval is in
        (at whichever stage the manager approved), the submitter covers the
        HR Supervisor and HR Manager stages, and the MD stage too when they are
        MD; otherwise the request waits at MD approval. Returns True when the
        request was moved on."""
        self.ensure_one()
        submitter = self.submitted_by_id or self.create_uid
        if not submitter or submitter == actor:
            return False
        if not (self._user_is_hr_supervisor(submitter) and self._user_is_hr_manager(submitter)):
            return False
        submitter_is_md = self._user_is_md(submitter)
        approved_body = _(
            "Auto-approved after Dept. Manager approval, as submitted by HR Supervisor, HR Manager and MD."
        )
        if self.state == "md_approval":
            if not submitter_is_md:
                return False
            self._finalize_approval(actor=submitter, approval_date=now, chatter_body=approved_body)
            return True
        if not self.hr_supervisor_approved_user_id:
            self.sudo().write({
                "hr_supervisor_approved_user_id": submitter.id,
                "hr_supervisor_approved_date": now,
            })
        self._complete_hr_manager_stage(
            actor=submitter,
            approval_date=now,
            chatter_body=None if submitter_is_md else _(
                "Auto-advanced to MD Approval after Dept. Manager approval, "
                "as submitted by HR Supervisor and HR Manager."
            ),
        )
        if self.state == "approved":
            self.sudo().message_post(body=approved_body)
        return True

    def _route_at_hr_supervisor_stage(self, actor=None, include_submitter=True):
        self.ensure_one()
        actor = actor or self.env.user
        now = fields.Datetime.now()
        actor_is_hr_sup = self._user_is_hr_supervisor(actor)
        actor_is_hr_mgr = self._user_is_hr_manager(actor)
        submitter = self.submitted_by_id or self.create_uid

        if actor_is_hr_sup and actor_is_hr_mgr:
            self.sudo().write({
                "hr_supervisor_approved_user_id": actor.id,
                "hr_supervisor_approved_date": now,
            })
            self._complete_hr_manager_stage(
                actor=actor,
                approval_date=now,
                chatter_body=_("Approved by HR Supervisor and HR Manager."),
            )
            if include_submitter and self.state == "md_approval":
                self._finalize_if_submitter_holds_hr_roles(actor, now)
            return

        if include_submitter and self._finalize_if_submitter_holds_hr_roles(actor, now):
            return

        if actor_is_hr_sup:
            self.sudo().write({
                "state": "hr_manager_approval",
                "approval_state": "hr_manager_approval",
                "hr_supervisor_approved_user_id": actor.id,
                "hr_supervisor_approved_date": now,
            })
            if submitter and actor == submitter:
                body = _("Submitted and auto-advanced to HR Manager Approval based on submitter access rights.")
            else:
                body = _("Auto-advanced to HR Manager Approval based on approver access rights.")
            self.sudo().message_post(body=body)
            self.sudo()._send_hr_manager_email()
            return

        if include_submitter and submitter and submitter != actor:
            if self._user_is_hr_supervisor(submitter) and not self._user_is_hr_manager(submitter):
                self.sudo().write({
                    "state": "hr_manager_approval",
                    "approval_state": "hr_manager_approval",
                    "hr_supervisor_approved_user_id": submitter.id,
                    "hr_supervisor_approved_date": now,
                })
                self.sudo().message_post(
                    body=_("Auto-advanced to HR Manager Approval based on submitter access rights.")
                )
                self.sudo()._send_hr_manager_email()
                return

        forward_state = self._get_hr_supervisor_forward_state()
        if forward_state == "md_approval":
            self.sudo().write({"state": "md_approval", "approval_state": "md_approval"})
            self.sudo().message_post(body=_(
                "Routed directly to MD Approval, as every HR Supervisor also holds "
                "HR Manager and MD rights."
            ))
            self.sudo()._send_md_email()
            return
        if forward_state == "hr_manager_approval":
            self.sudo().write({"state": "hr_manager_approval", "approval_state": "hr_manager_approval"})
            self.sudo().message_post(
                body=_("Routed directly to HR Manager Approval based on HR Supervisor approver access rights.")
            )
            self.sudo()._send_hr_manager_email()
            return

        self.sudo().write({
            "state": "hr_supervisor_approval",
            "approval_state": "hr_supervisor_approval",
        })
        self.sudo()._send_hr_supervisor_email()

    def _route_to_manager_role_gap(self, manager_user, gap_idx, now):
        """Record the Dept. Manager's approval for every stage before
        APPROVAL_STAGE_CHAIN[gap_idx] (the first role they lack) and route the
        request to that stage, through the same routing an approval at the
        previous stage would use."""
        self.ensure_one()
        approval_vals = {}
        for _state, user_field, date_field in STAGE_APPROVAL_FIELDS[:gap_idx]:
            approval_vals.update({user_field: manager_user.id, date_field: now})
        self.sudo().write(approval_vals)
        approved_labels = ", ".join(stage[2] for stage in APPROVAL_STAGE_CHAIN[:gap_idx])
        self.sudo().message_post(body=_(
            "%(stages)s auto-approved on submission by %(manager)s, who also holds later "
            "approval rights. Routed to %(gap)s, the first role they do not hold.",
            stages=approved_labels,
            manager=manager_user.name,
            gap=APPROVAL_STAGE_CHAIN[gap_idx][2],
        ))
        gap_state = APPROVAL_STAGE_CHAIN[gap_idx][0]
        if gap_state == "hr_supervisor_approval":
            # Same as a Dept. Manager approval (HR Supervisor forward-escalation,
            # submitter holding HR roles...).
            self._route_at_hr_supervisor_stage(actor=manager_user, include_submitter=True)
            return
        # gap_state == "hr_manager_approval": same as an HR Supervisor approval.
        if self._finalize_if_submitter_holds_hr_roles(manager_user, now):
            return
        self.sudo().write({"state": gap_state, "approval_state": gap_state})
        self.sudo()._send_hr_manager_email()

    def _route_on_submit(self, submitter=None):
        self.ensure_one()
        submitter = submitter or self.env.user
        now = fields.Datetime.now()
        submitter_is_hr_sup = self._user_is_hr_supervisor(submitter)
        submitter_is_hr_mgr = self._user_is_hr_manager(submitter)
        manager_user = (
            self.employee_id.parent_id.user_id.filtered(lambda u: u.active)
            or self.employee_manager_id.user_id.filtered(lambda u: u.active)
        )
        has_distinct_manager = bool(
            manager_user
            and self._get_user_identity_key(manager_user) != self._get_user_identity_key(submitter)
        )

        # Case 1: Dual HR Supervisor + HR Manager submitter who is also the employee's
        # direct manager (or the employee has no other active direct manager)
        # covers every stage up to HR Manager on submit. The request is approved
        # immediately when the submitter is also MD, else it waits at MD approval.
        if submitter_is_hr_sup and submitter_is_hr_mgr and not has_distinct_manager:
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
            if self._user_is_md(submitter):
                body = _("Auto-approved on submission by HR Supervisor, HR Manager and MD.")
            else:
                body = _(
                    "Submitted and auto-advanced to MD Approval based on submitter access rights "
                    "(HR Supervisor and HR Manager)."
                )
            self._complete_hr_manager_stage(actor=submitter, approval_date=now, chatter_body=body)
            return

        # Case 2: Employee has a distinct active Dept. Manager -> route to manager's
        # highest consecutive role along Dept. Manager -> HR Supervisor -> HR Manager
        # -> MD. This also applies to a dual HR Supervisor + HR Manager submitter
        # who is not the direct manager: the request waits for the direct manager
        # at that stage and the submitter covers the remaining HR roles once the
        # manager approves (see _finalize_if_submitter_holds_hr_roles).
        if has_distinct_manager:
            manager_roles = self._get_user_leave_request_roles(manager_user)
            last_held_idx = 0
            for idx, (_state, stage_role, _label) in enumerate(APPROVAL_STAGE_CHAIN[1:], start=1):
                if stage_role not in manager_roles:
                    break
                last_held_idx = idx
            target_state = APPROVAL_STAGE_CHAIN[last_held_idx][0]
            # Gap in the manager's roles (e.g. Dept. Manager + HR Manager + MD
            # without HR Supervisor): when the manager also holds a role AFTER the
            # first missing one, the request will come back to them anyway, so
            # their consecutive stages are approved on submit and the request goes
            # straight to the first role they are missing.
            gap_idx = last_held_idx + 1
            if any(stage[1] in manager_roles for stage in APPROVAL_STAGE_CHAIN[gap_idx + 1:]):
                self._route_to_manager_role_gap(manager_user, gap_idx, now)
                return
            route_vals = {
                "state": target_state,
                "approval_state": target_state,
            }
            # Stages skipped because the Dept. Manager holds the following
            # role(s) are recorded as approved by that manager.
            stage_states = [stage[0] for stage in STAGE_APPROVAL_FIELDS]
            for _state, user_field, date_field in STAGE_APPROVAL_FIELDS[:stage_states.index(target_state)]:
                route_vals.update({user_field: manager_user.id, date_field: now})
            self.sudo().write(route_vals)
            if target_state == "employee_manager_approval":
                self.sudo()._send_manager_email()
                self.sudo().message_post(body=_("Request submitted for Dept. Manager approval."))
            elif target_state == "hr_supervisor_approval":
                self.sudo()._send_hr_supervisor_email()
                self.sudo().message_post(
                    body=_("Request submitted directly for HR Supervisor approval based on manager access rights.")
                )
            elif target_state == "hr_manager_approval":
                self.sudo()._send_hr_manager_email()
                self.sudo().message_post(
                    body=_("Request submitted directly for HR Manager approval based on manager access rights.")
                )
            elif target_state == "md_approval":
                self.sudo()._send_md_email()
                self.sudo().message_post(
                    body=_("Request submitted directly for MD approval based on manager access rights.")
                )
            return

        # Case 3: No distinct Dept. Manager or submitter IS the Dept. Manager -> clear
        # Dept. Manager stage and continue routing from HR Supervisor stage.
        advance_vals = {}
        if self._user_is_dept_manager(submitter) or (
            manager_user
            and self._get_user_identity_key(manager_user) == self._get_user_identity_key(submitter)
        ):
            advance_vals.update({
                "manager_approved_user_id": submitter.id,
                "manager_approved_date": now,
            })
        if advance_vals:
            self.sudo().write(advance_vals)
        self._route_at_hr_supervisor_stage(actor=submitter, include_submitter=True)

    @api.depends("leave_type_id.leave_type")
    def _compute_is_sick_leave(self):
        for rec in self:
            rec.is_sick_leave = rec.leave_type_id.leave_type == "sick_leave"

    def _check_sick_leave_attachment(self):
        for rec in self:
            if rec.is_sick_leave and not rec.sudo().attachment_ids:
                raise ValidationError(_(
                    "Please attach a supporting document (e.g. medical certificate) for sick leave."
                ))

    def action_submit(self):
        actor = self.env.user
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only Draft leave requests can be submitted."))
            if not rec._user_can_submit(actor):
                raise AccessError(_("You are not allowed to submit this leave request."))

            rec._check_leave_request_weekend_dates()
            rec._check_annual_leave_start_date()
            rec._check_last_working_day()
            if rec._get_requested_days_count() <= 0:
                raise ValidationError(_("The selected period does not contain any working day to request."))
            rec._check_sick_leave_attachment()
            rec._check_requested_days_with_allocation()
            # Surface the errors of the final hr.leave creation now, not after
            # the whole approval chain (overlapping time off, contract rules...).
            rec._check_overlapping_leave_requests()
            rec._check_employee_leave_can_be_created()

            hr_supervisor_ids = self._get_group_users_for_company(HR_SUPERVISOR_GROUP, rec.company_id)
            hr_manager_ids = self._get_group_users_for_company(HR_MANAGER_GROUP, rec.company_id)
            setup_vals = {
                "submitted_by_id": actor.id,
                "employee_manager_id": rec.employee_id.parent_id.id if rec.employee_id.parent_id else False,
                "hr_supervisor_ids": [(6, 0, hr_supervisor_ids.ids)],
                "hr_manager_ids": [(6, 0, hr_manager_ids.ids)],
            }
            rec.sudo().write(setup_vals)
            rec._route_on_submit(submitter=actor)
        return True

    def action_manager_approve(self):
        actor = self.env.user
        for rec in self:
            if rec.state != "employee_manager_approval":
                raise UserError(_("This leave request is not awaiting Dept. Manager approval."))
            if not rec._user_is_dept_manager(actor):
                raise AccessError(_("Only the Dept. Manager can approve this stage."))
            now = fields.Datetime.now()
            rec.sudo().write({
                "manager_approved_user_id": actor.id,
                "manager_approved_date": now,
            })
            rec._route_at_hr_supervisor_stage(actor=actor, include_submitter=True)
        return True

    def action_employee_cancel_request(self):
        actor = self.env.user
        is_hr = self.env.is_superuser() or self._user_is_hr_supervisor(actor) or self._user_is_hr_manager(actor)
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("Only approved leave requests can be submitted for cancellation."))
            if not is_hr and rec.sudo().employee_id.user_id != actor:
                raise UserError(_("Only the employee or HR can request the cancellation of this leave request."))
            rec = rec.sudo()
            rec.write({
                "state": "cancel_request",
                "approval_state": "cancel_request",
            })
            rec._send_hr_manager_cancellation_email()
        return True

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
                'from_approval_dashboard': bool(self.env.context.get('from_approval_dashboard')),
            },
            'views': [(self.env.ref('pr_base.pr_reject_record_wizard_view_form').id, 'form')],
        }

    def action_reject(self):
        actor = self.env.user
        for rec in self:
            if rec.state not in APPROVAL_STATES:
                raise UserError(_("This leave request cannot be rejected in its current state."))
            if rec._user_can_reject_stage("md", actor):
                return rec._open_reject_wizard("md")
            if rec._user_can_reject_stage("hr_manager", actor):
                return rec._open_reject_wizard("hr_manager")
            if rec._user_can_reject_stage("hr_supervisor", actor):
                return rec._open_reject_wizard("hr_supervisor")
            if rec._user_can_reject_stage("manager", actor):
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
            rec._validate_dashboard_intermediate_approvals("hr_supervisor")
            if rec.state not in ("employee_manager_approval", "hr_supervisor_approval"):
                raise UserError(_("This leave request is not awaiting HR Supervisor approval."))
            prior_state = rec.state
            now = fields.Datetime.now()
            is_dept_mgr = rec._user_is_dept_manager(actor)
            vals = {
                "hr_supervisor_approved_user_id": actor.id,
                "hr_supervisor_approved_date": now,
            }
            if prior_state == "employee_manager_approval" and is_dept_mgr:
                vals["manager_approved_user_id"] = actor.id
                vals["manager_approved_date"] = now
            rec.sudo().write(vals)

            if rec._user_is_hr_manager(actor):
                if prior_state == "employee_manager_approval" and is_dept_mgr:
                    body = _("Approved by Dept. Manager, HR Supervisor, and HR Manager.")
                elif prior_state == "employee_manager_approval":
                    body = _("Approved by HR Supervisor and HR Manager via skip-level approval.")
                else:
                    body = _("Approved by HR Supervisor and HR Manager.")
                rec._complete_hr_manager_stage(
                    actor=actor,
                    approval_date=now,
                    chatter_body=body,
                )
                if rec.state == "md_approval":
                    rec._finalize_if_submitter_holds_hr_roles(actor, now)
                continue

            # Submitted by an HR Supervisor + HR Manager: the HR Manager stage is
            # already covered by the submitter.
            if rec._finalize_if_submitter_holds_hr_roles(actor, now):
                continue

            rec.sudo().write({
                "state": "hr_manager_approval",
                "approval_state": "hr_manager_approval",
            })
            if prior_state == "employee_manager_approval" and not is_dept_mgr:
                rec.sudo().message_post(
                    body=_("Approved by HR Supervisor via skip-level approval.")
                )
            elif prior_state == "employee_manager_approval" and is_dept_mgr:
                rec.sudo().message_post(
                    body=_("Approved by Dept. Manager and HR Supervisor.")
                )
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
            rec._validate_dashboard_intermediate_approvals("hr_manager")
            if rec.state not in ("employee_manager_approval", "hr_supervisor_approval", "hr_manager_approval"):
                raise UserError(_("This leave request is not awaiting HR Manager approval."))
            previous_state = rec.state
            now = fields.Datetime.now()
            is_dept_mgr = rec._user_is_dept_manager(actor)
            is_hr_sup = rec._user_is_hr_supervisor(actor)
            extra_vals = {}
            chatter_body = None

            if previous_state == "employee_manager_approval":
                if is_dept_mgr:
                    extra_vals["manager_approved_user_id"] = actor.id
                    extra_vals["manager_approved_date"] = now
                if is_hr_sup:
                    extra_vals["hr_supervisor_approved_user_id"] = actor.id
                    extra_vals["hr_supervisor_approved_date"] = now
                if is_dept_mgr and is_hr_sup:
                    chatter_body = _("Approved by Dept. Manager, HR Supervisor, and HR Manager.")
                else:
                    chatter_body = _("Approved by HR Manager via skip-level approval.")
            elif previous_state == "hr_supervisor_approval":
                if is_hr_sup:
                    extra_vals["hr_supervisor_approved_user_id"] = actor.id
                    extra_vals["hr_supervisor_approved_date"] = now
                    chatter_body = _("Approved by HR Supervisor and HR Manager.")
                else:
                    chatter_body = _("Approved by HR Manager via skip-level approval.")
            else:
                # Stages skipped by routing (e.g. every HR Supervisor is also
                # HR Manager) are recorded under the approver when they hold them.
                rec._record_skipped_stage_approvals(actor, now, previous_state)

            if extra_vals:
                rec.sudo().write(extra_vals)
            rec._complete_hr_manager_stage(
                actor=actor,
                approval_date=now,
                chatter_body=chatter_body,
            )
            if rec.state == "md_approval":
                rec._finalize_if_submitter_holds_hr_roles(actor, now)
        return True

    def action_hr_manager_reject(self):
        actor = self.env.user
        for rec in self:
            if not rec._user_can_reject_stage("hr_manager", actor):
                raise AccessError(_("You are not allowed to reject this leave request at the current stage."))
            return rec._open_reject_wizard("hr_manager")

    def action_md_approve(self):
        """Final approval. From an earlier stage (backend skip-level, or the
        dashboard when the MD holds every intermediate role) the stages whose
        role the MD holds are recorded under the MD."""
        actor = self.env.user
        if not self._user_is_md(actor):
            raise AccessError(_("Only the MD can approve this stage."))
        stage_states = [stage[0] for stage in STAGE_APPROVAL_FIELDS]
        role_by_state = {stage[0]: stage[1] for stage in APPROVAL_STAGE_CHAIN}
        for rec in self:
            rec._validate_dashboard_intermediate_approvals("md")
            if rec.state not in APPROVAL_STATES:
                raise UserError(_("This leave request cannot be approved in its current state."))
            previous_state = rec.state
            now = fields.Datetime.now()
            roles = rec._get_user_leave_request_roles(actor)
            extra_vals = {}
            skipped = False
            for state, user_field, date_field in STAGE_APPROVAL_FIELDS[stage_states.index(previous_state):-1]:
                if role_by_state[state] in roles:
                    extra_vals.update({user_field: actor.id, date_field: now})
                else:
                    skipped = True
            if extra_vals:
                rec.sudo().write(extra_vals)
            if previous_state == "md_approval":
                # Stages skipped by routing (e.g. every HR Supervisor is also
                # HR Manager and MD) are recorded under the MD when they hold them.
                rec._record_skipped_stage_approvals(actor, now, previous_state)
            if skipped:
                chatter_body = _("Approved by MD via skip-level approval.")
            elif previous_state != "md_approval":
                chatter_body = _("Approved by MD, who also holds every pending earlier approval role.")
            else:
                chatter_body = None
            rec._finalize_approval(actor=actor, approval_date=now, chatter_body=chatter_body)
        return True

    def action_md_reject(self):
        actor = self.env.user
        for rec in self:
            if not rec._user_can_reject_stage("md", actor):
                raise AccessError(_("You are not allowed to reject this leave request at the current stage."))
            return rec._open_reject_wizard("md")

    def _get_employee_leave_env(self, allocation_override=False):
        leave_context = {
            "tracking_disable": True,
            "mail_activity_automation_skip": True,
            "leave_fast_create": True,
            "leave_skip_state_check": True,
            "pr_leave_request_allocation_checked": True,
        }
        if allocation_override:
            leave_context["pr_leave_allocation_override"] = True
        return self.env["hr.leave"].with_context(**leave_context).sudo()

    def _prepare_employee_leave_vals(self):
        self.ensure_one()
        return {
            'name': f"{self.employee_id.name} Leave From {self.date_from} To {self.date_to}",
            "employee_id": self.employee_id.id,
            "holiday_status_id": self.leave_type_id.id,
            "request_date_from": self.date_from,
            "request_date_to": self.date_to,
            "leave_request_id": self.id,
            "allocation_override_applied": bool(self.allocation_override_applied),
            "allocation_override_note": self.allocation_override_note or False,
            "state": "confirm",
        }

    def _check_overlapping_leave_requests(self):
        """Overlap with other requests still in the approval pipeline (they have
        no hr.leave yet, so the hr.leave dry run cannot see them)."""
        for rec in self:
            if not (rec.employee_id and rec.date_from and rec.date_to):
                continue
            overlapping = self.sudo().with_context(approvals_of_leave_request=False, params=None).search([
                ("id", "!=", rec.id),
                ("employee_id", "=", rec.employee_id.id),
                ("state", "in", APPROVAL_STATES),
                ("date_from", "<=", rec.date_to),
                ("date_to", ">=", rec.date_from),
            ])
            if overlapping:
                states = dict(self._fields["state"]._description_selection(self.env))
                raise ValidationError(_(
                    "%(employee)s already has a leave request awaiting approval which overlaps with this period:\n%(requests)s"
                ) % {
                    "employee": rec.employee_id.name,
                    "requests": "\n".join(
                        "- %s: %s → %s (%s)" % (req.name, req.date_from, req.date_to, states.get(req.state))
                        for req in overlapping
                    ),
                })

    def _check_employee_leave_can_be_created(self):
        """Dry run of the hr.leave created at final approval: create it inside a
        savepoint (so every hr.leave constraint runs, e.g. overlapping time off,
        contract / working schedule rules) and roll it back. Errors surface on
        submit instead of after the whole approval chain."""
        Leave = self._get_employee_leave_env()
        for rec in self:
            try:
                with self.env.cr.savepoint():
                    Leave.create(rec._prepare_employee_leave_vals())
                    self.env.flush_all()
                    raise _LeaveDryRunDone()
            except _LeaveDryRunDone:
                pass
            finally:
                # drop anything the rolled-back hr.leave left in the ORM cache
                self.env.invalidate_all()

    def _create_employee_leave(self, allocation_override=False):
        """Create the hr.leave of each approved request and validate it through
        the standard hr.leave flow (action_validate), so resource.calendar.leaves,
        work-entry conflict handling and the attendance cleanup hook all run."""
        Leave = self._get_employee_leave_env(allocation_override=allocation_override)

        leaves = Leave
        for rec in self:
            leave = Leave.create(rec._prepare_employee_leave_vals())
            leave.action_validate()
            rec.sudo().write({"leave_id": leave.id})
            leaves |= leave
        return leaves

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
            if rec.state == "rejected":
                rec.sudo().approval_state = "rejected"
                rec._send_result_to_employee(result="Rejected")

    # endregion [Constrains]

    # region [Crud]

    @api.model
    def _can_write_workflow_fields(self):
        """Workflow fields are only written by the model's own action methods
        (through sudo) or by HR; a context flag is not accepted on purpose, as
        RPC callers control the context."""
        user = self.env.user
        return bool(
            self.env.is_superuser()
            or user._is_admin()
            or self._user_is_hr_supervisor(user)
            or self._user_is_hr_manager(user)
            or self._user_is_md(user)
        )

    @api.model
    def _check_workflow_fields_create_vals(self, vals):
        if self._can_write_workflow_fields():
            return
        forbidden = {
            fname for fname in WORKFLOW_PROTECTED_FIELDS.intersection(vals)
            if vals[fname] and not (fname in ("state", "approval_state") and vals[fname] == "draft")
        }
        if forbidden:
            raise AccessError(_("You are not allowed to set the approval workflow fields of a leave request."))

    def _check_workflow_fields_write_vals(self, vals):
        if WORKFLOW_PROTECTED_FIELDS.intersection(vals) and not self._can_write_workflow_fields():
            raise AccessError(_(
                "The approval workflow of a leave request can only be changed through its action buttons."
            ))

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
        We Inherit Create Method To Pass Sequence For Field Name
        '''
        enforce_self_only = not self.env.su and not self._user_can_select_any_employee()
        for vals in vals_list:
            self._check_workflow_fields_create_vals(vals)
            if enforce_self_only:
                emp_id = vals.get("employee_id") or self._default_employee_id()
                employee = self.env["hr.employee"].sudo().browse(emp_id) if emp_id else self.env["hr.employee"]
                if not employee or employee.user_id != self.env.user:
                    raise AccessError(_("You can only create leave requests for yourself."))
                vals["employee_id"] = employee.id
                if employee.company_id:
                    vals["company_id"] = employee.company_id.id
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
        return records

    def write(self, vals):
        self._check_workflow_fields_write_vals(vals)
        if "employee_id" in vals and not self.env.su and not self._user_can_select_any_employee():
            employee = self.env["hr.employee"].sudo().browse(vals["employee_id"])
            if not employee or employee.user_id != self.env.user:
                raise AccessError(_("You can only request leave for yourself."))
        res = super().write(vals)
        date_employee_fields = {"employee_id", "leave_type_id", "date_from", "date_to"}
        if date_employee_fields.intersection(vals.keys()):
            self._check_leave_request_weekend_dates()
            self._check_requested_days_with_allocation()
        elif "state" in vals:
            target_state = vals.get("state")
            if target_state not in ("cancel_request", "cancelled", "rejected", "approved"):
                self._check_requested_days_with_allocation()
        return res

    def unlink(self):
        enforce_self_only = not self.env.su and not self._user_can_select_any_employee()
        for rec in self:
            if rec.state != 'draft':
                raise ValidationError(_("Only Draft leave requests can be deleted."))
            if enforce_self_only and rec.employee_id.user_id != self.env.user and rec.create_uid != self.env.user:
                raise AccessError(_("You can only delete your own Draft leave requests."))
        return super().unlink()

    # endregion [Crud]
