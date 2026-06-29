from odoo import fields, models


class HrPayslipEmployees(models.TransientModel):
    _inherit = "hr.payslip.employees"

    def _pr_get_payroll_period(self):
        active_run = self.env["hr.payslip.run"]
        if self.env.context.get("active_model") == "hr.payslip.run" and self.env.context.get("active_id"):
            active_run = self.env["hr.payslip.run"].browse(self.env.context["active_id"]).exists()
        if active_run:
            return active_run.date_start, active_run.date_end
        return (
            fields.Date.to_date(self.env.context.get("default_date_start")),
            fields.Date.to_date(self.env.context.get("default_date_end")),
        )

    def _pr_filter_employees_for_period(self, employees):
        date_from, date_to = self._pr_get_payroll_period()
        if not employees or not date_from or not date_to:
            return employees
        contracts = self.env["hr.contract"].search([
            ("employee_id", "in", employees.ids),
            ("state", "in", ["open", "close"]),
            ("active", "=", True),
            ("date_start", "<=", date_to),
            "|",
            ("date_end", "=", False),
            ("date_end", ">=", date_from),
        ])
        return employees.filtered(lambda employee: employee in contracts.employee_id)

    def _get_employees(self):
        return self._pr_filter_employees_for_period(super()._get_employees())

    def _compute_employee_ids(self):
        super()._compute_employee_ids()
        for wizard in self:
            wizard.employee_ids = wizard._pr_filter_employees_for_period(wizard.employee_ids)
