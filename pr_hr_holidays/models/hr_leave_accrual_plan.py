from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrLeaveAccrualPlan(models.Model):
    _inherit = "hr.leave.accrual.plan"

    pr_annual_earning_limit = fields.Boolean(string="Service-year earning limit")
    pr_annual_entitlement = fields.Float(string="Annual entitlement (days)", default=21)
    pr_earning_days = fields.Integer(string="Calendar days to earn entitlement", default=330)

    @api.constrains("pr_annual_earning_limit", "pr_annual_entitlement", "pr_earning_days")
    def _check_pr_annual_settings(self):
        for plan in self.filtered("pr_annual_earning_limit"):
            if plan.pr_annual_entitlement <= 0 or not 1 <= plan.pr_earning_days <= 365:
                raise ValidationError(_("Enter a positive entitlement and an earning period from 1 to 365 days."))

    def write(self, vals):
        policy_fields = {
            "pr_annual_earning_limit", "pr_annual_entitlement", "pr_earning_days",
            "accrued_gain_time",
        }
        for plan in self:
            changed = any(key in vals and vals[key] != plan[key] for key in policy_fields)
            if changed and (plan.pr_annual_earning_limit or vals.get("pr_annual_earning_limit")):
                if self.env["hr.leave.allocation"].sudo().search_count([
                    ("accrual_plan_id", "=", plan.id), ("state", "!=", "refuse"),
                ]):
                    raise ValidationError(_(
                        "This plan already has allocations. Create a new plan for the new policy "
                        "and reconcile existing allocations before assigning it."
                    ))
        return super().write(vals)
