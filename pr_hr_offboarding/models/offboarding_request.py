from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.osv import expression


HR_SUPERVISOR_GROUP = "pr_hr_recruitment_request.group_onboarding_supervisor"
HR_MANAGER_GROUP = "hr.group_hr_manager"
MD_GROUP = "pr_hr_recruitment_request.group_onboarding_md"
WORKFLOW_CONTROLLED_FIELDS = {
    "name",
    "requested_by_id",
    "state",
    "submitted_by_id",
    "submitted_date",
    "approved_by_id",
    "approved_date",
    "hr_manager_approved_by_id",
    "hr_manager_approved_date",
    "md_approved_by_id",
    "md_approved_date",
    "rejected_by_id",
    "rejected_date",
    "rejection_reason",
    "eos_id",
    "clearance_completed_date",
    "final_release_date",
}
OPERATIONAL_EDIT_FIELDS = {
    "qiwa_acceptance_state",
    "exit_process",
    "final_exit_state",
    "local_transfer_state",
    "gosi_removal_state",
    "eos_reason_id",
    "clearance_line_ids",
}
CLEARANCE_CATEGORIES = [
    ("handover", "Handover"),
    ("asset", "Assets"),
    ("account", "Accounts"),
    ("payroll", "Payroll"),
    ("insurance", "Insurance"),
    ("gosi", "GOSI"),
    ("qiwa", "Qiwa"),
    ("final_exit", "Final Exit / Transfer"),
    ("other", "Other"),
]
CLEARANCE_SETTLEMENT_EFFECTS = [
    ("none", "No Settlement Effect"),
    ("addition", "Addition / Arrears"),
    ("deduction", "Deduction"),
]
CLEARANCE_APPLIES_TO = [
    ("all", "All Employees"),
    ("saudi", "Saudi Employees"),
    ("expat", "Expat Employees"),
]


class PrHrOffboardingClearanceTemplate(models.Model):
    _name = "pr.hr.offboarding.clearance.template"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Offboarding Clearance Checklist Template"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
    )
    applies_to = fields.Selection(
        CLEARANCE_APPLIES_TO,
        default="all",
        required=True,
    )
    line_ids = fields.One2many(
        "pr.hr.offboarding.clearance.template.line",
        "template_id",
        string="Checklist Items",
        copy=True,
    )


class PrHrOffboardingClearanceTemplateLine(models.Model):
    _name = "pr.hr.offboarding.clearance.template.line"
    _description = "Offboarding Clearance Checklist Template Line"
    _order = "sequence, id"

    template_id = fields.Many2one(
        "pr.hr.offboarding.clearance.template",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company",
        related="template_id.company_id",
        store=True,
        readonly=True,
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    category = fields.Selection(
        CLEARANCE_CATEGORIES,
        default="other",
        required=True,
    )
    name = fields.Char(required=True, translate=True)
    description = fields.Text(translate=True)
    applies_to = fields.Selection(
        CLEARANCE_APPLIES_TO,
        default="all",
        required=True,
    )
    responsible_user_id = fields.Many2one("res.users", string="Responsible")
    required = fields.Boolean(default=True)
    settlement_effect = fields.Selection(
        CLEARANCE_SETTLEMENT_EFFECTS,
        default="none",
        required=True,
    )
    reminder_delay_days = fields.Integer(
        string="Reminder Due After Days",
        default=1,
        help="Number of days after clearance starts before the assigned user's activity is due.",
    )
    reminder_activity_type_id = fields.Many2one(
        "mail.activity.type",
        string="Reminder Activity Type",
        default=lambda self: self.env.ref(
            "mail.mail_activity_data_todo",
            raise_if_not_found=False,
        ),
    )


class PrHrOffboardingEmployeeCodeLookup(models.Model):
    _name = "pr.hr.offboarding.employee.code.lookup"
    _description = "Offboarding Employee Code Lookup"
    _rec_name = "code"
    _order = "code, employee_name"

    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,
        ondelete="cascade",
        index=True,
    )
    code = fields.Char(related="employee_id.code", store=True, readonly=True)
    employee_name = fields.Char(related="employee_id.name", store=True, readonly=True)

    _sql_constraints = [
        (
            "employee_unique",
            "unique(employee_id)",
            "Each employee can only have one offboarding code lookup record.",
        ),
    ]

    @api.model
    def _get_or_create_for_employee(self, employee):
        employee = employee.exists()
        if not employee:
            return self
        lookup = self.sudo().search([("employee_id", "=", employee.id)], limit=1)
        if lookup:
            return lookup
        return self.sudo().create({"employee_id": employee.id})

    @api.model
    def _get_or_create_for_employees(self, employees):
        lookups = self.sudo()
        for employee in employees.exists():
            lookups |= self._get_or_create_for_employee(employee)
        return lookups

    def name_get(self):
        return [(lookup.id, lookup.code or "") for lookup in self]

    @api.depends("code")
    def _compute_display_name(self):
        for lookup in self:
            lookup.display_name = lookup.code or ""

    @api.model
    def name_search(self, name="", args=None, operator="ilike", limit=100):
        args = list(args or [])
        if name:
            employee_domain = expression.OR([
                [("code", operator, name)],
                [("name", operator, name)],
            ])
            employees = self.env["hr.employee"].search(employee_domain, limit=limit)
            lookups = self._get_or_create_for_employees(employees)
            if args:
                lookups = lookups.filtered_domain(args)
            return lookups.name_get()

        lookups = self.search(args, limit=limit)
        if not lookups and not args:
            employees = self.env["hr.employee"].search([], limit=limit)
            lookups = self._get_or_create_for_employees(employees)
        return lookups.name_get()


