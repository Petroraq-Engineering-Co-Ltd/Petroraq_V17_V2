# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import OrderedDict
from operator import itemgetter
from markupsafe import Markup

from odoo import conf, http, _, fields
from odoo.exceptions import AccessError, MissingError
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.addons.de_hr_workspace.controllers.portal_employee import (
    get_current_employee,
    require_current_employee,
)
from odoo.tools import format_date, groupby as groupbyelem

from odoo.osv.expression import OR, AND


class EmployeeLeaveDashboardPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'my_leave_dashboard_count' in counters:
            values['my_leave_dashboard_count'] = 1 if get_current_employee() else 0
        return values

    def _prepare_my_leaves_dashboard_domain(self):
        return [("employee_id.user_id", "=", request.env.user.id)]

    def _prepare_my_leaves_dashboard_searchbar_sortings(self):
        return {

        }

    @http.route(['/my/leaves_dashboard', '/my/leaves_dashboard/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_leaves_dashboard(self, page=1, date_begin=None, date_end=None, sortby=None, **kw):
        require_current_employee()
        values = self._prepare_portal_layout_values()
        LeaveDashboard = request.env['hr.leave'].sudo()
        domain = self._prepare_my_leaves_dashboard_domain()

        searchbar_sortings = self._prepare_my_leaves_dashboard_searchbar_sortings()
        # if not sortby:
        #     sortby = 'request_date_from'
        # order = searchbar_sortings[sortby]['order']

        # if date_begin and date_end:
        #     domain += [('request_date_from', '>', date_begin), ('request_date_from', '<=', date_end)]

        # projects count
        leave_dashboard_count = LeaveDashboard.search_count(domain)
        # pager
        pager = portal_pager(
            url="/my/leaves_dashboard",
            url_args={'date_begin': date_begin, 'date_end': date_end, 'sortby': sortby},
            total=leave_dashboard_count,
            page=page,
            step=self._items_per_page
        )

        # content according to pager and archive selected
        leaves_dashboard = LeaveDashboard.search(domain, limit=self._items_per_page, offset=pager['offset'])
        request.session['my_leaves_dashboard_history'] = leaves_dashboard.ids[:100]


        #######################################################

        today = fields.Date.today()
        current_user = request.env.user
        current_employee_id = request.env["hr.employee"].sudo().search(
            [("user_id", "=", current_user.id), ("active", "=", True)], limit=1)
        summary = []
        all_leaves = []
        pending = []
        taken_leaves = {}
        if current_employee_id:
            LeaveSummary = request.env["hr.leave"].sudo()
            leave_type_ids = request.env["hr.leave.type"].sudo().search(
                ["|", ("company_id", "=", request.env.company.id), ("company_id", "=", False)])
            balance_rows = LeaveSummary._de_get_leave_balance_summary(current_employee_id, leave_type_ids)
            summary = [row for row in balance_rows if row["allocation_days"] > 0]
            taken_leaves = {row["leave_name"]: row["taken_days"] for row in balance_rows}

            leaves_history = request.env["hr.leave"].sudo().search([
                ('employee_id', '=', current_employee_id.id)
            ], limit=5, order='request_date_from asc')

            status_labels = {
                'draft': 'To Submit',
                'confirm': 'To Approve',
                'validate1': 'Second Approval',
                'validate': 'Approved',
                'refuse': 'Refused',
                'cancel': 'Cancelled',
            }
            all_leaves = [{
                'employee': l.employee_id.name,
                'leave_type': l.holiday_status_id.name,
                'from': format_date(request.env, l.request_date_from),
                'to': format_date(request.env, l.request_date_to),
                'days': l.number_of_days_display,
                'status': status_labels.get(l.state, l.state),
            } for l in leaves_history]

            leave_req_model = request.env["pr.hr.leave.request"].sudo()
            state_labels = dict(leave_req_model._fields["state"].selection)
            pending = [{
                'employee': current_employee_id.name,
                'leave_type': l.leave_type_id.name,
                'from': format_date(request.env, l.date_from),
                'to': format_date(request.env, l.date_to),
                'days': (l.date_to - l.date_from).days + 1,
                'status': state_labels.get(l.state, l.state),
            } for l in leave_req_model.search([
                ("employee_id", "=", current_employee_id.id),
                ("state", "in", [
                    "employee_manager_approval",
                    "hr_supervisor_approval",
                    "hr_manager_approval",
                ]),
            ], limit=5)]

        values.update({
            'date': date_begin,
            'date_end': date_end,
            'leaves_dashboard_summary': summary,
            'leaves_dashboard_all_leaves': all_leaves,
            'leaves_dashboard_pending': pending,
            'leaves_dashboard_taken_leaves': taken_leaves,
            'page_name': 'leave_dashboard',
            'default_url': '/my/leaves_dashboard',
            'pager': pager,
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby
        })
        return request.render("de_hr_workspace_timeoff.portal_my_leaves_dashboard", values)
