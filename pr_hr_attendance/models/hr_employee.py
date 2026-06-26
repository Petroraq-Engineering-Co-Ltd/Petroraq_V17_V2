from odoo import models, fields, api, _
from odoo.tools import date_utils
from odoo.osv import expression
from dateutil.relativedelta import relativedelta
from odoo.exceptions import ValidationError
import re
import json
import math
from random import randint
import logging
from datetime import datetime, timedelta
import pandas as pd


_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    """
    """
    # region [Initial]
    _inherit = 'hr.employee'
    # endregion [Initial]

    # region [Fields]

    add_overtime = fields.Boolean(string="Attendance Overtime")
    attendance_email_enabled = fields.Boolean(
        string="Attendance Email Alerts",
        default=True,
        help="When enabled, daily attendance alert emails are sent for late, early check-out, or absence.",
    )
    attendance_entry_mode = fields.Selection(
        [
            ("automated", "Automated Attendance"),
            ("manual", "Manual / Site Attendance"),
        ],
        string="Attendance Entry Mode",
        required=True,
        default="automated",
        readonly=True,
        copy=False,
        tracking=True,
        help=(
            "Automated employees are controlled by biometric or scheduled processes. "
            "Only Manual / Site employees can have attendance entered by HR."
        ),
    )
    attendance_mode_change_request_count = fields.Integer(
        string="Attendance Mode Requests",
        compute="_compute_attendance_mode_change_request_count",
    )

    # endregion [Fields]

    @api.depends("attendance_entry_mode")
    def _compute_attendance_mode_change_request_count(self):
        counts = self.env["hr.attendance.mode.change.request"].sudo()._read_group(
            [("employee_id", "in", self.ids)],
            ["employee_id"],
            ["__count"],
        )
        count_by_employee = {employee.id: count for employee, count in counts}
        for employee in self:
            employee.attendance_mode_change_request_count = count_by_employee.get(
                employee.id, 0
            )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("install_mode"):
            for values in vals_list:
                if values.get("attendance_entry_mode", "automated") != "automated":
                    raise ValidationError(
                        _(
                            "New employees must start with Automated Attendance. "
                            "Use an approved Attendance Mode Change request to switch modes."
                        )
                    )
        return super().create(vals_list)

    def write(self, values):
        if "attendance_entry_mode" in values:
            changing = self.filtered(
                lambda employee: employee.attendance_entry_mode
                != values["attendance_entry_mode"]
            )
            if changing:
                request = self.env["hr.attendance.mode.change.request"].sudo().browse(
                    self.env.context.get("attendance_mode_approval_request_id")
                )
                authorized = (
                    self.env.su
                    and len(changing) == 1
                    and request.exists()
                    and request.state in ("hr_manager_approval", "md_approval")
                    and request.employee_id == changing
                    and request.current_mode == changing.attendance_entry_mode
                    and request.requested_mode == values["attendance_entry_mode"]
                )
                if not authorized:
                    raise ValidationError(
                        _(
                            "Attendance Entry Mode can only be changed through an "
                            "approved Attendance Mode Change request."
                        )
                    )
        if values.get("active") is False:
            self._close_open_attendances_for_archive()
        return super().write(values)

    def _attendance_policy_source_for_archive_checkout(self):
        self.ensure_one()
        if self.attendance_entry_mode != "automated":
            return False
        return "biometric" if self.compute_attendance else "scheduled"

    def _close_open_attendances_for_archive(self):
        Attendance = self.env["hr.attendance"].sudo()
        checkout_time = fields.Datetime.now()
        for employee in self.with_context(active_test=False):
            open_attendances = Attendance.search([
                ("employee_id", "=", employee.id),
                ("check_out", "=", False),
            ])
            if not open_attendances:
                continue

            attendance_context = {}
            source = employee._attendance_policy_source_for_archive_checkout()
            if source:
                attendance_context["attendance_policy_source"] = source
            open_attendances.with_context(**attendance_context).write({
                "check_out": checkout_time,
            })

    def action_archive(self):
        self._close_open_attendances_for_archive()
        return super().action_archive()

    def action_request_attendance_mode_change(self):
        self.ensure_one()
        self.check_access_rights("read")
        self.check_access_rule("read")
        return {
            "type": "ir.actions.act_window",
            "name": _("Request Attendance Mode Change"),
            "res_model": "hr.attendance.mode.change.request",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_employee_id": self.id,
                "default_current_mode": self.attendance_entry_mode,
                "default_requested_mode": (
                    "manual"
                    if self.attendance_entry_mode == "automated"
                    else "automated"
                ),
            },
        }

    def action_view_attendance_mode_change_requests(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "pr_hr_attendance.action_attendance_mode_change_request_all"
        )
        action["domain"] = [("employee_id", "=", self.id)]
        action["context"] = {"default_employee_id": self.id, "create": False}
        return action