class PrHrOffboardingRequest(models.Model):
    _name = "pr.hr.offboarding.request"
    _description = "Termination / Resignation Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(
        string="Request Number",
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _("New"),
        tracking=True,
    )
    request_type = fields.Selection(
        [
            ("termination", "Termination"),
            ("resignation", "Resignation"),
        ],
        string="Request Type",
        required=True,
        default="resignation",
        tracking=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,
        tracking=True,
    )
    employee_code_id = fields.Many2one(
        "pr.hr.offboarding.employee.code.lookup",
        string="Employee ID",
        compute="_compute_employee_code_id",
        inverse="_inverse_employee_code_id",
        store=True,
        help="Search and select the employee by internal employee code.",
    )
    requested_by_id = fields.Many2one(
        "res.users",
        string="Created By",
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: self.env.user,
        tracking=True,
    )
    request_date = fields.Date(
        string="Request Date",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    last_working_date = fields.Date(
        string="Proposed Last Working Date",
        required=True,
        tracking=True,
    )
    request_reason = fields.Text(
        string="Reason / Details",
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        related="employee_id.company_id",
        store=True,
        readonly=True,
    )
    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        related="employee_id.department_id",
        store=True,
        readonly=True,
    )
    job_id = fields.Many2one(
        "hr.job",
        string="Job Position",
        related="employee_id.job_id",
        store=True,
        readonly=True,
    )
    department_manager_id = fields.Many2one(
        "hr.employee",
        string="Department Manager",
        compute="_compute_department_manager",
        store=True,
        readonly=True,
    )
    department_manager_user_id = fields.Many2one(
        "res.users",
        string="Department Manager User",
        compute="_compute_department_manager",
        store=True,
        readonly=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Department Manager Approval"),
            ("hr_manager_approval", "HR Manager Approval"),
            ("md_approval", "MD Approval"),
            ("accepted", "Accepted"),
            ("clearance", "Clearance"),
            ("eos", "EOS Settlement"),
            ("done", "Done"),
            ("continued", "Continued Employment"),
            ("rejected", "Rejected"),
            ("cancel", "Cancelled"),
        ],
        string="Status",
        required=True,
        default="draft",
        readonly=True,
        copy=False,
        tracking=True,
    )
    submitted_by_id = fields.Many2one(
        "res.users",
        string="Submitted By",
        readonly=True,
        copy=False,
    )
    submitted_date = fields.Datetime(
        string="Submitted On",
        readonly=True,
        copy=False,
    )
    approved_by_id = fields.Many2one(
        "res.users",
        string="Department Manager Approved By",
        readonly=True,
        copy=False,
    )
    approved_date = fields.Datetime(
        string="Department Manager Approved On",
        readonly=True,
        copy=False,
    )
    hr_manager_approved_by_id = fields.Many2one(
        "res.users",
        string="HR Manager Approved By",
        readonly=True,
        copy=False,
    )
    hr_manager_approved_date = fields.Datetime(
        string="HR Manager Approved On",
        readonly=True,
        copy=False,
    )
    md_approved_by_id = fields.Many2one(
        "res.users",
        string="MD Approved By",
        readonly=True,
        copy=False,
    )
    md_approved_date = fields.Datetime(
        string="MD Approved On",
        readonly=True,
        copy=False,
    )
    rejected_by_id = fields.Many2one(
        "res.users",
        string="Rejected By",
        readonly=True,
        copy=False,
    )
    rejected_date = fields.Datetime(
        string="Rejected On",
        readonly=True,
        copy=False,
    )
    rejection_reason = fields.Text(
        string="Rejection Reason",
        readonly=True,
        copy=False,
        tracking=True,
    )
    is_saudi = fields.Boolean(
        string="Saudi Employee",
        compute="_compute_employee_exit_flags",
        store=True,
    )
    is_expat = fields.Boolean(
        string="Expat Employee",
        compute="_compute_employee_exit_flags",
        store=True,
    )
    qiwa_acceptance_state = fields.Selection(
        [
            ("not_required", "Not Required"),
            ("pending", "Pending"),
            ("accepted", "Accepted"),
            ("rejected", "Rejected"),
        ],
        string="Qiwa Acceptance",
        default="not_required",
        tracking=True,
    )
    exit_process = fields.Selection(
        [
            ("not_required", "Not Required"),
            ("final_exit", "Final Exit"),
            ("local_transfer", "Local Transfer"),
            ("continue", "Continue Employment"),
        ],
        string="Exit Process",
        default="not_required",
        tracking=True,
    )
    final_exit_state = fields.Selection(
        [
            ("not_required", "Not Required"),
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="Final Exit Approval",
        default="not_required",
        tracking=True,
    )
    local_transfer_state = fields.Selection(
        [
            ("not_required", "Not Required"),
            ("pending", "Pending"),
            ("accepted", "Accepted by Employee"),
            ("rejected", "Rejected by Employee"),
        ],
        string="Local Transfer",
        default="not_required",
        tracking=True,
    )
    gosi_removal_state = fields.Selection(
        [
            ("not_required", "Not Required"),
            ("pending", "Pending"),
            ("done", "Done"),
        ],
        string="GOSI Removal",
        default="not_required",
        tracking=True,
    )
    clearance_line_ids = fields.One2many(
        "pr.hr.offboarding.clearance.line",
        "request_id",
        string="Clearance Checklist",
        copy=True,
    )
    clearance_completed = fields.Boolean(
        string="Clearance Completed",
        compute="_compute_clearance_totals",
        store=True,
    )
    clearance_completed_date = fields.Datetime(
        string="Clearance Completed On",
        readonly=True,
        copy=False,
    )
    clearance_addition_amount = fields.Monetary(
        string="Clearance Additions",
        compute="_compute_clearance_totals",
        store=True,
        currency_field="currency_id",
    )
    clearance_deduction_amount = fields.Monetary(
        string="Clearance Deductions",
        compute="_compute_clearance_totals",
        store=True,
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        readonly=True,
    )
    eos_reason_id = fields.Many2one(
        "pr.end.service.reason",
        string="EOS Reason",
        default=lambda self: self.env.ref(
            "pr_end_of_service.reason_standard_final_settlement",
            raise_if_not_found=False,
        ),
        tracking=True,
    )
    eos_id = fields.Many2one(
        "pr.end.of.service",
        string="EOS Settlement",
        readonly=True,
        copy=False,
        tracking=True,
    )
    eos_state = fields.Selection(
        related="eos_id.state",
        string="EOS Status",
        readonly=True,
    )
    eos_employee_acceptance_state = fields.Selection(
        related="eos_id.employee_acceptance_state",
        string="Employee Settlement Acceptance",
        readonly=True,
    )
    eos_requested_amount = fields.Monetary(
        related="eos_id.requested_amount",
        string="Final Settlement Amount",
        readonly=True,
        currency_field="currency_id",
    )
    eos_employee_recovery_amount = fields.Monetary(
        related="eos_id.employee_recovery_amount",
        string="Recoverable From Employee",
        readonly=True,
        currency_field="currency_id",
    )
    eos_recovery_state = fields.Selection(
        related="eos_id.recovery_state",
        string="Recovery Status",
        readonly=True,
    )
    final_release_date = fields.Datetime(
        string="Final Release On",
        readonly=True,
        copy=False,
    )
    is_hr_supervisor = fields.Boolean(compute="_compute_user_permissions")
    is_department_manager = fields.Boolean(compute="_compute_user_permissions")
    is_hr_manager = fields.Boolean(compute="_compute_user_permissions")
    is_md_approver = fields.Boolean(compute="_compute_user_permissions")

    @api.depends(
        "employee_id",
        "employee_id.department_id",
        "employee_id.department_id.manager_id",
        "employee_id.department_id.manager_id.user_id",
    )
    def _compute_department_manager(self):
        for request in self:
            manager = request.employee_id.department_id.manager_id
            request.department_manager_id = manager
            request.department_manager_user_id = manager.user_id

    @api.depends("employee_id")
    def _compute_employee_code_id(self):
        for request in self:
            request.employee_code_id = self.env[
                "pr.hr.offboarding.employee.code.lookup"
            ]._get_or_create_for_employee(request.employee_id)

    def _inverse_employee_code_id(self):
        for request in self:
            request.employee_id = request.employee_code_id.employee_id

    @api.depends("employee_id", "employee_id.country_id", "employee_id.country_id.is_homeland")
    def _compute_employee_exit_flags(self):
        for request in self:
            country = request.employee_id.country_id
            is_saudi = bool(country and "is_homeland" in country._fields and country.is_homeland)
            request.is_saudi = is_saudi
            request.is_expat = bool(request.employee_id and not is_saudi)

    @api.depends(
        "clearance_line_ids.state",
        "clearance_line_ids.amount",
        "clearance_line_ids.settlement_effect",
    )
    def _compute_clearance_totals(self):
        for request in self:
            required_lines = request.clearance_line_ids.filtered(lambda line: line.required)
            request.clearance_completed = bool(
                request.clearance_line_ids
                and all(line.state in ("done", "waived") for line in required_lines)
            )
            request.clearance_addition_amount = sum(
                request.clearance_line_ids.filtered(
                    lambda line: line.settlement_effect == "addition"
                    and line.state == "done"
                ).mapped("amount")
            )
            request.clearance_deduction_amount = sum(
                request.clearance_line_ids.filtered(
                    lambda line: line.settlement_effect == "deduction"
                    and line.state == "done"
                ).mapped("amount")
            )

    @api.depends("department_manager_user_id")
    @api.depends_context("uid")
    def _compute_user_permissions(self):
        is_hr_supervisor = self.env.user.has_group(HR_SUPERVISOR_GROUP)
        is_hr_manager = self.env.user.has_group(
            HR_MANAGER_GROUP
        ) or self.env.user.has_group("base.group_system")
        is_md_approver = self.env.user.has_group(
            MD_GROUP
        ) or self.env.user.has_group("base.group_system")
        for request in self:
            request.is_hr_supervisor = is_hr_supervisor
            request.is_hr_manager = is_hr_manager
            request.is_md_approver = is_md_approver
            request.is_department_manager = (
                request.department_manager_user_id == self.env.user
            )

    def _current_user_can_manage(self):
        return self.env.su or self.env.user.has_group(
            HR_SUPERVISOR_GROUP
        ) or self.env.user.has_group("base.group_system")

    def _check_hr_supervisor(self):
        if not self._current_user_can_manage():
            raise AccessError(
                _("Only an HR Supervisor can perform this action.")
            )

    def _check_department_manager(self):
        self.ensure_one()
        if self.department_manager_user_id != self.env.user:
            raise AccessError(
                _(
                    "Only the employee's department manager can approve or "
                    "reject this request."
                )
            )

    def _check_hr_manager(self):
        if not (
            self.env.su
            or self.env.user.has_group(HR_MANAGER_GROUP)
            or self.env.user.has_group("base.group_system")
        ):
            raise AccessError(
                _("Only an HR Manager can perform this action.")
            )

    def _check_md_approver(self):
        if not (
            self.env.su
            or self.env.user.has_group(MD_GROUP)
            or self.env.user.has_group("base.group_system")
        ):
            raise AccessError(
                _("Only MD can perform this action.")
            )

    def _user_can_approve_state(self, user):
        self.ensure_one()
        if user.has_group("base.group_system"):
            return True
        if self.state == "submitted":
            return self.department_manager_user_id == user
        if self.state == "hr_manager_approval":
            return user.has_group(HR_MANAGER_GROUP)
        if self.state == "md_approval":
            return user.has_group(MD_GROUP)
        return False

    def _approve_department_manager_step(self, approver_user, automatic=False):
        self.ensure_one()
        self.sudo().write(
            {
                "state": "hr_manager_approval",
                "approved_by_id": approver_user.id,
                "approved_date": fields.Datetime.now(),
                "hr_manager_approved_by_id": False,
                "hr_manager_approved_date": False,
                "md_approved_by_id": False,
                "md_approved_date": False,
                "rejected_by_id": False,
                "rejected_date": False,
                "rejection_reason": False,
            }
        )
        if automatic:
            body = _(
                "Department Manager approval was automatically completed because %s also holds that approval authority."
            ) % approver_user.display_name
        else:
            body = _(
                "Offboarding request accepted by the department manager and sent for HR Manager approval."
            )
        self.message_post(body=body)

    def _approve_hr_manager_step(self, approver_user, automatic=False):
        self.ensure_one()
        self.sudo().write(
            {
                "state": "md_approval",
                "hr_manager_approved_by_id": approver_user.id,
                "hr_manager_approved_date": fields.Datetime.now(),
                "md_approved_by_id": False,
                "md_approved_date": False,
                "rejected_by_id": False,
                "rejected_date": False,
                "rejection_reason": False,
            }
        )
        if automatic:
            body = _(
                "HR Manager approval was automatically completed because %s also holds that approval authority."
            ) % approver_user.display_name
        else:
            body = _("Offboarding request approved by the HR Manager and sent for MD approval.")
        self.message_post(body=body)

    def _approve_md_step(self, approver_user, automatic=False):
        self.ensure_one()
        self.sudo().write(
            {
                "state": "accepted",
                "md_approved_by_id": approver_user.id,
                "md_approved_date": fields.Datetime.now(),
                "rejected_by_id": False,
                "rejected_date": False,
                "rejection_reason": False,
            }
        )
        if automatic:
            body = _(
                "MD approval was automatically completed because %s also holds that approval authority."
            ) % approver_user.display_name
        else:
            body = _("Offboarding request approved by MD and accepted.")
        self.message_post(body=body)

    def _auto_approve_same_user_steps(self, approver_user):
        for request in self:
            guard = 0
            while (
                request.state in ("submitted", "hr_manager_approval", "md_approval")
                and request._user_can_approve_state(approver_user)
                and guard < 3
            ):
                guard += 1
                if request.state == "submitted":
                    request._approve_department_manager_step(approver_user, automatic=True)
                elif request.state == "hr_manager_approval":
                    request._approve_hr_manager_step(approver_user, automatic=True)
                elif request.state == "md_approval":
                    request._approve_md_step(approver_user, automatic=True)

    def _sync_exit_defaults(self, vals):
        employee = self.env["hr.employee"].browse(vals.get("employee_id")).exists()
        if not employee:
            return vals
        country = employee.country_id
        is_saudi = bool(country and "is_homeland" in country._fields and country.is_homeland)
        vals.setdefault("exit_process", "not_required" if is_saudi else "final_exit")
        vals.setdefault("qiwa_acceptance_state", "not_required" if is_saudi else "pending")
        vals.setdefault("final_exit_state", "not_required" if is_saudi else "pending")
        vals.setdefault("local_transfer_state", "not_required")
        vals.setdefault("gosi_removal_state", "pending" if is_saudi else "not_required")
        return vals

    @api.onchange("employee_id")
    def _onchange_employee_id_exit_defaults(self):
        for request in self:
            request.employee_code_id = self.env[
                "pr.hr.offboarding.employee.code.lookup"
            ]._get_or_create_for_employee(request.employee_id)
            if not request.employee_id:
                continue
            if request.is_saudi:
                request.exit_process = "not_required"
                request.qiwa_acceptance_state = "not_required"
                request.final_exit_state = "not_required"
                request.local_transfer_state = "not_required"
                request.gosi_removal_state = "pending"
            else:
                request.exit_process = "final_exit"
                request.qiwa_acceptance_state = "pending"
                request.final_exit_state = "pending"
                request.local_transfer_state = "not_required"
                request.gosi_removal_state = "not_required"

    @api.onchange("employee_code_id")
    def _onchange_employee_code_id(self):
        for request in self:
            request.employee_id = request.employee_code_id.employee_id

    @api.model_create_multi
    def create(self, vals_list):
        if not self._current_user_can_manage():
            raise AccessError(
                _("Only an HR Supervisor can create offboarding requests.")
            )
        prepared_vals_list = []
        for incoming_vals in vals_list:
            vals = dict(incoming_vals)
            if "employee_code_id" in vals:
                lookup = self.env["pr.hr.offboarding.employee.code.lookup"].browse(
                    vals.pop("employee_code_id")
                )
                vals["employee_id"] = lookup.employee_id.id if lookup else False
            vals.update(
                {
                    "name": self.env["ir.sequence"].next_by_code(
                        "pr.hr.offboarding.request"
                    )
                    or _("New"),
                    "requested_by_id": self.env.user.id,
                    "state": "draft",
                    "submitted_by_id": False,
                    "submitted_date": False,
                    "approved_by_id": False,
                    "approved_date": False,
                    "hr_manager_approved_by_id": False,
                    "hr_manager_approved_date": False,
                    "md_approved_by_id": False,
                    "md_approved_date": False,
                    "rejected_by_id": False,
                    "rejected_date": False,
                    "rejection_reason": False,
                }
            )
            vals = self._sync_exit_defaults(vals)
            prepared_vals_list.append(vals)
        return super().create(prepared_vals_list)

    def write(self, vals):
        if "employee_code_id" in vals:
            vals = dict(vals)
            lookup = self.env["pr.hr.offboarding.employee.code.lookup"].browse(
                vals.pop("employee_code_id")
            )
            vals["employee_id"] = lookup.employee_id.id if lookup else False
        if not self.env.su:
            if WORKFLOW_CONTROLLED_FIELDS.intersection(vals):
                raise AccessError(
                    _(
                        "Workflow and audit fields can only be changed using "
                        "the request actions."
                    )
                )
            if not self._current_user_can_manage():
                raise AccessError(
                    _("Only an HR Supervisor can edit offboarding requests.")
                )
            if any(request.state != "draft" for request in self):
                disallowed_fields = set(vals) - OPERATIONAL_EDIT_FIELDS
                if disallowed_fields:
                    raise UserError(
                        _("Only draft offboarding requests can be edited. Clearance fields remain editable during the clearance workflow.")
                    )
                if any(request.state not in ("accepted", "clearance", "eos") for request in self):
                    raise UserError(
                        _("Clearance fields can only be edited while the request is accepted, in clearance, or linked to EOS.")
                    )
        return super().write(vals)

    def unlink(self):
        self._check_hr_supervisor()
        if any(request.state != "draft" for request in self):
            raise UserError(
                _("Only draft offboarding requests can be deleted.")
            )
        return super().unlink()

    def action_submit(self):
        self._check_hr_supervisor()
        for request in self:
            if request.state != "draft":
                raise UserError(_("Only a draft request can be submitted."))
            if not request.department_id:
                raise UserError(
                    _("The selected employee must have a department.")
                )
            if not request.department_manager_id:
                raise UserError(
                    _("The employee's department must have a manager.")
                )
            if not request.department_manager_user_id:
                raise UserError(
                    _(
                        "The department manager must be linked to a user before "
                        "the request can be submitted."
                    )
                )
            request.sudo().write(
                {
                    "state": "submitted",
                    "submitted_by_id": self.env.user.id,
                    "submitted_date": fields.Datetime.now(),
                    "approved_by_id": False,
                    "approved_date": False,
                    "hr_manager_approved_by_id": False,
                    "hr_manager_approved_date": False,
                    "md_approved_by_id": False,
                    "md_approved_date": False,
                    "rejected_by_id": False,
                    "rejected_date": False,
                    "rejection_reason": False,
                }
            )
            request.message_post(
                body=_(
                    "Offboarding request submitted to %s for department "
                    "manager approval."
                )
                % request.department_manager_id.display_name
            )
            request._auto_approve_same_user_steps(self.env.user)
        return True

    def action_accept(self):
        for request in self:
            request._check_department_manager()
            if request.state != "submitted":
                raise UserError(
                    _("Only a request pending Department Manager approval can be approved.")
                )
            request._approve_department_manager_step(self.env.user)
            request._auto_approve_same_user_steps(self.env.user)
        return True

    def action_hr_manager_approve(self):
        self._check_hr_manager()
        for request in self:
            if request.state != "hr_manager_approval":
                raise UserError(
                    _("Only a request pending HR Manager approval can be approved.")
                )
            request._approve_hr_manager_step(self.env.user)
            request._auto_approve_same_user_steps(self.env.user)
        return True

    def action_md_approve(self):
        self._check_md_approver()
        for request in self:
            if request.state != "md_approval":
                raise UserError(
                    _("Only a request pending MD approval can be approved.")
                )
            request._approve_md_step(self.env.user)
        return True

    def _get_clearance_template_lines(self):
        self.ensure_one()
        applies_to = "saudi" if self.is_saudi else "expat"
        domain = [
            ("active", "=", True),
            ("applies_to", "in", ["all", applies_to]),
        ]
        if self.company_id:
            domain += [
                "|",
                ("company_id", "=", False),
                ("company_id", "=", self.company_id.id),
            ]
        else:
            domain.append(("company_id", "=", False))
        templates = self.env[
            "pr.hr.offboarding.clearance.template"
        ].search(domain, order="sequence, id")
        lines = templates.mapped("line_ids").filtered(
            lambda line: line.active and line.applies_to in ("all", applies_to)
        )
        return lines.sorted(
            lambda line: (line.template_id.sequence, line.sequence, line.id)
        )

    def _template_clearance_line_vals(self, template_line, start_date):
        self.ensure_one()
        delay_days = max(template_line.reminder_delay_days or 0, 0)
        return {
            "sequence": template_line.sequence,
            "template_line_id": template_line.id,
            "category": template_line.category,
            "name": template_line.name,
            "description": template_line.description,
            "responsible_user_id": template_line.responsible_user_id.id,
            "required": template_line.required,
            "settlement_effect": template_line.settlement_effect,
            "deadline_date": start_date + timedelta(days=delay_days),
            "reminder_delay_days": template_line.reminder_delay_days,
            "reminder_activity_type_id": template_line.reminder_activity_type_id.id,
        }

    def _default_clearance_line_vals(self):
        self.ensure_one()
        start_date = fields.Date.context_today(self)
        template_lines = self._get_clearance_template_lines()
        if template_lines:
            return [
                (0, 0, self._template_clearance_line_vals(line, start_date))
                for line in template_lines
            ]
        lines = [
            ("handover", _("Job handover checklist"), _("Confirm responsibilities, files, and open tasks are handed over."), "none"),
            ("asset", _("Company assets clearance"), _("Laptop, phone, tools, vehicle, access cards, and other assets."), "deduction"),
            ("account", _("Accounts clearance"), _("Loans, advances, petty cash, reimbursements, and employee receivables."), "deduction"),
            ("payroll", _("Payroll arrears and deductions review"), _("Held salary, unpaid salary, attendance deductions, and payroll attachments."), "addition"),
            ("insurance", _("Insurance cancellation / clearance"), _("Medical insurance and related employee obligations."), "deduction"),
        ]
        if self.is_saudi:
            lines.append(("gosi", _("Remove employee from GOSI"), _("Confirm GOSI removal request is completed."), "none"))
        else:
            lines.append(("final_exit", _("Final exit / local transfer clearance"), _("Confirm final exit or local transfer approvals are complete."), "none"))
            lines.append(("qiwa", _("Qiwa acceptance"), _("Confirm Qiwa acceptance is completed or no longer required."), "none"))
        return [
            (0, 0, {
                "sequence": index * 10,
                "category": category,
                "name": name,
                "description": description,
                "settlement_effect": settlement_effect,
                "required": True,
                "deadline_date": start_date + timedelta(days=1),
                "reminder_delay_days": 1,
            })
            for index, (category, name, description, settlement_effect) in enumerate(lines, start=1)
        ]

    def action_start_clearance(self):
        self._check_hr_supervisor()
        for request in self:
            if request.state != "accepted":
                raise UserError(_("Only an accepted request can start clearance."))
            vals = {"state": "clearance"}
            if not request.clearance_line_ids:
                vals["clearance_line_ids"] = request._default_clearance_line_vals()
            request.sudo().write(vals)
            if request.employee_id.contract_id and request.last_working_date:
                request.employee_id.contract_id.sudo().write({"date_end": request.last_working_date})
            request.message_post(body=_("Offboarding clearance started."))
        return True

    def _check_exit_process_ready(self):
        self.ensure_one()
        if self.is_saudi:
            if self.gosi_removal_state != "done":
                raise UserError(_("Saudi employee must be removed from GOSI before EOS settlement."))
            return
        if self.qiwa_acceptance_state not in ("not_required", "accepted"):
            raise UserError(_("Qiwa acceptance must be accepted or marked not required."))
        if self.exit_process == "continue":
            raise UserError(_("This request is marked to continue employment. Use Continue Employment instead."))
        if self.exit_process == "final_exit" and self.final_exit_state != "approved":
            raise UserError(_("Final exit approval must be approved before EOS settlement."))
        if self.exit_process == "local_transfer" and self.local_transfer_state != "accepted":
            raise UserError(_("Local transfer must be accepted by the employee before EOS settlement."))

    def action_complete_clearance(self):
        self._check_hr_supervisor()
        for request in self:
            if request.state != "clearance":
                raise UserError(_("Only requests in clearance can be completed."))
            if not request.clearance_completed:
                raise UserError(_("All required clearance checklist lines must be Done or Waived."))
            request._check_exit_process_ready()
            request.sudo().write({
                "clearance_completed_date": fields.Datetime.now(),
            })
            request.message_post(body=_("Offboarding clearance completed."))
        return True

    def action_continue_employment(self):
        self._check_hr_supervisor()
        for request in self:
            if request.state not in ("accepted", "clearance"):
                raise UserError(_("Only accepted or clearance requests can be continued."))
            request.sudo().write({
                "state": "continued",
                "exit_process": "continue",
            })
            request.message_post(body=_("Employee will continue employment. Offboarding workflow closed."))
        return True

    def _prepare_eos_adjustment_commands(self):
        self.ensure_one()
        commands = []
        for line in self.clearance_line_ids.filtered(
            lambda item: item.state == "done"
            and item.settlement_effect != "none"
            and item.amount
        ):
            commands.append((0, 0, {
                "sequence": line.sequence,
                "name": line.name,
                "category": "clearance" if line.category not in ("payroll", "asset", "account", "insurance", "gosi") else line.category,
                "adjustment_type": line.settlement_effect,
                "amount": line.amount,
                "source_ref": "offboarding:clearance:%s" % line.id,
                "notes": line.notes or line.description,
            }))
        return commands

    def action_create_eos_settlement(self):
        self._check_hr_supervisor()
        for request in self:
            if request.state != "clearance":
                raise UserError(_("EOS settlement can only be created after clearance is completed."))
            if not request.clearance_completed:
                raise UserError(_("Complete all required clearance items before creating EOS settlement."))
            request._check_exit_process_ready()
            if request.eos_id:
                continue
            reason = request.eos_reason_id or self.env.ref(
                "pr_end_of_service.reason_standard_final_settlement",
                raise_if_not_found=False,
            )
            if not reason:
                raise UserError(_("Please configure an EOS reason before creating the settlement."))
            eos = self.env["pr.end.of.service"].sudo().create({
                "employee_id": request.employee_id.id,
                "company_id": request.company_id.id or self.env.company.id,
                "service_end_date": request.last_working_date,
                "settlement_type": "final",
                "reason_id": reason.id,
                "date_request": fields.Date.context_today(request),
                "notes": _("Created from offboarding request %s.") % request.name,
                "offboarding_request_id": request.id,
                "adjustment_line_ids": request._prepare_eos_adjustment_commands(),
            })
            eos.action_sync_payroll_adjustments()
            request.sudo().write({
                "eos_id": eos.id,
                "state": "eos",
            })
            request.message_post(body=_("EOS settlement %s was created.") % eos.name)
        if len(self) == 1:
            return self.action_view_eos_settlement()
        return True

    def action_view_eos_settlement(self):
        self.ensure_one()
        if not self.eos_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("EOS Settlement"),
            "res_model": "pr.end.of.service",
            "view_mode": "form",
            "res_id": self.eos_id.id,
        }

    def action_mark_final_released(self):
        self._check_hr_supervisor()
        for request in self:
            if not request.eos_id:
                raise UserError(_("Create the EOS settlement first."))
            if request.eos_id.state != "done":
                raise UserError(_("The EOS settlement must be done before final release."))
            if request.eos_id.employee_recovery_amount > 0.0 and request.eos_id.recovery_state == "pending":
                raise UserError(_("Collect or waive the employee recovery amount before final release."))
            request.sudo().write({
                "state": "done",
                "final_release_date": fields.Datetime.now(),
            })
            request.message_post(body=_("Final settlement released and offboarding completed."))
        return True

    def action_cancel(self):
        self._check_hr_supervisor()
        for request in self:
            if request.state in ("done", "cancel"):
                continue
            if request.eos_id and request.eos_id.state not in ("draft", "cancel"):
                raise UserError(_("Cancel or reset the linked EOS settlement before cancelling this offboarding request."))
            request.sudo().write({"state": "cancel"})
            request.message_post(body=_("Offboarding request cancelled."))
        return True

    def action_open_reject_wizard(self):
        self.ensure_one()
        if self.state == "submitted":
            self._check_department_manager()
        elif self.state == "hr_manager_approval":
            self._check_hr_manager()
        elif self.state == "md_approval":
            self._check_md_approver()
        else:
            raise UserError(
                _("Only a request pending approval can be rejected.")
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Reject Offboarding Request"),
            "res_model": "pr.hr.offboarding.reject.wizard",
            "view_mode": "form",
            "view_id": self.env.ref(
                "pr_hr_offboarding.view_offboarding_reject_wizard_form"
            ).id,
            "target": "new",
            "context": {
                "default_request_id": self.id,
            },
        }

    def _action_reject(self, reason):
        self.ensure_one()
        approval_state = self.state
        if self.state == "submitted":
            self._check_department_manager()
        elif self.state == "hr_manager_approval":
            self._check_hr_manager()
        elif self.state == "md_approval":
            self._check_md_approver()
        else:
            raise UserError(
                _("Only a request pending approval can be rejected.")
            )
        reason = (reason or "").strip()
        if not reason:
            raise UserError(_("A rejection reason is required."))
        values = {
            "state": "rejected",
            "rejected_by_id": self.env.user.id,
            "rejected_date": fields.Datetime.now(),
            "rejection_reason": reason,
            "md_approved_by_id": False,
            "md_approved_date": False,
        }
        if approval_state == "submitted":
            values.update(
                {
                    "approved_by_id": False,
                    "approved_date": False,
                    "hr_manager_approved_by_id": False,
                    "hr_manager_approved_date": False,
                }
            )
        elif approval_state == "hr_manager_approval":
            values.update(
                {
                    "hr_manager_approved_by_id": False,
                    "hr_manager_approved_date": False,
                }
            )
        self.sudo().write(values)
        self.message_post(
            body=_("Offboarding request rejected. Reason: %s") % reason
        )
        return True

    def action_reset_to_draft(self):
        self._check_hr_supervisor()
        for request in self:
            if request.state not in ("rejected", "cancel"):
                raise UserError(
                    _("Only a rejected or cancelled request can be reset to draft.")
                )
            request.sudo().write(
                {
                    "state": "draft",
                    "submitted_by_id": False,
                    "submitted_date": False,
                    "approved_by_id": False,
                    "approved_date": False,
                    "hr_manager_approved_by_id": False,
                    "hr_manager_approved_date": False,
                    "md_approved_by_id": False,
                    "md_approved_date": False,
                    "rejected_by_id": False,
                    "rejected_date": False,
                    "rejection_reason": False,
                }
            )
            request.message_post(body=_("Offboarding request reset to draft."))
        return True


