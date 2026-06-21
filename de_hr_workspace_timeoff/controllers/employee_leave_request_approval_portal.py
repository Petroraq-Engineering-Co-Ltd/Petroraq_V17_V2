# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import OrderedDict
from operator import itemgetter
from markupsafe import Markup

from odoo import conf, http, _
from odoo.exceptions import AccessError, MissingError
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.addons.de_hr_workspace.controllers.portal_employee import require_current_employee
from odoo.tools import groupby as groupbyelem

from odoo.osv.expression import OR, AND


class EmployeeLeaveRequestsApprovalPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'my_leave_request_approval_count' in counters:
            values['my_leave_request_approval_count'] = request.env['pr.hr.leave.request'].search_count(
                self._prepare_my_leave_request_approval_domain()
            )
        return values

    def _prepare_my_leave_request_approval_domain(self):
        return AND([
            [("employee_manager_id.user_id", "=", request.env.user.id)],
            OR([
                [("state", "=", "draft")],
                [
                    ("state", "=", "reject"),
                    ("rejected_stage", "=", "manager"),
                ],
            ]),
        ])

    def _prepare_my_leave_request_approval_searchbar_sortings(self):
        return {
            'date_from': {'label': _('Newest'), 'order': 'date_from desc'},
            'date_to': {'label': _('Oldest'), 'order': 'date_from asc'},
        }

    def _check_leave_request_manager(self, leave_request):
        if leave_request.employee_manager_id.user_id != request.env.user:
            raise MissingError(_("This leave request does not exist or you do not have access to it."))

    @http.route(['/my/leave_requests_approval', '/my/leave_requests_approval/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_leave_requests_approval(self, page=1, date_begin=None, date_end=None, sortby=None, **kw):
        require_current_employee()
        values = self._prepare_portal_layout_values()
        LeaveRequestApproval = request.env['pr.hr.leave.request'].sudo()
        domain = self._prepare_my_leave_request_approval_domain()

        searchbar_sortings = self._prepare_my_leave_request_approval_searchbar_sortings()
        if not sortby:
            sortby = 'date_from'
        order = searchbar_sortings[sortby]['order']

        if date_begin and date_end:
            domain += [('date_from', '>', date_begin), ('date_from', '<=', date_end)]

        # projects count
        leave_request_approval_count = LeaveRequestApproval.search_count(domain)
        # pager
        pager = portal_pager(
            url="/my/leave_requests_approval",
            url_args={'date_begin': date_begin, 'date_end': date_end, 'sortby': sortby},
            total=leave_request_approval_count,
            page=page,
            step=self._items_per_page
        )

        # content according to pager and archive selected
        leave_requests_approvals = LeaveRequestApproval.search(domain, order=order, limit=self._items_per_page, offset=pager['offset'])
        request.session['my_leave_requests_approvals_history'] = leave_requests_approvals.ids[:100]

        values.update({
            'date': date_begin,
            'date_end': date_end,
            'leave_requests_approvals': leave_requests_approvals,
            'page_name': 'leave_request_approval',
            'default_url': '/my/leave_requests_approval',
            'pager': pager,
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby
        })
        return request.render("de_hr_workspace_timeoff.portal_my_leave_requests_approvals", values)

    @http.route(['/my/leave_requests_approval/<model("pr.hr.leave.request"):leave_request_id>'], type='http', auth="user", website=True)
    def portal_my_leave_request_approval_info(self, leave_request_id, **kw):
        leave_request_obj = request.env["pr.hr.leave.request"].sudo().browse(int(leave_request_id))
        self._check_leave_request_manager(leave_request_obj)
        values = {"leave_request_id": leave_request_obj}
        return request.render("de_hr_workspace_timeoff.employee_leave_request_approval_info_portal", values)

    @http.route(['/my/leave_requests_approved/<model("pr.hr.leave.request"):leave_request_id>'], type='http',
                auth="user", website=True)
    def portal_my_leave_request_approved(self, leave_request_id, **kw):
        leave_request_obj = request.env["pr.hr.leave.request"].sudo().browse(int(leave_request_id))
        self._check_leave_request_manager(leave_request_obj)
        if leave_request_obj.state != 'draft':
            raise MissingError(_("This leave request is not awaiting your approval."))
        leave_request_obj.with_user(request.env.user).action_manager_approve()
        return request.redirect('/my/leave_requests_approval')

    @http.route(['/my/leave_requests_rejected/<model("pr.hr.leave.request"):leave_request_id>'], type='http',
                auth="user", website=True)
    def portal_my_leave_request_rejected(self, leave_request_id, **kw):
        leave_request_obj = request.env["pr.hr.leave.request"].sudo().browse(int(leave_request_id))
        self._check_leave_request_manager(leave_request_obj)
        leave_request_obj.with_user(request.env.user)._apply_stage_rejection(
            'manager',
            _("Rejected from the employee portal."),
        )
        return request.redirect('/my/leave_requests_approval')

    @http.route(['/my/leave_requests_reset_rejection/<model("pr.hr.leave.request"):leave_request_id>'], type='http',
                auth="user", website=True)
    def portal_my_leave_request_reset_rejection(self, leave_request_id, **kw):
        leave_request_obj = request.env["pr.hr.leave.request"].sudo().browse(int(leave_request_id))
        self._check_leave_request_manager(leave_request_obj)
        leave_request_obj.with_user(request.env.user).action_reset_rejection()
        return request.redirect('/my/leave_requests_approval')
