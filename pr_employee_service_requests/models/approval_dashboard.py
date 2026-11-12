# -*- coding: utf-8 -*-
from odoo import _, api, models
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
                ("exit_reentry_historical_company_paid", "=", False),
            ])
        if "accounts" in roles:
            domain_list.append([
                ("state", "=", "accounts_approval"),
                ("payment_responsibility", "!=", "self"),
                ("exit_reentry_historical_company_paid", "=", False),
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
        if action and getattr(action, "res_model", False) == "pr.employee.document.letter":
            return self._document_letter_pending_domain(menu=menu, action=action, domain=domain)
        return super()._override_domain_for_menu(menu, action, domain)

    @api.model
    def _document_letter_pending_domain(self, menu=None, action=None, domain=None):
        user = self.env.user
        roles = self.env["pr.employee.document.letter"]._get_user_document_letter_roles(user)

        domain_list = []
        if "hr_manager" in roles:
            domain_list.append([("state", "=", "hr_manager_approval")])
        if "department_manager" in roles:
            domain_list.append([
                ("state", "=", "department_manager_approval"),
                ("department_manager_user_id", "=", user.id),
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
                        "is_current_user_document_letter_approver",
                    )
                ):
                    extra_domain.append(tuple(leaf))

        if extra_domain:
            return expression.AND([extra_domain, state_domain])
        return state_domain

    @api.model
    def _get_employee_service_sub_tiles(self):
        service_configs = [
            {
                "key": "sub_reimbursement",
                "name": _("Reimbursement Requests"),
                "category_domain": [("request_type", "=", "reimbursement")],
                "action_xmlid": "pr_employee_service_requests.action_pr_employee_reimbursement_hr_approvals",
                "icon": "fa-money",
                "tone": "info",
                "res_model": "pr.employee.service.request",
            },
            {
                "key": "sub_exit_reentry",
                "name": _("Exit/Re-entry Requests"),
                "category_domain": [("request_type", "=", "exit_reentry")],
                "action_xmlid": "pr_employee_service_requests.action_pr_employee_exit_reentry_hr_approvals",
                "icon": "fa-plane",
                "tone": "primary",
                "res_model": "pr.employee.service.request",
            },
            {
                "key": "sub_iqama",
                "name": _("Iqama & Work Permit Requests"),
                "category_domain": [("request_type", "in", ["iqama_new", "iqama_renewal"])],
                "action_xmlid": "pr_employee_service_requests.action_pr_employee_iqama_new_hr_approvals",
                "icon": "fa-id-card-o",
                "tone": "warning",
                "res_model": "pr.employee.service.request",
            },
            {
                "key": "sub_medical",
                "name": _("Medical Insurance Requests"),
                "category_domain": [("request_type", "in", ["medical_insurance_new", "medical_insurance_renewal"])],
                "action_xmlid": "pr_employee_service_requests.action_pr_employee_medical_insurance_new_hr_approvals",
                "icon": "fa-medkit",
                "tone": "danger",
                "res_model": "pr.employee.service.request",
            },
            {
                "key": "sub_dependent",
                "name": _("Dependent Fee Requests"),
                "category_domain": [("request_type", "=", "dependent_fee")],
                "action_xmlid": "pr_employee_service_requests.action_pr_employee_dependent_fee_hr_approvals",
                "icon": "fa-users",
                "tone": "success",
                "res_model": "pr.employee.service.request",
            },
        ]

        sub_tiles = []
        for cfg in service_configs:
            action = self.env.ref(cfg["action_xmlid"], raise_if_not_found=False)
            domain = self._service_request_pending_domain(domain=cfg["category_domain"])
            records = self.env["pr.employee.service.request"].search(domain)
            tile_context = dict(self._context_from_action(action) if action else {})
            tile_context["from_approval_dashboard"] = True
            sub_tiles.append({
                "key": cfg["key"],
                "name": cfg["name"],
                "count": len(records),
                "icon": cfg["icon"],
                "tone": cfg["tone"],
                "action_id": action.id if action else False,
                "res_model": cfg["res_model"],
                "view_mode": (action.view_mode if action else False) or "list,form",
                "domain": [("id", "in", records.ids)],
                "context": tile_context,
                "_ids": set(records.ids),
            })

        # 6. Employee Document Letters
        letter_action = self.env.ref("pr_employee_service_requests.action_pr_employee_document_letter_hr_approvals", raise_if_not_found=False)
        letter_domain = self._document_letter_pending_domain()
        letter_records = self.env["pr.employee.document.letter"].search(letter_domain)
        letter_context = dict(self._context_from_action(letter_action) if letter_action else {})
        letter_context["from_approval_dashboard"] = True
        sub_tiles.append({
            "key": "sub_letters",
            "name": _("Employee Letters"),
            "count": len(letter_records),
            "icon": "fa-file-text-o",
            "tone": "primary",
            "action_id": letter_action.id if letter_action else False,
            "res_model": "pr.employee.document.letter",
            "view_mode": (letter_action.view_mode if letter_action else False) or "list,form",
            "domain": [("id", "in", letter_records.ids)],
            "context": letter_context,
            "_ids": set(letter_records.ids),
        })

        return sub_tiles

    @api.model
    def get_sections(self):
        sections = super().get_sections()
        exclude_models = {"pr.employee.service.request", "pr.employee.document.letter"}
        financial_action = self.env.ref(
            "pr_employee_service_requests.action_pr_employee_accounts_approvals",
            raise_if_not_found=False,
        )
        financial_action_id = financial_action.id if financial_action else False

        # Remove loose service-request and document-letter tiles from all
        # auto-discovered sections (including Accounts, where the menu item
        # stays available in the top navbar), and drop any non-HR sections
        # that become empty as a result.
        cleaned_sections = []
        for section in sections:
            tiles = [
                t for t in section.get("tiles", [])
                if t.get("res_model") not in exclude_models
                and (not financial_action_id or t.get("action_id") != financial_action_id)
            ]
            if len(tiles) != len(section.get("tiles", [])):
                section = dict(section, tiles=tiles)
                section["count"] = sum(t.get("count", 0) for t in tiles)
            if tiles or section.get("key") == "hr":
                cleaned_sections.append(section)
        sections = cleaned_sections

        hr_section = next((s for s in sections if s["key"] == "hr"), None)
        if not hr_section:
            definition = self.APPROVAL_SECTIONS.get("hr", self.APPROVAL_SECTIONS["other"])
            hr_section = {
                "key": "hr",
                "name": definition["name"],
                "icon": definition["icon"],
                "tone": definition["tone"],
                "sequence": definition["sequence"],
                "count": 0,
                "tiles": [],
            }
            sections.append(hr_section)
            sections.sort(key=lambda s: (s["sequence"], s["name"]))

        sub_tiles = self._get_employee_service_sub_tiles()
        total_sub_count = sum(t.get("count", 0) for t in sub_tiles)
        filtered_tiles = list(hr_section.get("tiles", []))

        parent_action = self.env.ref(
            "pr_employee_service_requests.action_pr_employee_manager_approvals",
            raise_if_not_found=False,
        )

        all_service_ids = [
            rec_id
            for t in sub_tiles
            if t.get("res_model") == "pr.employee.service.request"
            for rec_id in t.get("_ids", set())
        ]

        employee_services_tile = {
            "key": "hr|pr.employee.service.request|employee_services",
            "name": _("Employee Service Requests"),
            "icon": "fa-id-badge",
            "tone": "primary",
            "count": total_sub_count,
            "action_id": parent_action.id if parent_action else False,
            "res_model": "pr.employee.service.request",
            "view_mode": "list,form",
            "domain": [("id", "in", sorted(all_service_ids))],
            "context": {"from_approval_dashboard": True},
            "sub_tiles": sub_tiles,
        }

        # Clean _ids from sub_tiles
        for st in sub_tiles:
            st.pop("_ids", None)

        filtered_tiles.append(employee_services_tile)
        filtered_tiles.sort(key=lambda item: (0 if item.get("count", 0) else 1, item["name"]))
        hr_section["tiles"] = filtered_tiles
        hr_section["count"] = sum(t.get("count", 0) for t in filtered_tiles)

        return sections
