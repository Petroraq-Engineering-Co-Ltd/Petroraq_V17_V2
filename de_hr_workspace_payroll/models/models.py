# -*- coding: utf-8 -*-

from odoo import _, models, fields, api
from odoo.exceptions import AccessError


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    line_ids_filtered = fields.One2many("hr.payslip.line", "slip_id", compute="_compute_line_ids_filtered")

    @api.depends("line_ids", "line_ids.total")
    def _compute_line_ids_filtered(self):
        for rec in self:
            if rec.line_ids:
                line_ids_filtered = rec.line_ids.filtered(lambda l: l.total != 0)
                if line_ids_filtered:
                    rec.line_ids_filtered = line_ids_filtered.ids
                else:
                    rec.line_ids_filtered = False
            else:
                rec.line_ids_filtered = False

    def action_print_payslip(self):
        if self.env.user.has_group("hr_payroll.group_hr_payroll_user"):
            return super().action_print_payslip()

        self.ensure_one()
        if self.employee_id.user_id != self.env.user:
            raise AccessError(_("You can only print your own payslips."))

        return {
            "name": _("Payslip"),
            "type": "ir.actions.act_url",
            "url": "/my/payslips/%s/download" % self.id,
            "target": "self",
        }
