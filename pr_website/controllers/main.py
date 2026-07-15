import logging
import base64
import json
import re
import time
from html import escape
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class CareersController(http.Controller):
    CONTACT_RATE_LIMIT = 8
    CONTACT_RATE_WINDOW = 10 * 60
    CONTACT_CAPTCHA_TTL = 10 * 60
    _contact_attempts_by_ip = {}
    JOB_TITLE_AR = {
        'office receptionist': 'موظف استقبال مكتبي',
    }

    @http.route('/', type='http', auth='public', website=True, sitemap=True)
    def homepage(self, **kwargs):
        return request.render('pr_website.petroraq_homepage_custom')

    @http.route('/contact-us', type='http', auth='public', website=True, sitemap=True)
    def contact_us(self, **kwargs):
        captcha = self._generate_contact_captcha()
        return request.render('pr_website.petroraq_contact_us', {
            'contact_success': kwargs.get('success'),
            'contact_error': kwargs.get('error'),
            'contact_captcha_question': captcha['question'],
            'contact_captcha_nonce': captcha['nonce'],
        })

    @http.route(['/sign-in', '/signin'], type='http', auth='public', website=True, sitemap=True)
    def sign_in_options(self, **kwargs):
        return request.render('pr_website.petroraq_sign_in_options')

    def _generate_contact_captcha(self):
        return request.env['pr.website.captcha.challenge'].sudo().create_contact_challenge(
            ttl_seconds=self.CONTACT_CAPTCHA_TTL,
        )

    def _get_contact_client_ip(self):
        access_route = getattr(request.httprequest, 'access_route', None)
        if access_route:
            return access_route[0]
        return request.httprequest.remote_addr or 'unknown'

    def _validate_contact_rate_limit(self):
        now = time.time()
        client_ip = self._get_contact_client_ip()
        attempts = [
            attempt_time
            for attempt_time in self._contact_attempts_by_ip.get(client_ip, [])
            if now - attempt_time < self.CONTACT_RATE_WINDOW
        ]
        if len(attempts) >= self.CONTACT_RATE_LIMIT:
            self._contact_attempts_by_ip[client_ip] = attempts
            return 'Too many contact form attempts. Please try again later.'
        attempts.append(now)
        self._contact_attempts_by_ip[client_ip] = attempts
        return None

    def _validate_contact_antibot(self, post):
        if (post.get('website') or '').strip():
            return 'Your message could not be submitted. Please try again.'

        return None

    def _validate_contact_captcha(self, post):
        nonce = (post.get('contact_captcha_nonce') or '').strip()
        answer = (post.get('contact_captcha_answer') or '').strip()
        result = request.env['pr.website.captcha.challenge'].sudo().consume_contact_challenge(
            nonce,
            answer,
        )
        if result in ('missing', 'expired'):
            return 'The security question expired. Please answer the new question.'
        if result != 'valid':
            return 'Incorrect security answer. Please try the new question.'
        return None

    def _validate_contact_payload(self, post):
        length_rules = [
            ('name', 2, 100, 'Please enter a valid full name.'),
            ('subject', 2, 160, 'Please enter a valid subject.'),
            ('message', 5, 5000, 'Please enter a valid message.'),
        ]
        for field_name, min_length, max_length, message in length_rules:
            value = (post.get(field_name) or '').strip()
            if not min_length <= len(value) <= max_length:
                return message

        email = (post.get('email') or '').strip()
        if not re.fullmatch(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', email):
            return 'Please enter a valid email address.'

        phone = (post.get('phone') or '').strip()
        if phone and not re.fullmatch(r'^\+?[0-9][0-9\s().-]{7,19}$', phone):
            return 'Please enter a valid phone number.'

        company = (post.get('company') or '').strip()
        if len(company) > 120:
            return 'Company name is too long.'

        return None

    def _build_contact_email_body(self, values, lead):
        rows = [
            ('Name', values['name']),
            ('Email', values['email']),
            ('Phone', values.get('phone') or '-'),
            ('Company', values.get('company') or '-'),
            ('Subject', values['subject']),
            ('CRM Lead', lead.display_name),
        ]
        row_html = ''.join(
            '<tr><td style="padding:6px 12px;font-weight:600;">%s</td><td style="padding:6px 12px;">%s</td></tr>'
            % (escape(label), escape(value))
            for label, value in rows
        )
        return """
            <p>A new contact form submission was received from the Petroraq website.</p>
            <table style="border-collapse:collapse;">%s</table>
            <p style="font-weight:600;margin-top:16px;">Message</p>
            <p style="white-space:pre-wrap;">%s</p>
        """ % (row_html, escape(values['message']))

    @http.route('/website/mail/contact', type='http', auth='public', website=True, methods=['POST'], csrf=True)
    def website_mail_contact(self, **post):
        validation_error = (
            self._validate_contact_rate_limit()
            or self._validate_contact_antibot(post)
            or self._validate_contact_captcha(post)
            or self._validate_contact_payload(post)
        )
        if validation_error:
            return request.redirect('/contact-us?error=%s' % quote_plus(validation_error))

        values = {
            'name': (post.get('name') or '').strip(),
            'email': (post.get('email') or '').strip(),
            'phone': (post.get('phone') or '').strip(),
            'company': (post.get('company') or '').strip(),
            'subject': (post.get('subject') or '').strip(),
            'message': (post.get('message') or '').strip(),
        }

        Lead = request.env['crm.lead'].sudo()
        lead_vals = {
            'name': values['subject'],
            'contact_name': values['name'],
            'email_from': values['email'],
            'phone': values['phone'] or False,
            'partner_name': values['company'] or False,
            'description': values['message'],
            'company_id': request.website.company_id.id,
        }
        if 'type' in Lead._fields:
            lead_vals['type'] = 'lead'
        if 'website_id' in Lead._fields:
            lead_vals['website_id'] = request.website.id
        lead = Lead.create(lead_vals)

        company = request.website.company_id
        email_from = company.email or 'sales@petroraq.com'
        mail = request.env['mail.mail'].sudo().create({
            'subject': 'Website Contact: %s' % values['subject'],
            'body_html': self._build_contact_email_body(values, lead),
            'email_from': email_from,
            'email_to': 'sales@petroraq.com',
            'reply_to': values['email'],
        })
        try:
            mail.send()
        except Exception as exc:
            _logger.exception('Failed to send website contact email for lead %s: %s', lead.id, exc)
            lead.message_post(body='Website contact email notification could not be sent. Please check outgoing mail configuration.')

        return request.redirect('/contact-us?success=1')

    @http.route('/about-us', type='http', auth='public', website=True, sitemap=True)
    def about_us(self, **kwargs):
        return request.render('pr_website.petroraq_about_us')

    @http.route('/clients', type='http', auth='public', website=True, sitemap=True)
    def clients(self, **kwargs):
        return request.render('pr_website.petroraq_our_clients')

    @http.route('/projects', type='http', auth='public', website=True)
    def projects_page(self, **kw):
        return request.render('pr_website.projects_page_template')

    @http.route('/services/design-engineering', type='http', auth='public', website=True)
    def service_design_engineering(self, **kw):
        return request.render('pr_website.service_design_engineering')

    @http.route('/services/architecture-planning', type='http', auth='public', website=True)
    def service_architecture_planning(self, **kw):
        return request.render('pr_website.service_architecture_planning')

    @http.route('/services/civil-structural', type='http', auth='public', website=True)
    def service_civil_structural(self, **kw):
        return request.render('pr_website.service_civil_structural')

    @http.route('/services/electrical-telecommunication', type='http', auth='public', website=True)
    def service_electrical_telecommunication(self, **kw):
        return request.render('pr_website.service_electrical_telecommunication')

    @http.route('/services/mechanical-piping', type='http', auth='public', website=True)
    def service_mechanical_piping(self, **kw):
        return request.render('pr_website.service_mechanical_piping')

    @http.route('/services/cad-services', type='http', auth='public', website=True)
    def service_cad_services(self, **kw):
        return request.render('pr_website.service_cad_services')

    @http.route('/services/other-services', type='http', auth='public', website=True)
    def service_other_services(self, **kw):
        return request.render('pr_website.service_other_services')

    @http.route('/services/project-management', type='http', auth='public', website=True)
    def service_project_management(self, **kw):
        return request.render('pr_website.service_project_management')

    @http.route('/jobs', type='http', auth='public', website=True, sitemap=True)
    def jobs(self, **kwargs):
        jobs = request.env['hr.job'].sudo().search([('website_published', '=', True)], order='create_date desc')
        return request.render('pr_website.careers_jobs', {
            'jobs': jobs,
            'job_display_names': self._get_job_display_names(jobs),
        })

    @http.route('/job/<int:job_id>', type='http', auth='public', website=True, sitemap=True)
    def job_detail(self, job_id, **kwargs):
        job = request.env['hr.job'].sudo().browse(job_id)
        if not job.exists() or not job.website_published:
            return request.not_found()
        degrees = request.env['hr.recruitment.degree'].sudo().search([], order='name')
        countries = request.env['res.country'].sudo().search([], order='name')
        skills = request.env['hr.skill'].sudo().search([], order='skill_type_id, name')
        error_message = kwargs.get('error')
        return request.render('pr_website.careers_job_detail',
                              {
                                  'job': job,
                                  'job_display_name': self._get_job_display_name(job),
                                  'degrees': degrees,
                                  'countries': countries,
                                  'skills': skills,
                                  'error_message': error_message,
                              })

    def _is_arabic_request(self):
        lang = getattr(request, 'lang', None)
        lang_code = getattr(lang, 'code', None) or request.env.context.get('lang') or ''
        return lang_code.lower().startswith('ar')

    def _get_job_display_name(self, job):
        name = (job.with_context(lang=request.env.context.get('lang')).name or '').strip()
        if not self._is_arabic_request() or not name:
            return name
        if re.search(r'[\u0600-\u06FF]', name):
            return name
        return self.JOB_TITLE_AR.get(name.lower(), name)

    def _get_job_display_names(self, jobs):
        return {job.id: self._get_job_display_name(job) for job in jobs}

    def _validate_application_payload(self, post):
        validators = [
            ('partner_name', r"^[A-Za-z][A-Za-z\s'\.-]{1,79}$", 'Please enter a valid full name.'),
            ('email_from', r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', 'Please enter a valid email address.'),
            ('partner_phone', r'^\+?[0-9][0-9\s().-]{7,19}$', 'Please enter a valid phone number.'),
            ('partner_location', r"^[A-Za-z0-9][A-Za-z0-9,\s'\.-]{1,99}$", 'Please enter a valid location.'),
        ]

        for field_name, pattern, message in validators:
            value = (post.get(field_name) or '').strip()
            if not re.fullmatch(pattern, value):
                return message

        numeric_fields = [('experience', 0, 60), ('salary_expected', 1, 100000000), ('notice_period', 0, 3650)]
        for field_name, min_v, max_v in numeric_fields:
            value = (post.get(field_name) or '').strip()
            if not value.isdigit():
                return f'Please enter a valid numeric value for {field_name.replace("_", " ")}.'
            num = int(value)
            if num < min_v or num > max_v:
                return f'{field_name.replace("_", " ").title()} must be between {min_v} and {max_v}.'

        # if (post.get('will_relocate') or '') not in {'yes', 'no'}:
        #     return 'Please select a valid answer for relocation.'
        if (post.get('legally_required') or '') not in {'yes', 'no'}:
            return 'Please select whether you have National ID / Iqama.'

        has_national_id_iqama = post.get('legally_required') == 'yes'
        national_id_iqama = (post.get('national_id_iqama') or '').strip() if has_national_id_iqama else ''
        if has_national_id_iqama and not re.fullmatch(r'\d{10}', national_id_iqama):
            return 'National ID / Iqama Number must be exactly 10 digits.'

        linkedin_profile = (post.get('linkedin_profile') or '').strip()
        if linkedin_profile and not re.fullmatch(r'^(https?://)?([a-z]{2,3}\.)?linkedin\.com/.*$', linkedin_profile):
            return 'Please enter a valid LinkedIn URL.'

        nationality_id = (post.get('nationality_id') or '').strip()
        if not nationality_id.isdigit() or not request.env['res.country'].sudo().browse(int(nationality_id)).exists():
            return 'Please select a valid nationality.'

        # for skill_id in request.httprequest.form.getlist('skill_ids'):
        #     if skill_id and not skill_id.isdigit():
        #         return 'Please select valid skills.'

        return None

    @http.route('/job/<int:job_id>/apply', type='http', auth='public', website=True, methods=['POST'], csrf=True)
    def job_apply(self, job_id, **post):
        job = request.env['hr.job'].sudo().browse(job_id)
        if not job.exists() or not job.website_published:
            return request.not_found()

        validation_error = self._validate_application_payload(post)
        if validation_error:
            return request.redirect(f'/job/{job_id}?error={quote_plus(validation_error)}')

        existing = request.env['hr.applicant'].sudo().search_count([
            ('job_id', '=', job.id),
            ('email_from', '=', (post.get('email_from') or '').strip()),
            ('partner_phone', '=', (post.get('partner_phone') or '').strip()),
        ])
        if existing:
            return request.redirect(
                f'/job/{job_id}?error={quote_plus("Duplicate application detected: you have already applied to this job with the same email and phone number.")}')

        has_national_id_iqama = post.get('legally_required') == 'yes'
        national_id_iqama = (post.get('national_id_iqama') or '').strip() if has_national_id_iqama else ''

        applicant_vals = {
            'name': post.get('name') or post.get('partner_name') or 'Website Candidate',
            'partner_name': (post.get('partner_name') or '').strip(),
            'email_from': (post.get('email_from') or '').strip(),
            'partner_phone': (post.get('partner_phone') or '').strip(),
            'partner_mobile': post.get('partner_mobile'),
            'job_id': job.id,
            'linkedin_profile': (post.get('linkedin_profile') or '').strip(),
            'partner_location': (post.get('partner_location') or '').strip(),
            'will_relocate': post.get('will_relocate'),
            'notice_period': post.get('notice_period'),
            'legally_required': post.get('legally_required'),
            'national_id_iqama': national_id_iqama,
            'salary_expected': post.get('salary_expected'),
            'nationality_id': int(post['nationality_id']) if post.get('nationality_id') and post.get(
                'nationality_id').isdigit() else False,
            'type_id': int(post['type_id']) if post.get('type_id') and post.get('type_id').isdigit() else False,
            'experience': int(post['experience']) if post.get('experience') and post.get(
                'experience').isdigit() else False,
            'description': (
                (post.get('description') or '').strip()
            ),
        }

        applicant = request.env['hr.applicant'].sudo().create(applicant_vals)
        skill_ids = {
            int(skill_id)
            for skill_id in request.httprequest.form.getlist('skill_ids')
            if skill_id and skill_id.isdigit()
        }
        skills = request.env['hr.skill'].sudo().browse(list(skill_ids)).exists()
        for skill in skills:
            skill_levels = skill.skill_type_id.skill_level_ids
            skill_level = skill_levels.filtered('default_level')[:1] or skill_levels[:1]
            if skill_level:
                request.env['hr.applicant.skill'].sudo().create({
                    'applicant_id': applicant.id,
                    'skill_type_id': skill.skill_type_id.id,
                    'skill_id': skill.id,
                    'skill_level_id': skill_level.id,
                })

        resume = post.get('resume')
        if resume and getattr(resume, 'filename', False):
            content = resume.read()
            request.env['ir.attachment'].sudo().create({
                'name': resume.filename,
                'datas': base64.b64encode(content).decode('ascii'),
                'res_model': 'hr.applicant',
                'res_id': applicant.id,
                'mimetype': resume.content_type,
                'type': 'binary',
            })

        return request.redirect('/jobs/thank-you')

    @http.route('/jobs/thank-you', type='http', auth='public', website=True, sitemap=False)
    def job_thank_you(self, **kwargs):
        return request.render('pr_website.careers_thank_you')

    @http.route('/jobs/location_suggest', type='json', auth='public', website=True, methods=['POST'], csrf=False)
    def location_suggest(self, term=None, **kwargs):
        query = (term or '').strip()
        if len(query) < 2:
            return []

        endpoint = (
            "https://geocoding-api.open-meteo.com/v1/search"
            f"?name={quote_plus(query)}&count=8&language=en&format=json"
        )
        req = Request(endpoint, headers={'User-Agent': 'Petroraq-Odoo/1.0 (careers autocomplete)'})
        try:
            with urlopen(req, timeout=4) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except Exception as exc:
            _logger.warning('Location suggestion lookup failed: %s', exc)
            return []

        suggestions = []
        for item in payload.get('results', []):
            name = item.get('name')
            admin = item.get('admin1')
            country = item.get('country')
            parts = [part for part in [name, admin, country] if part]
            if parts:
                suggestions.append(', '.join(parts))
        return suggestions
