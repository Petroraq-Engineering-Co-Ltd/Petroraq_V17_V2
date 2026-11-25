# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import OrderedDict
from operator import itemgetter
from markupsafe import Markup

from odoo import conf, http, _
from odoo.exceptions import MissingError, UserError, ValidationError
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.addons.de_hr_workspace.controllers.portal_employee import require_current_employee
from odoo.tools import groupby as groupbyelem

from odoo.osv.expression import AND


class EmployeeShortageRequestsApprovalPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'my_shortage_request_approval_count' in counters:
            values['my_shortage_request_approval_count'] = request.env['pr.hr.shortage.request'].sudo().search_count(
                self._prepare_my_shortage_request_approval_domain()
            )
        return values

    def _prepare_my_shortage_request_approval_domain(self):
        # Same notion of a Dept. Manager as the model, restricted to the stage
        # the portal can decide.
        return AND([
            request.env['pr.hr.shortage.request']._get_pending_approval_domain(request.env.user),
            [("state", "=", "employee_manager_approval")],
        ])

    def _prepare_my_shortage_request_approval_searchbar_sortings(self):
        return {
            'date': {'label': _('Newest'), 'order': 'date desc'},
            'check_out': {'label': _('Oldest'), 'order': 'date asc'},
        }

    def _check_shortage_request_manager(self, shortage_request):
        if not shortage_request.exists() or not shortage_request._user_is_dept_manager(request.env.user):
            raise MissingError(_("This shortage request does not exist or you do not have access to it."))

    @http.route(['/my/shortage_requests_approval', '/my/shortage_requests_approval/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_shortage_requests_approval(self, page=1, date_begin=None, date_end=None, sortby=None, **kw):
        require_current_employee()
        values = self._prepare_portal_layout_values()
        ShortageRequestApproval = request.env['pr.hr.shortage.request'].sudo()
        domain = self._prepare_my_shortage_request_approval_domain()

        searchbar_sortings = self._prepare_my_shortage_request_approval_searchbar_sortings()
        if not sortby:
            sortby = 'date'
        order = searchbar_sortings[sortby]['order']

        if date_begin and date_end:
            domain += [('date', '>', date_begin), ('date', '<=', date_end)]

        # projects count
        shortage_request_approval_count = ShortageRequestApproval.search_count(domain)
        # pager
        pager = portal_pager(
            url="/my/shortage_requests_approval",
            url_args={'date_begin': date_begin, 'date_end': date_end, 'sortby': sortby},
            total=shortage_request_approval_count,
            page=page,
            step=self._items_per_page
        )

        # content according to pager and archive selected
        shortage_requests_approvals = ShortageRequestApproval.search(domain, order=order, limit=self._items_per_page, offset=pager['offset'])
        request.session['my_shortage_requests_approvals_history'] = shortage_requests_approvals.ids[:100]

        values.update({
            'date': date_begin,
            'date_end': date_end,
            'shortage_requests_approvals': shortage_requests_approvals,
            'page_name': 'shortage',
            'default_url': '/my/shortage_requests_approval',
            'pager': pager,
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby
        })
        return request.render("de_hr_workspace_attendance.portal_my_shortage_requests_approvals", values)

    @http.route(['/my/shortage_requests_approval/<int:request_id>'], type='http', auth="user", website=True)
    def portal_my_shortage_request_approval_info(self, request_id, error=None, **kw):
        shortage_request = self._get_managed_shortage_request(request_id)
        error_messages = {
            'reject_reason_required': _("Please provide a reason for the rejection."),
        }
        values = {
            "shortage_request": shortage_request,
            "tz_name": shortage_request.employee_id.tz or "Asia/Riyadh",
            "error_message": error_messages.get(error) or request.session.pop('shortage_request_error', False),
            "page_name": "shortage_request_approval",
        }
        return request.render("de_hr_workspace_attendance.portal_shortage_request_approval_page", values)

    # The decision routes change workflow state: POST only, CSRF protected
    # (default for type='http' routes), and always delegated to the model's
    # action methods, which check the current user's rights.

    def _get_managed_shortage_request(self, request_id):
        # sudo (portal managers only have read access) keeps the current user
        shortage_request = request.env["pr.hr.shortage.request"].sudo().browse(request_id)
        self._check_shortage_request_manager(shortage_request)
        return shortage_request

    def _decide(self, shortage_request, method, *args):
        try:
            with request.env.cr.savepoint():
                getattr(shortage_request, method)(*args)
        except (UserError, ValidationError) as ex:
            request.session['shortage_request_error'] = str(ex)
            return request.redirect('/my/shortage_requests_approval/%s' % shortage_request.id)
        return request.redirect('/my/shortage_requests_approval')

    @http.route(['/my/shortage_requests_approved/<int:request_id>'], type='http',
                auth="user", methods=['POST'], website=True)
    def portal_my_shortage_request_approved(self, request_id, **kw):
        return self._decide(self._get_managed_shortage_request(request_id), 'action_manager_approve')

    @http.route(['/my/shortage_requests_rejected/<int:request_id>'], type='http',
                auth="user", methods=['POST'], website=True)
    def portal_my_shortage_request_rejected(self, request_id, reject_reason=None, **kw):
        shortage_request = self._get_managed_shortage_request(request_id)
        reject_reason = (reject_reason or '').strip()
        if not reject_reason:
            return request.redirect(
                '/my/shortage_requests_approval/%s?error=reject_reason_required' % shortage_request.id
            )
        # Same path as pr.reject.record.wizard.action_reject for shortage requests.
        return self._decide(shortage_request, '_apply_stage_rejection', 'manager', reject_reason)

    @http.route(['/my/shortage_requests_reset_rejection/<int:request_id>'], type='http',
                auth="user", methods=['POST'], website=True)
    def portal_my_shortage_request_reset_rejection(self, request_id, **kw):
        return self._decide(self._get_managed_shortage_request(request_id), 'action_reset_rejection')
