from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


EDITABLE_HEADER_FIELDS = {
    "employee_id",
    "assign_date",
    "manager_remarks",
    "return_reason",
    "completion_notes",
    "task_line_ids",
    "attachment_ids",
}
PROGRESS_HEADER_FIELDS = {
    "completion_notes",
    "task_line_ids",
    "attachment_ids",
}
CHATTER_FIELDS = {
    "message_follower_ids",
    "message_partner_ids",
    "message_ids",
    "activity_ids",
}
TASK_STATES = [
    ("draft", "Draft"),
    ("submitted_manager", "Submitted to Manager"),
    ("returned_manager", "Returned by Manager"),
    ("manager_approved", "Manager Approved"),
    ("in_progress", "In Progress"),
    ("completed", "Completed"),
    ("closed", "Closed"),
]


class EmployeeTaskList(models.Model):
    _name = "employee.task.list"
    _description = "Employee Task List"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "assign_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(
        string="Task List Reference",
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _("New"),
        tracking=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        required=True,
        tracking=True,
        check_company=True,
        default=lambda self: self._default_employee(),
    )
    department_id = fields.Many2one(
        "hr.department",
        related="employee_id.department_id",
        store=True,
        readonly=True,
    )
    manager_id = fields.Many2one(
        "hr.employee",
        string="Immediate Manager",
        related="employee_id.parent_id",
        store=True,
        readonly=True,
    )
    manager_user_id = fields.Many2one(
        "res.users",
        related="manager_id.user_id",
        store=True,
        readonly=True,
        index=True,
    )
    assign_date = fields.Date(
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    end_date = fields.Date(
        string="Latest End Date",
        compute="_compute_task_metrics",
        store=True,
        index=True,
    )
    state = fields.Selection(
        TASK_STATES,
        required=True,
        default="draft",
        tracking=True,
        index=True,
    )
    manager_remarks = fields.Text(tracking=True)
    return_reason = fields.Text(readonly=True, tracking=True)
    completion_notes = fields.Text(tracking=True)
    task_line_ids = fields.One2many(
        "employee.task.line",
        "task_list_id",
        string="Task Details",
        copy=True,
    )
    history_ids = fields.One2many(
        "employee.task.approval.history",
        "task_list_id",
        string="Approval History",
        readonly=True,
    )
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "employee_task_list_attachment_rel",
        "task_list_id",
        "attachment_id",
        string="Supporting Files",
    )
    progress = fields.Float(
        string="Progress %",
        compute="_compute_task_metrics",
        store=True,
        group_operator="avg",
    )
    task_count = fields.Integer(compute="_compute_task_metrics", store=True)
    overdue = fields.Boolean(
        compute="_compute_task_metrics",
        store=True,
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    created_by_id = fields.Many2one(
        "res.users",
        string="Created By",
        related="create_uid",
        store=True,
        readonly=True,
    )
    approved_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    approved_date = fields.Datetime(readonly=True, copy=False)
    completed_date = fields.Datetime(readonly=True, copy=False)
    closed_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    closed_date = fields.Datetime(readonly=True, copy=False)

    can_submit = fields.Boolean(compute="_compute_action_flags")
    can_manager_approve = fields.Boolean(compute="_compute_action_flags")
    can_manager_return = fields.Boolean(compute="_compute_action_flags")
    can_start_work = fields.Boolean(compute="_compute_action_flags")
    can_mark_completed = fields.Boolean(compute="_compute_action_flags")
    can_close = fields.Boolean(compute="_compute_action_flags")

    @api.model
    def _default_employee(self):
        return self.env["hr.employee"].search(
            [("user_id", "=", self.env.user.id), ("company_id", "in", self.env.companies.ids)],
            limit=1,
        )

    @api.depends_context("uid")
    @api.depends("state", "employee_id.user_id", "manager_user_id")
    def _compute_action_flags(self):
        user = self.env.user
        is_admin = user.has_group("pr_employee_task_management.group_task_admin")
        is_manager_group = user.has_group("pr_employee_task_management.group_task_manager")
        for record in self:
            is_employee = record.employee_id.user_id == user
            is_manager = is_admin or (
                is_manager_group and record.manager_user_id == user and not is_employee
            )
            record.can_submit = (
                record.state in ("draft", "returned_manager")
                and (is_employee or is_admin or is_manager)
            )
            record.can_manager_approve = record.state == "submitted_manager" and is_manager
            record.can_manager_return = record.state == "submitted_manager" and is_manager
            record.can_start_work = record.state == "manager_approved" and (is_employee or is_admin)
            record.can_mark_completed = record.state == "in_progress" and (is_employee or is_admin)
            record.can_close = record.state == "completed" and is_manager

    @api.depends(
        "task_line_ids",
        "task_line_ids.progress",
        "task_line_ids.end_date",
        "task_line_ids.task_status",
        "state",
    )
    def _compute_task_metrics(self):
        today = fields.Date.context_today(self)
        for record in self:
            lines = record.task_line_ids
            record.task_count = len(lines)
            record.progress = sum(lines.mapped("progress")) / len(lines) if lines else 0.0
            dates = [value for value in lines.mapped("end_date") if value]
            record.end_date = max(dates) if dates else False
            record.overdue = bool(
                record.end_date
                and record.end_date < today
                and record.state not in ("completed", "closed")
            )

    @api.model_create_multi
    def create(self, vals_list):
        records = self.browse()
        sequence = self.env["ir.sequence"]
        today = fields.Date.context_today(self)
        for values in vals_list:
            employee = self.env["hr.employee"].browse(
                values.get("employee_id")
            ).exists() or self._default_employee()
            if not employee:
                raise ValidationError(_("Your user must be linked to an employee."))
            self._check_employee_assignment_access(employee)
            values["employee_id"] = employee.id
            assign_date = fields.Date.to_date(values.get("assign_date") or today)
            if assign_date < today:
                raise ValidationError(_("Assign Date cannot be before today."))
            if values.get("name", _("New")) == _("New"):
                values["name"] = sequence.next_by_code("employee.task.list") or _("New")
        records = super().create(vals_list)
        return records

    def write(self, values):
        if self.env.context.get("task_workflow_write"):
            return super().write(values)
        if (
            values.get("assign_date")
            and fields.Date.to_date(values["assign_date"]) < fields.Date.context_today(self)
        ):
            raise ValidationError(_("Assign Date cannot be before today."))
        business_fields = set(values) - CHATTER_FIELDS
        is_admin = self.env.user.has_group(
            "pr_employee_task_management.group_task_admin"
        )
        for record in self:
            if not business_fields or is_admin:
                continue
            if record.state == "closed":
                raise UserError(_("Closed task lists cannot be edited."))
            if record.state in ("draft", "returned_manager"):
                if not record._current_user_can_prepare():
                    raise AccessError(_("You are not allowed to edit this task list."))
                forbidden = business_fields - EDITABLE_HEADER_FIELDS
            elif (
                record.state == "submitted_manager"
                and record.manager_user_id == self.env.user
            ):
                forbidden = business_fields - {"manager_remarks"}
            elif record.state == "in_progress" and record.employee_id.user_id == self.env.user:
                forbidden = business_fields - PROGRESS_HEADER_FIELDS
            elif (
                record.state == "completed"
                and record.manager_user_id == self.env.user
            ):
                forbidden = business_fields - {"manager_remarks"}
            else:
                forbidden = business_fields
            if forbidden:
                raise UserError(
                    _("These fields cannot be edited in the current stage: %s")
                    % ", ".join(sorted(forbidden))
                )
        return super().write(values)

    @api.model
    def _check_employee_assignment_access(self, employee):
        user = self.env.user
        if user.has_group("pr_employee_task_management.group_task_admin"):
            return
        if employee.user_id == user:
            return
        if (
            user.has_group("pr_employee_task_management.group_task_manager")
            and employee.parent_id.user_id == user
        ):
            return
        raise AccessError(_("You can only create task lists for yourself or your direct reports."))

    def _current_user_can_prepare(self):
        self.ensure_one()
        user = self.env.user
        return bool(
            user.has_group("pr_employee_task_management.group_task_admin")
            or self.employee_id.user_id == user
            or (
                user.has_group("pr_employee_task_management.group_task_manager")
                and self.manager_user_id == user
            )
        )

    def _log_history(self, status, remarks=False):
        self.ensure_one()
        self.env["employee.task.approval.history"].sudo().create({
            "task_list_id": self.id,
            "action_by_id": self.env.user.id,
            "status": status,
            "remarks": remarks or False,
        })

    def _notify_user(self, user, subject, body, schedule_activity=False):
        self.ensure_one()
        if not user or not user.active:
            return
        self.message_post(
            body=body,
            partner_ids=user.partner_id.ids,
            message_type="notification",
            subtype_xmlid="mail.mt_note",
        )
        if schedule_activity:
            self.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=user.id,
                summary=subject,
                note=body,
            )

    def _complete_user_activities(self, user):
        self.ensure_one()
        self.activity_ids.filtered(lambda activity: activity.user_id == user).action_done()

    def action_submit_to_manager(self):
        for record in self:
            if not record.can_submit:
                raise AccessError(_("You are not allowed to submit this task list."))
            if not record.task_line_ids:
                raise ValidationError(_("Add at least one task before submission."))
            if not record.manager_user_id:
                raise ValidationError(
                    _("The employee's Immediate Manager must be linked to an Odoo user.")
                )
            if record.manager_user_id == record.employee_id.user_id:
                raise ValidationError(_("An employee cannot approve their own task list."))
            record.with_context(task_workflow_write=True).write({
                "state": "submitted_manager",
                "return_reason": False,
            })
            record._log_history("submitted_manager")
            record._notify_user(
                record.manager_user_id,
                _("Task List Approval Required"),
                _(
                    "Task list <b>%(task)s</b> submitted by %(employee)s requires your approval."
                )
                % {"task": record.name, "employee": record.employee_id.name},
                schedule_activity=True,
            )
        return True

    def action_manager_approve(self):
        for record in self:
            if not record.can_manager_approve:
                raise AccessError(_("Only the employee's Immediate Manager can approve."))
            record._complete_user_activities(self.env.user)
            record.with_context(task_workflow_write=True).write({
                "state": "manager_approved",
                "approved_by_id": self.env.user.id,
                "approved_date": fields.Datetime.now(),
            })
            record._log_history("manager_approved", record.manager_remarks)
            record._notify_user(
                record.employee_id.user_id,
                _("Task List Approved"),
                _("Your task list <b>%s</b> was approved and is ready to start.") % record.name,
            )
        return True

    def action_manager_return(self):
        for record in self:
            if not record.can_manager_return:
                raise AccessError(_("Only the employee's Immediate Manager can return this task list."))
            remarks = (record.manager_remarks or "").strip()
            if not remarks:
                raise ValidationError(_("Manager Remarks are required when returning a task list."))
            record._complete_user_activities(self.env.user)
            record.with_context(task_workflow_write=True).write({
                "state": "returned_manager",
                "return_reason": remarks,
            })
            record._log_history("returned_manager", remarks)
            record._notify_user(
                record.employee_id.user_id,
                _("Task List Returned for Correction"),
                _("Task list <b>%s</b> was returned: %s") % (record.name, remarks),
            )
        return True

    def action_start_work(self):
        today = fields.Date.context_today(self)
        for record in self:
            if not record.can_start_work:
                raise AccessError(_("Only the assigned employee can start this task list."))
            record.with_context(task_workflow_write=True).write({"state": "in_progress"})
            for line in record.task_line_ids.filtered(lambda item: item.task_status == "draft"):
                line.with_context(task_workflow_write=True).write({
                    "task_status": "in_progress",
                    "start_date": line.start_date or today,
                })
            record._log_history("in_progress")
        return True

    def action_mark_completed(self):
        for record in self:
            if not record.can_mark_completed:
                raise AccessError(_("Only the assigned employee can complete this task list."))
            incomplete = record.task_line_ids.filtered(
                lambda line: line.task_status not in ("completed", "closed")
                or line.progress < 100.0
            )
            if incomplete:
                raise ValidationError(
                    _("Every task line must be 100%% complete and marked Completed.")
                )
            record.with_context(task_workflow_write=True).write({
                "state": "completed",
                "completed_date": fields.Datetime.now(),
            })
            record._log_history("completed", record.completion_notes)
            record._notify_user(
                record.manager_user_id,
                _("Completed Task List Requires Review"),
                _("Task list <b>%s</b> is completed and ready for closure.") % record.name,
                schedule_activity=True,
            )
        return True

    def action_close(self):
        for record in self:
            if not record.can_close:
                raise AccessError(_("Only the employee's Immediate Manager can close this task list."))
            record._complete_user_activities(self.env.user)
            record.task_line_ids.with_context(task_workflow_write=True).write({
                "task_status": "closed",
                "progress": 100.0,
            })
            record.with_context(task_workflow_write=True).write({
                "state": "closed",
                "closed_by_id": self.env.user.id,
                "closed_date": fields.Datetime.now(),
            })
            record._log_history("closed", record.manager_remarks)
            record._notify_user(
                record.employee_id.user_id,
                _("Task List Closed"),
                _("Task list <b>%s</b> was reviewed and closed.") % record.name,
            )
        return True

    @api.model
    def _cron_refresh_overdue(self):
        self.search([
            ("state", "not in", ("completed", "closed")),
            ("end_date", "!=", False),
        ])._compute_task_metrics()

    @api.model
    def get_dashboard_data(self):
        state_labels = dict(self._fields["state"].selection)
        state_groups = self.read_group([], ["id:count"], ["state"], lazy=False)
        department_groups = self.read_group(
            [],
            ["task_count:sum", "progress:avg"],
            ["department_id"],
            lazy=False,
        )
        employee_groups = self.read_group(
            [("state", "in", ("completed", "closed"))],
            ["id:count"],
            ["employee_id"],
            lazy=False,
            limit=10,
        )
        monthly_groups = self.read_group(
            [("completed_date", "!=", False)],
            ["id:count"],
            ["completed_date:month"],
            lazy=False,
        )
        counts = {
            "total": self.search_count([]),
            "pending": self.search_count([("state", "=", "submitted_manager")]),
            "in_progress": self.search_count([("state", "=", "in_progress")]),
            "completed": self.search_count([("state", "=", "completed")]),
            "overdue": self.search_count([("overdue", "=", True)]),
            "closed": self.search_count([("state", "=", "closed")]),
        }
        return {
            "counts": counts,
            "states": [
                {
                    "key": group["state"],
                    "label": state_labels.get(group["state"], group["state"]),
                    "count": group["__count"],
                }
                for group in state_groups
                if group.get("state")
            ],
            "departments": [
                {
                    "label": group["department_id"][1] if group.get("department_id") else _("No Department"),
                    "tasks": group.get("task_count", 0),
                    "progress": round(group.get("progress", 0.0), 1),
                }
                for group in department_groups
            ],
            "employees": [
                {
                    "label": group["employee_id"][1] if group.get("employee_id") else _("No Employee"),
                    "count": group["__count"],
                }
                for group in employee_groups
            ],
            "months": [
                {
                    "label": group.get("completed_date:month") or _("Unknown"),
                    "count": group["__count"],
                }
                for group in monthly_groups
            ],
        }


