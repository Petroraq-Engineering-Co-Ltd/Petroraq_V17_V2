from datetime import timedelta
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


COMPLIANCE_REQUEST_TYPES = [
    ('iqama_transfer', 'Iqama Transfer Request'),
    ('work_permit_issuance', 'Work Permit Issuance'),
    ('work_permit_renewal', 'Work Permit Renewal'),
    ('medical_insurance_activation', 'Medical Insurance Activation'),
    ('iqama_renewal', 'Iqama Renewal'),
    ('gosi_registration', 'GOSI Registration'),
    ('other', 'Other Compliance Requirement'),
]

ONBOARDING_TASK_TYPES = [
    ('employee_id_assignment', 'Employee ID Assignment'),
    ('hr_laptop_assignment', 'HR Laptop Assignment'),
    ('official_email_creation', 'Official Email ID Creation'),
    ('work_permit_issuance', 'Work Permit Issuance'),
    ('iqama_transfer_completion', 'Iqama Transfer Completion'),
    ('gosi_registration', 'GOSI Registration'),
    ('medical_insurance_activation', 'Medical Insurance Activation'),
    ('company_car_assignment', 'Company Car Assignment'),
    ('signed_contract', 'Signed Contract'),
    ('bank_iban', 'Bank IBAN Confirmation'),
    ('emergency_contact', 'Emergency Contact Details'),
    ('passport_copy', 'Passport Copy'),
    ('iqama_copy', 'Iqama Copy'),
    ('national_id_copy', 'National ID Copy'),
    ('other', 'Other'),
]

TASK_TO_REQUEST_TYPE = {
    'work_permit_issuance': 'work_permit_issuance',
    'iqama_transfer_completion': 'iqama_transfer',
    'gosi_registration': 'gosi_registration',
    'medical_insurance_activation': 'medical_insurance_activation',
}

AUTO_ONBOARDING_TASK_TYPES = {
    task_type
    for task_type, _label in ONBOARDING_TASK_TYPES
    if task_type != 'other'
}

PAYMENT_REQUIRED_REQUEST_TYPES = {
    'iqama_transfer',
    'work_permit_issuance',
    'work_permit_renewal',
    'medical_insurance_activation',
    'iqama_renewal',
    'other',
}


