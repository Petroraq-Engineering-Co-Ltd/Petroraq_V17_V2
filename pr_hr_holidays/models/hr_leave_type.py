from odoo import SUPERUSER_ID, api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import random


class HolidaysType(models.Model):
    # region [Initial]
    _inherit = "hr.leave.type"
    # endregion [Initial]

    # region [Fields]

    is_paid = fields.Boolean(string="Is Paid ?")
    leave_type = fields.Selection([
        ("annual_leave", "Annual Leave"),
        ("sick_leave", "Sick Leave"),
        ("business_leave", "Business Trip"),
    ], string="Type")

    # endregion [Fields]

    def _pr_sync_due_accrual_allocations(self, employees):
        """Keep accrual balances current before dashboard/request computations."""
        if self.env.context.get("pr_skip_due_accrual_sync"):
            return

        employees = employees.exists()
        if not employees:
            return

        today = fields.Date.context_today(self)
        allocations = self.env["hr.leave.allocation"].sudo().search([
            ("employee_id", "in", employees.ids),
            ("holiday_status_id", "in", self.ids),
            ("state", "=", "validate"),
            ("allocation_type", "=", "accrual"),
            ("accrual_plan_id", "!=", False),
            ("date_from", "<=", today),
            "|",
            ("date_to", "=", False),
            ("date_to", ">=", today),
            "|",
            ("nextcall", "=", False),
            ("nextcall", "<=", today),
        ])
        if allocations:
            # Accrual processing is a system operation.  In particular,
            # hr_holidays_attendance checks the effective user's HR groups
            # while updating a validated allocation, even when the recordset
            # was obtained with sudo().  Use the actual superuser so employee
            # portal requests can refresh balances without receiving an HR
            # Officer-only ValidationError.
            allocations.with_user(SUPERUSER_ID).with_context(
                pr_skip_due_accrual_sync=True
            )._process_accrual_plans(today, log=False)

    def get_allocation_data(self, employees, target_date=None):
        self._pr_sync_due_accrual_allocations(employees)
        return super().get_allocation_data(employees, target_date)
