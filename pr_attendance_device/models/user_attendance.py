import logging
from datetime import datetime, time, timedelta
import random
import pytz

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo import tools

_logger = logging.getLogger(__name__)


class UserAttendance(models.Model):
    _name = 'user.attendance'
    _description = 'User Attendance'
    _order = 'timestamp DESC, user_id, status, attendance_state_id, device_id'

    device_id = fields.Many2one('attendance.device', string='Attendance Machine', required=True, ondelete='restrict',
                                index=True)
    user_id = fields.Many2one('attendance.device.user', string='Machine User', required=True, ondelete='cascade',
                              index=True)
    timestamp = fields.Datetime(string='Timestamp', required=True, index=True,
                                help="The date and time at which the employee took a check in/out action at the attendance machine")
    status = fields.Integer(string='Machine Attendance State', required=True,
                            help="The state which is the unique number stored in the machine to"
                                 " indicate type of attendance (e.g. 0: Checkin, 1: Checkout, etc)")
    attendance_state_id = fields.Many2one('attendance.state', string='Software Attendance State',
                                          help="This technical field is to map the attendance"
                                               " status stored in the machine and the attendance status in System",
                                          required=True, index=True)
    activity_id = fields.Many2one('attendance.activity', related='attendance_state_id.activity_id', store=True,
                                  index=True)
    hr_attendance_id = fields.Many2one('hr.attendance', string='HR Attendance', ondelete='set null',
                                       help="The technical field to link Machine Attendance Data with System Attendance Data",
                                       index=True)

    type = fields.Selection(string='Activity Type', related='attendance_state_id.type', store=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', related='user_id.employee_id', store=True,
                                  index=True)
    synced = fields.Boolean(string='Synced',
                            help="This field is to indicate whether the attendance data is synchronized to System or not")
    interpreted_type = fields.Selection(
        [('checkin', 'Check-in'), ('checkout', 'Check-out')],
        string='Interpreted Type',
        copy=False,
        index=True,
        help='The punch type selected by the reconciliation engine. The original machine type is preserved separately.',
    )
    reconciliation_status = fields.Selection(
        [
            ('pending', 'Pending'),
            ('synced', 'Synced'),
            ('auto_corrected', 'Auto-corrected'),
            ('duplicate', 'Duplicate'),
            ('needs_review', 'Needs Review'),
        ],
        string='Reconciliation Status',
        default='pending',
        required=True,
        copy=False,
        index=True,
    )
    reconciliation_note = fields.Char(string='Reconciliation Note', copy=False)
    reconciled_at = fields.Datetime(string='Reconciled At', copy=False)
    reconciled_by_id = fields.Many2one('res.users', string='Reconciled By', copy=False)

    _sql_constraints = [
        ('unique_user_id_device_id_timestamp',
         'UNIQUE(user_id, device_id, timestamp)',
         "The Timestamp and User must be unique per machine"),
    ]

    @api.constrains('status', 'attendance_state_id')
    def constrains_status_attendance_state_id(self):
        for r in self:
            if r.status != r.attendance_state_id.code:
                raise ValidationError(
                    _("Attendance Status conflict! The status number from machine must match the attendance status defined in System."))

    def _prepare_last_hr_attendance_domain(self):
        self.ensure_one()
        return [
            ('employee_id', '=', self.employee_id.id),
            ('check_in', '<=', self.timestamp),
            ('activity_id', 'in', [False, self.activity_id.id]),
        ]

    def _get_last_hr_attendance(self, user_attendance, hr_attendances):
        last_hr_attendance = hr_attendances.filtered(
            lambda hr_att: hr_att.employee_id == user_attendance.employee_id
                           and hr_att.checkin_device_id
                           and hr_att.check_in <= user_attendance.timestamp
                           and (hr_att.activity_id == user_attendance.activity_id
                                or not hr_att.activity_id)).sorted('check_in')
        return last_hr_attendance and last_hr_attendance[-1:] or False

    def _prepare_hr_attendance_vals(self):
        return {
            'employee_id': self.employee_id.id,
            'check_in': self.timestamp,
            'checkin_device_id': self.device_id.id,
            'activity_id': self.activity_id.id,
        }

    def _create_hr_attendance(self):
        vals_list = []
        for r in self:
            vals_list.append(r._prepare_hr_attendance_vals())
        return self.env['hr.attendance'].sudo().with_context(
            sync_from_device=True,
            attendance_policy_source='biometric',
        ).create(vals_list)

    @api.model
    def _reconciliation_duplicate_minutes(self):
        return max(
            int(self.env['ir.config_parameter'].sudo().get_param(
                'pr_attendance_device.duplicate_punch_minutes',
                3,
            )),
            0,
        )

    def _local_day_bounds(self):
        self.ensure_one()
        tz_name = (
            self.employee_id.user_id.tz
            or self.employee_id.resource_calendar_id.tz
            or self.device_id.tz
            or self.env.company.partner_id.tz
            or 'Asia/Riyadh'
        )
        timezone = pytz.timezone(tz_name)
        timestamp_utc = pytz.UTC.localize(fields.Datetime.to_datetime(self.timestamp))
        local_date = timestamp_utc.astimezone(timezone).date()
        local_start = timezone.localize(datetime.combine(local_date, time.min))
        local_end = local_start + timedelta(days=1)
        return (
            local_date,
            local_start.astimezone(pytz.UTC).replace(tzinfo=None),
            local_end.astimezone(pytz.UTC).replace(tzinfo=None),
        )

    def _previous_raw_punch(self):
        self.ensure_one()
        return self.search([
            ('id', '!=', self.id),
            ('employee_id', '=', self.employee_id.id),
            ('activity_id', '=', self.activity_id.id),
            ('timestamp', '<=', self.timestamp),
        ], order='timestamp desc, id desc', limit=1)

    def _is_duplicate_punch(self):
        self.ensure_one()
        previous = self._previous_raw_punch()
        if not previous:
            return False
        seconds = (
            fields.Datetime.to_datetime(self.timestamp)
            - fields.Datetime.to_datetime(previous.timestamp)
        ).total_seconds()
        return 0 <= seconds <= self._reconciliation_duplicate_minutes() * 60

    def _attendance_domain_for_day(self):
        self.ensure_one()
        _local_date, day_start, day_end = self._local_day_bounds()
        return [
            ('employee_id', '=', self.employee_id.id),
            ('activity_id', 'in', [False, self.activity_id.id]),
            ('check_in', '>=', fields.Datetime.to_string(day_start)),
            ('check_in', '<', fields.Datetime.to_string(day_end)),
        ]

    def _mark_reconciled(self, status, interpreted_type=False, attendance=False, note=False):
        self.ensure_one()
        successful = status in ('synced', 'auto_corrected') and bool(attendance)
        self.write({
            'synced': successful,
            'reconciliation_status': status,
            'interpreted_type': interpreted_type or False,
            'hr_attendance_id': attendance.id if attendance else False,
            'reconciliation_note': note or False,
            'reconciled_at': fields.Datetime.now(),
            'reconciled_by_id': self.env.user.id,
        })

    def _reconcile_single_punch(self):
        """Interpret one immutable raw punch using the employee's session state."""
        self.ensure_one()
        if not self.employee_id:
            self._mark_reconciled(
                'needs_review',
                note=_('The machine user is not mapped to an employee.'),
            )
            return self.env['hr.attendance']

        if self._is_duplicate_punch():
            self._mark_reconciled(
                'duplicate',
                note=_('Ignored within the duplicate-punch tolerance.'),
            )
            return self.env['hr.attendance']

        Attendance = self.env['hr.attendance'].sudo()
        timestamp = fields.Datetime.to_datetime(self.timestamp)
        open_attendance = Attendance.search([
            ('employee_id', '=', self.employee_id.id),
            ('activity_id', 'in', [False, self.activity_id.id]),
            ('check_out', '=', False),
            ('check_in', '<=', self.timestamp),
        ], order='check_in desc, id desc', limit=1)

        if open_attendance:
            open_checkin = fields.Datetime.to_datetime(open_attendance.check_in)
            _local_date, day_start, day_end = self._local_day_bounds()
            if not (day_start <= open_checkin < day_end):
                linked_raw = self.search([
                    ('hr_attendance_id', '=', open_attendance.id),
                    ('interpreted_type', '=', 'checkin'),
                ], order='timestamp asc, id asc', limit=1)
                if linked_raw:
                    linked_raw.write({
                        'reconciliation_status': 'needs_review',
                        'reconciliation_note': _('Missing checkout before the next attendance day.'),
                    })
                self._mark_reconciled(
                    'needs_review',
                    note=_('A previous-day attendance is still open. Resolve its missing checkout first.'),
                )
                return self.env['hr.attendance']

            if timestamp <= open_checkin:
                self._mark_reconciled(
                    'needs_review',
                    note=_('Punch time is not later than the open check-in.'),
                )
                return self.env['hr.attendance']

            open_attendance.with_context(
                not_manual_check_out_modification=True,
                sync_from_device=True,
                attendance_policy_source='biometric',
            ).write({
                'check_out': self.timestamp,
                'checkout_device_id': self.device_id.id,
            })
            corrected = self.type != 'checkout'
            self._mark_reconciled(
                'auto_corrected' if corrected else 'synced',
                interpreted_type='checkout',
                attendance=open_attendance,
                note=_('Machine Check-in interpreted as Check-out because a session was already open.')
                if corrected else False,
            )
            return open_attendance

        closed_attendance = Attendance.search(
            self._attendance_domain_for_day() + [('check_out', '!=', False)],
            order='check_out desc, id desc',
            limit=1,
        )

        # Multiple checkout punches without an intervening check-in extend the
        # latest same-day session to the final checkout.
        if self.type == 'checkout' and closed_attendance:
            closed_checkout = fields.Datetime.to_datetime(closed_attendance.check_out)
            if timestamp > closed_checkout:
                closed_attendance.with_context(
                    not_manual_check_out_modification=True,
                    sync_from_device=True,
                    attendance_policy_source='biometric',
                ).write({
                    'check_out': self.timestamp,
                    'checkout_device_id': self.device_id.id,
                })
                self._mark_reconciled(
                    'auto_corrected',
                    interpreted_type='checkout',
                    attendance=closed_attendance,
                    note=_('Extended the latest same-day session to the final checkout punch.'),
                )
                return closed_attendance

        # With no open session, a normal Check-in starts a split session. A
        # first-of-day Checkout is treated as an accidentally labelled Check-in.
        if self.type == 'checkin' or not closed_attendance:
            attendance = self._create_hr_attendance()
            corrected = self.type != 'checkin'
            self._mark_reconciled(
                'auto_corrected' if corrected else 'synced',
                interpreted_type='checkin',
                attendance=attendance,
                note=_('First punch interpreted as Check-in despite the machine Checkout state.')
                if corrected else False,
            )
            return attendance

        self._mark_reconciled(
            'needs_review',
            note=_('The punch could not be reconciled safely.'),
        )
        return self.env['hr.attendance']

    def _sync_attendance(self):
        """Central reconciliation entry point for cron, API, and manual sync."""
        error_msg = {}
        punches = self.sorted(lambda punch: (punch.timestamp, punch.id))
        for punch in punches:
            if (
                punch.hr_attendance_id
                and punch.reconciliation_status in ('synced', 'auto_corrected')
            ):
                continue
            try:
                with self.env.cr.savepoint(flush=False), tools.mute_logger('odoo.sql_db'):
                    punch._reconcile_single_punch()
                    self.flush_recordset()
            except Exception as error:
                punch._mark_reconciled(
                    'needs_review',
                    note=str(error),
                )
                error_msg.setdefault(punch.device_id, [])
                if str(error) not in error_msg[punch.device_id]:
                    error_msg[punch.device_id].append(str(error))
        if bool(error_msg):
            for device, msg_list in error_msg.items():
                device.message_post(body="<ol>%s</ol>" % "".join(["<li>%s</li>" % msg for msg in msg_list]))

    def action_sync_attendance(self):
        retryable = self.filtered(lambda punch: not punch.hr_attendance_id)
        retryable.write({
            'synced': False,
            'reconciliation_status': 'pending',
            'reconciliation_note': False,
        })
        self._sync_attendance()

    def action_mark_duplicate(self):
        for punch in self:
            punch._mark_reconciled(
                'duplicate',
                note=_('Marked as duplicate by %s.') % self.env.user.display_name,
            )

    def action_apply_interpretation(self):
        """Apply the type explicitly selected by HR on reviewed punches."""
        Attendance = self.env['hr.attendance'].sudo()
        for punch in self.sorted(lambda item: (item.timestamp, item.id)):
            if not punch.interpreted_type:
                punch._mark_reconciled(
                    'needs_review',
                    note=_('Select an Interpreted Type before applying the correction.'),
                )
                continue

            open_attendance = Attendance.search([
                ('employee_id', '=', punch.employee_id.id),
                ('activity_id', 'in', [False, punch.activity_id.id]),
                ('check_out', '=', False),
                ('check_in', '<=', punch.timestamp),
            ], order='check_in desc, id desc', limit=1)

            if punch.interpreted_type == 'checkin':
                if open_attendance:
                    punch._mark_reconciled(
                        'needs_review',
                        note=_('An attendance session is already open for this employee.'),
                    )
                    continue
                attendance = punch._create_hr_attendance()
                punch._mark_reconciled(
                    'auto_corrected',
                    interpreted_type='checkin',
                    attendance=attendance,
                    note=_('HR applied this punch manually as Check-in.'),
                )
                continue

            if open_attendance:
                _local_date, day_start, day_end = punch._local_day_bounds()
                open_checkin = fields.Datetime.to_datetime(open_attendance.check_in)
                if not (day_start <= open_checkin < day_end):
                    punch._mark_reconciled(
                        'needs_review',
                        note=_('The open attendance belongs to a previous day.'),
                    )
                    continue
                attendance = open_attendance
            else:
                attendance = Attendance.search(
                    punch._attendance_domain_for_day() + [('check_out', '!=', False)],
                    order='check_out desc, id desc',
                    limit=1,
                )

            if not attendance or punch.timestamp <= attendance.check_in:
                punch._mark_reconciled(
                    'needs_review',
                    note=_('No valid same-day attendance was found for this Checkout.'),
                )
                continue

            attendance.with_context(
                not_manual_check_out_modification=True,
                sync_from_device=True,
                attendance_policy_source='biometric',
            ).write({
                'check_out': punch.timestamp,
                'checkout_device_id': punch.device_id.id,
            })
            punch._mark_reconciled(
                'auto_corrected',
                interpreted_type='checkout',
                attendance=attendance,
                note=_('HR applied this punch manually as Check-out.'),
            )

    def action_reset_reconciliation(self):
        self.filtered(lambda punch: not punch.hr_attendance_id).write({
            'synced': False,
            'reconciliation_status': 'pending',
            'interpreted_type': False,
            'reconciliation_note': False,
            'reconciled_at': False,
            'reconciled_by_id': False,
        })

    @api.model
    def _prepare_unsynch_data_domain(self):
        return [
            ('hr_attendance_id', '=', False),
            ('employee_id', '!=', False),
            ('synced', '=', False),
            ('reconciliation_status', '=', 'pending'),
        ]

    @api.model
    def _cron_synch_hr_attendance(self):
        unsync_data = self.env['user.attendance'].search(self._prepare_unsynch_data_domain())
        unsync_data._sync_attendance()

    @api.model
    def _migrate_legacy_reconciliation_statuses(self):
        """Classify records created before reconciliation auditing existed."""
        legacy_domain = [
            ('reconciliation_status', '=', 'pending'),
            ('reconciled_at', '=', False),
        ]
        linked = self.search(legacy_domain + [('hr_attendance_id', '!=', False)])
        for punch_type in ('checkin', 'checkout'):
            linked.filtered(lambda punch: punch.type == punch_type).write({
                'reconciliation_status': 'synced',
                'interpreted_type': punch_type,
                'reconciliation_note': _('Migrated from the legacy synchronization engine.'),
            })

        unmatched_success = self.search(
            legacy_domain
            + [('hr_attendance_id', '=', False), ('synced', '=', True)]
        )
        unmatched_success.write({
            'synced': False,
            'reconciliation_status': 'needs_review',
            'reconciliation_note': _(
                'Legacy synchronization marked this punch successful without linking an HR attendance.'
            ),
        })
        return True

    @api.model
    def _get_checkin_leverage_tz(self):
        return (
                self.env['ir.config_parameter'].sudo().get_param('pr_attendance_device.checkin_leverage_tz')
                or self.env.user.tz
                or self.env.company.partner_id.tz
                or 'Asia/Riyadh'
        )

    @api.model
    def _apply_checkin_leverage_for_date(self, target_date, tz_name):

        seconds = random.randint(0, 59)
        minutes = random.randint(57, 59)
        leverage_start_local = datetime.combine(target_date, time(9, 0, 0))
        leverage_end_local = datetime.combine(target_date, time(9, 4, 0))
        normalized_checkin_local = datetime.combine(target_date, time(8, minutes, seconds))

        leverage_start_utc = fields.Datetime.to_datetime(
            self.env['to.base'].convert_local_to_utc(leverage_start_local, force_local_tz_name=tz_name, naive=True)
        )
        leverage_end_utc = fields.Datetime.to_datetime(
            self.env['to.base'].convert_local_to_utc(leverage_end_local, force_local_tz_name=tz_name, naive=True)
        )
        normalized_checkin_utc = fields.Datetime.to_datetime(
            self.env['to.base'].convert_local_to_utc(normalized_checkin_local, force_local_tz_name=tz_name, naive=True)
        )

        hr_attendances = self.env['hr.attendance'].search([
            ('check_in', '>=', leverage_start_utc),
            ('check_in', '<', leverage_end_utc),
        ])
        if hr_attendances:
            hr_attendances.sudo().with_context(
                sync_from_device=True,
                attendance_policy_source='biometric',
            ).write({'check_in': normalized_checkin_utc})

        user_attendances = self.search([
            ('timestamp', '>=', leverage_start_utc),
            ('timestamp', '<', leverage_end_utc),
            ('type', '=', 'checkin'),
        ])
        if user_attendances:
            user_attendances.write({'timestamp': normalized_checkin_utc})
        return len(hr_attendances), len(user_attendances)

    @api.model
    def _cron_apply_checkin_leverage(self):

        tz_name = self._get_checkin_leverage_tz()
        now_local = fields.Datetime.context_timestamp(self.with_context(tz=tz_name), fields.Datetime.now())
        today = now_local.date()
        yesterday = today - timedelta(days=1)

        hr_count_today, user_count_today = self._apply_checkin_leverage_for_date(today, tz_name)
        hr_count_yesterday, user_count_yesterday = self._apply_checkin_leverage_for_date(yesterday, tz_name)

        _logger.info(
            "Check-in leverage applied in TZ %s. Updated hr.attendance: today=%s, yesterday=%s | "
            "user.attendance: today=%s, yesterday=%s",
            tz_name, hr_count_today, hr_count_yesterday, user_count_today, user_count_yesterday
        )

    @api.model
    def _pr_cleanup_checkin_leverage_cron(self):
        xml_id = 'pr_attendance_device.ir_cron_scheduler_checkin_leverage'
        cron = self.env.ref(xml_id, raise_if_not_found=False)
        if cron and cron.exists():
            cron.sudo().unlink()

        self.env['ir.cron'].sudo().search([
            ('code', '=', 'model._cron_apply_checkin_leverage()'),
        ]).unlink()
        self.env['ir.model.data'].sudo().search([
            ('module', '=', 'pr_attendance_device'),
            ('name', '=', 'ir_cron_scheduler_checkin_leverage'),
        ]).unlink()
        return True
