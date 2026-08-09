from datetime import datetime, time, timedelta
import pytz
from odoo import models, fields


class HrShortageRequest(models.Model):
    _inherit = 'pr.hr.shortage.request'

    def _apply_shortage_in_attendance(self):
        res = super(HrShortageRequest, self)._apply_shortage_in_attendance()
        for rec in self:
            day_start = datetime.combine(rec.date, time.min)
            day_end = day_start + timedelta(days=1)
            attendance = self.env["hr.attendance"].sudo().search([
                ("employee_id", "=", rec.employee_id.id),
                ("check_in", ">=", day_start),
                ("check_in", "<", day_end),
            ], limit=1)
            if attendance and attendance.check_in == attendance.check_out:
                self.env.cr.execute("""
                    UPDATE hr_attendance
                    SET check_in = %s, check_out = %s
                    WHERE id = %s
                """, (rec.check_in, rec.check_out, attendance.id))
                attendance.invalidate_recordset(['check_in', 'check_out'])
        return res