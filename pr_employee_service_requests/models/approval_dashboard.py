# -*- coding: utf-8 -*-
from odoo import api, models
from odoo.osv import expression
from odoo.tools.safe_eval import safe_eval


class HrApprovalDashboardService(models.AbstractModel):
    _inherit = "de.hr.approval.dashboard.service"

    @api.model
    def _service_request_pending_domain(self, menu=None, action=None, domain=None):
        """Construct the strict single primary role approval domain for pr.employee.service.request,
        preserving any specific category/request-type criteria from the action domain."""
        user = self.env.user
        role = self.env["pr.employee.service.request"]._get_user_primary_service_request_role(user)

        if role == "md":
            state_domain = [("state", "=", "md_approval")]
        elif role == "finance":
            state_domain = [
                ("state", "=", "finance_approval"),
                ("payment_responsibility", "!=", "self"),
            ]
        elif role == "accounts":
            state_domain = [
                ("state", "=", "accounts_approval"),
                ("payment_responsibility", "!=", "self"),
            ]
        elif role == "hr_manager":
            state_domain = [("state", "=", "hr_manager_approval")]
        elif role == "hr_supervisor":
            state_domain = [("state", "=", "hr_supervisor_approval")]
        elif role == "employee_manager":
            state_domain = [
                ("state", "=", "employee_manager_approval"),
                ("employee_manager_user_id", "=", user.id),
            ]
        else:
            return [("id", "=", 0)]

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
