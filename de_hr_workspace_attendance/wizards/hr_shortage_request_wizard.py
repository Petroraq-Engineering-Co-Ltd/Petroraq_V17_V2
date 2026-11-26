from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrShortageRequestWizard(models.TransientModel):
    _name = "pr.hr.shortage.request.wizard"
    _description = "Shortage Request Wizard"

    attendance_id = fields.Many2one(
        "hr.attendance", string="Attendance", required=True, ondelete="cascade")
    date = fields.Date(compute="_compute_request_preview")
    check_in = fields.Datetime(string="Actual Check In", compute="_compute_request_preview")
    check_out = fields.Datetime(string="Actual Check Out", compute="_compute_request_preview")
    shortage_time = fields.Text(string="Shortage", compute="_compute_request_preview")
    scheduled_check_in = fields.Datetime(
        string="Check In to Apply", compute="_compute_request_preview")
    scheduled_check_out = fields.Datetime(
        string="Check Out to Apply", compute="_compute_request_preview")
    payroll_finalized = fields.Boolean(compute="_compute_request_preview")
    employee_reason = fields.Text(string="Reason", required=True)
    attachment_ids = fields.Many2many("ir.attachment", string="Attachments")

    @api.depends("attendance_id")
    def _compute_request_preview(self):
        for wizard in self:
            preview = self.env["pr.hr.shortage.request"]
            if wizard.attendance_id:
                preview = preview.new(wizard._prepare_shortage_request_vals())
            wizard.date = preview.date
            wizard.check_in = preview.check_in
            wizard.check_out = preview.check_out
            wizard.shortage_time = preview.shortage_time
            wizard.scheduled_check_in = preview.scheduled_check_in
            wizard.scheduled_check_out = preview.scheduled_check_out
            wizard.payroll_finalized = preview.payroll_finalized

    def _prepare_shortage_request_vals(self):
        self.ensure_one()
        attendance = self.attendance_id
        return {
            "request_type": "shortage",
            "apply_scheduled_shift": True,
            "employee_id": attendance.employee_id.id,
            "date": attendance._get_shortage_local_date(),
            "check_in": attendance.check_in,
            "check_out": attendance.check_out,
            "shortage_time": attendance.shortage_time,
            "employee_reason": (self.employee_reason or "").strip(),
        }

    def action_submit(self):
        self.ensure_one()
        # The attendance may have changed since the popup was opened.
        self.attendance_id._check_can_request_shortage()
        vals = self._prepare_shortage_request_vals()
        if not vals["employee_reason"]:
            raise UserError(_("Please enter the reason of your shortage request."))
        shortage_request = self.env["pr.hr.shortage.request"].create(vals)
        # No sudo: only files the user is allowed to modify can be attached.
        self.attachment_ids.write({
            "res_model": shortage_request._name,
            "res_id": shortage_request.id,
        })
        shortage_request.action_submit()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": _("Shortage request %s has been submitted.", shortage_request.name),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
