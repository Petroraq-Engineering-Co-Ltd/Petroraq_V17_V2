import base64
import io
import logging
import math
import random
import re
import string
from datetime import datetime, timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


NATIONALITY_COUNTRY_ALIASES = {
    'afghan': 'Afghanistan',
    'american': 'United States',
    'bangladeshi': 'Bangladesh',
    'british': 'United Kingdom',
    'egyptian': 'Egypt',
    'filipino': 'Philippines',
    'indian': 'India',
    'jordanian': 'Jordan',
    'lebanese': 'Lebanon',
    'nepali': 'Nepal',
    'pakistani': 'Pakistan',
    'saudi': 'Saudi Arabia',
    'sudanese': 'Sudan',
    'syrian': 'Syria',
    'yemeni': 'Yemen',
}


class QiwaContractProcessor(models.Model):
    _name = 'qiwa.contract.processor'
    _description = 'Qiwa Contract OCR Processor'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char('Reference', required=True, default=lambda self: _('Qiwa Contract'))
    applicant_id = fields.Many2one('hr.applicant', string='Applicant', ondelete='set null', tracking=True)
    pdf_file = fields.Binary('PDF File', attachment=True)
    filename = fields.Char('Filename')
    attachment_id = fields.Many2one('ir.attachment', string='Stored PDF', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('processing', 'Processing'),
        ('processed', 'Processed'),
        ('error', 'Error'),
    ], default='draft', tracking=True)
    error_message = fields.Text('Processing Error', readonly=True)
    raw_text = fields.Text('Extracted Text', readonly=True)
    processed_at = fields.Datetime('Processed On', readonly=True)

    # Contract information
    contract_number = fields.Char('Qiwa Contract Number')
    contract_type = fields.Char('Contract Type')
    contract_execution_date = fields.Date('Contract Execution Date')
    commencement_date = fields.Date('Commencement Date')
    contract_start = fields.Date('Contract Start')
    contract_end = fields.Date('Contract End')
    contract_execution_location = fields.Char('Contract Execution Location')

    # Employer information
    employer_name = fields.Char('Employer Name')
    establishment_type = fields.Char('Establishment Type')
    employer_cr = fields.Char('Unified National No.')
    employer_national_address = fields.Char('Employer National Address')
    employer_phone = fields.Char('Employer Phone')
    employer_mobile = fields.Char('Employer Mobile')
    employer_email = fields.Char('Employer Email')
    signatory_representative = fields.Char('Signatory Representative')
    signatory_id_no = fields.Char('Signatory ID No.')
    signatory_capacity = fields.Char('Signatory Capacity')

    # Employee information
    employee_name = fields.Char('Employee Name')
    nationality = fields.Char('Nationality')
    id_type = fields.Char('ID Type')
    iqama_no = fields.Char('Iqama / ID No.')
    passport_no = fields.Char('Passport No.')
    gender = fields.Char('Gender')
    marital_status = fields.Char('Marital Status')
    birth_date = fields.Date('Birth Date')
    employee_national_address = fields.Char('Employee National Address')
    education_level = fields.Char('Education Level')
    speciality = fields.Char('Speciality')
    mobile_number = fields.Char('Mobile Number')
    email = fields.Char('Email')

    # Job and contract terms
    occupation = fields.Char('Occupation')
    job_title = fields.Char('Job Title')
    work_domain = fields.Char('Work Domain')
    work_location = fields.Char('Work Location')
    work_type = fields.Char('Work Type')
    contract_period_text = fields.Char('Contract Period Text')
    contract_period_months = fields.Integer('Contract Period (Months)')
    probation_period_days = fields.Integer('Probation Period (Days)')
    notice_period_days = fields.Integer('Notice Period (Days)')
    annual_leave_days = fields.Integer('Annual Leave Days')
    working_days_per_week = fields.Integer('Working Days / Week')
    working_hours_per_week = fields.Integer('Working Hours / Week')

    # Wage and bank data
    basic_salary = fields.Float('Basic Salary')
    housing_allowance = fields.Float('Housing Allowance')
    transport_allowance = fields.Float('Transportation Allowance')
    total_salary = fields.Float('Total Salary')
    due_date = fields.Char('Wage Due Date')
    bank_name = fields.Char('Bank Name')
    iban = fields.Char('IBAN')

    employee_id = fields.Many2one('hr.employee', 'Created Employee', readonly=True, tracking=True)
    contract_id = fields.Many2one('hr.contract', 'Created Contract', readonly=True, tracking=True)

    def action_process_contract(self):
        for rec in self:
            rec.write({
                'state': 'processing',
                'error_message': False,
            })
            try:
                text = rec._clean_text(rec._extract_text_from_pdf())
                extracted_data = rec._parse_qiwa_data(text)
                extracted_data.update({
                    'raw_text': text,
                    'processed_at': fields.Datetime.now(),
                })
                extracted_data = rec._sanitize_write_values(extracted_data)
                rec.write(extracted_data)
                rec._create_employee_and_contract()
                rec.write({'state': 'processed'})
                rec.message_post(body=_('Qiwa contract processed successfully.'))
            except Exception as error:
                _logger.exception('Qiwa OCR processing failed for processor %s', rec.id)
                rec.write({
                    'state': 'error',
                    'error_message': str(error),
                })
        return self.action_open_processor()

    def action_open_processor(self):
        self.ensure_one()
        return {
            'name': _('Qiwa Contract OCR'),
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_employee(self):
        self.ensure_one()
        return {
            'name': _('Employee'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee',
            'res_id': self.employee_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_contract(self):
        self.ensure_one()
        return {
            'name': _('Contract'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.contract',
            'res_id': self.contract_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _extract_text_from_pdf(self):
        self.ensure_one()
        if not self.pdf_file:
            raise ValueError(_('Please upload a PDF contract before processing.'))

        pdf_bytes = base64.b64decode(self.pdf_file)
        text = self._extract_text_with_pypdf(pdf_bytes)
        if text.strip():
            return text
        return self._extract_text_with_ocr(pdf_bytes)

    def _extract_text_with_pypdf(self, pdf_bytes):
        try:
            from pypdf import PdfReader
        except ImportError:
            _logger.info('pypdf is not installed; falling back to OCR for Qiwa contract processing.')
            return ''

        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages_text = []
        for page in reader.pages:
            pages_text.append(page.extract_text() or '')
        return '\n'.join(pages_text)

    def _extract_text_with_ocr(self, pdf_bytes):
        try:
            import pytesseract
            from pdf2image import convert_from_bytes
            from PIL import ImageOps
        except ImportError as error:
            raise ValueError(_(
                'No embedded PDF text was found, and OCR dependencies are missing: %s'
            ) % error) from error

        pages_text = []
        for image in convert_from_bytes(pdf_bytes, dpi=220):
            gray_image = ImageOps.grayscale(image)
            pages_text.append(pytesseract.image_to_string(gray_image, lang='eng+ara'))
        text = '\n'.join(pages_text)
        if not text.strip():
            raise ValueError(_('No text could be extracted from the uploaded contract.'))
        return text

    def _parse_qiwa_data(self, text):
        clean_text = self._clean_text(text)
        contract_section = self._section_between(clean_text, '1. Contract Information', '2. First Party')
        employer_section = self._section_between(clean_text, '2. First Party', '3. Second Party')
        employee_section = self._section_between(clean_text, '3. Second Party', '4. Profession')
        profession_section = self._section_between(clean_text, '4. Profession', '5. Contract Period')
        period_section = self._section_between(clean_text, '5. Contract Period', '7. Work Hours')
        leave_section = self._section_between(clean_text, '8. Annual Leaves', '9. Wage')
        wage_section = self._section_between(clean_text, '9. Wage', '11. First Party')
        bank_section = self._section_between(clean_text, '10. Second Party', '11. First Party')

        data = {
            'contract_number': self._extract_label(contract_section, 'Contract number'),
            'contract_type': self._extract_label(contract_section, 'Contract type'),
            'contract_execution_date': self._parse_date(
                self._extract_label(contract_section, 'Contract execution date')
            ),
            'commencement_date': self._parse_date(
                self._extract_label(contract_section, 'Commencement date')
            ),
            'contract_start': self._parse_date(
                self._extract_label(contract_section, 'Starting date')
            ),
            'contract_end': self._parse_date(
                self._extract_label(contract_section, 'Contract end date')
            ),
            'contract_execution_location': (
                self._extract_label(contract_section, 'Contract execution location')
                or self._extract_label(contract_section, 'location')
            ),
            'employer_name': self._extract_label(employer_section, 'Establishment Name', max_follow=3),
            'establishment_type': self._extract_label(employer_section, 'Establishment type'),
            'employer_cr': self._extract_label(employer_section, 'Unified national no.'),
            'employer_national_address': self._extract_label(employer_section, 'National address'),
            'employer_phone': self._extract_label(employer_section, 'Establishment phone number'),
            'employer_mobile': self._extract_label(employer_section, 'Mobile number'),
            'employer_email': self._extract_label(employer_section, 'Official Email of the establishment'),
            'signatory_representative': self._extract_label(employer_section, 'Signatory representative'),
            'signatory_id_no': self._extract_label(employer_section, 'ID no.'),
            'signatory_capacity': self._extract_label(employer_section, 'Capacity'),
            'employee_name': self._extract_label(employee_section, 'Employee name', max_follow=2),
            'nationality': self._extract_label(employee_section, 'Nationality'),
            'id_type': self._extract_label(employee_section, 'ID type'),
            'iqama_no': self._extract_label(employee_section, 'ID no.'),
            'passport_no': self._extract_label(employee_section, 'Passport number'),
            'gender': self._extract_label(employee_section, 'Gender'),
            'marital_status': self._extract_label(employee_section, 'Marital status'),
            'birth_date': self._parse_date(self._extract_label(employee_section, 'Birth date')),
            'employee_national_address': self._extract_label(employee_section, 'National address'),
            'education_level': self._extract_label(employee_section, 'Education level'),
            'speciality': self._extract_label(employee_section, 'Speciality', max_follow=3),
            'mobile_number': self._extract_label(employee_section, 'Mobile number'),
            'email': self._extract_label(employee_section, 'E-mail'),
            'occupation': self._extract_label(profession_section, 'Occupation'),
            'job_title': self._extract_label(profession_section, 'Job title'),
            'work_domain': self._extract_label(profession_section, 'Work domain'),
            'work_location': self._extract_label(profession_section, 'Work location'),
            'work_type': self._extract_label(profession_section, 'Work type'),
            'contract_period_text': self._extract_contract_period_text(period_section),
            'contract_period_months': self._extract_contract_period_months(period_section),
            'probation_period_days': self._extract_int(r'probationary period of\s+(\d+)\s+days', period_section),
            'notice_period_days': self._extract_int(r'at least\s+(\d+)\s+days\s+before', period_section),
            'annual_leave_days': self._extract_int(r'vacation of\s+(\d+)\s+calendar days', leave_section),
            'working_days_per_week': self._extract_int(r'working days shall be\s+(\d+)\s+days', clean_text),
            'working_hours_per_week': self._extract_int(r'working hours shall be weekly\s*(\d+)', clean_text),
            'basic_salary': self._extract_amount(r'Basic\s+Wage\s*:?\s*([\d,]+(?:\.\d+)?)', wage_section),
            'housing_allowance': self._extract_amount(r'Housing\s+Allowance\s*:?\s*([\d,]+(?:\.\d+)?)', wage_section),
            'transport_allowance': self._extract_amount(
                r'Transportation\s+Allowance\s*:?\s*([\d,]+(?:\.\d+)?)',
                wage_section,
            ),
            'total_salary': self._extract_amount(r'Total\s+Wage\s*:?\s*([\d,]+(?:\.\d+)?)', wage_section),
            'due_date': self._extract_label(wage_section, 'Due Date'),
            'bank_name': self._extract_label(bank_section, 'Bank name'),
            'iban': self._normalize_iban(self._extract_label(bank_section, 'IBAN', max_follow=2)),
        }

        if not data['employee_name']:
            raise ValueError(_('Employee name could not be extracted from the Qiwa contract.'))
        if not data['contract_start']:
            data['contract_start'] = data['commencement_date']
        if not data['contract_period_months'] and data['contract_start'] and data['contract_end']:
            data['contract_period_months'] = self._months_between(
                data['contract_start'],
                data['contract_end'],
            )
        return data

    @staticmethod
    def _clean_text(text):
        text = text.replace('\x00', ' ')
        text = re.sub(r'[\x01-\x08\x0b-\x1f\x7f]', ' ', text)
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r' *\n *', '\n', text)
        return text

    @classmethod
    def _sanitize_write_values(cls, values):
        sanitized = {}
        for key, value in values.items():
            if isinstance(value, str):
                sanitized[key] = cls._clean_text(value)
            else:
                sanitized[key] = value
        return sanitized

    @staticmethod
    def _section_between(text, start_marker, end_marker=None):
        start_match = re.search(re.escape(start_marker), text, re.IGNORECASE)
        if not start_match:
            return ''
        start = start_match.start()
        if not end_marker:
            return text[start:]
        end_match = re.search(re.escape(end_marker), text[start_match.end():], re.IGNORECASE)
        if not end_match:
            return text[start:]
        return text[start:start_match.end() + end_match.start()]

    @classmethod
    def _extract_label(cls, text, label, max_follow=1):
        if not text:
            return ''
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        label_regex = re.compile(r'(?:^|\b)%s\s*:?\s*(.*)' % re.escape(label), re.IGNORECASE)
        for index, line in enumerate(lines):
            match = label_regex.search(line)
            if not match:
                continue

            values = [cls._clean_label_value(match.group(1))]
            for offset in range(1, max_follow + 1):
                if index + offset >= len(lines):
                    break
                next_line = lines[index + offset].strip()
                if cls._looks_like_new_english_label(next_line):
                    break
                cleaned_next = cls._clean_label_value(next_line)
                if cleaned_next:
                    values.append(cleaned_next)
            return cls._squash_value(' '.join(value for value in values if value))
        return ''

    @staticmethod
    def _looks_like_new_english_label(line):
        return bool(
            re.match(r'^[A-Z][A-Za-z0-9 &/.\'ʼ()_-]{1,70}:', line)
            or re.match(r'^IBAN\b', line)
        )

    @staticmethod
    def _clean_label_value(value):
        value = (value or '').strip()
        value = re.split(r'\s+:[^A-Za-z0-9]*', value, maxsplit=1)[0]
        if value.startswith(':'):
            return ''
        if not re.search(r'[A-Za-z0-9]', value):
            return ''
        return value.strip(' :-')

    @staticmethod
    def _squash_value(value):
        return re.sub(r'\s+', ' ', (value or '')).strip()

    @staticmethod
    def _parse_date(value):
        value = (value or '').strip()
        value = re.sub(r'[^0-9/-]', '', value)
        for date_format in ('%Y/%m/%d', '%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
            try:
                return datetime.strptime(value, date_format).date()
            except ValueError:
                continue
        return False

    @staticmethod
    def _extract_amount(pattern, text):
        match = re.search(pattern, text or '', re.IGNORECASE | re.DOTALL)
        if not match:
            return 0.0
        return float(match.group(1).replace(',', ''))

    @staticmethod
    def _extract_int(pattern, text):
        match = re.search(pattern, text or '', re.IGNORECASE | re.DOTALL)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _extract_contract_period_text(text):
        match = re.search(r'valid for a period of\s+(.+?),\s+starting', text or '', re.IGNORECASE | re.DOTALL)
        return re.sub(r'\s+', ' ', match.group(1)).strip() if match else ''

    @classmethod
    def _extract_contract_period_months(cls, text):
        period_text = cls._extract_contract_period_text(text)
        match = re.search(r'(\d+)\s*(year|years|month|months)', period_text, re.IGNORECASE)
        if not match:
            return 0
        number = int(match.group(1))
        unit = match.group(2).lower()
        return number * 12 if unit.startswith('year') else number

    @staticmethod
    def _normalize_iban(value):
        value = re.sub(r'[^A-Za-z0-9]', '', value or '')
        return value.upper()

    @staticmethod
    def _months_between(start_date, end_date):
        inclusive_end = end_date + timedelta(days=1)
        months = (inclusive_end.year - start_date.year) * 12 + inclusive_end.month - start_date.month
        if inclusive_end.day < start_date.day:
            months -= 1
        return max(months, 0)

    def _create_employee_and_contract(self):
        self.ensure_one()
        employee = self.employee_id or self._find_existing_employee()
        if employee:
            self.employee_id = employee.id
            employee.write(self._prepare_employee_vals(update_existing=True))
        else:
            employee = self.env['hr.employee'].sudo().create(self._prepare_employee_vals())
            self.employee_id = employee.id

        self._create_private_bank_account(employee)
        contract = self.contract_id
        contract_vals = self._prepare_contract_vals(employee)
        if contract:
            contract.write(contract_vals)
        else:
            contract = self.env['hr.contract'].sudo().create(contract_vals)
        self.contract_id = contract.id

        self._store_pdf_attachment(contract)
        self._link_applicant(employee, contract)

    def _find_existing_employee(self):
        domain = []
        if self.iqama_no:
            domain = [('identification_id', '=', self.iqama_no)]
        elif self.passport_no:
            domain = [('passport_id', '=', self.passport_no)]
        if domain:
            return self.env['hr.employee'].sudo().search(domain, limit=1)
        return self.env['hr.employee']

    def _prepare_employee_vals(self, update_existing=False):
        employee_model = self.env['hr.employee']
        partner = self._get_or_create_private_partner()
        country = self._find_country()
        job = self._get_or_create_job()
        company = (self.applicant_id.company_id if self.applicant_id else False) or self.env.company

        vals = {}
        self._set_if_exists(employee_model, vals, 'name', self.employee_name)
        self._set_if_exists(employee_model, vals, 'company_id', company.id)
        self._set_if_exists(employee_model, vals, 'identification_id', self.iqama_no)
        self._set_if_exists(employee_model, vals, 'passport_id', self.passport_no)
        self._set_if_exists(employee_model, vals, 'country_id', country.id)
        self._set_if_exists(employee_model, vals, 'job_id', job.id)
        if job.department_id:
            self._set_if_exists(employee_model, vals, 'department_id', job.department_id.id)
        self._set_if_exists(employee_model, vals, 'work_email', self.email)
        self._set_if_exists(employee_model, vals, 'private_email', self.email)
        self._set_if_exists(employee_model, vals, 'mobile_phone', self.mobile_number)
        self._set_if_exists(employee_model, vals, 'work_phone', self.mobile_number)
        self._set_if_exists(employee_model, vals, 'birthday', self.birth_date)
        self._set_if_exists(employee_model, vals, 'address_home_id', partner.id)

        gender = self._map_selection_value(employee_model, 'gender', self.gender, {
            'male': 'male',
            'female': 'female',
        })
        self._set_if_exists(employee_model, vals, 'gender', gender)

        marital = self._map_selection_value(employee_model, 'marital', self.marital_status, {
            'single': 'single',
            'married': 'married',
            'marrried': 'married',
            'divorced': 'divorced',
            'widowed': 'widower',
            'widower': 'widower',
        })
        self._set_if_exists(employee_model, vals, 'marital', marital)

        certificate = self._map_certificate(employee_model)
        self._set_if_exists(employee_model, vals, 'certificate', certificate)

        if 'code' in employee_model._fields and (not update_existing or not self.employee_id.code):
            self._set_if_exists(employee_model, vals, 'code', self._generate_employee_code())
        return vals

    def _prepare_contract_vals(self, employee):
        contract_model = self.env['hr.contract']
        job = employee.job_id or self._get_or_create_job()
        department = employee.department_id or job.department_id
        start_date = self.contract_start or self.commencement_date or fields.Date.context_today(self)
        end_date = self.contract_end
        contract_period = self.contract_period_months or (self._months_between(start_date, end_date) if end_date else 0)
        trial_period = math.ceil(self.probation_period_days / 30) if self.probation_period_days else 0
        notice_period = math.ceil(self.notice_period_days / 30) if self.notice_period_days else 0

        vals = {
            'name': self._get_contract_name(employee),
            'employee_id': employee.id,
            'date_start': start_date,
            'wage': self.basic_salary or self.total_salary or 0.0,
            'state': 'draft',
        }
        self._set_if_exists(contract_model, vals, 'date_end', end_date)
        self._set_if_exists(contract_model, vals, 'joining_date', self.commencement_date or start_date)
        self._set_if_exists(contract_model, vals, 'company_id', employee.company_id.id or self.env.company.id)
        self._set_if_exists(contract_model, vals, 'job_id', job.id)
        self._set_if_exists(contract_model, vals, 'department_id', department.id)
        self._set_if_exists(contract_model, vals, 'contract_employment_type', 'recruitment')
        self._set_if_exists(contract_model, vals, 'contract_period', contract_period)
        self._set_if_exists(contract_model, vals, 'trial_period', trial_period)
        self._set_if_exists(contract_model, vals, 'notice_period', notice_period)
        self._set_if_exists(contract_model, vals, 'notes', self._get_contract_notes())

        if 'contract_salary_rule_ids' in contract_model._fields:
            vals['contract_salary_rule_ids'] = [(5, 0, 0)] + self._prepare_salary_rule_lines()
        return vals

    def _prepare_salary_rule_lines(self):
        lines = []
        salary_rules = [
            (self.housing_allowance, 'pr_hr_contract.default_accommodation_salary_rule', 'ACCOMMODATION', 'Accommodation'),
            (self.transport_allowance, 'pr_hr_contract.default_transportation_salary_rule', 'TRANSPORTATION', 'Transportation'),
        ]
        for amount, xmlid, code, name in salary_rules:
            if not amount:
                continue
            rule = (
                self.env.ref(xmlid, raise_if_not_found=False)
                or self.env['hr.salary.rule'].sudo().search([('code', '=', code)], limit=1)
                or self.env['hr.salary.rule'].sudo().search([('name', 'ilike', name)], limit=1)
            )
            if not rule:
                continue
            lines.append((0, 0, {
                'salary_rule_id': rule.id,
                'pay_in_payslip': True,
                'amount_type': 'fixed',
                'amount_value': amount,
            }))
        return lines

    def _get_contract_name(self, employee):
        if self.contract_number:
            return _('Qiwa Contract %(number)s - %(employee)s') % {
                'number': self.contract_number,
                'employee': employee.name,
            }
        return _('Qiwa Contract - %s') % employee.name

    def _get_contract_notes(self):
        parts = [
            _('Qiwa Contract Number: %s') % (self.contract_number or ''),
            _('Contract Type: %s') % (self.contract_type or ''),
            _('Work Location: %s') % (self.work_location or self.contract_execution_location or ''),
            _('Work Type: %s') % (self.work_type or ''),
            _('Occupation: %s') % (self.occupation or ''),
            _('Total Wage: %s') % (self.total_salary or 0.0),
            _('Wage Due Date: %s') % (self.due_date or ''),
            _('Bank: %s') % (self.bank_name or ''),
            _('IBAN: %s') % (self.iban or ''),
        ]
        return '\n'.join(parts)

    def _get_or_create_private_partner(self):
        partner = self.applicant_id.partner_id if self.applicant_id else self.env['res.partner']
        if not partner and self.email:
            partner = self.env['res.partner'].sudo().search([('email', '=', self.email)], limit=1)
        if partner:
            partner_vals = {}
            if self.mobile_number and not partner.mobile:
                partner_vals['mobile'] = self.mobile_number
            if self.email and not partner.email:
                partner_vals['email'] = self.email
            if self.employee_national_address and not partner.street:
                partner_vals['street'] = self.employee_national_address
            if partner_vals:
                partner.sudo().write(partner_vals)
            return partner

        return self.env['res.partner'].sudo().create({
            'name': self.employee_name,
            'email': self.email or False,
            'mobile': self.mobile_number or False,
            'street': self.employee_national_address or False,
            'company_type': 'person',
        })

    def _create_private_bank_account(self, employee):
        if not self.iban or 'bank_account_id' not in employee._fields:
            return
        partner = self._get_employee_bank_partner(employee)
        if not partner:
            return
        bank = self.env['res.bank']
        if self.bank_name:
            bank = self.env['res.bank'].sudo().search([('name', 'ilike', self.bank_name)], limit=1)
            if not bank:
                bank = self.env['res.bank'].sudo().create({'name': self.bank_name})
        bank_account = self.env['res.partner.bank'].sudo().search([
            ('acc_number', '=', self.iban),
            ('partner_id', '=', partner.id),
        ], limit=1)
        if not bank_account:
            bank_account = self.env['res.partner.bank'].sudo().create({
                'acc_number': self.iban,
                'partner_id': partner.id,
                'bank_id': bank.id or False,
            })
        employee.sudo().bank_account_id = bank_account.id

    def _get_employee_bank_partner(self, employee):
        partner_fields = ('address_home_id', 'private_address_id', 'work_contact_id')
        for field_name in partner_fields:
            if field_name in employee._fields and employee[field_name]:
                return employee[field_name]

        partner = self._get_or_create_private_partner()
        for field_name in ('address_home_id', 'private_address_id'):
            if field_name in employee._fields:
                employee.sudo().write({field_name: partner.id})
                break
        return partner

    def _find_country(self):
        nationality = (self.nationality or '').strip()
        if not nationality:
            return self.env['res.country']
        country = self.env['res.country'].sudo().search([('name', '=ilike', nationality)], limit=1)
        if country:
            return country
        alias = NATIONALITY_COUNTRY_ALIASES.get(nationality.casefold())
        if alias:
            return self.env['res.country'].sudo().search([('name', '=ilike', alias)], limit=1)
        return self.env['res.country'].sudo().search([('name', 'ilike', nationality)], limit=1)

    def _get_or_create_job(self):
        applicant_job = self.applicant_id.job_id if self.applicant_id else self.env['hr.job']
        title = self.job_title or self.occupation or applicant_job.name
        if applicant_job and not title:
            return applicant_job
        if applicant_job and self._squash_value(title).casefold() == applicant_job.name.casefold():
            return applicant_job
        job = self.env['hr.job'].sudo().search([('name', '=ilike', title)], limit=1) if title else self.env['hr.job']
        if job or not title:
            return job or applicant_job

        vals = {'name': title}
        if 'company_id' in self.env['hr.job']._fields:
            company = (self.applicant_id.company_id if self.applicant_id else False) or self.env.company
            vals['company_id'] = company.id
        if applicant_job.department_id and 'department_id' in self.env['hr.job']._fields:
            vals['department_id'] = applicant_job.department_id.id
        return self.env['hr.job'].sudo().create(vals)

    def _store_pdf_attachment(self, contract):
        if not self.pdf_file:
            return
        if self.attachment_id:
            self.attachment_id.sudo().write({
                'res_model': 'hr.contract',
                'res_id': contract.id,
            })
            return
        attachment = self.env['ir.attachment'].sudo().create({
            'name': self.filename or self._get_contract_name(contract.employee_id),
            'type': 'binary',
            'datas': self.pdf_file,
            'res_model': 'hr.contract',
            'res_id': contract.id,
            'mimetype': 'application/pdf',
        })
        self.attachment_id = attachment.id

    def _link_applicant(self, employee, contract):
        applicant = self.applicant_id
        if not applicant:
            return

        vals = {'qiwa_contract_processor_id': self.id}
        if 'emp_id' in applicant._fields:
            vals['emp_id'] = employee.id
        if 'employee_id' in applicant._fields:
            vals['employee_id'] = employee.id
        applicant.sudo().write(vals)

        onboarding = applicant.applicant_onboarding_id
        if not onboarding:
            onboarding = self.env['hr.applicant.onboarding'].sudo().create({
                'name': applicant.partner_name or self.employee_name,
                'applicant_id': applicant.id,
                'employee_id': employee.id,
                'hire_type': 'local',
                'state': 'initialize',
            })
            applicant.sudo().applicant_onboarding_id = onboarding.id
        elif onboarding.employee_id != employee:
            onboarding.sudo().employee_id = employee.id

        message = _(
            'Qiwa contract %(contract)s processed. Employee %(employee)s and HR contract %(hr_contract)s are linked.'
        ) % {
            'contract': self.contract_number or self.name,
            'employee': employee.display_name,
            'hr_contract': contract.display_name,
        }
        applicant.message_post(body=message)

    @staticmethod
    def _set_if_exists(model, vals, field_name, value):
        if field_name in model._fields and value not in (False, None, ''):
            vals[field_name] = value

    @staticmethod
    def _map_selection_value(model, field_name, raw_value, mapping):
        if field_name not in model._fields or not raw_value:
            return False
        selection_values = dict(model._fields[field_name].selection).keys()
        mapped = mapping.get(raw_value.strip().casefold())
        return mapped if mapped in selection_values else False

    def _map_certificate(self, employee_model):
        if 'certificate' not in employee_model._fields or not self.education_level:
            return False
        value = self.education_level.casefold()
        selection_values = dict(employee_model._fields['certificate'].selection).keys()
        candidates = []
        if 'bachelor' in value:
            candidates = ['bachelor', 'graduate']
        elif 'master' in value:
            candidates = ['master']
        elif 'doctor' in value or 'phd' in value:
            candidates = ['doctor']
        elif 'diploma' in value:
            candidates = ['graduate', 'other']
        for candidate in candidates:
            if candidate in selection_values:
                return candidate
        return 'other' if 'other' in selection_values else False

    def _generate_employee_code(self):
        employee_model = self.env['hr.employee'].sudo()
        characters = string.ascii_uppercase + string.digits
        for dummy in range(100):
            code = ''.join(random.choice(characters) for _counter in range(4))
            if not employee_model.search_count([('code', '=', code)]):
                return code
        return False
