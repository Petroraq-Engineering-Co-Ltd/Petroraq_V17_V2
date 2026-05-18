from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


COMPLIANCE_REQUEST_TYPES = [
    ('iqama_transfer', 'Iqama Transfer Request'),
    ('work_permit_issuance', 'Work Permit Issuance'),
    ('work_permit_renewal', 'Work Permit Renewal'),
    ('medical_insurance_activation', 'Medical Insurance Activation'),
    ('iqama_renewal', 'Iqama Renewal'),
    ('gosi_registration', 'GOSI Registration'),
    ('other', 'Other Compliance Requirement'),
]

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

    @api.depends('employee_id', 'employee_id.country_id', 'employee_id.country_id.is_homeland')
    def _compute_employee_category(self):
        for rec in self:
            rec.employee_category = 'saudi' if rec.employee_id.country_id.is_homeland else 'expat'

    @api.depends('compliance_request_ids')
    def _compute_compliance_request_count(self):
        for rec in self:
            rec.compliance_request_count = len(rec.compliance_request_ids)

    def generate_checklist(self):
        for rec in self:
            rec._sync_employee_type_checklist()
            rec.state = 'checklist'

    def _sync_employee_type_checklist(self):
        self.ensure_one()
        checklist_vals = self._get_employee_type_checklist_vals()
        existing_keys = set()
        for checklist in self.checklist_ids:
            existing_keys.add(checklist.request_type or checklist.checklist_item)

        lines_to_create = []
        for item in checklist_vals:
            key = item.get('request_type') or item['checklist_item']
            if key not in existing_keys:
                lines_to_create.append((0, 0, item))
        if lines_to_create:
            self.write({'checklist_ids': lines_to_create})

    def _get_employee_type_checklist_vals(self):
        self.ensure_one()
        common_items = [
            {'checklist_item': 'Signed Qiwa Contract / Employment Contract'},
            {'checklist_item': 'Bank IBAN Confirmation'},
            {'checklist_item': 'Emergency Contact Details'},
        ]
        if self.employee_category == 'saudi':
            return common_items + [
                {'checklist_item': 'National ID Copy'},
                {'checklist_item': 'GOSI Registration', 'request_type': 'gosi_registration'},
                {
                    'checklist_item': 'Medical Insurance Activation',
                    'request_type': 'medical_insurance_activation',
                },
            ]

        return common_items + [
            {'checklist_item': 'Passport Copy'},
            {'checklist_item': 'Iqama Copy'},
            {'checklist_item': 'Iqama Transfer Request', 'request_type': 'iqama_transfer'},
            {'checklist_item': 'Work Permit Issuance', 'request_type': 'work_permit_issuance'},
            {'checklist_item': 'Work Permit Renewal', 'request_type': 'work_permit_renewal'},
            {'checklist_item': 'Iqama Renewal', 'request_type': 'iqama_renewal'},
            {
                'checklist_item': 'Medical Insurance Activation',
                'request_type': 'medical_insurance_activation',
            },
            {'checklist_item': 'GOSI Registration', 'request_type': 'gosi_registration'},
        ]

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

    request_type = fields.Selection(COMPLIANCE_REQUEST_TYPES, string='Request Type')
    compliance_request_id = fields.Many2one(
        'hr.onboarding.compliance.request',
        string='Compliance Request',
        readonly=True,
    )


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
        return super().create(vals)

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
        is_md = self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_md')
        for rec in self:
            rec.is_onboarding_supervisor = is_supervisor
            rec.is_onboarding_md = is_md

    @api.depends('bank_payment_id')
    def _compute_payment_flags(self):
        for rec in self:
            rec.has_bank_payment = bool(rec.bank_payment_id)

    def action_submit(self):
        if not self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_supervisor'):
            raise UserError(_('Only Onboarding Supervisor can submit onboarding compliance requests.'))
        for rec in self:
            if rec.state == 'draft':
                rec.state = 'md_approval'

    def action_approve_md(self):
        if not self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_md'):
            raise UserError(_('Only Onboarding MD can approve onboarding compliance requests.'))
        for rec in self:
            if rec.state != 'md_approval':
                continue
            rec._create_or_update_linked_record()
            rec._ensure_accounting_payment()
            rec.write({
                'state': 'approved',
                'md_approved_by_id': self.env.user.id,
                'md_approved_date': fields.Datetime.now(),
            })

    def action_reject(self):
        if not self.env.user.has_group('pr_hr_recruitment_request.group_onboarding_md'):
            raise UserError(_('Only Onboarding MD can reject onboarding compliance requests.'))
        self.write({'state': 'rejected'})

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
        self.write({'state': 'cancelled'})

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
            'state': 'draft',
        }
        if work_permit:
            work_permit_vals.pop('state', None)
            work_permit.write(work_permit_vals)
        else:
            work_permit = self.env['hr.work.permit'].sudo().create(work_permit_vals)
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

        bank_payment.action_submit()
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

    onboarding_compliance_request_id = fields.Many2one(
        'hr.onboarding.compliance.request',
        string='Onboarding Compliance Request',
        readonly=True,
    )


class HREmployeeIqama(models.Model):
    _inherit = 'hr.employee.iqama'

    onboarding_compliance_request_id = fields.Many2one(
        'hr.onboarding.compliance.request',
        string='Onboarding Compliance Request',
        readonly=True,
    )


class HREmployeeMedicalInsurance(models.Model):
    _inherit = 'hr.employee.medical.insurance'

    onboarding_compliance_request_id = fields.Many2one(
        'hr.onboarding.compliance.request',
        string='Onboarding Compliance Request',
        readonly=True,
    )


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
