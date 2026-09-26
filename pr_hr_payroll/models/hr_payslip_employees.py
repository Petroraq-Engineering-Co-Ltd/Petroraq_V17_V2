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

    def _pr_get_gosi_recovery_employees(self):
        """Employees whose contract is flagged for post-termination GOSI-only
        payslips. Searched with active_test=False since these employees may
        already be archived by the time the recovery period is payrolled."""
        return self.env["hr.employee"].with_context(active_test=False).search([
            ("contract_ids.state", "=", "close"),
            ("contract_ids.calculate_payslip_gosi", "=", True),
        ])

    def _pr_filter_employees_for_period(self, employees):
        date_from, date_to = self._pr_get_payroll_period()
        if not employees or not date_from or not date_to:
            return employees
        contracts = self.env["hr.contract"].with_context(active_test=False).search([
            ("employee_id", "in", employees.ids),
            ("state", "in", ["open", "close"]),
            ("active", "=", True),
            ("date_start", "<=", date_to),
            "|",
            ("date_end", "=", False),
            ("date_end", ">=", date_from),
        ])
        gosi_recovery_contracts = self.env["hr.contract"].with_context(active_test=False).search([
            ("employee_id", "in", employees.ids),
            ("state", "=", "close"),
            ("calculate_payslip_gosi", "=", True),
        ])
        eligible_employees = contracts.employee_id | gosi_recovery_contracts.employee_id
        return employees.filtered(lambda employee: employee in eligible_employees)

    def _get_employees(self):
        employees = super()._get_employees() | self._pr_get_gosi_recovery_employees()
        return self._pr_filter_employees_for_period(employees)

    def _compute_employee_ids(self):
        super()._compute_employee_ids()
        for wizard in self:
            employees = wizard.employee_ids | wizard._pr_get_gosi_recovery_employees()
            wizard.employee_ids = wizard._pr_filter_employees_for_period(employees)
