# -*- coding: utf-8 -*-

from odoo import fields, http
from odoo.http import request
from odoo.exceptions import AccessError, UserError, ValidationError
from datetime import datetime
from dateutil.relativedelta import relativedelta
import pytz
import base64
import json
import logging
logger = logging.getLogger(__name__)


class ShortageRequestTemplate(http.Controller):
    def _ensure_portal_creation_allowed(self):
        user = request.env.user
        if user.has_group('base.group_portal') and not user.has_group('base.group_user'):
            raise AccessError("Portal users are not allowed to create shortage requests.")

    def _current_employee(self):
        employee = request.env["hr.employee"].sudo().search([
            ("user_id", "=", request.env.user.id),
            ("active", "=", True),
        ], limit=1)
        if not employee:
            raise ValidationError("Your user is not linked to an active employee.")
        return employee

    def _local_to_utc(self, employee, value):
        local_value = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
        timezone = pytz.timezone(employee.tz or request.env.user.tz or "Asia/Riyadh")
        return timezone.localize(local_value).astimezone(pytz.UTC).replace(tzinfo=None)

    def _utc_to_local_string(self, employee, value):
        if not value:
            return ""
        timezone = pytz.timezone(employee.tz or request.env.user.tz or "Asia/Riyadh")
        utc_value = pytz.UTC.localize(fields.Datetime.to_datetime(value))
        return utc_value.astimezone(timezone).strftime("%Y-%m-%dT%H:%M:%S")

    def _prepare_attendance_values(self, employee_id, for_date):
        employee = request.env["hr.employee"].sudo().browse(employee_id)
        timezone = pytz.timezone(employee.tz or request.env.user.tz or "Asia/Riyadh")
        local_day_start = timezone.localize(datetime.combine(for_date, datetime.min.time()))
        local_day_end = local_day_start + relativedelta(days=1)
        day_start = local_day_start.astimezone(pytz.UTC).replace(tzinfo=None)
        day_end = local_day_end.astimezone(pytz.UTC).replace(tzinfo=None)
        attendance = request.env["hr.attendance"].sudo().search([
            ("employee_id", "=", employee_id),
            ("check_in", ">=", day_start),
            ("check_in", "<", day_end),
        ], limit=1)
        return {
            "check_in": attendance.check_in if attendance else False,
            "check_out": attendance.check_out if attendance else False,
            "shortage_text": attendance.shortage_time if attendance else "",
            "has_attendance": bool(attendance),
        }

    @http.route('/shortage_request', auth='user', type='http')
    def display_shortage_request_form(self, **kw):
        self._ensure_portal_creation_allowed()
        current_employee_id = self._current_employee()
        email = current_employee_id.work_email
        check_in = kw.get("check_in")
        check_out = kw.get("check_out")
        shortage_text = kw.get("shortage_text")
        date_value = kw.get("date")
        shortage_date = datetime.strptime(date_value, "%Y-%m-%d").date() if date_value else False
        if check_in:
            check_in = datetime.strptime(check_in, "%Y-%m-%d %H:%M:%S")
            shortage_date = check_in.date()
        if check_out:
            check_out = datetime.strptime(check_out, "%Y-%m-%d %H:%M:%S")
        if not shortage_date:
            shortage_date = datetime.today().date()
        has_attendance = False
        if not check_in or not check_out:
            attendance_vals = self._prepare_attendance_values(current_employee_id.id, shortage_date)
            has_attendance = attendance_vals["has_attendance"]
            check_in = attendance_vals["check_in"] if has_attendance else False
            check_out = attendance_vals["check_out"] if has_attendance else False
            if not shortage_text:
                shortage_text = attendance_vals["shortage_text"]
        else:
            has_attendance = True
        return http.request.render('de_hr_workspace_attendance.shortage_request_template', {
            "current_employee_id": current_employee_id,
            "employee_email": email,
            "check_in": self._utc_to_local_string(current_employee_id, check_in),
            "check_out": self._utc_to_local_string(current_employee_id, check_out),
            "shortage_text": shortage_text or "",
            "shortage_date": shortage_date,
            "has_attendance": has_attendance,
            "request_type": "shortage" if has_attendance else "no_punch",
            "error_message": False,
        })

    @http.route('/shortage_request/attendance_info', auth='user', type='http', methods=['GET'])
    def get_attendance_info(self, **kw):
        employee = self._current_employee()
        employee_id = employee.id
        requested_date = datetime.strptime(kw.get("date"), "%Y-%m-%d").date()
        attendance_vals = self._prepare_attendance_values(employee_id, requested_date)
        response_data = {
            "check_in": self._utc_to_local_string(employee, attendance_vals["check_in"]),
            "check_out": self._utc_to_local_string(employee, attendance_vals["check_out"]),
            "shortage_text": attendance_vals["shortage_text"] or "",
            "has_attendance": attendance_vals["has_attendance"],
        }
        return request.make_response(
            json.dumps(response_data),
            headers=[('Content-Type', 'application/json')]
        )

    @http.route('/shortage_request/create', type='http', auth="user")
    def contact_created(self, **kw):
        self._ensure_portal_creation_allowed()
        # logger.warning(
        #     f"{kw.get('employee_id')} -> employee shortage request"
        # )
        # print(kw.get('employee_id'), "employee shortage request")
        employee_obj = self._current_employee()
        employee_id = employee_obj.id
        str_date = kw.get('date')
        str_check_in = kw.get('checkin')
        str_check_out = kw.get('checkout')
        date = datetime.strptime(str_date, "%Y-%m-%d").date()
        attendance_vals = self._prepare_attendance_values(employee_id, date)
        request_type = "shortage" if attendance_vals["has_attendance"] else "no_punch"

        if request_type == "shortage" and (not str_check_in or not str_check_out):
            str_check_in = self._utc_to_local_string(employee_obj, attendance_vals["check_in"])
            str_check_out = self._utc_to_local_string(employee_obj, attendance_vals["check_out"])
        if not str_check_in or not str_check_out:
            raise ValidationError("Actual check-in and check-out are required.")

        if len(str_check_in) == 16:  # If no seconds part is present
            str_check_in += ':00'
        if len(str_check_out) == 16:  # If no seconds part is present
            str_check_out += ':00'
        shortage_time = kw.get('shortage')
        if request_type == "shortage" and not shortage_time:
            raise ValidationError("Shortage can only be requested for days that have attendance shortage.")
        check_in = self._local_to_utc(employee_obj, str_check_in)
        check_out = self._local_to_utc(employee_obj, str_check_out)
        reason = kw.get('message') if kw.get('message') else False
        try:
            with request.env.cr.savepoint():
                shortage_request_id = request.env['pr.hr.shortage.request'].sudo().create({
                    'date': date,
                    'request_type': request_type,
                    'employee_id': employee_id,
                    'check_in': check_in,
                    'check_out': check_out,
                    'shortage_time': shortage_time,
                    'company_id': employee_obj.company_id.id if employee_obj.company_id else request.env.company.id,
                    'employee_reason': reason,
                })
                for att in request.httprequest.files.getlist('attachment_ids'):
                    if not att.filename:
                        continue
                    request.env['ir.attachment'].sudo().create({
                        'name': att.filename,
                        'res_name': att.filename,
                        'res_model': 'pr.hr.shortage.request',
                        'res_id': shortage_request_id.id,
                        'datas': base64.encodebytes(att.read()),
                        'type': 'binary',
                    })
                # sudo keeps the current user: action_submit checks their rights
                shortage_request_id.action_submit()
        except (UserError, ValidationError) as ex:
            return request.render('de_hr_workspace_attendance.shortage_request_template', {
                "current_employee_id": employee_obj,
                "employee_email": employee_obj.work_email,
                "check_in": str_check_in,
                "check_out": str_check_out,
                "shortage_text": shortage_time or "",
                "shortage_date": date,
                "has_attendance": attendance_vals["has_attendance"],
                "request_type": request_type,
                "error_message": str(ex),
            })
        return request.render('de_hr_workspace_attendance.thanks_template')
