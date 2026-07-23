from odoo import _, api, models
from odoo.osv import expression


class HrApprovalDashboardService(models.AbstractModel):
    _inherit = "de.hr.approval.dashboard.service"

    @api.model
    def _offboarding_pending_domain(self):
        """Return every offboarding stage the current user can approve."""
        user = self.env.user
        domains = [
            [
                ("state", "=", "submitted"),
                ("department_manager_user_id", "=", user.id),
            ]
        ]
        if user.has_group("hr.group_hr_manager"):
            domains.append([("state", "=", "hr_manager_approval")])
        if user.has_group("pr_hr_recruitment_request.group_onboarding_md"):
            domains.append([("state", "=", "md_approval")])
        return expression.OR(domains)

    @api.model
    def _override_domain_for_menu(self, menu, action, domain):
        if action.res_model == "pr.hr.offboarding.request":
            return self._offboarding_pending_domain()
        return super()._override_domain_for_menu(menu, action, domain)

    @api.model
    def _section_key_for_menu(self, menu, action):
        if (
            action
            and action._name == "ir.actions.act_window"
            and action.res_model == "pr.hr.offboarding.request"
        ):
            return "hr"
        return super()._section_key_for_menu(menu, action)

    @api.model
    def _dedupe_key_for_tile(self, section_key, menu, action, payload):
        if payload and payload.get("res_model") == "pr.hr.offboarding.request":
            return "hr|pr.hr.offboarding.request|pending-approvals"
        return super()._dedupe_key_for_tile(
            section_key, menu, action, payload
        )

    @api.model
    def _make_tile(self, section_key, menu, action):
        tile = super()._make_tile(section_key, menu, action)
        if tile.get("res_model") == "pr.hr.offboarding.request":
            tile.update({
                "name": _("Offboarding Approvals"),
                "icon": "fa-user-times",
                "tone": "warning",
            })
        return tile
