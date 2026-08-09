from odoo import models, fields, api

class HrLeave(models.Model):
    _inherit = 'hr.leave'

    @api.model
    def get_employee_absentee_day_details(self, employee_id=None, duration='current_contract', date_from=False, date_to=False):
        res = super().get_employee_absentee_day_details(
            employee_id=employee_id,
            duration=duration,
            date_from=date_from,
            date_to=date_to
        )
        emp_id = res.get('employee_id')
        if not emp_id:
            return res
        d_from = fields.Date.from_string(res.get('date_from')) if res.get('date_from') else False
        d_to = fields.Date.from_string(res.get('date_to')) if res.get('date_to') else False
        domain = [
            ('employee_id', '=', emp_id),
            ('check_in', '!=', False),
            ('check_out', '!=', False)
        ]
        if d_from:
            domain.append(('check_in', '>=', d_from))
        if d_to:
            domain.append(('check_in', '<=', d_to))
        attendances = self.env['hr.attendance'].sudo().search(domain)
        missing_checkout_recs = attendances.filtered(lambda a: a.check_in == a.check_out)
        new_rows = list(res.get('rows', []))
        for att in missing_checkout_recs:
            emp = att.employee_id
            new_rows.append({
                'date': att.check_in.date(),
                'day_name': att.check_in.strftime('%A'),
                'employee_id': emp.id,
                'employee_code': getattr(emp, 'registration_number', False) or emp.barcode or '',
                'department': emp.department_id.name if emp.department_id else '',
                'job_position': emp.job_id.name if emp.job_id else '',
                'check_in': fields.Datetime.to_string(att.check_in),
                'reason': 'Missing Checkout',
                'shift': emp.resource_calendar_id.name if emp.resource_calendar_id else '',
            })

        res['rows'] = new_rows
        res['count'] = len(new_rows)
        return res

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
        existing_dates = {row.get('date') for row in rows}
        for att in missing_checkout_recs:
            local_check_in = self._to_absentee_local_datetime(employee, att.check_in)
            if not local_check_in:
                continue
            att_date_str = fields.Date.to_string(local_check_in.date())
            if att_date_str not in existing_dates:
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