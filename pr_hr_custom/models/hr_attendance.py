from odoo import models, fields, api
from datetime import datetime, time, timedelta


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    @api.model
    def _cron_auto_handle_missing_checkouts(self):
        today_midnight = datetime.combine(fields.Date.today(), time.min)
        missing_records = self.sudo().search([
            ('check_out', '=', False),
            ('check_in', '<', today_midnight)
        ])
        if not missing_records:
            return
        for record in missing_records:
            if record.employee_id.id == 120:
                self.env.cr.execute("""
                    UPDATE hr_attendance
                    SET check_out = %s
                    WHERE id = %s
                """, (record.check_in, record.id))
                if missing_records:
                    missing_records.invalidate_recordset(['check_out'])