class PrHrOffboardingClearanceLine(models.Model):
    _name = "pr.hr.offboarding.clearance.line"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Offboarding Clearance Checklist Line"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    request_id = fields.Many2one(
        "pr.hr.offboarding.request",
        string="Offboarding Request",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company",
        related="request_id.company_id",
        store=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="request_id.currency_id",
        readonly=True,
    )
    template_line_id = fields.Many2one(
        "pr.hr.offboarding.clearance.template.line",
        string="Template Item",
        readonly=True,
    )
    category = fields.Selection(
        CLEARANCE_CATEGORIES,
        default="other",
        required=True,
    )
    name = fields.Char(required=True)
    description = fields.Text()
    responsible_user_id = fields.Many2one("res.users", string="Responsible")
    required = fields.Boolean(default=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("done", "Done"),
            ("waived", "Waived"),
        ],
        default="pending",
        required=True,
    )
    settlement_effect = fields.Selection(
        CLEARANCE_SETTLEMENT_EFFECTS,
        default="none",
        required=True,
    )
    amount = fields.Monetary(currency_field="currency_id")
    deadline_date = fields.Date(string="Due Date")
    reminder_delay_days = fields.Integer(string="Reminder Due After Days")
    reminder_activity_type_id = fields.Many2one(
        "mail.activity.type",
        string="Reminder Activity Type",
        default=lambda self: self.env.ref(
            "mail.mail_activity_data_todo",
            raise_if_not_found=False,
        ),
    )
    reminder_activity_id = fields.Many2one(
        "mail.activity",
        string="Reminder Activity",
        readonly=True,
        copy=False,
    )
    completed_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    completed_date = fields.Datetime(readonly=True, copy=False)
    waiver_reason = fields.Text(string="Waive Off Reason")
    notes = fields.Text()

    def _current_user_can_manage_clearance(self):
        return self.env.su or self.env.user.has_group(
            HR_SUPERVISOR_GROUP
        ) or self.env.user.has_group("base.group_system")

    def _check_clearance_manager(self):
        if not self._current_user_can_manage_clearance():
            raise AccessError(
                _("Only an HR Supervisor can waive or reset clearance items.")
            )

    def _check_responsible_can_complete(self):
        if self._current_user_can_manage_clearance():
            return
        if any(line.responsible_user_id != self.env.user for line in self):
            raise AccessError(
                _("Only the assigned responsible user can complete this clearance item.")
            )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("skip_clearance_activity_sync"):
            records._sync_reminder_activity()
        return records

    def write(self, vals):
        if not self.env.su and not self._current_user_can_manage_clearance():
            allowed_fields = {
                "state",
                "notes",
                "completed_by_id",
                "completed_date",
            }
            if set(vals) - allowed_fields:
                raise AccessError(
                    _("Only an HR Supervisor can edit clearance item details.")
                )
            if vals.get("state") and vals["state"] != "done":
                raise AccessError(
                    _("Assigned users can only mark clearance items as done.")
                )
            self._check_responsible_can_complete()
        result = super().write(vals)
        tracked_fields = {
            "responsible_user_id",
            "deadline_date",
            "reminder_activity_type_id",
            "state",
            "name",
            "description",
        }
        if (
            tracked_fields.intersection(vals)
            and not self.env.context.get("skip_clearance_activity_sync")
        ):
            self._sync_reminder_activity()
        return result

    def unlink(self):
        activities = self.mapped("reminder_activity_id")
        result = super().unlink()
        activities.sudo().unlink()
        return result

    def _sync_reminder_activity(self):
        Activity = self.env["mail.activity"].sudo()
        model_id = self.env["ir.model"].sudo()._get_id(self._name)
        today = fields.Date.context_today(self)
        default_activity_type = self.env.ref(
            "mail.mail_activity_data_todo",
            raise_if_not_found=False,
        )
        for line in self:
            activity = line.reminder_activity_id.exists()
            activity_type = line.reminder_activity_type_id or default_activity_type
            if not line.responsible_user_id or line.state != "pending" or not activity_type:
                activity.unlink()
                if line.reminder_activity_id:
                    line.with_context(skip_clearance_activity_sync=True).sudo().write(
                        {"reminder_activity_id": False}
                    )
                continue
            deadline = line.deadline_date or today
            values = {
                "activity_type_id": activity_type.id,
                "date_deadline": deadline,
                "summary": _("Offboarding clearance: %s") % line.name,
                "note": line.description or "",
                "user_id": line.responsible_user_id.id,
                "res_model_id": model_id,
                "res_id": line.id,
            }
            if activity:
                activity.write(values)
            else:
                activity = Activity.create(values)
                line.with_context(skip_clearance_activity_sync=True).sudo().write(
                    {"reminder_activity_id": activity.id}
                )

    def action_done(self):
        self._check_responsible_can_complete()
        for line in self:
            line.write({
                "state": "done",
                "completed_by_id": self.env.user.id,
                "completed_date": fields.Datetime.now(),
            })
        return True

    def action_waive(self):
        self._check_clearance_manager()
        for line in self:
            line.write({
                "state": "waived",
                "completed_by_id": self.env.user.id,
                "completed_date": fields.Datetime.now(),
            })
        return True

    def action_reset(self):
        self._check_clearance_manager()
        for line in self:
            line.write({
                "state": "pending",
                "completed_by_id": False,
                "completed_date": False,
            })
        return True


class PrEndOfService(models.Model):
    _inherit = "pr.end.of.service"

    offboarding_request_id = fields.Many2one(
        "pr.hr.offboarding.request",
        string="Offboarding Request",
        readonly=True,
        copy=False,
    )

    def _mark_done_from_payment(self, payment):
        res = super()._mark_done_from_payment(payment)
        for eos in self.filtered("offboarding_request_id"):
            eos.offboarding_request_id.message_post(
                body=_("Linked EOS settlement %s was completed.") % eos.name
            )
        return res
