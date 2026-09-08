from datetime import datetime

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestMissingCheckout(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        calendar = cls.env['resource.calendar'].create({'name': 'Riyadh test', 'tz': 'Asia/Riyadh'})
        vals = {'name': 'Missing checkout test', 'resource_calendar_id': calendar.id}
        if 'compute_attendance' in cls.env['hr.employee']._fields:
            vals['compute_attendance'] = True
        cls.employee = cls.env['hr.employee'].create(vals)
        location = cls.env['attendance.device.location'].create({
            'name': 'Test gate', 'tz': 'Asia/Riyadh',
            'hr_work_location_id': cls.env['hr.work.location'].create({'name': 'Test site'}).id,
        })
        cls.device = cls.env['attendance.device'].create({'name': 'Test device', 'location_id': location.id})
        cls.device_user = cls.env['attendance.device.user'].create({
            'name': cls.employee.name, 'device_id': cls.device.id,
            'employee_id': cls.employee.id, 'user_id': '99123', 'uid': 99123,
        })

    def punch(self, timestamp, code=0):
        state = self.env.ref('pr_attendance_device.attendance_device_state_code_%s' % code)
        return self.env['user.attendance'].create({
            'device_id': self.device.id, 'user_id': self.device_user.id,
            'timestamp': timestamp, 'status': code, 'attendance_state_id': state.id,
        })

    def test_later_day_syncs_and_old_day_can_be_corrected(self):
        old = self.punch('2026-09-01 05:00:00')
        old._sync_attendance()
        original = old.hr_attendance_id
        incoming = self.punch('2026-09-02 05:00:00', 1)
        outgoing = self.punch('2026-09-02 14:00:00', 0)
        (outgoing | incoming)._sync_attendance()
        self.assertTrue(incoming.synced)
        self.assertEqual(incoming.hr_attendance_id, outgoing.hr_attendance_id)
        self.assertNotEqual(original, incoming.hr_attendance_id)
        self.assertFalse(original.check_out)
        self.assertEqual(old.reconciliation_status, 'needs_review')
        self.assertEqual(incoming.hr_attendance_id.check_out, datetime(2026, 9, 2, 14))
        (old | incoming | outgoing)._sync_attendance()
        self.assertEqual(old.hr_attendance_id, original)
        self.assertFalse(original.check_out)
        # Same operation used by an approved shortage: real checkout supplied later.
        original.sudo().with_context(attendance_policy_source='approved_shortage', allow_late_attendance=True).write({
            'check_out': datetime(2026, 9, 1, 14),
        })
        self.assertEqual(incoming.hr_attendance_id.check_in, datetime(2026, 9, 2, 5))
        self.assertEqual(original.check_out, datetime(2026, 9, 1, 14))

    def test_multiple_unresolved_days_and_backlog_retry(self):
        first = self.punch('2026-09-01 05:00:00')
        first._sync_attendance()
        second = self.punch('2026-09-02 05:00:00')
        second.write({
            'reconciliation_status': 'needs_review',
            'reconciliation_note': 'A previous-day attendance is still open. Resolve its missing checkout first.',
        })
        domain = self.env['user.attendance']._prepare_unsynch_data_domain()
        self.assertIn(second, self.env['user.attendance'].search(domain))
        second._sync_attendance()
        third = self.punch('2026-09-03 05:00:00')
        third._sync_attendance()
        self.assertEqual(len((first | second | third).mapped('hr_attendance_id')), 3)
        self.assertTrue(all((first | second | third).mapped('synced')))
        self.assertFalse(first.hr_attendance_id.check_out)
        self.assertFalse(second.hr_attendance_id.check_out)

    def test_local_day_boundary_and_late_old_checkout(self):
        # Both check-ins have the same UTC date but different Riyadh dates.
        first = self.punch('2026-09-01 18:00:00')
        second = self.punch('2026-09-01 22:00:00')
        (first | second)._sync_attendance()
        self.assertNotEqual(first.hr_attendance_id, second.hr_attendance_id)
        late_checkout = self.punch('2026-09-01 20:00:00', 1)
        late_checkout._sync_attendance()
        self.assertEqual(late_checkout.hr_attendance_id, first.hr_attendance_id)
        self.assertFalse(second.hr_attendance_id.check_out)