class HrApplicantOnboarding(models.Model):
    _inherit = 'hr.applicant.onboarding'

    employee_category = fields.Selection(
        [('saudi', 'Saudi'), ('expat', 'Expat')],
        string='Employee Type',
        compute='_compute_employee_category',
        store=True,
    )
    compliance_request_ids = fields.One2many(
        'hr.onboarding.compliance.request',
        'onboarding_id',
        string='Compliance Requests',
    )
    compliance_request_count = fields.Integer(
        string='Compliance Requests',
        compute='_compute_compliance_request_count',
    )
    onboarding_start_date = fields.Date(
        string='Onboarding Start Date',
        default=fields.Date.context_today,
        tracking=True,
    )
    onboarding_task_initialized = fields.Boolean(
        string='Reminder Tasks Started',
        readonly=True,
        copy=False,
    )
    needs_hr_laptop = fields.Boolean(string='HR Laptop Required', default=True, tracking=True)
    needs_official_email = fields.Boolean(string='Official Email Required', default=True, tracking=True)
    needs_medical_insurance = fields.Boolean(string='Medical Insurance Required', default=True, tracking=True)
    needs_company_car = fields.Boolean(string='Company Car Required', tracking=True)
    checklist_total_count = fields.Integer(string='Total Tasks', compute='_compute_checklist_progress')
    checklist_done_count = fields.Integer(string='Done Tasks', compute='_compute_checklist_progress')
    checklist_overdue_count = fields.Integer(string='Overdue Tasks', compute='_compute_checklist_progress')
    checklist_progress = fields.Float(string='Progress', compute='_compute_checklist_progress')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get('skip_onboarding_auto_tasks'):
            records.filtered('employee_id')._auto_start_onboarding_reminders()
        return records

    def write(self, vals):
        res = super().write(vals)
        watched_fields = {
            'employee_id',
            'hire_type',
            'needs_hr_laptop',
            'needs_official_email',
            'needs_medical_insurance',
            'needs_company_car',
        }
        if not self.env.context.get('skip_onboarding_auto_tasks') and watched_fields.intersection(vals):
            self.filtered('employee_id').with_context(skip_onboarding_auto_tasks=True).action_start_onboarding_reminders()
        return res

    @api.depends('employee_id', 'employee_id.country_id', 'employee_id.country_id.is_homeland')
    def _compute_employee_category(self):
        for rec in self:
            rec.employee_category = 'saudi' if rec.employee_id.country_id.is_homeland else 'expat'

    @api.depends('compliance_request_ids')
    def _compute_compliance_request_count(self):
        for rec in self:
            rec.compliance_request_count = len(rec.compliance_request_ids)

    @api.depends('checklist_ids', 'checklist_ids.task_state', 'checklist_ids.is_completed')
    def _compute_checklist_progress(self):
        for rec in self:
            required_tasks = rec.checklist_ids.filtered(lambda line: line.is_required and line.task_state != 'cancelled')
            rec.checklist_total_count = len(required_tasks)
            rec.checklist_done_count = len(required_tasks.filtered(lambda line: line.task_state == 'done' or line.is_completed))
            rec.checklist_overdue_count = len(required_tasks.filtered(lambda line: line.task_state == 'overdue'))
            rec.checklist_progress = (
                (rec.checklist_done_count / rec.checklist_total_count) * 100.0
                if rec.checklist_total_count else 0.0
            )

    def generate_checklist(self):
        for rec in self:
            rec._sync_employee_type_checklist()
            rec.state = 'checklist'
            rec._schedule_open_task_reminders()

    def action_start_onboarding_reminders(self):
        for rec in self:
            was_initialized = rec.onboarding_task_initialized
            rec._sync_employee_type_checklist()
            rec.with_context(skip_onboarding_auto_tasks=True).write({
                'state': 'checklist',
                'onboarding_task_initialized': True,
            })
            rec._schedule_open_task_reminders()
            rec.message_post(body=_(
                'Onboarding checklist reminders have been refreshed.'
                if was_initialized else 'Onboarding checklist reminders have been started.'
            ))

    def _auto_start_onboarding_reminders(self):
        for rec in self:
            if rec.onboarding_task_initialized or not rec.employee_id:
                continue
            rec.with_context(skip_onboarding_auto_tasks=True).action_start_onboarding_reminders()

    def _sync_employee_type_checklist(self):
        self.ensure_one()
        self.checklist_ids._apply_missing_task_defaults()
        checklist_vals = self._get_employee_type_checklist_vals()
        desired_task_types = {item.get('task_type') for item in checklist_vals if item.get('task_type')}
        existing_keys = set()
        existing_task_types = set()
        for checklist in self.checklist_ids:
            existing_keys.add(checklist.request_type or checklist.checklist_item)
            if checklist.task_type and checklist.task_type != 'other':
                existing_task_types.add(checklist.task_type)

        lines_to_create = []
        for item in checklist_vals:
            if item.get('task_type') in existing_task_types:
                continue
            key = item.get('request_type') or item['checklist_item']
            if key not in existing_keys:
                lines_to_create.append((0, 0, item))
        if lines_to_create:
            self.write({'checklist_ids': lines_to_create})
        self._cancel_no_longer_applicable_tasks(desired_task_types)
        self.checklist_ids._apply_missing_task_defaults()

    def _cancel_no_longer_applicable_tasks(self, desired_task_types):
        self.ensure_one()
        stale_tasks = self.checklist_ids.filtered(
            lambda line: (
                line.task_type in AUTO_ONBOARDING_TASK_TYPES
                and line.task_type not in desired_task_types
                and line.task_state not in ('done', 'cancelled')
                and not line.compliance_request_id
            )
        )
        if stale_tasks:
            stale_tasks.action_cancel_task()

    def _get_employee_type_checklist_vals(self):
        self.ensure_one()
        common_items = [
            self._prepare_task_vals('employee_id_assignment', 'Employee ID Assignment', due_days=0),
            self._prepare_task_vals('signed_contract', 'Signed Qiwa Contract / Employment Contract', due_days=0),
            self._prepare_task_vals('bank_iban', 'Bank IBAN Confirmation', due_days=1),
            self._prepare_task_vals('emergency_contact', 'Emergency Contact Details', due_days=1),
        ]
        if self.needs_official_email:
            common_items.append(self._prepare_task_vals('official_email_creation', 'Official Email ID Creation', due_days=1))
        if self.needs_hr_laptop:
            common_items.append(self._prepare_task_vals('hr_laptop_assignment', 'HR Laptop Assignment', due_days=1))
        if self.needs_company_car:
            common_items.append(self._prepare_task_vals('company_car_assignment', 'Company Car Assignment', due_days=3))

        if self.employee_category == 'saudi':
            items = common_items + [
                self._prepare_task_vals('national_id_copy', 'National ID Copy', due_days=1),
                self._prepare_task_vals('gosi_registration', 'GOSI Registration', due_days=3),
            ]
            if self.needs_medical_insurance:
                items.append(self._prepare_task_vals('medical_insurance_activation', 'Medical Insurance Activation', due_days=3))
            return items

        items = common_items + [
            self._prepare_task_vals('passport_copy', 'Passport Copy', due_days=1),
            self._prepare_task_vals('iqama_copy', 'Iqama Copy', due_days=1),
            self._prepare_task_vals('iqama_transfer_completion', 'Iqama Transfer Completion', due_days=5),
            self._prepare_task_vals('work_permit_issuance', 'Work Permit Issuance', due_days=3),
            self._prepare_task_vals('gosi_registration', 'GOSI Registration', due_days=4),
        ]
        if self.needs_medical_insurance:
            items.append(self._prepare_task_vals('medical_insurance_activation', 'Medical Insurance Activation', due_days=4))
        return items

    def _prepare_task_vals(self, task_type, checklist_item, due_days=1):
        self.ensure_one()
        start_date = self.onboarding_start_date or fields.Date.context_today(self)
        due_date = start_date + timedelta(days=due_days)
        group = self._get_default_task_group()
        assigned_user = self._get_default_task_user(group)
        return {
            'checklist_item': checklist_item,
            'task_type': task_type,
            'request_type': TASK_TO_REQUEST_TYPE.get(task_type),
            'responsible_group_id': group.id if group else False,
            'assigned_user_id': assigned_user.id if assigned_user else False,
            'due_date': due_date,
            'reminder_date': start_date,
            'is_required': True,
            'task_state': 'pending',
        }

    def _get_default_task_group(self):
        return (
            self.env.ref('pr_hr_recruitment_request.group_onboarding_supervisor', raise_if_not_found=False)
            or self.env.ref('hr_recruitment.group_hr_recruitment_user', raise_if_not_found=False)
        )

    @staticmethod
    def _get_default_task_user(group):
        return group.users.filtered(lambda user: user.active)[:1] if group else False

    def _schedule_open_task_reminders(self):
        for rec in self:
            open_tasks = rec.checklist_ids.filtered(lambda line: line.task_state in ('pending', 'in_progress', 'overdue'))
            open_tasks._schedule_reminder_activity(force=True)

    def action_create_compliance_request(self):
        if (
            not self.env.su
            and not self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_supervisor')
        ):
            raise UserError(_('Only Onboarding Supervisor can initiate onboarding compliance requests.'))

        self.ensure_one()
        if not self.employee_id:
            raise UserError(_('Please set an employee before creating a compliance request.'))
        self._sync_employee_type_checklist()
        self.state = 'checklist'

        view = self.env.ref('qiwa_contract_ocr.view_hr_onboarding_compliance_request_form')
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Compliance Request'),
            'res_model': 'hr.onboarding.compliance.request',
            'view_mode': 'form',
            'views': [(view.id, 'form')],
            'target': 'current',
            'context': self._get_compliance_request_default_context(),
        }

    def action_generate_compliance_requests(self):
        return self.action_create_compliance_request()

    def _get_compliance_request_default_context(self):
        self.ensure_one()
        employee = self.employee_id
        contract = employee.contract_id
        issue_date = contract.date_start or fields.Date.context_today(self)
        expiry_date = contract.date_end or fields.Date.context_today(self) + timedelta(days=365)
        return {
            'default_onboarding_id': self.id,
            'default_applicant_id': self.applicant_id.id,
            'default_employee_id': employee.id,
            'default_contract_id': contract.id,
            'default_employee_category': self.employee_category,
            'default_requested_by_id': self.env.user.id,
            'default_required_date': issue_date,
            'default_iqama_no': employee.identification_id,
            'default_passport_no': employee.passport_id,
            'default_profession': employee.job_id.name,
            'default_issue_date': issue_date,
            'default_expiry_date': expiry_date,
            'default_insurance_company': _('To Be Confirmed'),
            'default_insurance_category': _('To Be Confirmed'),
        }

    def action_open_compliance_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Onboarding Compliance Requests'),
            'res_model': 'hr.onboarding.compliance.request',
            'view_mode': 'tree,form',
            'domain': [('onboarding_id', '=', self.id)],
            'context': {
                'default_onboarding_id': self.id,
                'default_applicant_id': self.applicant_id.id,
                'default_employee_id': self.employee_id.id,
                'default_employee_category': self.employee_category,
            },
            'target': 'current',
        }


