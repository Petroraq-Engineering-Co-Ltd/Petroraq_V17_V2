# -*- coding: utf-8 -*-

from odoo import http, fields
from odoo.http import request
from odoo.exceptions import AccessError, ValidationError, UserError
from odoo.tools import format_date
from datetime import datetime
from werkzeug.exceptions import NotFound
import base64

from odoo.addons.de_hr_workspace.controllers.portal_employee import require_current_employee


class LeaveRequestTemplate(http.Controller):
    def _ensure_portal_creation_allowed(self):
        user = request.env.user
        if user.has_group('base.group_portal') and not user.has_group('base.group_user'):
            raise AccessError("Portal users are not allowed to create leave requests.")

    @http.route('/leave_request', auth='user', type='http')
    def display_leave_request_form(self, **kw):
        self._ensure_portal_creation_allowed()

        current_employee_id = require_current_employee()
        email = current_employee_id.work_email
        return http.request.render('de_hr_workspace_timeoff.leave_request_template', {
            "current_employee_id": current_employee_id,
            "employee_email": email,
            "company_name": current_employee_id.company_id.name,
            "form_values": {},
            "error_message": False,
        })

    @http.route('/leave_request/create', type='http', auth="user")
    def leave_created(self, **kw):
        self._ensure_portal_creation_allowed()
        current_employee_id = require_current_employee()
        employee_id = current_employee_id.id
        leave_type_id = int(kw.get('leave_type_id'))
        str_date_from = kw.get('date_from')
        str_date_to = kw.get('date_to')
        date_from = datetime.strptime(str_date_from, "%Y-%m-%d").date()
        date_to = datetime.strptime(str_date_to, "%Y-%m-%d").date()
        employee_obj = request.env['hr.employee'].sudo().browse(employee_id)
        leave_type_obj = request.env['hr.leave.type'].sudo().browse(leave_type_id)
        notes = kw.get('message') if kw.get('message') else False
        try:
            with request.env.cr.savepoint():
                leave_request_id = request.env['pr.hr.leave.request'].sudo().create({
                    'employee_id': employee_id,
                    'leave_type_id': leave_type_id,
                    'date_from': date_from,
                    'date_to': date_to,
                    'note': notes if notes else False,
                    'company_id': employee_obj.company_id.id if employee_obj.company_id else request.env.company.id,
                    # employee_manager_id / hr_supervisor_ids / hr_manager_ids are
                    # set by create() and action_submit() (active users, request company).
                })
                leave_request_id.with_user(request.env.user).action_submit()
        except (ValidationError, UserError) as ex:
            current_user = request.env.user
            current_employee_id = request.env["hr.employee"].sudo().search([("user_id", "=", current_user.id)], limit=1)
            return http.request.render('de_hr_workspace_timeoff.leave_request_template', {
                "current_employee_id": current_employee_id,
                "employee_email": current_employee_id.work_email,
                "company_name": current_employee_id.company_id.name,
                "form_values": kw,
                "error_message": str(ex),
            })
        if leave_request_id:
            # Create Attachments And Add Them To Leave Request
            attachment_ids = []
            attachment_list = request.httprequest.files.getlist('attachment_ids')
            for att in attachment_list:
                if kw.get('attachment_ids'):
                    attachments = {
                        'res_name': att.filename,
                        'res_model': 'pr.hr.leave.request',
                        'res_id': leave_request_id.sudo().id,
                        'datas': base64.encodebytes(att.read()),
                        'type': 'binary',
                        'name': att.filename,
                    }
                    attachment_obj = http.request.env['ir.attachment']
                    att_record = attachment_obj.sudo().create(attachments)
                    attachment_ids.append(att_record.id)
            # if attachment_ids:
            #     leave_request_id.update({'attachment_ids': [(6, 0, attachment_ids)]})
            return http.request.render('de_hr_workspace_timeoff.thanks_template')
        else:
            print(kw, 'False')
            return False

    @http.route(['/get_dashboard_data'], type='json', auth="user")
    def get_dashboard_data(self):
        today = fields.Date.today()
        current_user = request.env.user
        current_employee_id = request.env["hr.employee"].sudo().search(
            [("user_id", "=", current_user.id), ("active", "=", True)], limit=1)
        summary = []
        if current_employee_id:
            LeaveDashboard = request.env["hr.leave"].sudo()
            leave_type_ids = request.env["hr.leave.type"].sudo().search(
                ["|", ("company_id", "=", request.env.company.id), ("company_id", "=", False)])
            summary = [
                row for row in LeaveDashboard._de_get_leave_balance_summary(current_employee_id, leave_type_ids)
                if row["allocation_days"] > 0
            ]

            leaves_history = request.env["hr.leave"].sudo().search([
                ('employee_id', '=', current_employee_id.id)
            ], limit=5, order='request_date_from asc')

            all_leaves = [{
                'employee': l.employee_id.name,
                'leave_type': l.holiday_status_id.name,
                'from': format_date(request.env, l.request_date_from),
                'to': format_date(request.env, l.request_date_to),
                'days': l.number_of_days_display,
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
            # } for l in request.env["hr.leave"].sudo().search([('state', 'in', ['draft', 'confirm', 'validate1'])], limit=5)]

            chart_data = {
                'labels': ['7 Dec', '8 Dec', '9 Dec', '10 Dec', '11 Dec', '12 Dec', '13 Dec'],
                'datasets': [
                    {
                        'label': 'Emergency Leave',
                        'data': [4, 3, 2, 1, 5, 2, 3],
                        'backgroundColor': 'rgba(255, 99, 132, 0.6)',
                    },
                    {
                        'label': 'Annual Leave',
                        'data': [6, 5, 4, 3, 7, 5, 4],
                        'backgroundColor': 'rgba(54, 162, 235, 0.6)',
                    },
                ]
            }

            return {
                'summary': summary,
                'all_leaves': all_leaves,
                'pending': pending,
                'chart': chart_data,
            }
        return None
