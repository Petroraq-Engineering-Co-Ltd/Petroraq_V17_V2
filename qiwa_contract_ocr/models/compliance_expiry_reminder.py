from datetime import timedelta
import logging

from odoo import _, api, fields, models


_logger = logging.getLogger(__name__)


class HRComplianceExpiryReminderLog(models.Model):
    _name = 'hr.compliance.expiry.reminder.log'
    _description = 'HR Compliance Expiry Reminder Log'
    _order = 'sent_date desc, id desc'

    name = fields.Char(required=True)
    model_name = fields.Char(required=True, index=True)
    res_id = fields.Integer(required=True, index=True)
    expiry_field = fields.Char(required=True)
    expiry_date = fields.Date(required=True, index=True)
    reminder_days = fields.Integer(required=True, index=True)
    sent_date = fields.Date(required=True, default=fields.Date.context_today, index=True)
    recipient_user_ids = fields.Many2many('res.users', string='Recipients', readonly=True)

    _sql_constraints = [
        (
            'unique_expiry_reminder',
            'unique(model_name, res_id, expiry_field, expiry_date, reminder_days)',
            'This expiry reminder has already been sent.',
        ),
    ]

    @api.model
    def get_reminder_dashboard_data(self):
        today = fields.Date.context_today(self)
        soon_date = today + timedelta(days=30)
        critical_date = today + timedelta(days=10)
        week_date = today + timedelta(days=7)
        month_start = today.replace(day=1)

        open_task_domain = [
            ('is_required', '=', True),
            ('task_state', 'in', ['pending', 'in_progress', 'overdue']),
        ]
        overdue_task_domain = open_task_domain + [
            '|',
            ('task_state', '=', 'overdue'),
            ('due_date', '<', self._date_to_string(today)),
        ]
        upcoming_task_domain = open_task_domain + [
            ('due_date', '>=', self._date_to_string(today)),
            ('due_date', '<=', self._date_to_string(week_date)),
        ]
        pending_compliance_domain = [
            ('state', 'in', ['hr_manager_approval', 'md_approval']),
        ]
        pending_payment_domain = [
            ('payment_state', '=', 'pending'),
        ]
        reminder_log_domain = [
            ('sent_date', '>=', self._date_to_string(month_start)),
        ]
        activity_domain = self._get_dashboard_activity_domain(today)

        expired_count = self._count_expiry_documents(before=today)
        expiring_count = self._count_expiry_documents(from_date=today, to_date=soon_date)
        critical_count = self._count_expiry_documents(from_date=today, to_date=critical_date)

        tiles = [
            self._dashboard_tile(
                'expired_documents',
                _('Expired Documents'),
                expired_count,
                _('Iqama, work permit, and insurance records already past expiry.'),
                'fa-exclamation-triangle',
                'danger',
            ),
            self._dashboard_tile(
                'expiring_documents',
                _('Expiring in 30 Days'),
                expiring_count,
                _('Compliance documents inside the renewal window.'),
                'fa-clock-o',
                'warning',
            ),
            self._dashboard_tile(
                'critical_documents',
                _('Critical 10 Days'),
                critical_count,
                _('Documents that need urgent follow-up.'),
                'fa-bell',
                'critical',
            ),
            self._dashboard_tile(
                'open_activities',
                _('Open Activities'),
                self.env['mail.activity'].sudo().search_count(activity_domain),
                _('Reminder activities assigned to you.'),
                'fa-tasks',
                'info',
                'mail.activity',
                activity_domain,
            ),
            self._dashboard_tile(
                'overdue_tasks',
                _('Overdue Tasks'),
                self.env['hr.applicant.onboarding.checklist'].sudo().search_count(overdue_task_domain),
                _('Onboarding reminder tasks past their due date.'),
                'fa-calendar-times-o',
                'danger',
                'hr.applicant.onboarding.checklist',
                overdue_task_domain,
            ),
            self._dashboard_tile(
                'upcoming_tasks',
                _('Upcoming Tasks'),
                self.env['hr.applicant.onboarding.checklist'].sudo().search_count(upcoming_task_domain),
                _('Open onboarding tasks due in the next 7 days.'),
                'fa-calendar-check-o',
                'success',
                'hr.applicant.onboarding.checklist',
                upcoming_task_domain,
            ),
            self._dashboard_tile(
                'pending_approvals',
                _('Pending Approvals'),
                self.env['hr.onboarding.compliance.request'].sudo().search_count(pending_compliance_domain),
                _('Compliance requests waiting for HR Manager or MD.'),
                'fa-check-square-o',
                'primary',
                'hr.onboarding.compliance.request',
                pending_compliance_domain,
            ),
            self._dashboard_tile(
                'pending_payments',
                _('Pending Payments'),
                self.env['hr.onboarding.compliance.request'].sudo().search_count(pending_payment_domain),
                _('Approved requests already sent to accounting.'),
                'fa-money',
                'warning',
                'hr.onboarding.compliance.request',
                pending_payment_domain,
            ),
            self._dashboard_tile(
                'sent_reminders',
                _('Reminders Sent'),
                self.sudo().search_count(reminder_log_domain),
                _('Expiry reminders sent during this month.'),
                'fa-envelope-o',
                'muted',
                'hr.compliance.expiry.reminder.log',
                reminder_log_domain,
            ),
        ]

        return {
            'today': self._date_to_string(today),
            'tiles': tiles,
            'expiry_rows': self._get_dashboard_expiry_rows(today, soon_date),
            'task_rows': self._get_dashboard_task_rows(open_task_domain),
            'activity_rows': self._get_dashboard_activity_rows(activity_domain),
        }

    @api.model
    def _cron_send_expiry_reminders(self):
        today = fields.Date.context_today(self)
        reminder_days = (30, 20, 10)
        supervisor_users = self._get_supervisor_users()
        if not supervisor_users:
            return True

        specs = self._get_expiry_specs()
        for days in reminder_days:
            target_date = today + timedelta(days=days)
            for spec in specs:
                self._send_due_reminders_for_spec(spec, target_date, days, today, supervisor_users)
        return True

    @api.model
    def _get_expiry_specs(self):
        return [
            {
                'model': 'hr.employee.iqama',
                'field': 'expiry_date',
                'label': _('Iqama'),
                'domain': [('active', '=', True), ('state', 'in', ['approve', 'valid', 'expired'])],
            },
            {
                'model': 'hr.employee.medical.insurance',
                'field': 'expiry_date',
                'label': _('Medical Insurance'),
                'domain': [('active', '=', True), ('state', 'in', ['approve', 'valid', 'expired'])],
            },
            {
                'model': 'hr.work.permit',
                'field': 'work_permit_expiry_date',
                'label': _('Work Permit'),
                'domain': [('state', 'in', ['approved', 'issued'])],
            },
            {
                'model': 'hr.work.permit',
                'field': 'iqama_expiry_date',
                'label': _('Work Permit Iqama'),
                'domain': [('state', 'in', ['approved', 'issued'])],
                'skip_if_same_as': 'work_permit_expiry_date',
            },
        ]

    @api.model
    def _dashboard_tile(self, key, title, count, subtitle, icon, tone, model=False, domain=False):
        return {
            'key': key,
            'title': title,
            'count': count,
            'subtitle': subtitle,
            'icon': icon,
            'tone': tone,
            'model': model,
            'domain': domain or [],
        }

    @api.model
    def _date_to_string(self, value):
        return fields.Date.to_string(value) if value else False

    @api.model
    def _count_expiry_documents(self, from_date=False, to_date=False, before=False):
        return len(self._get_expiry_records(from_date=from_date, to_date=to_date, before=before, limit=False))

    @api.model
    def _get_expiry_records(self, from_date=False, to_date=False, before=False, limit=8):
        rows = []
        for spec in self._get_expiry_specs():
            model_name = spec['model']
            model_ref = self.env['ir.model']._get(model_name)
            if not model_ref:
                continue

            model = self.env[model_name].sudo()
            expiry_field = spec['field']
            if expiry_field not in model._fields:
                continue

            domain = list(spec.get('domain', []))
            if before:
                domain.append((expiry_field, '<', self._date_to_string(before)))
            if from_date:
                domain.append((expiry_field, '>=', self._date_to_string(from_date)))
            if to_date:
                domain.append((expiry_field, '<=', self._date_to_string(to_date)))

            for record in model.search(domain, order='%s asc, id desc' % expiry_field):
                expiry_date = record[expiry_field]
                skip_field = spec.get('skip_if_same_as')
                if skip_field and skip_field in record._fields and record[skip_field] == expiry_date:
                    continue
                rows.append((record, spec, expiry_date))

        rows.sort(key=lambda item: (item[2] or fields.Date.today(), item[0]._name, item[0].id))
        return rows[:limit] if limit else rows

    @api.model
    def _get_dashboard_expiry_rows(self, today, soon_date):
        rows = []
        for record, spec, expiry_date in self._get_expiry_records(to_date=soon_date, limit=10):
            days_left = (expiry_date - today).days if expiry_date else 0
            rows.append({
                'id': '%s-%s-%s' % (record._name, record.id, spec['field']),
                'model': record._name,
                'res_id': record.id,
                'document': spec['label'],
                'employee': self._get_record_employee_name(record),
                'record_name': record.display_name,
                'expiry_date': self._date_to_string(expiry_date),
                'days_left': days_left,
                'status': _('Expired') if days_left < 0 else _('%s day(s)') % days_left,
                'tone': 'danger' if days_left < 0 else ('critical' if days_left <= 10 else 'warning'),
            })
        return rows

    @api.model
    def _get_dashboard_task_rows(self, domain):
        tasks = self.env['hr.applicant.onboarding.checklist'].sudo().search(
            domain,
            order='due_date asc, id desc',
            limit=10,
        )
        return [{
            'id': task.id,
            'model': task._name,
            'res_id': task.id,
            'task': task.checklist_item,
            'employee': task.employee_id.name or task.applicant_onboarding_id.display_name,
            'assigned_to': task.assigned_user_id.name or '',
            'due_date': self._date_to_string(task.due_date),
            'state': dict(task._fields['task_state'].selection).get(task.task_state, task.task_state),
            'tone': 'danger' if task.task_state == 'overdue' else ('warning' if task.task_state == 'in_progress' else 'info'),
        } for task in tasks]

    @api.model
    def _get_dashboard_activity_domain(self, today):
        model_ids = self.env['ir.model'].sudo().search([
            ('model', 'in', [
                'hr.applicant.onboarding',
                'hr.onboarding.compliance.request',
                'hr.employee.iqama',
                'hr.employee.medical.insurance',
                'hr.work.permit',
            ]),
        ]).ids
        return [
            ('user_id', '=', self.env.user.id),
            ('res_model_id', 'in', model_ids),
            ('date_deadline', '<=', self._date_to_string(today)),
        ]

    @api.model
    def _get_dashboard_activity_rows(self, domain):
        activities = self.env['mail.activity'].sudo().search(
            domain,
            order='date_deadline asc, id desc',
            limit=10,
        )
        rows = []
        for activity in activities:
            rows.append({
                'id': activity.id,
                'model': activity.res_model,
                'res_id': activity.res_id,
                'summary': activity.summary,
                'record_name': activity.res_name,
                'assigned_to': activity.user_id.name,
                'deadline': self._date_to_string(activity.date_deadline),
                'tone': 'danger' if activity.date_deadline and activity.date_deadline < fields.Date.context_today(self) else 'warning',
            })
        return rows

    @api.model
    def _send_due_reminders_for_spec(self, spec, target_date, days, today, supervisor_users):
        model_name = spec['model']
        if not self.env['ir.model']._get(model_name):
            return

        model = self.env[model_name].sudo()
        if spec['field'] not in model._fields:
            return

        domain = list(spec.get('domain', [])) + [(spec['field'], '=', target_date)]
        for record in model.search(domain):
            skip_field = spec.get('skip_if_same_as')
            if skip_field and skip_field in record._fields and record[skip_field] == target_date:
                continue
            if self._reminder_already_sent(record, spec['field'], target_date, days):
                continue
            self._send_record_reminder(record, spec, target_date, days, today, supervisor_users)

    @api.model
    def _get_supervisor_users(self):
        group = self.env.ref('pr_hr_recruitment_request.group_onboarding_supervisor', raise_if_not_found=False)
        users = group.users.filtered(lambda user: user.active) if group else self.env['res.users']
        if users:
            return users

        hr_manager_group = self.env.ref('hr.group_hr_manager', raise_if_not_found=False)
        return hr_manager_group.users.filtered(lambda user: user.active) if hr_manager_group else self.env['res.users']

    @api.model
    def _reminder_already_sent(self, record, expiry_field, expiry_date, days):
        return bool(self.sudo().search_count([
            ('model_name', '=', record._name),
            ('res_id', '=', record.id),
            ('expiry_field', '=', expiry_field),
            ('expiry_date', '=', expiry_date),
            ('reminder_days', '=', days),
        ]))

    @api.model
    def _send_record_reminder(self, record, spec, expiry_date, days, today, supervisor_users):
        subject = _('%(document)s expiry reminder: %(employee)s - %(days)s days left') % {
            'document': spec['label'],
            'employee': self._get_record_employee_name(record),
            'days': days,
        }
        body = self._get_reminder_body(record, spec, expiry_date, days)

        self._post_chatter_note(record, subject, body)
        self._schedule_activities(record, subject, body, today, supervisor_users)
        self._send_email(subject, body, supervisor_users)
        self.sudo().create({
            'name': subject,
            'model_name': record._name,
            'res_id': record.id,
            'expiry_field': spec['field'],
            'expiry_date': expiry_date,
            'reminder_days': days,
            'sent_date': today,
            'recipient_user_ids': [(6, 0, supervisor_users.ids)],
        })

    @api.model
    def _get_reminder_body(self, record, spec, expiry_date, days):
        employee_name = self._get_record_employee_name(record)
        record_name = record.display_name or record.name or ''
        return _(
            '<p>Dear HR Supervisor,</p>'
            '<p><strong>%(document)s</strong> for <strong>%(employee)s</strong> will expire in '
            '<strong>%(days)s day(s)</strong>.</p>'
            '<p>Record: %(record)s<br/>Expiry Date: %(expiry_date)s</p>'
            '<p>Please review and start the renewal process if it has not already been completed.</p>'
        ) % {
            'document': spec['label'],
            'employee': employee_name,
            'days': days,
            'record': record_name,
            'expiry_date': expiry_date,
        }

    @api.model
    def _get_record_employee_name(self, record):
        employee = record.employee_id if 'employee_id' in record._fields else False
        if employee:
            return employee.name or record.display_name
        return record.display_name or record.name or _('Unknown Employee')

    @api.model
    def _post_chatter_note(self, record, subject, body):
        if hasattr(record, 'message_post'):
            record.sudo().message_post(
                body=body,
                subject=subject,
                subtype_xmlid='mail.mt_note',
            )

    @api.model
    def _schedule_activities(self, record, subject, body, activity_deadline, supervisor_users):
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        model = self.env['ir.model']._get(record._name)
        if not activity_type or not model:
            return

        for user in supervisor_users:
            activity = self.env['mail.activity'].sudo().search([
                ('res_model_id', '=', model.id),
                ('res_id', '=', record.id),
                ('user_id', '=', user.id),
                ('summary', '=', subject),
            ], limit=1)
            vals = {
                'activity_type_id': activity_type.id,
                'summary': subject,
                'note': body,
                'date_deadline': activity_deadline,
                'user_id': user.id,
                'res_model_id': model.id,
                'res_id': record.id,
            }
            if activity:
                activity.write(vals)
            else:
                self.env['mail.activity'].sudo().create(vals)

    @api.model
    def _send_email(self, subject, body, supervisor_users):
        sender = self.env.company.email or self.env.user.email or 'noreply@petroraq.com'
        for user in supervisor_users.filtered(lambda rec: rec.email):
            try:
                self.env['mail.mail'].sudo().create({
                    'subject': subject,
                    'body_html': body,
                    'email_from': sender,
                    'email_to': user.email,
                    'auto_delete': True,
                }).send()
            except Exception:
                _logger.exception('Failed to send compliance expiry reminder email to %s', user.email)
