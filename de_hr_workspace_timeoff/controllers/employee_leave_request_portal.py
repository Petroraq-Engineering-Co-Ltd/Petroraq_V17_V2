# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import OrderedDict
from operator import itemgetter
from markupsafe import Markup

from odoo import conf, http, _
from odoo.exceptions import AccessError, MissingError
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.addons.de_hr_workspace.controllers.portal_employee import (
    employee_portal_count,
    require_current_employee,
)
from odoo.tools import groupby as groupbyelem

from odoo.osv.expression import OR, AND


class EmployeeLeaveRequestPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'my_leave_request_count' in counters:
            values['my_leave_request_count'] = employee_portal_count(
                'pr.hr.leave.request',
                self._prepare_my_leave_requests_domain(),
            )
        return values

    def _prepare_my_leave_requests_domain(self):
        return [("employee_id.user_id", "=", request.env.user.id)]

    def _prepare_my_leave_requests_searchbar_sortings(self):
        return {
            'date_from': {'label': _('Newest'), 'order': 'date_from desc'},
            'date_to': {'label': _('Oldest'), 'order': 'date_from asc'},
        }

    @http.route(['/my/leave_requests', '/my/leave_requests/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_leave_requests(self, page=1, date_begin=None, date_end=None, sortby=None, **kw):
        require_current_employee()
        values = self._prepare_portal_layout_values()
        LeaveRequest = request.env['pr.hr.leave.request'].sudo()
        domain = self._prepare_my_leave_requests_domain()

        searchbar_sortings = self._prepare_my_leave_requests_searchbar_sortings()
        if not sortby:
            sortby = 'date_from'
        order = searchbar_sortings[sortby]['order']

        if date_begin and date_end:
            domain += [('date_from', '>', date_begin), ('date_from', '<=', date_end)]

        # projects count
        leave_request_count = LeaveRequest.search_count(domain)
        # pager
        pager = portal_pager(
            url="/my/leave_requests",
            url_args={'date_begin': date_begin, 'date_end': date_end, 'sortby': sortby},
            total=leave_request_count,
            page=page,
            step=self._items_per_page
        )

        # content according to pager and archive selected
        leave_requests = LeaveRequest.search(domain, order=order, limit=self._items_per_page, offset=pager['offset'])
        request.session['my_leave_requests_history'] = leave_requests.ids[:100]

        values.update({
            'date': date_begin,
            'date_end': date_end,
            'leave_requests': leave_requests,
            'page_name': 'leave_request',
            'default_url': '/my/leave_requests',
            'pager': pager,
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby
        })
        return request.render("de_hr_workspace_timeoff.portal_my_leave_requests", values)
