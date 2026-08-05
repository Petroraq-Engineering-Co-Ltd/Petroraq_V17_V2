from odoo import _, api, fields, models


class HrLeaveAbsenteeDetail(models.TransientModel):
    _name = "de.hr.leave.absentee.detail"
    _description = "Employee Absentee Detail"
    _order = "absence_date desc, employee_id"

    absence_date = fields.Date(string="Date", required=True, readonly=True)
    day_name = fields.Char(string="Day", readonly=True)
    employee_id = fields.Many2one("hr.employee", required=True, readonly=True)
    employee_code = fields.Char(string="Employee ID", readonly=True)
    department = fields.Char(readonly=True)
    job_position = fields.Char(string="Job Position", readonly=True)
    first_check_in = fields.Char(string="First Check In", readonly=True)
    reason = fields.Char(readonly=True)
    expected_shift = fields.Char(string="Expected Shift", readonly=True)

    @api.model
    def action_open_employee_absentees(
        self,
        employee_id,
        duration="current_contract",
        date_from=False,
        date_to=False,
    ):
        details = self.env["hr.leave"].with_context(
            show_all_leave_dashboard=True
        ).get_employee_absentee_day_details(
            employee_id,
            duration,
            date_from,
            date_to,
        )
        self.search([("create_uid", "=", self.env.user.id)]).unlink()
        records = self.create([
            {
                "absence_date": row.get("date"),
                "day_name": row.get("day_name"),
                "employee_id": row.get("employee_id") or employee_id,
                "employee_code": row.get("employee_code"),
                "department": row.get("department"),
                "job_position": row.get("job_position"),
                "first_check_in": row.get("check_in"),
                "reason": row.get("reason"),
                "expected_shift": row.get("shift"),
            }
            for row in details.get("rows", [])
        ])
        tree_view = self.env.ref(
            "de_hr_workspace_leave_management.view_hr_leave_absentee_detail_tree"
        )
        form_view = self.env.ref(
            "de_hr_workspace_leave_management.view_hr_leave_absentee_detail_form"
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Absentees: %(employee)s (%(start)s - %(end)s)") % {
                "employee": details.get("employee_name") or _("Employee"),
                "start": details.get("date_from_display") or details.get("date_from") or "",
                "end": details.get("date_to_display") or details.get("date_to") or "",
            },
            "res_model": "de.hr.leave.absentee.detail",
            "view_mode": "tree,form",
            "views": [(tree_view.id, "tree"), (form_view.id, "form")],
            "domain": [("id", "in", records.ids)],
            "context": {"create": False, "edit": False, "delete": False},
            "target": "current",
        }