class HrApplicantOnboardingChecklist(models.Model):
    _inherit = 'hr.applicant.onboarding.checklist'

    task_type = fields.Selection(ONBOARDING_TASK_TYPES, string='Task Type', default='other')
    request_type = fields.Selection(COMPLIANCE_REQUEST_TYPES, string='Request Type')
    compliance_request_id = fields.Many2one(
        'hr.onboarding.compliance.request',
        string='Compliance Request',
        readonly=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        related='applicant_onboarding_id.employee_id',
        store=True,
        readonly=True,
    )
    responsible_group_id = fields.Many2one('res.groups', string='Responsible Group')
    assigned_user_id = fields.Many2one('res.users', string='Assigned To')
    due_date = fields.Date(string='Due Date')
    reminder_date = fields.Date(string='First Reminder Date')
    last_reminder_date = fields.Date(string='Last Reminder Date', readonly=True, copy=False)
    reminder_count = fields.Integer(string='Reminders Sent', readonly=True, copy=False)
    task_state = fields.Selection(
        [
            ('pending', 'Pending'),
            ('in_progress', 'In Progress'),
            ('done', 'Done'),
            ('overdue', 'Overdue'),
            ('cancelled', 'Cancelled'),
        ],
        string='Task Status',
        default='pending',
    )
    is_required = fields.Boolean(string='Required', default=True)
    activity_ids = fields.Many2many(
        'mail.activity',
        'hr_onboarding_checklist_activity_rel',
        'checklist_id',
        'activity_id',
        string='Reminder Activities',
        readonly=True,
        copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._apply_missing_task_defaults()
        return records

    def write(self, vals):
        vals = dict(vals)
        if vals.get('is_completed') and 'task_state' not in vals:
            vals['task_state'] = 'done'
        if vals.get('task_state') == 'done':
            vals['is_completed'] = True
        if vals.get('task_state') in ('pending', 'in_progress', 'overdue'):
            vals.setdefault('is_completed', False)
        res = super().write(vals)
        if vals.get('task_state') == 'done' or vals.get('is_completed'):
            self._clear_reminder_activities()
        return res

    def _apply_missing_task_defaults(self):
        for rec in self:
            vals = {}
            inferred_task_type = rec._infer_task_type()
            if (not rec.task_type or rec.task_type == 'other') and inferred_task_type != 'other':
                vals['task_type'] = inferred_task_type
            task_type = vals.get('task_type') or rec.task_type
            if not rec.request_type and task_type in TASK_TO_REQUEST_TYPE:
                vals['request_type'] = TASK_TO_REQUEST_TYPE[task_type]
            if not rec.responsible_group_id:
                group = rec.applicant_onboarding_id._get_default_task_group()
                if group:
                    vals['responsible_group_id'] = group.id
            if not rec.assigned_user_id:
                group = rec.responsible_group_id
                if not group and vals.get('responsible_group_id'):
                    group = self.env['res.groups'].browse(vals['responsible_group_id'])
                assigned_user = rec.applicant_onboarding_id._get_default_task_user(group)
                if assigned_user:
                    vals['assigned_user_id'] = assigned_user.id
            start_date = rec.applicant_onboarding_id.onboarding_start_date or fields.Date.context_today(rec)
            if not rec.due_date:
                vals['due_date'] = start_date + timedelta(days=rec._get_default_due_days(task_type))
            if not rec.reminder_date:
                vals['reminder_date'] = start_date
            if vals:
                rec.sudo().write(vals)

    def _infer_task_type(self):
        self.ensure_one()
        label = (self.checklist_item or '').casefold()
        candidates = [
            ('employee_id_assignment', ('employee id',)),
            ('hr_laptop_assignment', ('laptop',)),
            ('official_email_creation', ('official email', 'email id')),
            ('work_permit_issuance', ('work permit',)),
            ('iqama_transfer_completion', ('iqama transfer', 'transfer request')),
            ('gosi_registration', ('gosi',)),
            ('medical_insurance_activation', ('medical insurance', 'insurance')),
            ('company_car_assignment', ('company car', 'car assignment')),
            ('signed_contract', ('contract',)),
            ('bank_iban', ('iban', 'bank')),
            ('emergency_contact', ('emergency',)),
            ('passport_copy', ('passport',)),
            ('iqama_copy', ('iqama copy',)),
            ('national_id_copy', ('national id',)),
        ]
        for task_type, keywords in candidates:
            if any(keyword in label for keyword in keywords):
                return task_type
        return 'other'

    @staticmethod
    def _get_default_due_days(task_type):
        due_days = {
            'employee_id_assignment': 0,
            'signed_contract': 0,
            'bank_iban': 1,
            'emergency_contact': 1,
            'official_email_creation': 1,
            'hr_laptop_assignment': 1,
            'company_car_assignment': 3,
            'passport_copy': 1,
            'iqama_copy': 1,
            'national_id_copy': 1,
            'work_permit_issuance': 3,
            'iqama_transfer_completion': 5,
            'gosi_registration': 4,
            'medical_insurance_activation': 4,
        }
        return due_days.get(task_type, 2)

    def action_start_progress(self):
        self.write({'task_state': 'in_progress'})

    def action_mark_done(self):
        self.write({'task_state': 'done', 'is_completed': True})

    def action_reset_pending(self):
        self.write({'task_state': 'pending', 'is_completed': False})
        self._schedule_reminder_activity(force=True)

    def action_cancel_task(self):
        self.write({'task_state': 'cancelled', 'is_completed': False})
        self._clear_reminder_activities()

    def _schedule_reminder_activity(self, force=False):
        today = fields.Date.context_today(self)
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            return
        onboarding_model = self.env['ir.model']._get('hr.applicant.onboarding')
        for rec in self.sudo():
            onboarding = rec.applicant_onboarding_id
            if not onboarding or rec.task_state in ('done', 'cancelled') or not rec.is_required:
                continue
            if not force and rec.reminder_date and rec.reminder_date > today and rec.due_date and rec.due_date > today:
                continue
            responsible_users = rec._get_responsible_users()
            if not responsible_users:
                continue
            if rec.due_date and rec.due_date < today and rec.task_state != 'overdue':
                rec.task_state = 'overdue'
            deadline = today if rec.task_state == 'overdue' else (rec.due_date or today)
            created_or_updated = self.env['mail.activity']
            for user in responsible_users:
                activity = rec._find_existing_activity(user)
                activity_vals = {
                    'activity_type_id': activity_type.id,
                    'summary': rec._get_activity_summary(),
                    'note': rec._get_activity_note(),
                    'date_deadline': deadline,
                    'user_id': user.id,
                    'res_model_id': onboarding_model.id,
                    'res_id': onboarding.id,
                }
                if activity:
                    activity.write(activity_vals)
                else:
                    activity = self.env['mail.activity'].sudo().create(activity_vals)
                created_or_updated |= activity
            rec.activity_ids = [(6, 0, created_or_updated.ids)]
            rec._send_reminder_email(responsible_users)

    def _get_responsible_users(self):
        self.ensure_one()
        if self.assigned_user_id and self.assigned_user_id.active:
            return self.assigned_user_id
        if self.responsible_group_id:
            users = self.responsible_group_id.users.filtered(lambda user: user.active)
            if users:
                return users
        return self._get_fallback_reminder_users()

    def _get_fallback_reminder_users(self):
        users = self.env['res.users']
        group_xmlids = [
            'pr_hr_recruitment_request.group_onboarding_supervisor',
            'hr_recruitment.group_hr_recruitment_user',
            'hr.group_hr_user',
            'hr.group_hr_manager',
        ]
        for group_xmlid in group_xmlids:
            group = self.env.ref(group_xmlid, raise_if_not_found=False)
            if group:
                users |= group.users.filtered(lambda user: user.active)
        return users

    def _find_existing_activity(self, user):
        self.ensure_one()
        onboarding_model = self.env['ir.model']._get('hr.applicant.onboarding')
        return self.env['mail.activity'].sudo().search([
            ('res_model_id', '=', onboarding_model.id),
            ('res_id', '=', self.applicant_onboarding_id.id),
            ('user_id', '=', user.id),
            ('summary', '=', self._get_activity_summary()),
        ], limit=1)

    def _get_activity_summary(self):
        self.ensure_one()
        return _('Onboarding: %s') % (self.checklist_item or _('Checklist Task'))

    def _get_activity_note(self):
        self.ensure_one()
        employee_name = self.employee_id.name or self.applicant_onboarding_id.name
        status = dict(self._fields['task_state'].selection).get(self.task_state, self.task_state)
        return _(
            '<p>Please complete onboarding task <strong>%(task)s</strong> for %(employee)s.</p>'
            '<p>Status: %(status)s<br/>Due Date: %(due_date)s</p>'
        ) % {
            'task': self.checklist_item or '',
            'employee': employee_name or '',
            'status': status,
            'due_date': self.due_date or '',
        }

    def _send_reminder_email(self, users):
        self.ensure_one()
        email_users = users.filtered(lambda user: user.active and user.email)
        if not email_users:
            return

        onboarding = self.applicant_onboarding_id
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        record_url = ''
        if base_url and onboarding:
            record_url = '%s/web#id=%s&model=hr.applicant.onboarding&view_type=form' % (
                base_url.rstrip('/'),
                onboarding.id,
            )

        subject = self._get_activity_summary()
        body = self._get_activity_note()
        if record_url:
            body += _('<p><a href="%s">Open Onboarding Record</a></p>') % record_url

        sender = self.env.company.email or self.env.user.email or 'noreply@petroraq.com'
        for user in email_users:
            try:
                self.env['mail.mail'].sudo().create({
                    'subject': subject,
                    'body_html': body,
                    'email_from': sender,
                    'email_to': user.email,
                    'auto_delete': True,
                }).send()
            except Exception:
                _logger.exception('Failed to send onboarding reminder email to %s', user.email)

    def _clear_reminder_activities(self):
        activities = self.mapped('activity_ids').exists()
        if activities:
            activities.sudo().unlink()
        self.sudo().write({'activity_ids': [(5, 0, 0)]})

    @api.model
    def _cron_send_onboarding_task_reminders(self):
        today = fields.Date.context_today(self)
        tasks = self.sudo().search([
            ('is_required', '=', True),
            ('task_state', 'in', ['pending', 'in_progress', 'overdue']),
            ('applicant_onboarding_id', '!=', False),
            '|',
            ('reminder_date', '<=', today),
            ('due_date', '<=', today),
        ])
        for task in tasks:
            if task.last_reminder_date == today:
                continue
            task._schedule_reminder_activity(force=True)
            task.write({
                'last_reminder_date': today,
                'reminder_count': task.reminder_count + 1,
            })


class HrOnboardingComplianceRequest(models.Model):
    _name = 'hr.onboarding.compliance.request'
    _description = 'Onboarding Compliance Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Request Reference',
        required=True,
        copy=False,
        readonly=True,
        default='/',
        tracking=True,
    )
    onboarding_id = fields.Many2one(
        'hr.applicant.onboarding',
        string='Applicant Onboarding',
        required=True,
        ondelete='cascade',
        tracking=True,
    )
    applicant_id = fields.Many2one('hr.applicant', string='Applicant', tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    contract_id = fields.Many2one('hr.contract', string='Contract', tracking=True)
    requested_by_id = fields.Many2one(
        'res.users',
        string='Requested By',
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
    )
    request_type = fields.Selection(
        COMPLIANCE_REQUEST_TYPES,
        string='Request Type',
        required=True,
        tracking=True,
    )
    employee_category = fields.Selection(
        [('saudi', 'Saudi'), ('expat', 'Expat')],
        string='Employee Type',
        required=True,
        tracking=True,
    )
    required_date = fields.Date(string='Required Date', tracking=True)
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('hr_manager_approval', 'HR Manager Approval'),
            ('md_approval', 'MD Approval'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('done', 'Done'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        tracking=True,
    )
    is_onboarding_supervisor = fields.Boolean(compute='_compute_approval_permissions')
    is_onboarding_manager = fields.Boolean(compute='_compute_approval_permissions')
    is_onboarding_md = fields.Boolean(compute='_compute_approval_permissions')

    iqama_no = fields.Char(string='Iqama / ID No.', tracking=True)
    passport_no = fields.Char(string='Passport No.', tracking=True)
    visa_number = fields.Char(string='Visa Number', tracking=True)
    profession = fields.Char(string='Profession', tracking=True)
    issue_date = fields.Date(string='Issue Date', tracking=True)
    expiry_date = fields.Date(string='Expiry Date', tracking=True)
    amount = fields.Float(string='Expected Fees / Amount', tracking=True)
    insurance_company = fields.Char(string='Insurance Company', tracking=True)
    insurance_category = fields.Char(string='Insurance Category', tracking=True)
    gosi_number = fields.Char(string='GOSI Number', tracking=True)
    gosi_registration_date = fields.Date(string='GOSI Registration Date', tracking=True)
    government_reference = fields.Char(string='Government Reference', tracking=True)
    description = fields.Text(string='Description')
    attachment_file = fields.Binary(string='Supporting File', attachment=True)
    attachment_filename = fields.Char(string='File Name')

    requires_payment = fields.Boolean(string='Requires Payment', tracking=True)
    payment_state = fields.Selection(
        [
            ('not_required', 'Not Required'),
            ('draft', 'Not Sent'),
            ('pending', 'Pending Accounting'),
            ('paid', 'Paid'),
            ('cancelled', 'Cancelled'),
        ],
        string='Payment Status',
        default='not_required',
        readonly=True,
        tracking=True,
    )
    payment_account_id = fields.Many2one(
        'account.account',
        string='Payment Account',
        default=lambda self: self._default_bank_payment_account(),
        tracking=True,
    )
    payment_expense_account_id = fields.Many2one(
        'account.account',
        string='Expense Account',
        tracking=True,
    )
    bank_payment_id = fields.Many2one(
        'pr.account.bank.payment',
        string='Bank Payment',
        readonly=True,
        copy=False,
        tracking=True,
    )
    paid_move_id = fields.Many2one(
        'account.move',
        string='Paid Journal Entry',
        related='bank_payment_id.journal_entry_id',
        store=True,
        readonly=True,
    )
    has_bank_payment = fields.Boolean(
        string='Has Bank Payment',
        compute='_compute_payment_flags',
        store=True,
    )

    hr_manager_approved_by_id = fields.Many2one(
        'res.users',
        string='HR Manager Approved By',
        readonly=True,
        copy=False,
    )
    hr_manager_approved_date = fields.Datetime(string='HR Manager Approved On', readonly=True, copy=False)
    md_approved_by_id = fields.Many2one('res.users', string='MD Approved By', readonly=True, copy=False)
    md_approved_date = fields.Datetime(string='MD Approved On', readonly=True, copy=False)

    work_permit_id = fields.Many2one('hr.work.permit', string='Work Permit', readonly=True)
    iqama_id = fields.Many2one('hr.employee.iqama', string='Iqama', readonly=True)
    medical_insurance_id = fields.Many2one(
        'hr.employee.medical.insurance',
        string='Medical Insurance',
        readonly=True,
    )

    @api.model
    def create(self, vals):
        if (
            not self.env.su
            and not self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_supervisor')
        ):
            raise UserError(_('Only Onboarding Supervisor can initiate onboarding compliance requests.'))
        if vals.get('name', '/') == '/':
            vals['name'] = self.env['ir.sequence'].next_by_code('hr.onboarding.compliance.request') or '/'
        if 'requires_payment' not in vals and vals.get('request_type'):
            vals['requires_payment'] = vals['request_type'] in PAYMENT_REQUIRED_REQUEST_TYPES
        if 'payment_state' not in vals:
            vals['payment_state'] = 'draft' if vals.get('requires_payment') else 'not_required'
        rec = super().create(vals)
        rec._link_checklist_task()
        return rec

    @api.onchange('onboarding_id')
    def _onchange_onboarding_id(self):
        for rec in self:
            onboarding = rec.onboarding_id
            if onboarding:
                rec.applicant_id = onboarding.applicant_id
                rec.employee_id = onboarding.employee_id
                rec.employee_category = onboarding.employee_category
                rec.contract_id = onboarding.employee_id.contract_id

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        for rec in self:
            employee = rec.employee_id
            if employee:
                rec.employee_category = 'saudi' if employee.country_id.is_homeland else 'expat'
                rec.contract_id = employee.contract_id
                rec.iqama_no = employee.identification_id
                rec.passport_no = employee.passport_id
                rec.profession = employee.job_id.name
                if 'employee_account_id' in employee._fields and employee.employee_account_id:
                    rec.payment_expense_account_id = employee.employee_account_id

    @api.onchange('request_type')
    def _onchange_request_type(self):
        for rec in self:
            rec.requires_payment = rec.request_type in PAYMENT_REQUIRED_REQUEST_TYPES
            rec.payment_state = 'draft' if rec.requires_payment else 'not_required'

    @api.onchange('requires_payment')
    def _onchange_requires_payment(self):
        for rec in self:
            rec.payment_state = 'draft' if rec.requires_payment else 'not_required'

    def _compute_approval_permissions(self):
        is_supervisor = self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_supervisor')
        is_manager = self._is_hr_manager_approver()
        is_md = self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_md')
        for rec in self:
            rec.is_onboarding_supervisor = is_supervisor
            rec.is_onboarding_manager = is_manager
            rec.is_onboarding_md = is_md

    def _is_hr_manager_approver(self):
        return (
            self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_manager')
            or self.env.user.has_group('hr.group_hr_manager')
        )

    @api.depends('bank_payment_id')
    def _compute_payment_flags(self):
        for rec in self:
            rec.has_bank_payment = bool(rec.bank_payment_id)

    def action_submit(self):
        if not self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_supervisor'):
            raise UserError(_('Only Onboarding Supervisor can submit onboarding compliance requests.'))
        for rec in self:
            if rec.state == 'draft':
                rec.state = 'hr_manager_approval'
                rec._link_checklist_task(task_state='in_progress')

    def action_approve_hr_manager(self):
        if not self._is_hr_manager_approver():
            raise UserError(_('Only HR Manager can approve onboarding compliance requests.'))
        for rec in self:
            if rec.state != 'hr_manager_approval':
                continue
            rec.write({
                'state': 'md_approval',
                'hr_manager_approved_by_id': self.env.user.id,
                'hr_manager_approved_date': fields.Datetime.now(),
            })

    def action_approve_md(self):
        if not self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_md'):
            raise UserError(_('Only Onboarding MD can approve onboarding compliance requests.'))
        for rec in self:
            if rec.state != 'md_approval':
                continue
            rec._create_or_update_linked_record()
            rec._ensure_accounting_payment()
            rec._link_checklist_task(task_state='in_progress')
            rec.write({
                'state': 'approved',
                'md_approved_by_id': self.env.user.id,
                'md_approved_date': fields.Datetime.now(),
            })

    def action_reject(self):
        for rec in self:
            if rec.state == 'hr_manager_approval':
                if not self._is_hr_manager_approver():
                    raise UserError(_('Only HR Manager can reject onboarding compliance requests.'))
            elif rec.state == 'md_approval':
                if not self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_md'):
                    raise UserError(_('Only Onboarding MD can reject onboarding compliance requests.'))
            else:
                continue
            rec.state = 'rejected'

    def action_set_done(self):
        if not self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_supervisor'):
            raise UserError(_('Only Onboarding Supervisor can complete onboarding compliance requests.'))
        for rec in self:
            if rec.requires_payment and rec.payment_state != 'paid':
                raise UserError(_('This request cannot be marked done until Accounting posts the payment.'))
            rec.write({'state': 'done'})
            checklist = rec.onboarding_id.checklist_ids.filtered(
                lambda line: line.compliance_request_id == rec
            )
            if checklist:
                checklist.sudo().write({'is_completed': True})

    def action_cancel(self):
        if not self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_supervisor'):
            raise UserError(_('Only Onboarding Supervisor can cancel onboarding compliance requests.'))
        self.filtered(lambda rec: rec.state in ('draft', 'hr_manager_approval', 'md_approval', 'approved')).write({
            'state': 'cancelled'
        })

    def action_reset_to_draft(self):
        if not self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_supervisor'):
            raise UserError(_('Only Onboarding Supervisor can reset onboarding compliance requests.'))
        self.write({'state': 'draft'})

    def action_send_to_accounting(self):
        if not (
            self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_supervisor')
            or self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_md')
        ):
            raise UserError(_('Only Onboarding Supervisor or MD can send requests to Accounting.'))
        for rec in self:
            if rec.state not in ('approved', 'done'):
                raise UserError(_('Only approved onboarding compliance requests can be sent to Accounting.'))
            rec._ensure_accounting_payment()

    def _create_or_update_linked_record(self):
        self.ensure_one()
        if self.request_type in ('work_permit_issuance', 'work_permit_renewal'):
            self._ensure_work_permit()
        elif self.request_type in ('iqama_transfer', 'iqama_renewal'):
            self._ensure_iqama()
        elif self.request_type == 'medical_insurance_activation':
            self._ensure_medical_insurance()
        elif self.request_type == 'gosi_registration':
            self._update_contract_gosi()

    def _link_checklist_task(self, task_state=False):
        self.ensure_one()
        if not self.onboarding_id or not self.request_type:
            return
        checklist = self.onboarding_id.checklist_ids.filtered(
            lambda line: line.request_type == self.request_type
        )[:1]
        if checklist:
            vals = {'compliance_request_id': self.id}
            if task_state and checklist.task_state not in ('done', 'cancelled'):
                vals['task_state'] = task_state
            checklist.sudo().write(vals)

    def _ensure_work_permit(self):
        if self.work_permit_id:
            return
        employee = self.employee_id
        expiry_date = self._get_effective_expiry_date()
        issue_date = self.issue_date or fields.Date.context_today(self)
        visa_number = self.visa_number or self.iqama_no or self.passport_no or self.name
        work_permit = self.env['hr.work.permit'].sudo().search([
            ('employee_id', '=', employee.id),
            ('visa_number', '=', visa_number),
        ], limit=1)
        if not work_permit:
            work_permit = self.env['hr.work.permit'].sudo().search([
                ('employee_id', '=', employee.id),
            ], order='id desc', limit=1)
        work_permit_vals = {
            'applicant_onboarding_id': self.onboarding_id.id,
            'name': self.name,
            'employee_id': employee.id,
            'visa_number': visa_number,
            'iqama_profession': self.profession or employee.job_id.name or _('To Be Confirmed'),
            'work_permit_fees': self.amount or 0.0,
            'iqama_issuance_date': issue_date,
            'iqama_expiry_date': expiry_date,
            'work_permit_expiry_date': expiry_date,
            'state': 'approved',
            'payment_state': 'pending' if self.requires_payment else 'draft',
        }
        if work_permit:
            work_permit_vals.pop('state', None)
            work_permit.write(work_permit_vals)
        else:
            work_permit = self.env['hr.work.permit'].sudo().create(work_permit_vals)
        if work_permit.state not in ('approved', 'issued', 'reject'):
            work_permit.state = 'approved'
        if self.requires_payment and work_permit.payment_state == 'draft':
            work_permit.payment_state = 'pending'
        self.work_permit_id = work_permit.id
        if 'onboarding_compliance_request_id' in work_permit._fields:
            work_permit.onboarding_compliance_request_id = self.id

    def _ensure_iqama(self):
        if self.iqama_id:
            return
        iqama_no = self.iqama_no or self.employee_id.identification_id
        if not iqama_no:
            raise UserError(_('Please set Iqama / ID No. before approving this request.'))
        iqama = self.env['hr.employee.iqama'].sudo().search([
            ('identification_id', '=', iqama_no),
        ], limit=1)
        if not iqama:
            iqama = self.env['hr.employee.iqama'].sudo().create({
                'name': self.name,
                'employee_id': self.employee_id.id,
                'identification_id': iqama_no,
                'place_of_issue': self.government_reference or False,
                'expiry_date': self._get_effective_expiry_date(),
                'state': 'approve',
            })
        self.iqama_id = iqama.id
        if 'onboarding_compliance_request_id' in iqama._fields:
            iqama.onboarding_compliance_request_id = self.id

    def _ensure_medical_insurance(self):
        if self.medical_insurance_id:
            return
        iqama_no = self.iqama_no or self.employee_id.identification_id or self.passport_no or self.name
        insurance = self.env['hr.employee.medical.insurance'].sudo().search([
            ('identification_id', '=', iqama_no),
        ], limit=1)
        if not insurance:
            insurance = self.env['hr.employee.medical.insurance'].sudo().create({
                'name': self.name,
                'employee_id': self.employee_id.id,
                'identification_id': iqama_no,
                'insurance_company': self.insurance_company or _('To Be Confirmed'),
                'insurance_category': self.insurance_category or _('To Be Confirmed'),
                'expiry_date': self._get_effective_expiry_date(),
                'state': 'approve',
            })
        self.medical_insurance_id = insurance.id
        if 'onboarding_compliance_request_id' in insurance._fields:
            insurance.onboarding_compliance_request_id = self.id

    def _update_contract_gosi(self):
        contract = self.contract_id or self.employee_id.contract_id
        if contract and hasattr(contract, '_set_gosi_salary'):
            contract.sudo()._set_gosi_salary()

    def _ensure_accounting_payment(self):
        self.ensure_one()
        if not self.requires_payment:
            self.payment_state = 'not_required'
            return
        if self.bank_payment_id and self.bank_payment_id.state != 'cancel':
            self.payment_state = 'paid' if self.bank_payment_id.state == 'posted' else 'pending'
            return
        if self.amount <= 0:
            raise UserError(_('Please set a positive amount before sending this request to Accounting.'))

        payment_account = self.payment_account_id or self._default_bank_payment_account()
        expense_account = self.payment_expense_account_id or self._get_default_payment_expense_account()
        if not payment_account:
            raise UserError(_('Please set the Payment Account before sending this request to Accounting.'))
        if not expense_account:
            raise UserError(_('Please set the Expense Account before sending this request to Accounting.'))

        description = self._get_payment_description()
        bank_payment = self.env['pr.account.bank.payment'].sudo().create({
            'account_id': payment_account.id,
            'description': description,
            'accounting_date': fields.Date.context_today(self),
            'bank_payment_line_ids': [(0, 0, {
                'account_id': expense_account.id,
                'cs_project_id': self._get_employee_project_cost_center_id(),
                'partner_id': self._get_payment_partner_id(),
                'description': description,
                'reference_number': self.name,
                'amount': self.amount,
                'analytic_distribution': self._get_payment_analytic_distribution(),
            })],
        })
        bank_payment.onboarding_compliance_request_id = self.id
        if self.work_permit_id and 'work_permit_id' in bank_payment._fields:
            bank_payment.work_permit_id = self.work_permit_id.id
            if 'bank_payment_id' in self.work_permit_id._fields:
                self.work_permit_id.bank_payment_id = bank_payment.id
            if 'payment_state' in self.work_permit_id._fields:
                self.work_permit_id.payment_state = 'pending'
            if self.work_permit_id.state not in ('approved', 'issued', 'reject'):
                self.work_permit_id.state = 'approved'

        # bank_payment.action_submit()
        self.write({
            'bank_payment_id': bank_payment.id,
            'payment_state': 'pending',
            'payment_account_id': payment_account.id,
            'payment_expense_account_id': expense_account.id,
        })

    def _get_payment_description(self):
        self.ensure_one()
        request_label = dict(COMPLIANCE_REQUEST_TYPES).get(self.request_type, self.request_type)
        employee_name = self.employee_id.name or _('Employee')
        return _('%(request)s - %(employee)s - %(ref)s', request=request_label, employee=employee_name, ref=self.name)

    def _get_payment_partner_id(self):
        self.ensure_one()
        employee = self.employee_id
        for field_name in ('work_contact_id', 'user_partner_id', 'private_address_id'):
            if field_name in employee._fields and employee[field_name]:
                return employee[field_name].id
        return False

    def _get_employee_project_cost_center_id(self):
        self.ensure_one()
        employee = self.employee_id
        if 'project_cost_center_id' in employee._fields and employee.project_cost_center_id:
            return employee.project_cost_center_id.id
        return False

    def _get_payment_analytic_distribution(self):
        self.ensure_one()
        employee = self.employee_id
        distribution = {}
        for field_name in (
            'department_cost_center_id',
            'section_cost_center_id',
            'employee_cost_center_id',
            'project_cost_center_id',
        ):
            if field_name in employee._fields and employee[field_name]:
                distribution[str(employee[field_name].id)] = 100.0
        return distribution or False

    def _default_bank_payment_account(self):
        account = self.env['account.account'].sudo().search([('code', '=', '1001.02.00.07')], limit=1)
        if account:
            return account
        return self.env['account.account'].sudo().browse(749).exists()

    def _get_default_payment_expense_account(self):
        self.ensure_one()
        employee = self.employee_id
        if 'employee_account_id' in employee._fields and employee.employee_account_id:
            return employee.employee_account_id
        return self.env['account.account'].sudo().search([
            ('main_head', '=', 'expense'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)

    def _get_effective_expiry_date(self):
        return (
            self.expiry_date
            or self.contract_id.date_end
            or fields.Date.context_today(self) + timedelta(days=365)
        )

    def action_open_work_permit(self):
        self.ensure_one()
        return self._open_linked_record(self.work_permit_id, _('Work Permit'))

    def action_open_iqama(self):
        self.ensure_one()
        return self._open_linked_record(self.iqama_id, _('Iqama'))

    def action_open_medical_insurance(self):
        self.ensure_one()
        return self._open_linked_record(self.medical_insurance_id, _('Medical Insurance'))

    def action_open_bank_payment(self):
        self.ensure_one()
        return self._open_linked_record(self.bank_payment_id, _('Bank Payment'))

    @staticmethod
    def _open_linked_record(record, name):
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': record._name,
            'res_id': record.id,
            'view_mode': 'form',
            'target': 'current',
        }


class HRWorkPermit(models.Model):
    _inherit = 'hr.work.permit'

    state = fields.Selection(
        selection_add=[
            ('hr_manager_approval', 'HR Manager Approval'),
            ('md_approval', 'MD Approval'),
        ],
        ondelete={
            'hr_manager_approval': 'set default',
            'md_approval': 'set default',
        },
    )
    onboarding_compliance_request_id = fields.Many2one(
        'hr.onboarding.compliance.request',
        string='Onboarding Compliance Request',
        readonly=True,
    )
    hr_manager_approved_by_id = fields.Many2one(
        'res.users',
        string='HR Manager Approved By',
        readonly=True,
        copy=False,
    )
    hr_manager_approved_date = fields.Datetime(string='HR Manager Approved On', readonly=True, copy=False)
    md_approved_by_id = fields.Many2one('res.users', string='MD Approved By', readonly=True, copy=False)
    md_approved_date = fields.Datetime(string='MD Approved On', readonly=True, copy=False)

    def _is_hr_manager_approver(self):
        return (
            self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_manager')
            or self.env.user.has_group('hr.group_hr_manager')
            or self.env.user.has_group('hr_recruitment.group_hr_recruitment_manager')
        )

    def action_submit(self):
        for rec in self:
            if rec.state == 'draft':
                rec.state = 'hr_manager_approval'

    def action_approve_hr_manager(self):
        if not self._is_hr_manager_approver():
            raise UserError(_('Only HR Manager can approve work permits.'))
        for rec in self:
            if rec.state not in ('submit', 'hr_manager_approval'):
                continue
            rec.write({
                'state': 'md_approval',
                'hr_manager_approved_by_id': self.env.user.id,
                'hr_manager_approved_date': fields.Datetime.now(),
            })

    def action_approve_md(self):
        if not self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_md'):
            raise UserError(_('Only Onboarding MD can approve work permits.'))
        for rec in self:
            if rec.state != 'md_approval':
                continue
            rec._create_or_reuse_bank_payment()
            if rec.applicant_onboarding_id:
                rec.applicant_onboarding_id.work_permit_id = rec.id
                rec.applicant_onboarding_id.state = 'work_permit'
            rec.write({
                'state': 'approved',
                'payment_state': 'paid' if rec.bank_payment_id.state == 'posted' else 'pending',
                'md_approved_by_id': self.env.user.id,
                'md_approved_date': fields.Datetime.now(),
            })

    def action_approve(self):
        return self.action_approve_hr_manager()

    def action_reject(self):
        for rec in self:
            if rec.state in ('submit', 'hr_manager_approval'):
                if not self._is_hr_manager_approver():
                    raise UserError(_('Only HR Manager can reject work permits.'))
            elif rec.state == 'md_approval':
                if not self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_md'):
                    raise UserError(_('Only Onboarding MD can reject work permits.'))
            else:
                continue
            rec.state = 'reject'

    def _create_or_reuse_bank_payment(self):
        self.ensure_one()
        if self.bank_payment_id and self.bank_payment_id.state != 'cancel':
            return self.bank_payment_id
        bank_account_id = self.env['account.account'].sudo().search([('code', '=', '1001.02.00.07')], limit=1)
        account_id = bank_account_id if bank_account_id else self.env['account.account'].sudo().browse(749)
        bank_payment = self.env['pr.account.bank.payment'].sudo().create({
            'account_id': account_id.id,
            'description': _('Payment For Work Permit of Visa Number %s') % self.visa_number,
        })
        self.bank_payment_id = bank_payment.id
        bank_payment.work_permit_id = self.id
        return bank_payment

    def _cron_check_alerts(self):
        return self.env['hr.compliance.expiry.reminder.log']._cron_send_expiry_reminders()


class HREmployeeIqama(models.Model):
    _inherit = 'hr.employee.iqama'

    state = fields.Selection(
        selection_add=[
            ('hr_manager_approval', 'HR Manager Approval'),
            ('md_approval', 'MD Approval'),
        ],
        ondelete={
            'hr_manager_approval': 'set default',
            'md_approval': 'set default',
        },
    )
    onboarding_compliance_request_id = fields.Many2one(
        'hr.onboarding.compliance.request',
        string='Onboarding Compliance Request',
        readonly=True,
    )
    hr_manager_approved_by_id = fields.Many2one(
        'res.users',
        string='HR Manager Approved By',
        readonly=True,
        copy=False,
    )
    hr_manager_approved_date = fields.Datetime(string='HR Manager Approved On', readonly=True, copy=False)
    md_approved_by_id = fields.Many2one('res.users', string='MD Approved By', readonly=True, copy=False)
    md_approved_date = fields.Datetime(string='MD Approved On', readonly=True, copy=False)

    def _is_hr_manager_approver(self):
        return (
            self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_manager')
            or self.env.user.has_group('hr.group_hr_manager')
        )

    def action_request_approval(self):
        for rec in self:
            if rec.state == 'draft':
                rec.state = 'hr_manager_approval'

    def action_approve_hr_manager(self):
        if not self._is_hr_manager_approver():
            raise UserError(_('Only HR Manager can approve Iqama requests.'))
        for rec in self:
            if rec.state not in ('pending_approval', 'hr_manager_approval'):
                continue
            rec.write({
                'state': 'md_approval',
                'hr_manager_approved_by_id': self.env.user.id,
                'hr_manager_approved_date': fields.Datetime.now(),
            })

    def action_approve_md(self):
        if not self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_md'):
            raise UserError(_('Only Onboarding MD can approve Iqama requests.'))
        for rec in self:
            if rec.state != 'md_approval':
                continue
            rec.write({
                'state': 'approve',
                'md_approved_by_id': self.env.user.id,
                'md_approved_date': fields.Datetime.now(),
            })

    def action_approve(self):
        return self.action_approve_hr_manager()


class HREmployeeMedicalInsurance(models.Model):
    _inherit = 'hr.employee.medical.insurance'

    state = fields.Selection(
        selection_add=[
            ('hr_manager_approval', 'HR Manager Approval'),
            ('md_approval', 'MD Approval'),
        ],
        ondelete={
            'hr_manager_approval': 'set default',
            'md_approval': 'set default',
        },
    )
    onboarding_compliance_request_id = fields.Many2one(
        'hr.onboarding.compliance.request',
        string='Onboarding Compliance Request',
        readonly=True,
    )
    hr_manager_approved_by_id = fields.Many2one(
        'res.users',
        string='HR Manager Approved By',
        readonly=True,
        copy=False,
    )
    hr_manager_approved_date = fields.Datetime(string='HR Manager Approved On', readonly=True, copy=False)
    md_approved_by_id = fields.Many2one('res.users', string='MD Approved By', readonly=True, copy=False)
    md_approved_date = fields.Datetime(string='MD Approved On', readonly=True, copy=False)

    def _is_hr_manager_approver(self):
        return (
            self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_manager')
            or self.env.user.has_group('hr.group_hr_manager')
        )

    def action_request_approval(self):
        for rec in self:
            if rec.state == 'draft':
                rec.state = 'hr_manager_approval'

    def action_approve_hr_manager(self):
        if not self._is_hr_manager_approver():
            raise UserError(_('Only HR Manager can approve medical insurance requests.'))
        for rec in self:
            if rec.state not in ('pending_approval', 'hr_manager_approval'):
                continue
            rec.write({
                'state': 'md_approval',
                'hr_manager_approved_by_id': self.env.user.id,
                'hr_manager_approved_date': fields.Datetime.now(),
            })

    def action_approve_md(self):
        if not self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_md'):
            raise UserError(_('Only Onboarding MD can approve medical insurance requests.'))
        for rec in self:
            if rec.state != 'md_approval':
                continue
            rec.write({
                'state': 'approve',
                'md_approved_by_id': self.env.user.id,
                'md_approved_date': fields.Datetime.now(),
            })

    def action_approve(self):
        return self.action_approve_hr_manager()


class AccountBankPayment(models.Model):
    _inherit = 'pr.account.bank.payment'

    onboarding_compliance_request_id = fields.Many2one(
        'hr.onboarding.compliance.request',
        string='Onboarding Compliance Request',
        readonly=True,
    )

    def open_onboarding_compliance_request(self):
        self.ensure_one()
        if not self.onboarding_compliance_request_id:
            return None
        view = self.env.ref('qiwa_contract_ocr.view_hr_onboarding_compliance_request_form')
        return {
            'name': _('Onboarding Compliance Request'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.onboarding.compliance.request',
            'views': [(view.id, 'form')],
            'res_id': self.onboarding_compliance_request_id.id,
            'target': 'current',
        }

    def action_post(self):
        res = super().action_post()
        for rec in self:
            request = rec.onboarding_compliance_request_id
            if request:
                request.sudo().payment_state = 'paid'
        return res

    def action_draft(self):
        res = super().action_draft()
        for rec in self:
            request = rec.onboarding_compliance_request_id
            if request and request.requires_payment:
                request.sudo().payment_state = 'pending'
        return res

    def action_cancel(self):
        res = super().action_cancel()
        for rec in self:
            request = rec.onboarding_compliance_request_id
            if request:
                request.sudo().payment_state = 'cancelled'
        return res
