from odoo import api, models
from odoo.osv import expression


class HrApprovalDashboardService(models.AbstractModel):
    _inherit = "de.hr.approval.dashboard.service"

    @api.model
    def _eos_pending_domain(self):
        user = self.env.user
        domains = []
        if user.has_group("hr.group_hr_manager"):
            domains.append([("state", "=", "hr_approval")])
        if user.has_group("pr_hr_recruitment_request.group_onboarding_md"):
            domains.append([("state", "=", "md_approval")])
        if (
            user.has_group("account.group_account_manager")
            or user.has_group("pr_account.custom_group_accounting_manager")
        ):
            domains.append([("state", "=", "accounts_approval")])
        if user.has_group("hr.group_hr_user"):
            domains.append([("state", "in", ["draft", "employee_acceptance"])])
        return expression.OR(domains) if domains else [("id", "=", False)]

    @api.model
    def _override_domain_for_menu(self, menu, action, domain):
        if action.res_model == "pr.end.of.service":
            return self._eos_pending_domain()
        return super()._override_domain_for_menu(menu, action, domain)

    @api.model
    def _section_key_for_menu(self, menu, action):
        if (
            action
            and action._name == "ir.actions.act_window"
            and action.res_model == "pr.end.of.service"
        ):
            return "hr"
        return super()._section_key_for_menu(menu, action)
