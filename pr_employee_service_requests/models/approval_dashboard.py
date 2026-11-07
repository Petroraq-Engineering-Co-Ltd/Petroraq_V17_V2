# -*- coding: utf-8 -*-
from odoo import api, models
from odoo.osv import expression
from odoo.tools.safe_eval import safe_eval


class HrApprovalDashboardService(models.AbstractModel):
    _inherit = "de.hr.approval.dashboard.service"

    @api.model
    def _service_request_pending_domain(self, menu=None, action=None, domain=None):
        """Construct the combined approval domain for pr.employee.service.request across
        all roles the user holds, preserving any specific category/request-type criteria from the action domain."""
        user = self.env.user
        roles = self.env["pr.employee.service.request"]._get_user_service_request_roles(user)

        domain_list = []
        if "md" in roles:
            domain_list.append([("state", "=", "md_approval")])
        if "finance" in roles:
            domain_list.append([
                ("state", "=", "finance_approval"),
                ("payment_responsibility", "!=", "self"),
            ])
        if "accounts" in roles:
            domain_list.append([
                ("state", "=", "accounts_approval"),
                ("payment_responsibility", "!=", "self"),
            ])
        if "hr_manager" in roles:
            domain_list.append([("state", "=", "hr_manager_approval")])
        if "hr_supervisor" in roles:
            domain_list.append([("state", "=", "hr_supervisor_approval")])
        if "employee_manager" in roles:
            domain_list.append([
                ("state", "=", "employee_manager_approval"),
                ("employee_manager_user_id", "=", user.id),
            ])

        if not domain_list:
            return [("id", "=", 0)]

        state_domain = expression.OR(domain_list)

        parsed_domain = domain
        if isinstance(parsed_domain, str):
            try:
                parsed_domain = safe_eval(parsed_domain)
            except Exception:
                parsed_domain = []

        extra_domain = []
        if parsed_domain and isinstance(parsed_domain, (list, tuple)):
            for leaf in parsed_domain:
                if (
                    isinstance(leaf, (list, tuple))
                    and len(leaf) == 3
                    and leaf[0] not in (
                        "state",
                        "is_current_user_service_request_approver",
                        "is_current_user_financial_approver",
                    )
                ):
                    extra_domain.append(tuple(leaf))

        if extra_domain:
            return expression.AND([extra_domain, state_domain])
        return state_domain

    @api.model
    def _override_domain_for_menu(self, menu, action, domain):
        if action and getattr(action, "res_model", False) == "pr.employee.service.request":
            return self._service_request_pending_domain(menu=menu, action=action, domain=domain)
        return super()._override_domain_for_menu(menu, action, domain)
