from odoo import api, models
from odoo.osv import expression


class HrShortageRequest(models.Model):
    _inherit = 'pr.hr.shortage.request'

    # region [System Methods]

    @api.model
    def search_fetch(self, domain, field_names, offset=0, limit=None, order=None):
        view_action_id = self.env.ref(
            "de_hr_workspace_attendance.action_my_shortage_request_approvals",
            raise_if_not_found=False,
        )
        params = self.env.context.get("params")
        action_id = params.get("action") if params else False
        if self.env.context.get("approvals_of_shortage_request") or (
            view_action_id and action_id and action_id == view_action_id.id
        ):
            domain = expression.AND([domain or [], self._get_pending_approval_domain(self.env.user)])
        return super().search_fetch(domain, field_names, offset, limit, order)

    # endregion [System Methods]
