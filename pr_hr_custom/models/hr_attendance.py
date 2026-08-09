from odoo import models, fields, api
from datetime import datetime, time, timedelta

class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    class HrAttendance(models.Model):
        _inherit = 'hr.attendance'

        def _cron_auto_handle_missing_checkouts(self):
            today_midnight = datetime.combine(fields.Date.today(), time.min)
            missing_records = self.sudo().search([('check_out', '=', False), ('check_in', '<', today_midnight)])
            if not missing_records:
                return
            AbsenteeDetail = self.env['de.hr.leave.absentee.detail'].sudo()
            for record in missing_records:
                emp = record.employee_id
                check_in_dt = record.check_in
                formatted_check_in = fields.Datetime.to_string(check_in_dt)
                AbsenteeDetail.create({
                    'absence_date': check_in_dt.date(),
                    'day_name': check_in_dt.strftime('%A'),
                    'employee_id': emp.id,
                    'employee_code': getattr(emp, 'registration_number', False) or emp.barcode or '',
                    'department': emp.department_id.name if emp.department_id else '',
                    'job_position': emp.job_id.name if emp.job_id else '',
                    'first_check_in': formatted_check_in,
                    'reason': 'Missing Checkout',
                    'expected_shift': emp.resource_calendar_id.name if emp.resource_calendar_id else '',
                })
                self.env.cr.execute("""
                    UPDATE hr_attendance
                    SET check_out = %s
                    WHERE id = %s
                """, (record.check_in, record.id))
            missing_records.invalidate_recordset(['check_out'])