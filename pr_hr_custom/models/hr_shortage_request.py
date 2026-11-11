from odoo import fields, models


class HrShortageRequest(models.Model):
    _inherit = 'pr.hr.shortage.request'

    def _apply_shortage_in_attendance(self):
        res = super(HrShortageRequest, self)._apply_shortage_in_attendance()
        Attendance = self.env['hr.attendance'].sudo()
        for rec in self:
            if not rec.check_in or not rec.check_out:
                continue
            day_start, day_end, _timezone = Attendance._get_auto_attendance_day_bounds(
                rec.employee_id, rec.date
            )
            attendance = Attendance.search([
                ('employee_id', '=', rec.employee_id.id),
                ('check_in', '>=', fields.Datetime.to_string(day_start)),
                ('check_in', '<', fields.Datetime.to_string(day_end)),
            ], limit=1)
            if attendance and attendance.check_in == attendance.check_out:
                attendance.with_context(
                    allow_late_attendance=True,
                    attendance_policy_source='approved_shortage',
                ).write({
                    'check_in': rec.check_in,
                    'check_out': rec.check_out,
                })
        return res