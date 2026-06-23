from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute(
        """
        UPDATE hr_employee
           SET attendance_entry_mode = 'automated'
         WHERE attendance_entry_mode IS NULL
        """
    )

    attendance_fields = env["hr.attendance"]._fields
    if "checkin_device_id" in attendance_fields:
        cr.execute(
            """
            UPDATE hr_attendance
               SET attendance_entry_source = CASE
                   WHEN auto_generated_attendance IS TRUE THEN 'scheduled'
                   WHEN checkin_device_id IS NOT NULL OR checkout_device_id IS NOT NULL
                       THEN 'biometric'
                   ELSE 'manual'
               END
            """
        )
    else:
        cr.execute(
            """
            UPDATE hr_attendance
               SET attendance_entry_source = CASE
                   WHEN auto_generated_attendance IS TRUE THEN 'scheduled'
                   ELSE 'manual'
               END
            """
        )
