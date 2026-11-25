import logging
from datetime import datetime

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)

EMPLOYEE_ID = 143
EMPLOYEE_NAME = 'Shahd Saied Bin Mousa'
CHECKIN_PUNCH_ID, CHECKIN = 3156, datetime(2026, 10, 29, 4, 54, 37)  # 07:54:37 Riyadh
CHECKOUT_PUNCH_ID, CHECKOUT = 3164, datetime(2026, 10, 29, 13, 56, 4)  # 16:56:04 Riyadh
DAY_START, DAY_END = '2026-10-28 21:00:00', '2026-10-29 21:00:00'


class RepairSkipped(Exception):
    pass


def _require(condition, message):
    if not condition:
        raise RepairSkipped(message)


def _repair(env):
    Attendance = env['hr.attendance']
    _require(
        'attendance_day_status' in Attendance._fields
        and 'attendance_entry_source' in Attendance._fields,
        'attendance status fields are not installed',
    )
    # Serialize with the device synchronization of these punches.
    env.cr.execute(
        'SELECT id FROM user_attendance WHERE id IN %s FOR UPDATE',
        [(CHECKIN_PUNCH_ID, CHECKOUT_PUNCH_ID)],
    )
    employee = env['hr.employee'].with_context(active_test=False).browse(EMPLOYEE_ID).exists()
    _require(employee and employee.name == EMPLOYEE_NAME, 'employee not found')
    checkin = env['user.attendance'].browse(CHECKIN_PUNCH_ID).exists()
    checkout = env['user.attendance'].browse(CHECKOUT_PUNCH_ID).exists()
    for punch, expected in ((checkin, CHECKIN), (checkout, CHECKOUT)):
        _require(
            punch and punch.employee_id == employee and punch.timestamp == expected,
            'the device punches are not as expected',
        )
    _require(
        not checkin._has_attendance_replacing_leave_for_day(CHECKIN.date()),
        'an approved leave covers the day',
    )

    domain = [
        ('employee_id', '=', employee.id),
        ('check_in', '>=', DAY_START),
        ('check_in', '<', DAY_END),
    ]
    attendances = Attendance.search(domain)
    attendance = checkout.hr_attendance_id
    duplicate = attendances - attendance
    _require(
        attendance and attendance in attendances and len(duplicate) <= 1,
        'unexpected attendance records %s' % attendances.ids,
    )
    if not duplicate and attendance.check_in == CHECKIN and attendance.check_out == CHECKOUT:
        raise RepairSkipped('already repaired')
    _require(
        attendance.check_in == CHECKOUT
        and (not attendance.check_out or attendance.check_out == CHECKOUT),
        'attendance %s is not as expected' % attendance.id,
    )
    _require(
        all(att.attendance_entry_source == 'biometric' for att in attendances),
        'a non-biometric attendance exists on the day',
    )
    _require(
        checkin.hr_attendance_id == duplicate,
        'the morning punch is linked to an unexpected attendance',
    )
    if duplicate:
        # Left by a manual re-sync of the morning punch.
        _require(
            duplicate.check_in == CHECKIN
            and (not duplicate.check_out or duplicate.check_out == CHECKIN),
            'attendance %s is not a removable duplicate' % duplicate.id,
        )
        duplicate.with_context(attendance_policy_source='biometric').unlink()

    attendance.with_context(
        sync_from_device=True,
        not_manual_check_out_modification=True,
        allow_late_attendance=True,
        attendance_policy_source='biometric',
    ).write({
        'check_in': CHECKIN,
        'checkin_device_id': checkin.device_id.id,
        'check_out': CHECKOUT,
        'checkout_device_id': checkout.device_id.id,
    })
    note = 'Migration 17.0.1.3.3: check-in and check-out joined in one attendance.'
    checkin._mark_reconciled('synced', interpreted_type='checkin', attendance=attendance, note=note)
    checkout._mark_reconciled('synced', interpreted_type='checkout', attendance=attendance, note=note)
    env.flush_all()
    _require(
        Attendance.search(domain) == attendance
        and attendance.attendance_day_status == 'normal',
        'the repaired attendance is still %s' % attendance.attendance_day_status,
    )
    return attendance


def migrate(cr, version):
    """Restore the 29 Oct 2026 attendance deleted by a future leave approval.

    Runs as an end script because the daily status belongs to pr_hr_attendance,
    which may be loaded after this module. Any unexpected situation is logged
    and skipped, so it can never block the upgrade.
    """
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    try:
        with cr.savepoint():
            attendance = _repair(env)
    except RepairSkipped as reason:
        _logger.info('29 Oct 2026 attendance repair skipped: %s.', reason)
    except Exception:
        _logger.exception('29 Oct 2026 attendance repair failed; nothing was changed.')
    else:
        _logger.info('29 Oct 2026 attendance repaired: hr.attendance %s.', attendance.id)
