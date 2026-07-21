from odoo import api, models


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    @api.model
    def _qiwa_update_optional_workspace_compliance_entries(self):
        """Update workspace entries when an older database actually contains them."""
        supervisor = self.env.ref(
            "pr_hr_recruitment_request.group_onboarding_supervisor",
            raise_if_not_found=False,
        )
        manager = self.env.ref(
            "pr_hr_recruitment_request.group_onboarding_manager",
            raise_if_not_found=False,
        )
        md_group = self.env.ref(
            "pr_hr_recruitment_request.group_onboarding_md",
            raise_if_not_found=False,
        )

        groups = self.env["res.groups"]
        approval_groups = groups
        manager_groups = groups
        for group in (supervisor, manager, md_group):
            if group:
                approval_groups |= group
        for group in (manager, md_group):
            if group:
                manager_groups |= group

        menu_groups = {
            "de_hr_workspace.menu_my_employee_approvals": approval_groups,
            "de_hr_workspace.hr_approvals_menu_root": approval_groups,
            "de_hr_workspace.de_hr_workspace_hr_employee_iqama_approvals_menu": manager_groups,
            "de_hr_workspace.de_hr_workspace_hr_employee_medical_insurance_approvals_menu": manager_groups,
        }
        for xmlid, groups in menu_groups.items():
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if menu and groups:
                menu.sudo().write({"groups_id": [(4, group.id) for group in groups]})

        approval_domain = "[('state', 'in', ('pending_approval', 'hr_manager_approval', 'md_approval'))]"
        for xmlid in (
            "de_hr_workspace.de_hr_workspace_hr_employee_iqama_approvals_view_action",
            "de_hr_workspace.de_hr_workspace_hr_employee_medical_insurance_approvals_view_action",
        ):
            action = self.env.ref(xmlid, raise_if_not_found=False)
            if action:
                action.sudo().write({"domain": approval_domain})

        return True
