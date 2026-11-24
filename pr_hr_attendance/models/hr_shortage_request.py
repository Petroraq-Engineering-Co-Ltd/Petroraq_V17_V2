from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.osv import expression

HR_SUPERVISOR_GROUP = "pr_hr.group_hr_supervisor"
HR_MANAGER_GROUP = "pr_hr.group_hr_manager"
MD_GROUP = "pr_hr.group_hr_md"
APPROVAL_STATES = (
    "employee_manager_approval",
    "hr_supervisor_approval",
    "hr_manager_approval",
    "md_approval",
)
# Only written through the action methods (sudo).
WORKFLOW_PROTECTED_FIELDS = frozenset({
    "state",
    "approval_state",
    "submitted_by_id",
    "employee_manager_id",
    "hr_supervisor_ids",
    "hr_manager_ids",
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
})
# Only editable while the request is in draft.
CORRECTION_FIELDS = frozenset({
    "request_type", "date", "check_in", "check_out",
    "employee_id", "company_id", "employee_reason",
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


class _ShortageDryRunDone(Exception):
    """Raised to roll back the savepoint of a successful attendance dry run."""


class HrShortageRequest(models.Model):
    """Attendance correction request. The approval workflow mirrors
    pr.hr.leave.request (pr_hr_holidays): keep both in step."""
    # region [Initial]
    _name = 'pr.hr.shortage.request'
    _description = 'Hr Shortage Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = "id"
    # endregion [Initial]

    # region [Fields]

    name = fields.Char(string="Name", copy=False)
    request_type = fields.Selection([
        ('shortage', 'Attendance Shortage'),
        ('no_punch', 'No Punch Record'),
    ], string="Request Type", required=True, default='shortage', tracking=True)
    date = fields.Date(string="Date", required=True)
    check_in = fields.Datetime(string="Check In", required=False)
    check_out = fields.Datetime(string="Check Out", required=False)
    company_id = fields.Many2one(
        'res.company', string='Company', tracking=True, required=True,
        default=lambda self: self.env.user.employee_id.company_id or self.env.company,
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', tracking=True, required=True,
        default=lambda self: self.env.user.employee_id,
    )
    employee_manager_id = fields.Many2one(
        'hr.employee', string='Manager', tracking=True, readonly=True, copy=False)
    hr_supervisor_ids = fields.Many2many('res.users', 'shortage_request_hr_supervisor_users', 'hr_supervisor_id',
                                         'shortage_request_id', string='HR Supervisors', tracking=True,
                                         readonly=True, copy=False)
    hr_manager_ids = fields.Many2many('res.users', 'shortage_request_hr_manager_users', 'hr_manager_id',
                                      'shortage_request_id', string='HR Managers', tracking=True,
                                      readonly=True, copy=False)
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
    employee_reason = fields.Text(string="Reason")
    reject_reason = fields.Text(string="Rejection Reason", readonly=True, tracking=True, copy=False)
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
    shortage_time = fields.Text(string="Shortage Time", readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('employee_manager_approval', 'Dept. Manager'),
        ('hr_supervisor_approval', 'HR Supervisor'),
        ('hr_manager_approval', 'HR Manager'),
        ('md_approval', 'MD'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
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
    ], default='draft', tracking=True, copy=False,
        string='Approval Status')
    can_select_employee = fields.Boolean(compute="_compute_can_select_employee")
    can_submit = fields.Boolean(compute="_compute_approval_button_visibility")
    can_manager_approve = fields.Boolean(compute="_compute_approval_button_visibility")
    can_hr_supervisor_approve = fields.Boolean(compute="_compute_approval_button_visibility")
    can_hr_manager_approve = fields.Boolean(compute="_compute_approval_button_visibility")
    can_md_approve = fields.Boolean(compute="_compute_approval_button_visibility")
    can_reject = fields.Boolean(compute="_compute_approval_button_visibility")
    payroll_finalized = fields.Boolean(compute="_compute_payroll_finalized")

    # endregion [Fields]

    # region [Constrains]

    @api.constrains("request_type", "date", "check_in", "check_out")
    def _check_no_punch_times(self):
        for rec in self.sudo().filtered(lambda item: item.request_type == "no_punch"):
            if not rec.check_in or not rec.check_out:
                raise ValidationError(
                    _("Actual Check In and Actual Check Out are required for a No Punch Record request.")
                )
            if rec.check_out <= rec.check_in:
                raise ValidationError(_("Actual Check Out must be later than Actual Check In."))
            employee_tz = pytz.timezone(rec.employee_id.tz or self.env.user.tz or "UTC")
            local_check_in = pytz.UTC.localize(rec.check_in).astimezone(employee_tz)
            local_check_out = pytz.UTC.localize(rec.check_out).astimezone(employee_tz)
            if local_check_in.date() != rec.date or local_check_out.date() != rec.date:
                raise ValidationError(
                    _("Actual attendance times must belong to the selected attendance date.")
                )
            local_day_start = employee_tz.localize(datetime.combine(rec.date, time.min))
            local_day_end = local_day_start + timedelta(days=1)
            day_start = local_day_start.astimezone(pytz.UTC).replace(tzinfo=None)
            day_end = local_day_end.astimezone(pytz.UTC).replace(tzinfo=None)
            attendance_exists = self.env["hr.attendance"].sudo().search_count([
                ("employee_id", "=", rec.employee_id.id),
                ("check_in", "<", fields.Datetime.to_string(day_end)),
                "|",
                ("check_out", "=", False),
                ("check_out", ">", fields.Datetime.to_string(day_start)),
            ])
            if attendance_exists:
                raise ValidationError(
                    _("A No Punch Record request is only allowed when no attendance exists for that date.")
                )
            duplicate_request = self.sudo().search_count([
                ("id", "!=", rec.id),
                ("employee_id", "=", rec.employee_id.id),
                ("date", "=", rec.date),
                ("request_type", "=", "no_punch"),
                ("state", "!=", "rejected"),
            ])
            if duplicate_request:
                raise ValidationError(
                    _("A No Punch Record request already exists for this employee and date.")
                )

    @api.constrains("state")
    def _check_reject_state(self):
        for rec in self:
            if rec.state == "rejected":
                rec.sudo().approval_state = "rejected"
                rec._send_result_to_employee(result="Rejected")

    def _check_duplicate_pending_request(self):
        """Only one request per employee and date may await approval."""
        for rec in self.sudo():
            # search_count: search() is filtered by the approvals queue context.
            if self.sudo().search_count([
                ("id", "!=", rec.id),
                ("employee_id", "=", rec.employee_id.id),
                ("date", "=", rec.date),
                ("state", "in", APPROVAL_STATES),
            ]):
                raise ValidationError(_(
                    "%(employee)s already has a shortage request awaiting approval for %(date)s.",
                    employee=rec.employee_id.name, date=rec.date,
                ))

    def _check_shortage_can_be_applied(self):
        """Dry run of the attendance update done at final approval, inside a
        savepoint that is rolled back. Errors surface on submit instead of
        after the whole approval chain."""
        for rec in self:
            rec._check_no_punch_times()
            try:
                with self.env.cr.savepoint():
                    rec.sudo()._apply_shortage_in_attendance()
                    self.env.flush_all()
                    raise _ShortageDryRunDone()
            except _ShortageDryRunDone:
                pass
            finally:
                # drop anything the rolled-back attendance left in the ORM cache
                self.env.invalidate_all()

    # endregion [Constrains]

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
        # sudo: hr.employee hierarchy is not readable by every approver
        rec = self.sudo()
        return bool(
            (rec.employee_id.parent_id.user_id and rec.employee_id.parent_id.user_id == user)
            or (rec.employee_manager_id.user_id and rec.employee_manager_id.user_id == user)
        )

    def _get_user_shortage_request_roles(self, user=None):
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
        roles = self._get_user_shortage_request_roles(user)
        highest = False
        for _state, role, _label in APPROVAL_STAGE_CHAIN[state_keys.index(from_state):]:
            if role not in roles:
                break
            highest = role
        return highest

    @api.model
    def _user_can_select_any_employee(self, user=None):
        user = user or self.env.user
        return bool(
            user
            and (
                user._is_admin()
                or user.has_group(HR_SUPERVISOR_GROUP)
                or user.has_group(HR_MANAGER_GROUP)
                or user.has_group("hr_attendance.group_hr_attendance_officer")
            )
        )

    def _user_can_submit(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        if not user:
            return False
        rec = self.sudo()
        return bool(
            user._is_admin()
            or (rec.employee_id.user_id and rec.employee_id.user_id == user)
            or (rec.create_uid and rec.create_uid == user)
            or self._user_is_dept_manager(user)
            or self._user_is_hr_supervisor(user)
            or self._user_is_hr_manager(user)
        )

    def _user_can_reset_to_draft(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        if not user:
            return False
        rec = self.sudo()
        return bool(
            user._is_admin()
            or (rec.employee_id.user_id and rec.employee_id.user_id == user)
            or (rec.create_uid and rec.create_uid == user)
            or (rec.submitted_by_id and rec.submitted_by_id == user)
            or self._user_is_hr_supervisor(user)
            or self._user_is_hr_manager(user)
            or self._user_is_md(user)
        )

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

        user_roles = self._get_user_shortage_request_roles(user)
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

    def _check_approval_permission(self, role, user=None):
        self.ensure_one()
        user = user or self.env.user
        return role in self._get_user_shortage_request_roles(user)

    def _get_forward_escalated_stage(self, default_next_role):
        """Inspect the user(s) holding default_next_role and determine if the record
        can escalate further along the chain to their highest continuous access rights
        without skipping any unheld intermediate rights."""
        self.ensure_one()
        chain = (
            ("hr_supervisor", "hr_supervisor_approval"),
            ("hr_manager", "hr_manager_approval"),
            ("md", "md_approval"),
        )
        role_keys = [stage[0] for stage in chain]
        if default_next_role not in role_keys:
            role_to_state = dict(chain)
            return default_next_role, role_to_state.get(default_next_role, default_next_role)

        start_idx = role_keys.index(default_next_role)
        sub_chain = chain[start_idx:]

        # 1. If current user holds default_next_role, evaluate current user's continuous authority
        if self._check_approval_permission(default_next_role):
            u_roles = self._get_user_shortage_request_roles(self.env.user)
            curr_role, curr_state = sub_chain[0]
            for r, s in sub_chain:
                if r in u_roles:
                    curr_role, curr_state = r, s
                else:
                    break
            return curr_role, curr_state

        # 2. Otherwise, inspect active company users holding default_next_role
        role_to_xmlid = {
            "hr_supervisor": HR_SUPERVISOR_GROUP,
            "hr_manager": HR_MANAGER_GROUP,
            "md": MD_GROUP,
        }
        xmlid = role_to_xmlid.get(default_next_role)
        group_users = self._get_group_users_for_company(xmlid, self.company_id) if xmlid else self.env["res.users"]
        if not group_users:
            return sub_chain[0]

        if default_next_role == "hr_supervisor":
            all_hr_manager = all(self._check_approval_permission("hr_manager", u) for u in group_users)
            all_md = all(self._check_approval_permission("md", u) for u in group_users)
            if all_hr_manager and all_md:
                return "md", "md_approval"
            if all_hr_manager or all_md:
                return "hr_manager", "hr_manager_approval"
            return sub_chain[0]
        elif default_next_role == "hr_manager":
            all_md = all(self._check_approval_permission("md", u) for u in group_users)
            if all_md:
                return "md", "md_approval"
            return sub_chain[0]

        return sub_chain[0]

    def _get_hr_supervisor_forward_state(self):
        self.ensure_one()
        _role, state = self._get_forward_escalated_stage("hr_supervisor")
        return state if state != "hr_supervisor_approval" else False

    def _enter_hr_manager_stage(self, extra_vals=None, chatter_body=None):
        """Move the request to HR Manager approval, or straight on to MD
        approval when every HR Manager also holds MD."""
        self.ensure_one()
        vals = dict(extra_vals or {})
        _next_role, target_state = self._get_forward_escalated_stage("hr_manager")
        forward_to_md = (target_state == "md_approval")
        vals.update({"state": target_state, "approval_state": target_state})
        self.sudo().write(vals)
        if chatter_body:
            self.sudo().message_post(body=chatter_body)
        if forward_to_md:
            self.sudo().message_post(body=_(
                "Routed directly to MD Approval, as every HR Manager also holds MD rights."
            ))
            self.sudo()._send_md_email()
        else:
            self.sudo()._send_hr_manager_email()

    def _record_skipped_stage_approvals(self, actor, approval_date, before_state):
        """Record `actor` on every earlier stage that was skipped (no approver
        recorded) and whose role `actor` holds. Stages the actor does not hold
        stay empty."""
        self.ensure_one()
        stage_states = [stage[0] for stage in STAGE_APPROVAL_FIELDS]
        role_by_state = {stage[0]: stage[1] for stage in APPROVAL_STAGE_CHAIN}
        roles = self._get_user_shortage_request_roles(actor)
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
            role_domains.append([("state", "=", "hr_manager_approval")])
        if self._user_is_md(user):
            role_domains.append([("state", "=", "md_approval")])
        return expression.OR(role_domains) if len(role_domains) > 1 else role_domains[0]

    # endregion [Role Helpers]

    # region [Compute Methods]

    @api.depends_context("uid")
    def _compute_can_select_employee(self):
        self.can_select_employee = self._user_can_select_any_employee()

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

            rec.can_manager_approve = selected_role == "employee_manager"
            rec.can_hr_supervisor_approve = selected_role == "hr_supervisor"
            rec.can_hr_manager_approve = selected_role == "hr_manager"
            rec.can_md_approve = selected_role == "md"
            rec.can_reject = bool(selected_role)

    @api.depends("state", "rejected_stage", "rejected_by_user_id", "employee_id.parent_id.user_id",
                 "employee_manager_id.user_id")
    @api.depends_context("uid")
    def _compute_can_reset_rejection(self):
        user = self.env.user
        for rec in self:
            rec.can_reset_rejection = (
                rec.state == 'rejected'
                and rec._user_can_decide_rejected_stage(user)
            )

    @api.depends('state', 'employee_id.user_id', 'create_uid', 'submitted_by_id')
    @api.depends_context('uid')
    def _compute_can_reset_to_draft(self):
        user = self.env.user
        for rec in self:
            rec.can_reset_to_draft = (
                bool(rec.id)
                and rec.state == 'rejected'
                and rec._user_can_reset_to_draft(user)
            )

    @api.depends("employee_id", "date", "state")
    def _compute_payroll_finalized(self):
        """Pending request on a day whose attendance sheet is already final: its
        approval will not recalculate that sheet or payslip."""
        Sheet = self.env["attendance.sheet"].sudo()
        for rec in self:
            rec.payroll_finalized = bool(
                rec.employee_id
                and rec.date
                and rec.state in ("draft", *APPROVAL_STATES)
                and Sheet.search_count([
                    ("employee_id", "=", rec.employee_id._origin.id),
                    ("state", "=", "done"),
                    ("date_from", "<=", rec.date),
                    ("date_to", ">=", rec.date),
                ], limit=1)
            )

    # endregion [Compute Methods]

    # region [Onchange Methods]

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        self.ensure_one()
        if self.employee_id.company_id:
            self.company_id = self.employee_id.company_id.id

    @api.onchange("employee_id", "date")
    def _onchange_employee_id_date_attendance(self):
        self.ensure_one()
        if not self.employee_id or not self.date:
            return
        day_start = datetime.combine(self.date, time.min)
        day_end = day_start + timedelta(days=1)
        attendance_id = self.env["hr.attendance"].sudo().search([
            ("employee_id", "=", self.employee_id.id),
            ("check_in", ">=", day_start),
            ("check_in", "<", day_end),
        ], limit=1)
        if attendance_id:
            self.check_in = attendance_id.check_in
            self.check_out = attendance_id.check_out
            self.shortage_time = attendance_id.shortage_time or False

    # endregion [Onchange Methods]

    # region [Emails]

    def _prepare_email_vals(self, body_message, receiver):
        self.ensure_one()
        return {
            "email_from": "noreply@petroraq.com",
            "subject": f"{self.employee_id.code} - Shortage Request For {self.date}",
            "body_html": body_message,
            "email_to": receiver,
        }

    def _send_manager_email(self):
        for rec in self:
            manager = rec.employee_id.parent_id or rec.employee_manager_id
            receiver = manager.work_email if manager else False
            if not receiver:
                continue
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            record_url = base_url + "/web#id=" + str(
                rec.id) + "&view_type=form&model=pr.hr.shortage.request&view_type=form"

            body_message = f"""Dear Mr/Mrs. {manager.name},<br/><br/>

                We wish to inform you that your employee {rec.employee_id.name} has been asked for <strong>Shortage Request For {rec.date}</strong>.<br/><br/>
                You can check the request to take a decision by clicking this button <a class="btn btn-primary" href="{record_url}" role="button">Shortage Request</a><br/><br/><br/>
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
        self._send_approver_group_email(HR_SUPERVISOR_GROUP)

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
                rec.id) + "&view_type=form&model=pr.hr.shortage.request&view_type=form"

            user_ids = rec._get_group_users_for_company(group_xmlid, rec.company_id)
            if user_ids:
                for user in user_ids:
                    employee_id = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
                    if employee_id and employee_id.work_email:
                        body_message = f"""Dear Mr/Mrs. {employee_id.name},<br/><br/>

                            We wish to inform you that your employee {rec.employee_id.name} has been asked for <strong>Shortage Request For {rec.date}</strong>.<br/><br/>
                            You can check the request to take a decision by clicking this button <a class="btn btn-primary" href="{record_url}" role="button">Shortage Request</a><br/><br/><br/>
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
        for rec in self.sudo():
            receiver = rec.employee_id.work_email
            if not receiver:
                continue
            body_message = f"""Dear Mr/Mrs. {rec.employee_id.name},<br/><br/>

                We wish to inform you that your Shortage Request {rec.name} has been <strong>{result}</strong>.<br/><br/>
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

    # region [Routing]

    def _get_user_identity_key(self, user):
        employee = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
        if employee:
            return ("emp", employee.id)
        return ("user", user.id)

    def _finalize_approval(self, actor, approval_date, chatter_body=None):
        """Final (MD) approval: record the MD approver, approve the request and
        apply it to the attendance."""
        self.ensure_one()
        actor = actor or self.env.user
        rec = self.sudo()
        rec._check_no_punch_times()
        rec.write({
            "state": "approved",
            "approval_state": "approved",
            "md_approved_user_id": actor.id,
            "md_approved_date": approval_date,
        })
        rec._apply_shortage_in_attendance()
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
            if submitter and actor == submitter:
                body = _("Submitted and auto-advanced to HR Manager Approval based on submitter access rights.")
            else:
                body = _("Auto-advanced to HR Manager Approval based on approver access rights.")
            self._enter_hr_manager_stage(
                extra_vals={
                    "hr_supervisor_approved_user_id": actor.id,
                    "hr_supervisor_approved_date": now,
                },
                chatter_body=body,
            )
            return

        if include_submitter and submitter and submitter != actor:
            if self._user_is_hr_supervisor(submitter) and not self._user_is_hr_manager(submitter):
                self._enter_hr_manager_stage(
                    extra_vals={
                        "hr_supervisor_approved_user_id": submitter.id,
                        "hr_supervisor_approved_date": now,
                    },
                    chatter_body=_("Auto-advanced to HR Manager Approval based on submitter access rights."),
                )
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
            self._enter_hr_manager_stage(
                chatter_body=_("Routed directly to HR Manager Approval based on HR Supervisor approver access rights."),
            )
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
        self._enter_hr_manager_stage()

    def _route_on_submit(self, submitter=None):
        self.ensure_one()
        submitter = submitter or self.env.user
        now = fields.Datetime.now()
        submitter_is_hr_sup = self._user_is_hr_supervisor(submitter)
        submitter_is_hr_mgr = self._user_is_hr_manager(submitter)
        rec = self.sudo()
        manager_user = (
            rec.employee_id.parent_id.user_id.filtered(lambda u: u.active)
            or rec.employee_manager_id.user_id.filtered(lambda u: u.active)
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
            manager_roles = self._get_user_shortage_request_roles(manager_user)
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

    # endregion [Routing]

    # region [Actions]

    def action_submit(self):
        actor = self.env.user
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only Draft shortage requests can be submitted."))
            if not rec._user_can_submit(actor):
                raise AccessError(_("You are not allowed to submit this shortage request."))

            rec._check_duplicate_pending_request()
            # Surface the errors of the final attendance update now, not after
            # the whole approval chain.
            rec._check_shortage_can_be_applied()

            rec.sudo().write(rec._prepare_approver_vals(actor))
            rec._route_on_submit(submitter=actor)
        return True

    def _prepare_approver_vals(self, submitter=None):
        self.ensure_one()
        rec = self.sudo()
        vals = {
            "employee_manager_id": rec.employee_id.parent_id.id,
            "hr_supervisor_ids": [(6, 0, self._get_group_users_for_company(
                HR_SUPERVISOR_GROUP, rec.company_id).ids)],
            "hr_manager_ids": [(6, 0, self._get_group_users_for_company(
                HR_MANAGER_GROUP, rec.company_id).ids)],
        }
        if submitter:
            vals["submitted_by_id"] = submitter.id
        return vals

    def action_manager_approve(self):
        actor = self.env.user
        for rec in self:
            if rec.state != "employee_manager_approval":
                raise UserError(_("This shortage request is not awaiting Dept. Manager approval."))
            if not rec._user_is_dept_manager(actor):
                raise AccessError(_("Only the Dept. Manager can approve this stage."))
            rec._check_no_punch_times()
            now = fields.Datetime.now()
            rec.sudo().write({
                "manager_approved_user_id": actor.id,
                "manager_approved_date": now,
            })
            rec._route_at_hr_supervisor_stage(actor=actor, include_submitter=True)
        return True

    def action_hr_supervisor_approve(self):
        actor = self.env.user
        if not self._user_is_hr_supervisor(actor):
            raise AccessError(_("Only an HR Supervisor can approve this stage."))
        for rec in self:
            rec._validate_dashboard_intermediate_approvals("hr_supervisor")
            if rec.state not in ("employee_manager_approval", "hr_supervisor_approval"):
                raise UserError(_("This shortage request is not awaiting HR Supervisor approval."))
            prior_state = rec.state
            rec._check_no_punch_times()
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

            body = None
            if prior_state == "employee_manager_approval" and not is_dept_mgr:
                body = _("Approved by HR Supervisor via skip-level approval.")
            elif prior_state == "employee_manager_approval" and is_dept_mgr:
                body = _("Approved by Dept. Manager and HR Supervisor.")
            rec._enter_hr_manager_stage(chatter_body=body)
        return True

    def action_hr_manager_approve(self):
        actor = self.env.user
        if not self._user_is_hr_manager(actor):
            raise AccessError(_("Only an HR Manager can approve this stage."))
        for rec in self:
            rec._validate_dashboard_intermediate_approvals("hr_manager")
            if rec.state not in ("employee_manager_approval", "hr_supervisor_approval", "hr_manager_approval"):
                raise UserError(_("This shortage request is not awaiting HR Manager approval."))
            previous_state = rec.state
            rec._check_no_punch_times()
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
                raise UserError(_("This shortage request cannot be approved in its current state."))
            previous_state = rec.state
            rec._check_no_punch_times()
            now = fields.Datetime.now()
            roles = rec._get_user_shortage_request_roles(actor)
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
                'pr_shortage_rejection_stage': stage,
                'from_approval_dashboard': bool(self.env.context.get('from_approval_dashboard')),
            },
            'views': [(self.env.ref('pr_base.pr_reject_record_wizard_view_form').id, 'form')],
        }

    def action_reject(self):
        actor = self.env.user
        for rec in self:
            if rec.state not in APPROVAL_STATES:
                raise UserError(_("This shortage request cannot be rejected in its current state."))
            if rec._user_can_reject_stage("md", actor):
                return rec._open_reject_wizard("md")
            if rec._user_can_reject_stage("hr_manager", actor):
                return rec._open_reject_wizard("hr_manager")
            if rec._user_can_reject_stage("hr_supervisor", actor):
                return rec._open_reject_wizard("hr_supervisor")
            if rec._user_can_reject_stage("manager", actor):
                return rec._open_reject_wizard("manager")
            raise AccessError(_("You are not allowed to reject this shortage request at the current stage."))

    def action_manager_reject(self):
        actor = self.env.user
        for rec in self:
            if not rec._user_can_reject_stage("manager", actor):
                raise AccessError(_("You are not allowed to reject this shortage request at the current stage."))
            return rec._open_reject_wizard("manager")

    def action_hr_supervisor_reject(self):
        actor = self.env.user
        for rec in self:
            if not rec._user_can_reject_stage("hr_supervisor", actor):
                raise AccessError(_("You are not allowed to reject this shortage request at the current stage."))
            return rec._open_reject_wizard("hr_supervisor")

    def action_hr_manager_reject(self):
        actor = self.env.user
        for rec in self:
            if not rec._user_can_reject_stage("hr_manager", actor):
                raise AccessError(_("You are not allowed to reject this shortage request at the current stage."))
            return rec._open_reject_wizard("hr_manager")

    def action_md_reject(self):
        actor = self.env.user
        for rec in self:
            if not rec._user_can_reject_stage("md", actor):
                raise AccessError(_("You are not allowed to reject this shortage request at the current stage."))
            return rec._open_reject_wizard("md")

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
            raise UserError(_("Please provide a reason for rejecting this shortage request."))
        for rec in self:
            if rec.state not in APPROVAL_STATES:
                raise UserError(_('This shortage request cannot be rejected in its current state.'))
            if not rec._user_can_reject_stage(stage, actor):
                raise AccessError(_('You are not allowed to reject this shortage request at the current stage.'))
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

            rec._check_duplicate_pending_request()
            rejected_stage = rec.rejected_stage
            target_state = rec.rejected_from_state or stage_to_state[rejected_stage]
            reset_vals = {
                'state': target_state,
                'approval_state': target_state,
                'reject_reason': False,
                'rejected_stage': False,
                'rejected_from_state': False,
                'rejected_by_user_id': False,
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
            if rec.state != 'rejected':
                raise UserError(_('Only rejected shortage requests can be reset to draft.'))
            if not rec._user_can_reset_to_draft(actor):
                raise AccessError(_('You are not allowed to reset this shortage request to draft.'))
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
            })
            rec.sudo().message_post(
                body=_('%(user)s reset this shortage request to Draft.') % {'user': actor.display_name}
            )
        return True

    def _apply_shortage_in_attendance(self):
        for rec in self:
            Attendance = self.env["hr.attendance"].sudo()
            day_start, day_end, _timezone = Attendance._get_auto_attendance_day_bounds(
                rec.employee_id, rec.date
            )
            attendance_id = self.env["hr.attendance"].sudo().search([
                ("employee_id", "=", rec.employee_id.id),
                ("check_in", ">=", fields.Datetime.to_string(day_start)),
                ("check_in", "<", fields.Datetime.to_string(day_end)),
            ], limit=1)

            if rec.request_type == "no_punch":
                check_in_dt = rec.check_in
                check_out_dt = rec.check_out
            else:
                scheduled_check_in, scheduled_check_out = Attendance._get_auto_attendance_datetimes(
                    rec.employee_id, rec.date
                )
                check_in_dt = rec.check_in or scheduled_check_in
                check_out_dt = rec.check_out or scheduled_check_out

            if attendance_id:
                attendance_id.sudo().with_context(
                    allow_late_attendance=True,
                    attendance_policy_source="approved_shortage",
                ).write({
                    "check_in": check_in_dt,
                    "check_out": check_out_dt,
                })
            else:
                self.env["hr.attendance"].sudo().with_context(
                    allow_late_attendance=True,
                    attendance_policy_source="approved_shortage",
                ).create({
                    "employee_id": rec.employee_id.id,
                    "check_in": check_in_dt,
                    "check_out": check_out_dt,
                })

    # endregion [Actions]

    # region [Crud]

    @api.model_create_multi
    def create(self, vals_list):
        enforce_self_only = not self.env.su and not self._user_can_select_any_employee()
        for vals in vals_list:
            if not self.env.su:
                forbidden = [
                    fname for fname in WORKFLOW_PROTECTED_FIELDS.intersection(vals)
                    if vals[fname] and not (fname in ("state", "approval_state") and vals[fname] == "draft")
                ]
                if forbidden:
                    raise AccessError(_("You are not allowed to set the approval workflow fields of a shortage request."))
            employee = self.env["hr.employee"].sudo().browse(
                vals.get("employee_id") or self.env.user.employee_id.id
            ).exists()
            if enforce_self_only:
                if not employee or employee.user_id != self.env.user:
                    raise AccessError(_("You can only create shortage requests for yourself."))
                vals["employee_id"] = employee.id
                if employee.company_id:
                    vals["company_id"] = employee.company_id.id
            if employee and not vals.get("company_id"):
                vals["company_id"] = employee.company_id.id or self.env.company.id
            if not vals.get("name"):
                vals["name"] = self.env['ir.sequence'].next_by_code('hr.attendance.shortage.request.seq.code') or ''
        records = super().create(vals_list)
        for rec in records:
            rec.sudo().write(rec._prepare_approver_vals())
        return records

    def write(self, vals):
        if not self.env.su:
            if WORKFLOW_PROTECTED_FIELDS.intersection(vals):
                raise AccessError(_(
                    "The approval workflow of a shortage request can only be changed through its action buttons."
                ))
            if CORRECTION_FIELDS.intersection(vals) and any(rec.state != "draft" for rec in self):
                raise ValidationError(_("Only Draft shortage requests can be edited."))
            if "employee_id" in vals and not self._user_can_select_any_employee():
                employee = self.env["hr.employee"].sudo().browse(vals["employee_id"])
                if not employee or employee.user_id != self.env.user:
                    raise AccessError(_("You can only create shortage requests for yourself."))
        return super().write(vals)

    def unlink(self):
        enforce_self_only = not self.env.su and not self._user_can_select_any_employee()
        for rec in self.sudo():
            if rec.state != 'draft':
                raise ValidationError(_("Only Draft shortage requests can be deleted."))
            if enforce_self_only and rec.employee_id.user_id != self.env.user and rec.create_uid != self.env.user:
                raise AccessError(_("You can only delete your own Draft shortage requests."))
        return super().unlink()

    # endregion [Crud]
