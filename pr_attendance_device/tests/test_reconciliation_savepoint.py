from datetime import datetime
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestReconciliationSavepoint(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        calendar = cls.env['resource.calendar'].create({
            'name': 'Riyadh Savepoint Test',
            'tz': 'Asia/Riyadh',
            'attendance_ids': [Command.clear()],
        })
        work_location_vals = {
            'name': 'Savepoint Site',
        }
        if 'address_id' in cls.env['hr.work.location']._fields:
            work_location_vals['address_id'] = cls.env.company.partner_id.id
        cls.location = cls.env['attendance.device.location'].create({
            'name': 'Savepoint Gate',
            'tz': 'Asia/Riyadh',
            'hr_work_location_id': cls.env['hr.work.location'].create(
                work_location_vals
            ).id,
        })
        cls.device = cls.env['attendance.device'].create({
            'name': 'Savepoint Device',
            'location_id': cls.location.id,
        })

        bio_vals = {
            'name': 'Biometric Employee',
            'identification_id': 'SAVEPOINT-BIO-001',
            'resource_calendar_id': calendar.id,
        }
        if 'compute_attendance' in cls.env['hr.employee']._fields:
            bio_vals['compute_attendance'] = True
        cls.bio_employee = cls.env['hr.employee'].create(bio_vals)
        cls.bio_user = cls.env['attendance.device.user'].create({
            'name': cls.bio_employee.name,
            'device_id': cls.device.id,
            'employee_id': cls.bio_employee.id,
            'user_id': '98001',
            'uid': 98001,
        })

        other_vals = {
            'name': 'Manual Or Second Employee',
            'identification_id': 'SAVEPOINT-OTH-002',
            'resource_calendar_id': calendar.id,
        }
        if 'attendance_entry_mode' in cls.env['hr.employee']._fields:
            other_vals['attendance_entry_mode'] = 'manual'
            other_vals['compute_attendance'] = False
            cls.other_employee = cls.env['hr.employee'].with_context(
                install_mode=True,
            ).create(other_vals)
        else:
            cls.other_employee = cls.env['hr.employee'].create(other_vals)
        cls.other_user = cls.env['attendance.device.user'].create({
            'name': cls.other_employee.name,
            'device_id': cls.device.id,
            'employee_id': cls.other_employee.id,
            'user_id': '98002',
            'uid': 98002,
        })

    def _punch(self, device_user, timestamp, code=0):
        state = self.env.ref('pr_attendance_device.attendance_device_state_code_%s' % code)
        return self.env['user.attendance'].create({
            'device_id': self.device.id,
            'user_id': device_user.id,
            'timestamp': timestamp,
            'status': code,
            'attendance_state_id': state.id,
        })

    def test_savepoint_isolation_preserves_previous_checkout_on_subsequent_error(self):
        checkin = self._punch(self.bio_user, '2026-09-10 05:30:00', 0)
        checkin._sync_attendance()
        attendance = checkin.hr_attendance_id

        checkout = self._punch(self.bio_user, '2026-09-10 14:30:00', 1)
        failing_punch = self._punch(self.other_user, '2026-09-10 14:31:00', 0)

        original_reconcile = type(self.env['user.attendance'])._reconcile_single_punch

        def failing_on_second(records):
            if records == failing_punch:
                # Force a DB write/flush inside the second savepoint before failing,
                # verifying rollback never reverts or corrupts the first punch.
                self.env['hr.attendance'].search([('id', '=', attendance.id)])
                raise ValidationError('Simulated downstream failure')
            return original_reconcile(records)

        with patch.object(type(self.env['user.attendance']), '_reconcile_single_punch', autospec=True, side_effect=failing_on_second):
            (checkout | failing_punch)._sync_attendance()

        self.env.invalidate_all()
        reloaded_att = self.env['hr.attendance'].browse(attendance.id)
        self.assertEqual(reloaded_att.check_out, datetime(2026, 9, 10, 14, 30, 0))
        self.assertEqual(reloaded_att.checkout_device_id, self.device)
        self.assertAlmostEqual(reloaded_att.worked_hours, 9.0, places=2)
        if 'attendance_day_status' in reloaded_att._fields:
            self.assertEqual(reloaded_att.attendance_day_status, 'normal')
        self.assertEqual(checkout.reconciliation_status, 'synced')
        self.assertEqual(failing_punch.reconciliation_status, 'needs_review')
        self.assertIn('Simulated downstream failure', failing_punch.reconciliation_note or '')

    def test_ineligible_manual_employee_punch_routes_to_needs_review_cleanly(self):
        if 'attendance_entry_mode' not in self.other_employee._fields:
            self.skipTest('pr_hr_attendance not installed')
        msg_count_before = len(self.device.message_ids)
        checkin = self._punch(self.bio_user, '2026-09-11 05:30:00', 0)
        checkin._sync_attendance()

        checkout = self._punch(self.bio_user, '2026-09-11 14:30:00', 1)
        manual_punch = self._punch(self.other_user, '2026-09-11 14:31:00', 0)
        (checkout | manual_punch)._sync_attendance()

        self.assertEqual(checkout.reconciliation_status, 'synced')
        self.assertEqual(checkout.hr_attendance_id.check_out, datetime(2026, 9, 11, 14, 30, 0))
        self.assertEqual(checkout.hr_attendance_id.attendance_day_status, 'normal')
        self.assertFalse(manual_punch.hr_attendance_id)
        self.assertFalse(manual_punch.synced)
        self.assertEqual(manual_punch.reconciliation_status, 'needs_review')
        self.assertEqual(
            manual_punch.reconciliation_note,
            'Employee is not configured for biometric attendance synchronization.',
        )
        self.assertEqual(len(self.device.message_ids), msg_count_before)

    def test_post_midnight_sentinel_replaced_by_late_checkout(self):
        checkin = self._punch(self.bio_user, '2026-09-12 05:30:00', 0)
        checkin._sync_attendance()
        attendance = checkin.hr_attendance_id

        # Simulate midnight sentinel written after day ended.
        write_ctx = {
            'sync_from_device': True,
            'not_manual_check_out_modification': True,
            'allow_late_attendance': True,
        }
        if 'attendance_entry_source' in attendance._fields:
            write_ctx['attendance_policy_source'] = 'biometric'
        attendance.sudo().with_context(**write_ctx).write({'check_out': attendance.check_in})

        # Next day punch flags yesterday's check-in as missing checkout.
        next_day = self._punch(self.bio_user, '2026-09-13 05:30:00', 0)
        next_day._sync_attendance()
        self.assertEqual(checkin.reconciliation_status, 'needs_review')

        # Late biometric checkout for Sep 12 arrives afterward.
        late_checkout = self._punch(self.bio_user, '2026-09-12 14:45:00', 1)
        late_checkout._sync_attendance()

        self.assertEqual(attendance.check_out, datetime(2026, 9, 12, 14, 45, 0))
        self.assertEqual(attendance.checkout_device_id, self.device)
        self.assertGreater(attendance.worked_hours, 8.0)
        self.assertEqual(late_checkout.reconciliation_status, 'synced')
        self.assertFalse(late_checkout.reconciliation_note)
        self.assertEqual(checkin.reconciliation_status, 'synced')
        self.assertFalse(checkin.reconciliation_note)
        if 'attendance_day_status' in attendance._fields:
            self.assertEqual(attendance.attendance_day_status, 'normal')
            self.assertFalse(attendance.attendance_status_reason)

    def test_repair_desynced_checkouts_is_idempotent(self):
        # 1) Desynced pair: user.attendance checkout synced, but SQL rolled hr_attendance back to check_in.
        in1 = self._punch(self.bio_user, '2026-09-14 05:30:00', 0)
        out1 = self._punch(self.bio_user, '2026-09-14 14:30:00', 1)
        (in1 | out1)._sync_attendance()
        desynced = in1.hr_attendance_id
        in1.write({
            'reconciliation_status': 'needs_review',
            'reconciliation_note': 'Missing checkout; later attendance days continue syncing independently.',
        })
        self.env.cr.execute(
            """
            UPDATE hr_attendance
               SET check_out = check_in,
                   checkout_device_id = NULL,
                   worked_hours = 9.0
             WHERE id = %s
            """,
            [desynced.id],
        )
        if 'attendance_day_status' in desynced._fields:
            self.env.cr.execute(
                """
                UPDATE hr_attendance
                   SET attendance_day_status = 'absent',
                       attendance_status_reason = 'The missing daily punch was not resolved before midnight.'
                 WHERE id = %s
                """,
                [desynced.id],
            )
        desynced.invalidate_recordset()

        # 2) Genuine single-punch sentinel with no checkout punch.
        in2 = self._punch(self.bio_user, '2026-09-15 05:30:00', 0)
        in2._sync_attendance()
        genuine_missing = in2.hr_attendance_id
        self.env.cr.execute(
            """
            UPDATE hr_attendance
               SET check_out = check_in,
                   worked_hours = 0.0
             WHERE id = %s
            """,
            [genuine_missing.id],
        )
        if 'attendance_day_status' in genuine_missing._fields:
            self.env.cr.execute(
                """
                UPDATE hr_attendance
                   SET attendance_day_status = 'absent',
                       attendance_status_reason = 'The missing daily punch was not resolved before midnight.'
                 WHERE id = %s
                """,
                [genuine_missing.id],
            )
        genuine_missing.invalidate_recordset()

        repaired = self.env['user.attendance']._repair_desynced_checkouts()
        self.assertEqual(repaired, 1)

        desynced.invalidate_recordset()
        genuine_missing.invalidate_recordset()
        self.assertEqual(desynced.check_out, datetime(2026, 9, 14, 14, 30, 0))
        self.assertEqual(desynced.checkout_device_id, self.device)
        self.assertAlmostEqual(desynced.worked_hours, 9.0, places=2)
        self.assertEqual(in1.reconciliation_status, 'synced')
        self.assertFalse(in1.reconciliation_note)
        if 'attendance_day_status' in desynced._fields:
            self.assertEqual(desynced.attendance_day_status, 'normal')
            self.assertFalse(desynced.attendance_status_reason)

        self.assertEqual(genuine_missing.check_out, genuine_missing.check_in)
        self.assertEqual(genuine_missing.worked_hours, 0.0)
        if 'attendance_day_status' in genuine_missing._fields:
            self.assertEqual(genuine_missing.attendance_day_status, 'absent')

        # Second pass is a complete no-op.
        self.assertEqual(self.env['user.attendance']._repair_desynced_checkouts(), 0)

