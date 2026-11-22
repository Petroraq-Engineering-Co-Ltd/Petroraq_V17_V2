from odoo import models, api
from odoo.osv import expression


class HrLeaveRequest(models.Model):
    _inherit = 'pr.hr.leave.request'

    # region [System Methods]

    @api.model
    def search_fetch(self, domain, field_names, offset=0, limit=None, order=None):
        user = self.env.user
        view_action_id = self.env.ref(
            "de_hr_workspace_timeoff.action_my_leave_request_approvals",
            raise_if_not_found=False,
        )
        approvals_of_leave_request = self.env.context.get("approvals_of_leave_request")
        params = self.env.context.get("params")
        action_id = params.get("action") if params else False
        domain = list(domain or [])
        if approvals_of_leave_request or (
            view_action_id and action_id and action_id == view_action_id.id
        ):
            role_domain = self._get_pending_approval_domain(user)
            domain = expression.AND([domain, role_domain]) if domain else role_domain
        return super().search_fetch(domain, field_names, offset, limit, order)

    # endregion [System Methods]
