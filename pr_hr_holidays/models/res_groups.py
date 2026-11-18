from odoo import api, fields, models, _


class ResGroups(models.Model):
    """

    """
    # region [Initial]
    _inherit = 'res.groups'
    # endregion [Initial]

    # region [Fields]

    # endregion

    @api.constrains("users")
    def _check_users_to_check_approvals(self):
        res = super()._check_users_to_check_approvals()
        hr_supervisor_group_id = self.env.ref('pr_hr.group_hr_supervisor', raise_if_not_found=False)
        hr_manager_group_id = self.env.ref('pr_hr.group_hr_manager', raise_if_not_found=False)
        LeaveRequest = self.env["pr.hr.leave.request"].sudo()
        for group in self:
            if hr_supervisor_group_id and group.id == hr_supervisor_group_id.id:
                leave_request_ids = LeaveRequest.search([("state", "in", ["draft", "manager_approve"])])
                for leave_request in leave_request_ids:
                    users = LeaveRequest._get_group_users_for_company(
                        "pr_hr.group_hr_supervisor", leave_request.company_id
                    )
                    leave_request.write({"hr_supervisor_ids": [(6, 0, users.ids)]})
            if hr_manager_group_id and group.id == hr_manager_group_id.id:
                leave_request_ids = LeaveRequest.search([
                    ("state", "in", ["draft", "manager_approve", "hr_supervisor", "cancel_request"])
                ])
                for leave_request in leave_request_ids:
                    users = LeaveRequest._get_group_users_for_company(
                        "pr_hr.group_hr_manager", leave_request.company_id
                    )
                    leave_request.write({"hr_manager_ids": [(6, 0, users.ids)]})
        return res
