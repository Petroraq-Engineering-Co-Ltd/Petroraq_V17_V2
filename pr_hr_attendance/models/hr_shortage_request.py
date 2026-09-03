from odoo import models, fields, api, _
from odoo.tools import date_utils
from odoo.osv import expression
from dateutil.relativedelta import relativedelta
from odoo.exceptions import ValidationError, UserError
import re
import json
import math
from random import randint
import logging
from datetime import datetime, timedelta, time
import pytz
import pandas as pd

_logger = logging.getLogger(__name__)


class HrShortageRequest(models.Model):
    """
    """
    # region [Initial]
    _name = 'pr.hr.shortage.request'
    _description = 'Hr Shortage Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = "id"
    # endregion [Initial]

    # region [Fields]

    name = fields.Char(string="Name")
    request_type = fields.Selection([
        ('shortage', 'Attendance Shortage'),
        ('no_punch', 'No Punch Record'),
    ], string="Request Type", required=True, default='shortage', tracking=True)
    date = fields.Date(string="Date", required=True)
    check_in = fields.Datetime(string="Check In", required=False)
    check_out = fields.Datetime(string="Check Out", required=False)
    company_id = fields.Many2one(
        'res.company', string='Company', tracking=True, required=True,
        default=lambda self: self.env.company,
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', tracking=True, required=True,
        default=lambda self: self.env.user.employee_id,
    )
    employee_manager_id = fields.Many2one('hr.employee', string='Manager', tracking=True, readonly=True)
    hr_supervisor_ids = fields.Many2many('res.users', 'shortage_request_hr_supervisor_users', 'hr_supervisor_id',
                                         'shortage_request_id', string='HR Supervisors', tracking=True, readonly=True)
    hr_manager_ids = fields.Many2many('res.users', 'shortage_request_hr_manager_users', 'hr_manager_id',
                                      'shortage_request_id', string='HR Managers', tracking=True, readonly=True)
    employee_reason = fields.Text(string="Reason")
    reject_reason = fields.Text(string="Rejection Reason", readonly=True)
    shortage_time = fields.Text(string="Shortage Time", readonly=True)
    state = fields.Selection([
        ('draft', 'Submitted'),
        ('manager_approve', 'Manager Approved'),
        ('hr_supervisor', 'HR Supervisor Approved'),
        ('hr_approve', 'HR Manager Approved'),
        ('reject', 'Rejected'),
    ], default='draft', track_visibility='always',
        string='Status', required=True, index=True)
    approval_state = fields.Selection([
        ('draft', 'Pending Approval'),
        ('manager_approve', 'Pending Approval'),
        ('hr_supervisor', 'Pending Approval'),
        ('hr_approve', 'Approved'),
        ('reject', 'Rejected'),
    ], default='draft', track_visibility='always',
        string='Approval Status')
    employee_manager_check = fields.Boolean(compute="_compute_employee_manager_check")
    hr_supervisor_check = fields.Boolean(compute="_compute_hr_supervisor_check")
    hr_manager_check = fields.Boolean(compute="_compute_hr_manager_check")

    @api.constrains("request_type", "date", "check_in", "check_out")
    def _check_no_punch_times(self):
        for rec in self.filtered(lambda item: item.request_type == "no_punch"):
            if not rec.check_in or not rec.check_out:
                raise ValidationError(
                    _("Actual Check In and Actual Check Out are required for a No Punch Record request.")
                )
            if rec.check_out <= rec.check_in:
                raise ValidationError(_("Actual Check Out must be later than Actual Check In."))
            employee_tz = pytz.timezone(rec.employee_id.tz or self.env.user.tz or "UTC")
            local_check_in = pytz.UTC.localize(rec.check_in).astimezone(employee_tz)
            local_check_out = pytz.UTC.localize(rec.check_out).astimezone(employee_tz)
            if local_check_in.date() != rec.date or local_check_out.date() != rec.date:
                raise ValidationError(
                    _("Actual attendance times must belong to the selected attendance date.")
                )
            local_day_start = employee_tz.localize(datetime.combine(rec.date, time.min))
            local_day_end = local_day_start + timedelta(days=1)
            day_start = local_day_start.astimezone(pytz.UTC).replace(tzinfo=None)
            day_end = local_day_end.astimezone(pytz.UTC).replace(tzinfo=None)
            attendance_exists = self.env["hr.attendance"].sudo().search_count([
                ("employee_id", "=", rec.employee_id.id),
                ("check_in", "<", fields.Datetime.to_string(day_end)),
                "|",
                ("check_out", "=", False),
                ("check_out", ">", fields.Datetime.to_string(day_start)),
            ])
            if attendance_exists:
                raise ValidationError(
                    _("A No Punch Record request is only allowed when no attendance exists for that date.")
                )
            duplicate_request = self.sudo().search_count([
                ("id", "!=", rec.id),
                ("employee_id", "=", rec.employee_id.id),
                ("date", "=", rec.date),
                ("request_type", "=", "no_punch"),
                ("state", "not in", ["reject"]),
            ])
            if duplicate_request:
                raise ValidationError(
                    _("A No Punch Record request already exists for this employee and date.")
                )

    # endregion [Fields]

    # region [Compute Methods]

    @api.depends("employee_id", "employee_id.parent_id", "employee_id.parent_id.user_id", "employee_manager_id",
                 "employee_manager_id.user_id")
    def _compute_employee_manager_check(self):
        for rec in self:
            employee_manager_id = rec.employee_id.parent_id
            if employee_manager_id.user_id and employee_manager_id.user_id.id == self.env.user.id:
                rec.employee_manager_check = True
            else:
                rec.employee_manager_check = False

    def _compute_hr_supervisor_check(self):
        for rec in self:
            # if self.env.user.has_group('hr_attendance.group_hr_attendance_officer'):
            if self.env.user.has_group('pr_hr_attendance.custom_group_hr_attendance_supervisor'):
                rec.hr_supervisor_check = True
            else:
                rec.hr_supervisor_check = False

    def _compute_hr_manager_check(self):
        for rec in self:
            if self.env.user.has_group('hr_attendance.group_hr_attendance_manager'):
                rec.hr_manager_check = True
            else:
                rec.hr_manager_check = False

    # region [Compute Methods]

    # region [Onchange Methods]

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        self.ensure_one()
        if self.employee_id.company_id:
            self.company_id = self.employee_id.company_id.id

    @api.onchange("employee_id", "date")
    def _onchange_employee_id_date_attendance(self):
        self.ensure_one()
        if not self.employee_id or not self.date:
            return
        day_start = datetime.combine(self.date, time.min)
        day_end = day_start + timedelta(days=1)
        attendance_id = self.env["hr.attendance"].sudo().search([
            ("employee_id", "=", self.employee_id.id),
            ("check_in", ">=", day_start),
            ("check_in", "<", day_end),
        ], limit=1)
        if attendance_id:
            self.check_in = attendance_id.check_in
            self.check_out = attendance_id.check_out
            self.shortage_time = attendance_id.shortage_time or False

    # endregion [Onchange Methods]

    # region [Emails]

    def _prepare_email_vals(self, body_message, receiver):
        for rec in self:
            message = {
                "email_from": "noreply@petroraq.com",
                "subject": f"{rec.employee_id.code} - Shortage Request For {rec.date}",
                "body_html": body_message,
                "email_to": receiver,
            }
            return message

    def _send_manager_email(self):
        for rec in self:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            record_url = base_url + "/web#id=" + str(
                rec.id) + "&view_type=form&model=pr.hr.shortage.request&view_type=form"

            body_message = f"""Dear Mr/Mrs. {rec.employee_id.parent_id.name},<br/><br/>

                We wish to inform you that your employee {rec.employee_id.name} has been asked for <strong>Shortage Request For {rec.date}</strong>.<br/><br/>
                You can check the request to take a decision by clicking this button <a class="btn btn-primary" href="{record_url}" role="button">Shortage Request</a><br/><br/><br/>
                Thank you for your attention to this matter.<br/><br/>
                Best regards,<br/>
                <strong>HR Department</strong><br/>
                Petroraq Engineering
                """
            receiver = rec.employee_id.parent_id.work_email
            mail = self.env["mail.mail"]
            mail_id = mail.sudo().create(rec._prepare_email_vals(body_message=body_message, receiver=receiver))
            if mail_id:
                mail_id.sudo().send()

    def _send_hr_supervisor_email(self):
        for rec in self:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            record_url = base_url + "/web#id=" + str(
                rec.id) + "&view_type=form&model=pr.hr.shortage.request&view_type=form"

            # group_ids = [self.env.ref('hr_attendance.group_hr_attendance_officer').id]
            group_ids = [self.env.ref('pr_hr_attendance.custom_group_hr_attendance_supervisor').id]
            user_ids = self.env['res.users'].sudo().search([('groups_id', 'in', group_ids)])
            if user_ids:
                for user in user_ids:
                    employee_id = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
                    if employee_id and employee_id.work_email:
                        body_message = f"""Dear Mr/Mrs. {employee_id.name},<br/><br/>

                            We wish to inform you that your employee {rec.employee_id.name} has been asked for <strong>Shortage Request For {rec.date}</strong>.<br/><br/>
                            You can check the request to take a decision by clicking this button <a class="btn btn-primary" href="{record_url}" role="button">Shortage Request</a><br/><br/><br/>
                            Thank you for your attention to this matter.<br/><br/>
                            Best regards,<br/>
                            <strong>HR Department</strong><br/>
                            Petroraq Engineering
                            """
                        receiver = employee_id.work_email
                        mail = self.env["mail.mail"]
                        mail_id = mail.sudo().create(
                            rec._prepare_email_vals(body_message=body_message, receiver=receiver))
                        if mail_id:
                            mail_id.sudo().send()

    def _send_hr_manager_email(self):
        for rec in self:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            record_url = base_url + "/web#id=" + str(
                rec.id) + "&view_type=form&model=pr.hr.shortage.request&view_type=form"

            group_ids = [self.env.ref('hr_attendance.group_hr_attendance_manager').id]
            user_ids = self.env['res.users'].sudo().search([('groups_id', 'in', group_ids)])
            if user_ids:
                for user in user_ids:
                    employee_id = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
                    if employee_id and employee_id.work_email:
                        body_message = f"""Dear Mr/Mrs. {employee_id.name},<br/><br/>

                            We wish to inform you that your employee {rec.employee_id.name} has been asked for <strong>Shortage Request For {rec.date}</strong>.<br/><br/>
                            You can check the request to take a decision by clicking this button <a class="btn btn-primary" href="{record_url}" role="button">Shortage Request</a><br/><br/><br/>
                            Thank you for your attention to this matter.<br/><br/>
                            Best regards,<br/>
                            <strong>HR Department</strong><br/>
                            Petroraq Engineering
                            """
                        receiver = employee_id.work_email
                        mail = self.env["mail.mail"]
                        mail_id = mail.sudo().create(
                            rec._prepare_email_vals(body_message=body_message, receiver=receiver))
                        if mail_id:
                            mail_id.sudo().send()

    def _send_result_to_employee(self, result):
        for rec in self:

            body_message = f"""Dear Mr/Mrs. {rec.employee_id.name},<br/><br/>

                We wish to inform you that your Shortage Request {rec.name} has been <strong>{result}</strong>.<br/><br/>
                Thank you for your attention to this matter.<br/><br/>
                Best regards,<br/>
                <strong>HR Department</strong><br/>
                Petroraq Engineering
                """
            receiver = rec.employee_id.work_email
            mail = self.env["mail.mail"]
            mail_id = mail.sudo().create(rec._prepare_email_vals(body_message=body_message, receiver=receiver))
            if mail_id:
                mail_id.sudo().send()

    # endregion [Emails]

    # region [Actions]

    def _approval_identity(self, user):
        employee = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
        return ("employee", employee.id) if employee else ("user", user.id)

    def _stage_has_unique_approver(self, users, higher_users):
        higher_keys = {self._approval_identity(user) for user in higher_users.filtered("active")}
        return any(
            self._approval_identity(user) not in higher_keys
            for user in users.filtered("active")
        )

    def _advance_duplicate_approval_stages(self):
        """Skip lower levels when all their people also hold a higher level."""
        for rec in self:
            manager_users = rec.employee_manager_id.user_id
            supervisor_users = rec.hr_supervisor_ids
            manager_users_hr = rec.hr_manager_ids
            if rec.state == "draft" and not rec._stage_has_unique_approver(
                manager_users, supervisor_users | manager_users_hr
            ):
                rec.sudo().write({"state": "manager_approve", "approval_state": "manager_approve"})
            if rec.state == "manager_approve" and not rec._stage_has_unique_approver(
                supervisor_users, manager_users_hr
            ):
                rec.sudo().write({"state": "hr_supervisor", "approval_state": "hr_supervisor"})

    def action_manager_approve(self):
        for rec in self:
            if rec.employee_manager_id.user_id != self.env.user:
                raise UserError(_("Only the employee's manager can approve this stage."))
            rec._check_no_punch_times()
            rec = rec.sudo()
            rec.state = "manager_approve"
            rec.approval_state = "manager_approve"
            rec._advance_duplicate_approval_stages()
            if rec.state == "manager_approve":
                rec._send_hr_supervisor_email()
            elif rec.state == "hr_supervisor":
                rec._send_hr_manager_email()

    def action_manager_reject(self):
        for rec in self:
            if rec.employee_manager_id.user_id != self.env.user:
                raise UserError(_("Only the employee's manager can reject this stage."))
            view = {
                'type': 'ir.actions.act_window',
                'name': 'Reject Reason',
                'res_model': 'pr.reject.record.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_record_id': '%s,%s' % (rec._name, rec.id),
                },
                'views': [(self.env.ref('pr_base.pr_reject_record_wizard_view_form').id, 'form')],
            }
            return view

    def action_hr_supervisor_approve(self):
        for rec in self:
            if not self.env.user.has_group('pr_hr_attendance.custom_group_hr_attendance_supervisor'):
                raise UserError(_("Only an HR Supervisor can approve this stage."))
            rec._check_no_punch_times()
            rec = rec.sudo()
            rec.state = "hr_supervisor"
            rec.approval_state = "hr_supervisor"
            rec._advance_duplicate_approval_stages()
            rec._send_hr_manager_email()

    def action_hr_supervisor_reject(self):
        for rec in self:
            if not self.env.user.has_group('pr_hr_attendance.custom_group_hr_attendance_supervisor'):
                raise UserError(_("Only an HR Supervisor can reject this stage."))
            view = {
                'type': 'ir.actions.act_window',
                'name': 'Reject Reason',
                'res_model': 'pr.reject.record.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_record_id': '%s,%s' % (rec._name, rec.id),
                },
                'views': [(self.env.ref('pr_base.pr_reject_record_wizard_view_form').id, 'form')],
            }
            return view

    def action_hr_manager_approve(self):
        for rec in self:
            if not self.env.user.has_group('hr_attendance.group_hr_attendance_manager'):
                raise UserError(_("Only an HR Attendance Manager can approve this stage."))
            rec._check_no_punch_times()
            rec = rec.sudo()
            rec.state = "hr_approve"
            rec.approval_state = "hr_approve"
            rec._apply_shortage_in_attendance()
            rec._send_result_to_employee(result="Approved")

    def _apply_shortage_in_attendance(self):
        for rec in self:
            Attendance = self.env["hr.attendance"].sudo()
            day_start, day_end, _timezone = Attendance._get_auto_attendance_day_bounds(
                rec.employee_id, rec.date
            )
            attendance_id = self.env["hr.attendance"].sudo().search([
                ("employee_id", "=", rec.employee_id.id),
                ("check_in", ">=", fields.Datetime.to_string(day_start)),
                ("check_in", "<", fields.Datetime.to_string(day_end)),
            ], limit=1)

            if rec.request_type == "no_punch":
                check_in_dt = rec.check_in
                check_out_dt = rec.check_out
            else:
                scheduled_check_in, scheduled_check_out = Attendance._get_auto_attendance_datetimes(
                    rec.employee_id, rec.date
                )
                check_in_dt = rec.check_in or scheduled_check_in
                check_out_dt = rec.check_out or scheduled_check_out

            if attendance_id:
                attendance_id.sudo().with_context(
                    allow_late_attendance=True,
                    attendance_policy_source="approved_shortage",
                ).write({
                    "check_in": check_in_dt,
                    "check_out": check_out_dt,
                })
            else:
                self.env["hr.attendance"].sudo().with_context(
                    allow_late_attendance=True,
                    attendance_policy_source="approved_shortage",
                ).create({
                    "employee_id": rec.employee_id.id,
                    "check_in": check_in_dt,
                    "check_out": check_out_dt,
                })

    def action_hr_manager_reject(self):
        for rec in self:
            if not self.env.user.has_group('hr_attendance.group_hr_attendance_manager'):
                raise UserError(_("Only an HR Attendance Manager can reject this stage."))
            view = {
                'type': 'ir.actions.act_window',
                'name': 'Reject Reason',
                'res_model': 'pr.reject.record.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_record_id': '%s,%s' % (rec._name, rec.id),
                },
                'views': [(self.env.ref('pr_base.pr_reject_record_wizard_view_form').id, 'form')],
            }
            return view

    # endregion [Actions]

    # region [Constrains]

    @api.constrains("state")
    def _check_reject_state(self):
        for rec in self:
            if rec.state == "reject":
                rec.approval_state = "reject"
                rec._send_result_to_employee(result="Rejected")

    # region [Constrains]

    # region [Crud]

    @api.model
    def create(self, vals):
        '''
        We Inherit Create Method To Pass Sequence Fo Field Name
        '''
        employee = self.env["hr.employee"].browse(vals.get("employee_id")).exists()
        current_employee = self.env.user.employee_id
        if (
            not self.env.su
            and current_employee
            and not self.env.user.has_group("hr_attendance.group_hr_attendance_officer")
            and not self.env.user.has_group("hr_attendance.group_hr_attendance_manager")
            and not self.env.user.has_group("pr_hr_attendance.custom_group_hr_attendance_supervisor")
            and employee != current_employee
        ):
            raise ValidationError(_("Employees can only create attendance correction requests for themselves."))
        if employee and not vals.get("company_id"):
            vals["company_id"] = employee.company_id.id or self.env.company.id
        res = super().create(vals)
        res.name = self.env['ir.sequence'].next_by_code('hr.attendance.shortage.request.seq.code') or ''
        employee_manager_id = res.employee_id.parent_id
        if employee_manager_id:
            res.employee_manager_id = employee_manager_id.id
        hr_supervisor_group_ids = [self.env.ref('pr_hr_attendance.custom_group_hr_attendance_supervisor').id]
        hr_manager_group_ids = [self.env.ref('hr_attendance.group_hr_attendance_manager').id]
        hr_supervisor_ids = self.env['res.users'].sudo().search([('groups_id', 'in', hr_supervisor_group_ids)])
        hr_manager_ids = self.env['res.users'].sudo().search([('groups_id', 'in', hr_manager_group_ids)])
        if hr_supervisor_ids:
            res.hr_supervisor_ids = hr_supervisor_ids.ids
        if hr_manager_ids:
            res.hr_manager_ids = hr_manager_ids.ids
        res.sudo()._advance_duplicate_approval_stages()
        if res.state == "draft":
            res.sudo()._send_manager_email()
        elif res.state == "manager_approve":
            res.sudo()._send_hr_supervisor_email()
        else:
            res.sudo()._send_hr_manager_email()
        return res

    def write(self, vals):
        if not self.env.su:
            if {"state", "approval_state"} & set(vals):
                raise ValidationError(_("Approval status can only be changed using the approval actions."))
            correction_fields = {
                "request_type", "date", "check_in", "check_out",
                "employee_id", "employee_reason",
            }
            if correction_fields & set(vals) and any(rec.state != "draft" for rec in self):
                raise ValidationError(_("Only submitted requests can be edited."))
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state != 'draft':
                raise ValidationError("This Shortage Request Should Be Draft To Can Delete !!")
        return super().unlink()

    # endregion [Crud]
