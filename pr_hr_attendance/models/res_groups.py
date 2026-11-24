from odoo import api, models

from .hr_shortage_request import APPROVAL_STATES, HR_MANAGER_GROUP, HR_SUPERVISOR_GROUP


class ResGroups(models.Model):
    """

    """
    # region [Initial]
    _inherit = 'res.groups'
    # endregion [Initial]

    @api.constrains("users")
    def _check_users_to_check_approvals(self):
        res = super()._check_users_to_check_approvals()
        ShortageRequest = self.env["pr.hr.shortage.request"].sudo()
        for xmlid, field_name in (
            (HR_SUPERVISOR_GROUP, "hr_supervisor_ids"),
            (HR_MANAGER_GROUP, "hr_manager_ids"),
        ):
            if self.env.ref(xmlid) not in self:
                continue
            for request in ShortageRequest.search([("state", "in", ("draft", *APPROVAL_STATES))]):
                users = ShortageRequest._get_group_users_for_company(xmlid, request.company_id)
                request.write({field_name: [(6, 0, users.ids)]})
        return res