class EmployeeTaskLine(models.Model):
    _name = "employee.task.line"
    _description = "Employee Task Line"
    _order = "sequence, id"

    task_list_id = fields.Many2one(
        "employee.task.list",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(string="Sr. No.", default=10)
    description = fields.Text(required=True)
    assign_date = fields.Date(required=True, default=fields.Date.context_today)
    start_date = fields.Date()
    activities = fields.Text()
    end_date = fields.Date()
    remarks = fields.Text()
    progress = fields.Float(default=0.0)
    task_status = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_progress", "In Progress"),
            ("completed", "Completed"),
            ("closed", "Closed"),
        ],
        required=True,
        default="draft",
    )
    company_id = fields.Many2one(
        related="task_list_id.company_id",
        store=True,
        readonly=True,
    )

    @api.constrains("progress")
    def _check_progress(self):
        for line in self:
            if not 0.0 <= line.progress <= 100.0:
                raise ValidationError(_("Progress must be between 0 and 100."))

    @api.constrains("start_date", "end_date")
    def _check_dates(self):
        for line in self:
            if line.start_date and line.end_date and line.end_date < line.start_date:
                raise ValidationError(_("End Date cannot be earlier than Start Date."))

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            task_list = self.env["employee.task.list"].browse(
                values.get("task_list_id")
            ).exists()
            if task_list and task_list.state not in ("draft", "returned_manager"):
                raise UserError(_("New task lines can only be added in Draft or Returned stage."))
        return super().create(vals_list)

    def write(self, values):
        if self.env.context.get("task_workflow_write"):
            return super().write(values)
        progress_fields = {"activities", "remarks", "progress", "task_status", "start_date", "end_date"}
        for line in self:
            task_list = line.task_list_id
            if task_list.state == "closed":
                raise UserError(_("Closed task lines cannot be edited."))
            if task_list.state in ("draft", "returned_manager"):
                if not task_list._current_user_can_prepare():
                    raise AccessError(_("You are not allowed to edit this task line."))
            elif task_list.state == "in_progress":
                if task_list.employee_id.user_id != self.env.user and not self.env.user.has_group(
                    "pr_employee_task_management.group_task_admin"
                ):
                    raise AccessError(_("Only the assigned employee can update task progress."))
                forbidden = set(values) - progress_fields
                if forbidden:
                    raise UserError(_("Only progress-related fields can be updated during execution."))
                requested_status = values.get("task_status")
                requested_progress = values.get("progress", line.progress)
                if requested_status == "closed":
                    raise UserError(_("Only the manager can close task lines with the task list."))
                if requested_status == "completed" and requested_progress < 100.0:
                    raise ValidationError(_("A completed task line must have 100% progress."))
            else:
                raise UserError(_("Task lines cannot be edited in the current stage."))
        result = super().write(values)
        if "progress" in values:
            for line in self:
                if line.progress >= 100.0 and line.task_status != "closed":
                    super(EmployeeTaskLine, line).write({"task_status": "completed"})
                elif line.progress > 0.0 and line.task_status == "draft":
                    super(EmployeeTaskLine, line).write({"task_status": "in_progress"})
        return result

    def unlink(self):
        for line in self:
            if line.task_list_id.state not in ("draft", "returned_manager"):
                raise UserError(_("Task lines can only be removed in Draft or Returned stage."))
        return super().unlink()


class EmployeeTaskApprovalHistory(models.Model):
    _name = "employee.task.approval.history"
    _description = "Employee Task Approval History"
    _order = "action_date desc, id desc"

    task_list_id = fields.Many2one(
        "employee.task.list",
        required=True,
        ondelete="cascade",
        index=True,
    )
    action_by_id = fields.Many2one("res.users", required=True, readonly=True)
    action_date = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    status = fields.Selection(
        selection=TASK_STATES,
        required=True,
        readonly=True,
    )
    remarks = fields.Text(readonly=True)
    company_id = fields.Many2one(
        related="task_list_id.company_id",
        store=True,
        readonly=True,
    )
