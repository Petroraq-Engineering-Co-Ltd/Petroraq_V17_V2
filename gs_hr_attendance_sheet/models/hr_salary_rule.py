from odoo import api, models


class HrSalaryRule(models.Model):
    _inherit = "hr.salary.rule"

    @api.model
    def configure_unpaid_leave_salary_rule(self):
        """Keep the unpaid deduction immediately after Staff Salary."""
        unpaid = self.env.ref(
            "gs_hr_attendance_sheet.gs_unpaid_leave", raise_if_not_found=False
        )
        if not unpaid:
            return
        staff = self.search([
            ("name", "ilike", "Staff Salary"),
            ("struct_id", "=", unpaid.struct_id.id),
        ], order="sequence, id", limit=1)
        values = {
            "name": "Unpaid Leave Salary",
            "code": "UNPAID_LEAVE",
        }
        if staff:
            values["sequence"] = staff.sequence + 1
        unpaid.write(values)
