from odoo import fields, models, _


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    pr_eos_ids = fields.One2many(
        "pr.end.of.service",
        "employee_id",
        string="End of Service",
    )
    pr_eos_count = fields.Integer(
        string="End of Service Count",
        compute="_compute_pr_eos_count",
    )

    def _compute_pr_eos_count(self):
        for employee in self:
            employee.pr_eos_count = self.env["pr.end.of.service"].search_count([
                ("employee_id", "=", employee.id),
            ])

    def action_view_pr_eos(self):
        self.ensure_one()
        action = self.env.ref("pr_end_of_service.action_pr_end_of_service").read()[0]
        action["domain"] = [("employee_id", "=", self.id)]
        action["context"] = {
            "default_employee_id": self.id,
        }
        return action

    def set_out_of_service(self):
        res = super().set_out_of_service()
        service_end_date = self.env.context.get("pr_eos_service_end_date") or fields.Date.context_today(self)
        for employee in self:
            vals = {"state": "out_service"}
            if "active" in employee._fields:
                vals["active"] = True
            employee.write(vals)
            contract = employee.contract_id
            if contract:
                contract_vals = {
                    "date_end": service_end_date,
                }
                if "state" in contract._fields:
                    contract_vals["state"] = "cancel"
                contract.sudo().write(contract_vals)
            employee.message_post(
                body=_("Employee moved to Out-Service from end of service settlement.")
            )
        return res
