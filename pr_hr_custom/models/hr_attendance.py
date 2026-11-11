from odoo import api, fields, models


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    @api.model
    def _cron_auto_handle_missing_checkouts(self, now=None):
        utc_now = fields.Datetime.to_datetime(now or fields.Datetime.now())
        open_records = self.sudo().search([
            ('check_out', '=', False),
            ('check_in', '!=', False),
            ('check_in', '<', fields.Datetime.to_string(utc_now)),
        ])
        overdue_records = open_records.filtered(
            lambda record: record._attendance_local_datetime(utc_now).date()
            > record._attendance_local_datetime(record.check_in).date()
        )
        if not overdue_records:
            return self.browse()
        for record in overdue_records:
            write_context = {
                'allow_late_attendance': True,
                'not_manual_check_out_modification': True,
                'sync_from_device': True,
            }
            source = record.employee_id.with_context(
                active_test=False
            )._attendance_policy_source_for_archive_checkout()
            if source:
                write_context['attendance_policy_source'] = source
            record.sudo().with_context(**write_context).write({
                'check_out': record.check_in,
            })
            record._refresh_daily_attendance_status(now=utc_now)
        return overdue_records