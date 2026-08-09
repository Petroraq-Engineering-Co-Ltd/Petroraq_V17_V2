from odoo import models, fields, api

class HrLeave(models.Model):
    _inherit = 'hr.leave'

    @api.model
    def _get_employee_absentee_day_rows(self, employee, start, end):
        rows = super()._get_employee_absentee_day_rows(employee, start, end)
        if not employee or not start or not end:
            return rows
        start_dt, _ = self._get_absentee_day_bounds_utc(employee, start)
        _, end_dt = self._get_absentee_day_bounds_utc(employee, end)

        attendances = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', fields.Datetime.to_string(start_dt)),
            ('check_in', '<', fields.Datetime.to_string(end_dt)),
            ('check_out', '!=', False),
        ])
        missing_checkout_recs = attendances.filtered(lambda a: a.check_in == a.check_out)
        existing_dates = {row.get('date') for row in rows if row.get('date')}
        for att in missing_checkout_recs:
            local_check_in = self._to_absentee_local_datetime(employee, att.check_in)
            if not local_check_in:
                continue
            att_date_str = fields.Date.to_string(local_check_in.date())
            if att_date_str in existing_dates:
                for row in rows:
                    if row.get('date') == att_date_str:
                        row['reason'] = 'Missing Checkout'
                        row['check_in'] = self._format_absentee_check_in(local_check_in)
            else:
                rows.append({
                    'employee_id': employee.id,
                    'employee_code': employee.code or employee.barcode or '',
                    'employee_name': employee.name,
                    'department': employee.department_id.name or '',
                    'job_position': employee.job_title or employee.job_id.name or '',
                    'date': att_date_str,
                    'date_display': self._format_dashboard_date(local_check_in.date()),
                    'day_name': local_check_in.strftime('%A'),
                    'shift': self._get_employee_absentee_shift_label(employee, local_check_in.date()),
                    'check_in': self._format_absentee_check_in(local_check_in),
                    'reason': 'Missing Checkout',
                })
                existing_dates.add(att_date_str)

        return rows