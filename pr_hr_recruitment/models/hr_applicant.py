import base64
from datetime import timedelta
from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date
import logging
import random
import string

_logger = logging.getLogger(__name__)

AVAILABLE_PRIORITIES = [
    ('0', 'Normal'),
    ('1', 'Good'),
    ('2', 'Very Good'),
    ('3', 'Excellent')
]

INTERVIEW_SCORE_SELECTION = [
    ('0', 'Not Rated'),
    ('1', '1'),
    ('2', '2'),
    ('3', '3'),
    ('4', '4'),
    ('5', '5'),
]

INTERVIEW_RECOMMENDATION_SELECTION = [
    ('shortlist', 'Shortlist for Next Round'),
    ('reject', 'Reject'),
    ('hold', 'Keep on Hold'),
    ('hire', 'Hire'),
]

ALLOWANCE_TYPE_SELECTION = [
    ('none', 'None'),
    ('fixed', 'Fixed Amount'),
    ('percentage', 'Percentage of Basic Salary'),
]

FIRST_INTERVIEW_STAGE_KEYWORDS = (
    '1st interview',
    'first interview',
)
SECOND_INTERVIEW_STAGE_KEYWORDS = (
    '2nd interview',
    'second interview',
)
CONTRACT_PROPOSAL_STAGE_KEYWORDS = (
    'contract proposal',
    'offer letter',
    'job offer',
)


class HrApplicant(models.Model):
    """
    """
    # region [Initial]
    _inherit = 'hr.applicant'
    # endregion [Initial]

    # region [Fields]

    applicant_onboarding_id = fields.Many2one("hr.applicant.onboarding", string="Application Onboarding")
    second_interviewer_ids = fields.Many2many('res.users', 'hr_applicant_res_users_2interviewers_rel',
                                              string='Interviewers', index=True, tracking=True,
                                              domain="[('share', '=', False), ('company_ids', 'in', company_id)]")
    second_priority = fields.Selection(AVAILABLE_PRIORITIES, "Evaluation", default='0')
    second_availability = fields.Date("Availability",
                               help="The date at which the applicant will be available to start working", tracking=True)
    second_salary_proposed = fields.Float("Proposed Salary", group_operator="avg", help="Salary Proposed by the Organisation",
                                   tracking=True, groups="hr_recruitment.group_hr_recruitment_user")
    check_first_interview_stage_sequence = fields.Boolean(compute="_compute_check_first_interview_stage_sequence")
    check_second_interview_stage_sequence = fields.Boolean(compute="_compute_check_second_interview_stage_sequence")
    next_stage_id = fields.Many2one(
        "hr.recruitment.stage", string="Next Stage", compute="_compute_next_stage_id")
    show_first_interview_evaluation = fields.Boolean(compute="_compute_interview_evaluation_visibility")
    show_second_interview_evaluation = fields.Boolean(compute="_compute_interview_evaluation_visibility")
    readonly_first_interview_evaluation = fields.Boolean(compute="_compute_interview_evaluation_visibility")
    readonly_second_interview_evaluation = fields.Boolean(compute="_compute_interview_evaluation_visibility")
    check_contract_proposal_stage = fields.Boolean(compute="_compute_check_contract_proposal_stage")
    show_recruitment_tracking_fields = fields.Boolean(compute="_compute_show_recruitment_tracking_fields")
    offer_letter_attachment_id = fields.Many2one(
        "ir.attachment", string="Offer Letter PDF", readonly=True, copy=False)
    offer_letter_sent_date = fields.Datetime(string="Offer Letter Sent On", readonly=True, copy=False)

    first_communication_score = fields.Selection(
        INTERVIEW_SCORE_SELECTION, string="Communication Skills", default='0', tracking=True)
    first_technical_score = fields.Selection(
        INTERVIEW_SCORE_SELECTION, string="Technical Knowledge", default='0', tracking=True)
    first_experience_score = fields.Selection(
        INTERVIEW_SCORE_SELECTION, string="Relevant Experience", default='0', tracking=True)
    first_behavior_score = fields.Selection(
        INTERVIEW_SCORE_SELECTION, string="Attitude / Behavior", default='0', tracking=True)
    first_overall_score = fields.Selection(
        INTERVIEW_SCORE_SELECTION, string="Overall Rating", default='0', tracking=True)
    first_total_score = fields.Integer(
        string="Total Score", compute="_compute_interview_scores", store=True)
    first_average_score = fields.Float(
        string="Average Score", compute="_compute_interview_scores", store=True, digits=(16, 2))
    first_interview_summary = fields.Text(string="Feedback", tracking=True)
    first_strengths = fields.Text(string="Strengths", tracking=True)
    first_recommendation = fields.Selection(
        INTERVIEW_RECOMMENDATION_SELECTION, string="Recommendation", tracking=True)

    second_communication_score = fields.Selection(
        INTERVIEW_SCORE_SELECTION, string="Communication Skills", default='0', tracking=True)
    second_technical_score = fields.Selection(
        INTERVIEW_SCORE_SELECTION, string="Technical Knowledge", default='0', tracking=True)
    second_experience_score = fields.Selection(
        INTERVIEW_SCORE_SELECTION, string="Relevant Experience", default='0', tracking=True)
    second_behavior_score = fields.Selection(
        INTERVIEW_SCORE_SELECTION, string="Attitude / Behavior", default='0', tracking=True)
    second_overall_score = fields.Selection(
        INTERVIEW_SCORE_SELECTION, string="Overall Rating", default='0', tracking=True)
    second_total_score = fields.Integer(
        string="Total Score", compute="_compute_interview_scores", store=True)
    second_average_score = fields.Float(
        string="Average Score", compute="_compute_interview_scores", store=True, digits=(16, 2))
    second_interview_summary = fields.Text(string="Feedback", tracking=True)
    second_strengths = fields.Text(string="Strengths", tracking=True)
    second_recommendation = fields.Selection(
        INTERVIEW_RECOMMENDATION_SELECTION, string="Recommendation", tracking=True)
    overall_total_score = fields.Integer(
        string="Overall Total Score", compute="_compute_interview_scores", store=True)
    overall_average_score = fields.Float(
        string="Overall Average Score", compute="_compute_interview_scores", store=True, digits=(16, 2))
    overall_interview_summary = fields.Text(
        string="Overall Interview Summary",
        compute="_compute_overall_interview_summary",
        store=True,
        readonly=True,
        tracking=True)

    offer_basic_salary = fields.Float(string="Basic Salary", tracking=True)
    offer_housing_allowance_type = fields.Selection(
        ALLOWANCE_TYPE_SELECTION, string="Housing Allowance", default="percentage", tracking=True)
    offer_housing_allowance_amount = fields.Float(string="Housing Fixed Amount", tracking=True)
    offer_housing_allowance_percentage = fields.Float(string="Housing Percentage", default=25.0, tracking=True)
    offer_transportation_allowance_type = fields.Selection(
        ALLOWANCE_TYPE_SELECTION, string="Transportation Allowance", default="percentage", tracking=True)
    offer_transportation_allowance_amount = fields.Float(string="Transportation Fixed Amount", tracking=True)
    offer_transportation_allowance_percentage = fields.Float(
        string="Transportation Percentage", default=10.0, tracking=True)
    offer_food_allowance_type = fields.Selection(
        ALLOWANCE_TYPE_SELECTION, string="Food Allowance", default="none", tracking=True)
    offer_food_allowance_amount = fields.Float(string="Food Fixed Amount", tracking=True)
    offer_food_allowance_percentage = fields.Float(string="Food Percentage", tracking=True)
    offer_fixed_overtime = fields.Float(string="Fixed Overtime", tracking=True)
    offer_gross_salary = fields.Float(
        string="Gross Salary", compute="_compute_offer_gross_salary", store=True, tracking=True)
    offer_contract_status = fields.Char(string="Contract Status", default="Single", tracking=True)
    offer_medical = fields.Char(string="Medical", default="Provided by company as per company policy", tracking=True)
    offer_contract_duration = fields.Char(string="Contract Duration", default="02 (Two) Years (Renewable)", tracking=True)
    offer_probation_period = fields.Char(string="Probation Period", default="90 Days", tracking=True)
    offer_vacation = fields.Char(string="Vacation", default="21 working days paid vacation per annum", tracking=True)
    offer_working_hours = fields.Char(string="Working Hours", default="48 hours per week", tracking=True)
    offer_validity = fields.Char(string="Offer Validity (Legacy)", tracking=True)
    offer_validity_date = fields.Date(
        string="Offer Validity",
        default=lambda self: fields.Date.context_today(self) + timedelta(days=1),
        tracking=True)
    offer_iqama_number = fields.Char(string="Iqama Number", tracking=True)

    # endregion [Fields]

    @staticmethod
    def _stage_matches_keywords(stage, keywords):
        if not stage:
            return False
        stage_name = (stage.name or '').casefold()
        return any(keyword in stage_name for keyword in keywords)

    def _get_interview_stage(self, keywords):
        self.ensure_one()
        domain = []
        if self.job_id:
            domain = ["|", ("job_ids", "=", False), ("job_ids", "in", self.job_id.ids)]
        stages = self.env["hr.recruitment.stage"].search(domain, order="sequence, id")
        return stages.filtered(lambda stage: self._stage_matches_keywords(stage, keywords))[:1]

    def _get_next_recruitment_stage(self, from_stage=False):
        self.ensure_one()
        stage = from_stage or self.stage_id
        if not stage:
            return self.env["hr.recruitment.stage"]

        domain = [("sequence", ">", stage.sequence)]
        if self.job_id:
            domain += ["|", ("job_ids", "=", False), ("job_ids", "in", self.job_id.ids)]
        return self.env["hr.recruitment.stage"].search(domain, order="sequence, id", limit=1)

    @api.depends("stage_id", "job_id")
    def _compute_next_stage_id(self):
        for rec in self:
            rec.next_stage_id = rec._get_next_recruitment_stage()

    @api.depends("stage_id", "job_id")
    def _compute_interview_evaluation_visibility(self):
        for rec in self:
            stage = rec.stage_id
            first_stage = rec._get_interview_stage(FIRST_INTERVIEW_STAGE_KEYWORDS)
            second_stage = rec._get_interview_stage(SECOND_INTERVIEW_STAGE_KEYWORDS)
            is_first_stage = rec._stage_matches_keywords(stage, FIRST_INTERVIEW_STAGE_KEYWORDS)
            is_second_stage = rec._stage_matches_keywords(stage, SECOND_INTERVIEW_STAGE_KEYWORDS)

            after_first_stage = bool(first_stage and stage and stage.sequence > first_stage.sequence)
            after_second_stage = bool(second_stage and stage and stage.sequence > second_stage.sequence)

            rec.show_first_interview_evaluation = is_first_stage or after_first_stage
            rec.show_second_interview_evaluation = is_second_stage or after_second_stage
            rec.readonly_first_interview_evaluation = not is_first_stage
            rec.readonly_second_interview_evaluation = not is_second_stage

    def action_move_to_next_stage(self):
        for rec in self:
            next_stage = rec.next_stage_id
            if not next_stage:
                raise UserError(_("There is no next recruitment stage configured for %s.") % rec.display_name)
            rec.stage_id = next_stage.id
        return True

    def _get_offer_letter_email(self):
        self.ensure_one()
        return self.email_from or self.partner_id.email

    @api.depends("stage_id")
    def _compute_check_contract_proposal_stage(self):
        for rec in self:
            rec.check_contract_proposal_stage = rec._stage_matches_keywords(
                rec.stage_id, CONTRACT_PROPOSAL_STAGE_KEYWORDS)

    def _get_recruitment_stages_for_job(self):
        self.ensure_one()
        domain = []
        if self.job_id:
            domain = ["|", ("job_ids", "=", False), ("job_ids", "in", self.job_id.ids)]
        return self.env["hr.recruitment.stage"].search(domain, order="sequence, id")

    @api.depends("stage_id", "job_id")
    def _compute_show_recruitment_tracking_fields(self):
        for rec in self:
            rec.show_recruitment_tracking_fields = False
            if not rec.stage_id:
                continue
            stages = rec._get_recruitment_stages_for_job()
            if len(stages) >= 2 and rec.stage_id in stages:
                rec.show_recruitment_tracking_fields = rec.stage_id not in stages[:2]
            elif len(stages) >= 2:
                rec.show_recruitment_tracking_fields = rec.stage_id.sequence > stages[1].sequence

    def _get_offer_allowance_amount(self, allowance_type, fixed_amount, percentage, basic_salary=None):
        self.ensure_one()
        basic_salary = self.offer_basic_salary if basic_salary is None else basic_salary
        if allowance_type == "fixed":
            return fixed_amount or 0.0
        if allowance_type == "percentage":
            return basic_salary * (percentage or 0.0) / 100.0
        return 0.0

    @api.depends(
        "offer_basic_salary",
        "offer_housing_allowance_type", "offer_housing_allowance_amount", "offer_housing_allowance_percentage",
        "offer_transportation_allowance_type", "offer_transportation_allowance_amount",
        "offer_transportation_allowance_percentage",
        "offer_food_allowance_type", "offer_food_allowance_amount", "offer_food_allowance_percentage",
        "offer_fixed_overtime")
    def _compute_offer_gross_salary(self):
        for rec in self:
            gross_salary = rec.offer_basic_salary or 0.0
            gross_salary += rec._get_offer_allowance_amount(
                rec.offer_housing_allowance_type,
                rec.offer_housing_allowance_amount,
                rec.offer_housing_allowance_percentage)
            gross_salary += rec._get_offer_allowance_amount(
                rec.offer_transportation_allowance_type,
                rec.offer_transportation_allowance_amount,
                rec.offer_transportation_allowance_percentage)
            gross_salary += rec._get_offer_allowance_amount(
                rec.offer_food_allowance_type,
                rec.offer_food_allowance_amount,
                rec.offer_food_allowance_percentage)
            gross_salary += rec.offer_fixed_overtime or 0.0
            rec.offer_gross_salary = gross_salary

    def _format_offer_letter_date(self, date_value):
        date_value = fields.Date.to_date(date_value)
        return format_date(self.env, date_value)

    @staticmethod
    def _format_offer_letter_amount(amount, currency_name='SAR'):
        return f"{amount:,.2f} {currency_name or 'SAR'}"

    def _format_offer_letter_free_text(self, value, default='To be confirmed'):
        return (value or '').strip() or default

    def _format_offer_allowance_line(self, allowance_type, fixed_amount, percentage, currency_name, basic_salary=None):
        amount = self._get_offer_allowance_amount(allowance_type, fixed_amount, percentage, basic_salary)
        if allowance_type == "fixed":
            return f"{self._format_offer_letter_amount(amount, currency_name)} per month"
        if allowance_type == "percentage":
            return "%s%% of Basic Salary (%s)" % (
                ("%g" % (percentage or 0.0)),
                self._format_offer_letter_amount(amount, currency_name),
            )
        return "Not Applicable"

    def _get_applicant_country(self):
        self.ensure_one()
        country = self.env['res.country']
        if 'nationality_id' in self._fields and self.nationality_id:
            return self.nationality_id
        elif 'country_id' in self._fields and self.country_id:
            return self.country_id
        elif self.partner_id.country_id:
            return self.partner_id.country_id
        return country

    def _get_offer_letter_values(self):
        self.ensure_one()
        offer_date = fields.Date.context_today(self)
        validity_date = offer_date + timedelta(days=1)
        gross_salary = self.offer_gross_salary or self.second_salary_proposed or self.salary_proposed or 0.0
        basic_salary = self.offer_basic_salary or (gross_salary / 1.35 if gross_salary else 0.0)
        housing_type = self.offer_housing_allowance_type or "percentage"
        housing_percentage = self.offer_housing_allowance_percentage or 25.0
        transportation_type = self.offer_transportation_allowance_type or "percentage"
        transportation_percentage = self.offer_transportation_allowance_percentage or 10.0
        food_type = self.offer_food_allowance_type or "none"
        food_percentage = self.offer_food_allowance_percentage or 0.0
        if self.offer_basic_salary:
            gross_salary = basic_salary
            gross_salary += self._get_offer_allowance_amount(
                housing_type, self.offer_housing_allowance_amount, housing_percentage, basic_salary)
            gross_salary += self._get_offer_allowance_amount(
                transportation_type, self.offer_transportation_allowance_amount,
                transportation_percentage, basic_salary)
            gross_salary += self._get_offer_allowance_amount(
                food_type, self.offer_food_allowance_amount, food_percentage, basic_salary)
            gross_salary += self.offer_fixed_overtime or 0.0
        country = self._get_applicant_country()
        nationality = country.name or ''
        if country and 'nationality' in country._fields and country.nationality:
            nationality = country.nationality
        currency_name = (self.company_id.currency_id or self.env.company.currency_id).name or 'SAR'
        validity_display = self._format_offer_letter_date(self.offer_validity_date or validity_date)
        if not self.offer_validity_date and self.offer_validity:
            validity_display = self.offer_validity
        return {
            'date': self._format_offer_letter_date(offer_date),
            'candidate_name': self.partner_name or self.name or '',
            'nationality': nationality,
            'iqama_number': self._format_offer_letter_free_text(self.offer_iqama_number, ''),
            'position': self.job_id.name or '',
            'basic_salary': self._format_offer_letter_amount(basic_salary, currency_name),
            'gross_salary': self._format_offer_letter_amount(gross_salary, currency_name),
            'housing_allowance': self._format_offer_allowance_line(
                housing_type,
                self.offer_housing_allowance_amount,
                housing_percentage,
                currency_name,
                basic_salary),
            'transportation_allowance': self._format_offer_allowance_line(
                transportation_type,
                self.offer_transportation_allowance_amount,
                transportation_percentage,
                currency_name,
                basic_salary),
            'food_allowance': self._format_offer_allowance_line(
                food_type,
                self.offer_food_allowance_amount,
                food_percentage,
                currency_name,
                basic_salary),
            'fixed_overtime': self._format_offer_letter_amount(self.offer_fixed_overtime or 0.0, currency_name),
            'contract_status': self._format_offer_letter_free_text(self.offer_contract_status, 'Single'),
            'medical': self._format_offer_letter_free_text(
                self.offer_medical, 'Provided by company as per company policy'),
            'contract_duration': self._format_offer_letter_free_text(
                self.offer_contract_duration, '02 (Two) Years (Renewable)'),
            'probation_period': self._format_offer_letter_free_text(self.offer_probation_period, '90 Days'),
            'vacation': self._format_offer_letter_free_text(
                self.offer_vacation, '21 working days paid vacation per annum'),
            'working_hours': self._format_offer_letter_free_text(self.offer_working_hours, '48 hours per week'),
            'validity_date': validity_display,
            'company_name': self.company_id.name or self.env.company.name or 'Petroraq Engineering Co. Ltd.',
            'signatory_name': 'Mustafa Abdulrasheed',
            'signatory_title': 'Managing Director',
        }

    def _get_offer_letter_pdf_filename(self):
        self.ensure_one()
        candidate_name = self.partner_name or self.name or _('Applicant')
        return f"Offer Letter - {candidate_name}.pdf"

    def _get_offer_letter_report(self):
        report = self.env.ref(
            'pr_hr_recruitment.action_report_applicant_offer_letter', raise_if_not_found=False)
        if report:
            return report

        return self.env['ir.actions.report'].search([
            ('model', '=', 'hr.applicant'),
            ('report_name', '=', 'pr_hr_recruitment.report_applicant_offer_letter_document'),
            ('report_type', '=', 'qweb-pdf'),
        ], limit=1)

    def _generate_offer_letter_attachment(self):
        self.ensure_one()
        report = self._get_offer_letter_report()
        if not report:
            raise UserError(_(
                "The offer letter report is not loaded in the database yet. "
                "Please upgrade the Petroraq HR Recruitment module so Odoo imports "
                "reports/applicant_offer_letter_report.xml."))
        pdf_content, _content_type = self.env['ir.actions.report']._render_qweb_pdf(report.report_name, self.ids)
        attachment = self.env['ir.attachment'].sudo().create({
            'name': self._get_offer_letter_pdf_filename(),
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })
        self.offer_letter_attachment_id = attachment.id
        return attachment

    def _get_offer_letter_email_template(self):
        template = self.env.ref(
            'pr_hr_recruitment.email_template_applicant_offer_letter', raise_if_not_found=False)
        if template:
            return template

        model_id = self.env['ir.model']._get_id('hr.applicant')
        return self.env['mail.template'].search([
            ('name', '=', 'Applicant Offer Letter'),
            ('model_id', '=', model_id),
        ], limit=1)

    def _send_offer_letter_fallback_email(self, attachment):
        self.ensure_one()
        body_message = self._get_offer_letter_mail_body()
        email_from = (
            self.user_id.email_formatted
            or self.company_id.email
            or self.env.user.email_formatted
        )
        mail = self.env['mail.mail'].sudo().create({
            'email_from': email_from,
            'email_to': self._get_offer_letter_email(),
            'subject': self._get_offer_letter_mail_subject(),
            'body_html': body_message,
            'attachment_ids': [(4, attachment.id)],
        })
        mail.send()

    def _get_offer_letter_mail_body(self):
        self.ensure_one()
        return f"""
            <p>Dear {self.partner_name or self.name},</p>
            <p>
                Congratulations. Please find attached your offer letter for
                <strong>{self.job_id.name or 'the offered position'}</strong>.
            </p>
            <p>
                Kindly review the attached PDF, sign the acceptance section, and return the signed copy to HR.
            </p>
            <p>
                Best regards,<br/>
                <strong>Human Resources Department</strong><br/>
                {self.company_id.name or self.env.company.name}
            </p>
        """

    def _get_offer_letter_mail_subject(self):
        self.ensure_one()
        return f"Offer Letter - {self.job_id.name or self.company_id.name or 'Petroraq'}"

    def _send_offer_letter_direct(self):
        template = self._get_offer_letter_email_template()
        for rec in self:
            email_to = rec._get_offer_letter_email()
            if not email_to:
                raise UserError(_(
                    "Please set an email address for %s before sending the offer letter.") % rec.display_name)
            attachment = rec._generate_offer_letter_attachment()
            if template:
                template.send_mail(
                    rec.id,
                    force_send=True,
                    email_values={'attachment_ids': [(4, attachment.id)]},
                )
            else:
                rec._send_offer_letter_fallback_email(attachment)
            rec.offer_letter_sent_date = fields.Datetime.now()
        return True

    def action_send_offer_letter(self):
        self.ensure_one()
        email_to = self._get_offer_letter_email()
        if not email_to:
            raise UserError(_(
                "Please set an email address for %s before sending the offer letter.") % self.display_name)
        if self.check_contract_proposal_stage and not self.offer_basic_salary:
            raise UserError(_("Please fill the Contract Proposal tab before sending the offer letter."))

        attachment = self._generate_offer_letter_attachment()
        template = self._get_offer_letter_email_template()
        context = {
            'default_model': self._name,
            'default_res_ids': self.ids,
            'default_composition_mode': 'comment',
            'default_email_layout_xmlid': 'mail.mail_notification_layout_with_responsible_signature',
            'force_email': True,
            'default_attachment_ids': [(4, attachment.id)],
            'default_subject': self._get_offer_letter_mail_subject(),
            'default_body': self._get_offer_letter_mail_body(),
            'default_email_to': email_to,
            'default_partner_ids': [self.partner_id.id] if self.partner_id else [],
        }
        if template:
            context.update({
                'default_template_id': template.id,
                'default_use_template': True,
            })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Offer Letter'),
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': context,
        }

    def _send_offer_letter_on_contract_proposal(self):
        return True

    def write(self, vals):
        return super().write(vals)

    @api.depends(
        "first_communication_score", "first_technical_score", "first_experience_score",
        "first_behavior_score", "first_overall_score", "second_communication_score",
        "second_technical_score", "second_experience_score", "second_behavior_score",
        "second_overall_score")
    def _compute_interview_scores(self):
        first_fields = [
            "first_communication_score", "first_technical_score", "first_experience_score",
            "first_behavior_score", "first_overall_score",
        ]
        second_fields = [
            "second_communication_score", "second_technical_score", "second_experience_score",
            "second_behavior_score", "second_overall_score",
        ]
        for rec in self:
            first_total = sum(int(getattr(rec, field_name) or 0) for field_name in first_fields)
            second_total = sum(int(getattr(rec, field_name) or 0) for field_name in second_fields)
            rec.first_total_score = first_total
            rec.first_average_score = first_total / len(first_fields)
            rec.second_total_score = second_total
            rec.second_average_score = second_total / len(second_fields)
            rec.overall_total_score = first_total + second_total
            rec.overall_average_score = rec.overall_total_score / (len(first_fields) + len(second_fields))

    @api.depends(
        "first_total_score", "first_average_score", "first_interview_summary",
        "first_strengths", "first_recommendation", "second_total_score",
        "second_average_score", "second_interview_summary", "second_strengths",
        "second_recommendation", "overall_total_score", "overall_average_score")
    def _compute_overall_interview_summary(self):
        recommendation_labels = dict(INTERVIEW_RECOMMENDATION_SELECTION)
        for rec in self:
            first_recommendation = recommendation_labels.get(rec.first_recommendation or "", "Not provided")
            second_recommendation = recommendation_labels.get(rec.second_recommendation or "", "Not provided")
            rec.overall_interview_summary = "\n".join([
                "Scores",
                "1st Interview: %s/25, Average %.2f/5" % (
                    rec.first_total_score or 0, rec.first_average_score or 0.0),
                "2nd Interview: %s/25, Average %.2f/5" % (
                    rec.second_total_score or 0, rec.second_average_score or 0.0),
                "Overall: %s/50, Average %.2f/5" % (
                    rec.overall_total_score or 0, rec.overall_average_score or 0.0),
                "",
                "Recommendations",
                "1st Interview: %s" % first_recommendation,
                "2nd Interview: %s" % second_recommendation,
                "",
                "Feedback / Remarks",
                "1st Interview: %s" % (rec.first_interview_summary or "Not provided"),
                "2nd Interview: %s" % (rec.second_interview_summary or "Not provided"),
                "",
                "Strengths",
                "1st Interview: %s" % (rec.first_strengths or "Not provided"),
                "2nd Interview: %s" % (rec.second_strengths or "Not provided"),
            ])

    @api.depends("stage_id")
    def _compute_check_first_interview_stage_sequence(self):
        for rec in self:
            rec.check_first_interview_stage_sequence = rec._stage_matches_keywords(
                rec.stage_id, FIRST_INTERVIEW_STAGE_KEYWORDS)

    @api.depends("stage_id")
    def _compute_check_second_interview_stage_sequence(self):
        for rec in self:
            rec.check_second_interview_stage_sequence = rec._stage_matches_keywords(
                rec.stage_id, SECOND_INTERVIEW_STAGE_KEYWORDS)

    @api.constrains("stage_id")
    def _check_stage_to_generate_onboarding(self):
        for rec in self:

            # Check Next Stage

            old_stage = rec.last_stage_id
            new_stage = rec.stage_id
            if old_stage and new_stage and new_stage.sequence != 0:
                next_stage = rec._get_next_recruitment_stage(from_stage=old_stage)
                if new_stage != next_stage:
                    raise ValidationError("You can not go to this step directly, please forward the rules")

            if rec.stage_id and rec.stage_id.hired_stage and not rec.applicant_onboarding_id:
                employee_vals = {
                    "name": rec.partner_name,
                    # "code": "Enter Code Here",
                    "code": self.generate_random_4_char_string(),
                    "company_id": self.env.company.id,
                }
                applicant_country = rec._get_applicant_country()
                if applicant_country:
                    employee_vals["country_id"] = applicant_country.id
                employee_id = self.env["hr.employee"].sudo().create(employee_vals)
                applicant_onboarding_id = self.env["hr.applicant.onboarding"].create({
                    "name": rec.partner_name,
                    "applicant_id": rec.id,
                    "employee_id": employee_id.id if employee_id else False,
                    "hire_type": "local",
                    "state": "initialize",
                })
                if applicant_onboarding_id:
                    rec.applicant_onboarding_id = applicant_onboarding_id.id

    def generate_random_4_char_string(self):
        """Generates a random four-character string composed of letters and digits."""
        characters = string.ascii_letters + string.digits  # All uppercase/lowercase letters and digits
        random_string = ''.join(random.choice(characters) for _ in range(4))
        return random_string

    def open_applicant_onboarding_id_view_form(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Applicant Onboarding'),
            'res_model': 'hr.applicant.onboarding',
            'view_type': 'form',
            'view_mode': 'form',
            'res_id': self.applicant_onboarding_id.id,
        }

    @api.model
    def get_recruitment_dashboard_data(self):
        Applicant = self.env["hr.applicant"].sudo().with_context(active_test=False)
        ActiveApplicant = self.env["hr.applicant"].sudo()
        Job = self.env["hr.job"].sudo().with_context(active_test=False)
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)

        hired_domain = ["|", ("stage_id.hired_stage", "=", True), ("emp_id", "!=", False)]
        open_applicant_domain = [
            ("active", "=", True),
            "|", ("stage_id", "=", False), ("stage_id.hired_stage", "=", False),
        ]
        published_job_domain = [("active", "=", True)]
        if "website_published" in Job._fields:
            published_job_domain.append(("website_published", "=", True))

        total_applicants = Applicant.search_count([])
        hired_applicants = Applicant.search_count(hired_domain)
        open_applicants = Applicant.search_count(open_applicant_domain)
        published_jobs = Job.search_count(published_job_domain)
        active_jobs = Job.search_count([("active", "=", True)])
        month_applicants = Applicant.search_count([
            ("create_date", ">=", fields.Datetime.to_string(month_start)),
        ])
        month_hires = Applicant.search_count(hired_domain + [
            ("write_date", ">=", fields.Datetime.to_string(month_start)),
        ])
        conversion_rate = round((hired_applicants / total_applicants) * 100.0, 1) if total_applicants else 0.0

        pipeline = []
        stages = self.env["hr.recruitment.stage"].sudo().search([], order="sequence, id")
        max_stage_count = 1
        stage_counts = {}
        for stage in stages:
            count = ActiveApplicant.search_count([("stage_id", "=", stage.id)])
            stage_counts[stage.id] = count
            max_stage_count = max(max_stage_count, count)
        for stage in stages:
            count = stage_counts[stage.id]
            pipeline.append({
                "id": stage.id,
                "name": stage.name,
                "count": count,
                "percent": round((count / max_stage_count) * 100.0, 1) if count else 0.0,
                "hired": bool(stage.hired_stage),
            })

        top_jobs = []
        job_groups = Applicant.read_group(
            [("job_id", "!=", False)],
            ["job_id"],
            ["job_id"],
            orderby="job_id_count desc",
            limit=6,
        )
        for group in job_groups:
            job_id = group.get("job_id")
            if not job_id:
                continue
            job = Job.browse(job_id[0])
            hired_for_job = Applicant.search_count([("job_id", "=", job.id)] + hired_domain)
            total_for_job = group.get("job_id_count") or group.get("__count", 0)
            top_jobs.append({
                "id": job.id,
                "name": job.display_name,
                "department": job.department_id.display_name or _("No Department"),
                "count": total_for_job,
                "hired": hired_for_job,
                "target": job.no_of_recruitment or 0,
                "percent": round((hired_for_job / (job.no_of_recruitment or total_for_job or 1)) * 100.0, 1),
            })

        department_counts = {}
        applicants_with_department = Applicant.search([("job_id", "!=", False)])
        for applicant in applicants_with_department:
            department = applicant.job_id.department_id
            if not department:
                continue
            department_counts.setdefault(department.id, {
                "id": department.id,
                "name": department.display_name,
                "count": 0,
            })
            department_counts[department.id]["count"] += 1
        departments = sorted(
            department_counts.values(),
            key=lambda department: department["count"],
            reverse=True,
        )[:6]
        max_department_count = max([department["count"] for department in departments] or [1])
        for department in departments:
            department["percent"] = round(
                (department["count"] / max_department_count) * 100.0,
                1,
            ) if department["count"] else 0.0

        monthly = []
        for index in range(5, -1, -1):
            start = (month_start - relativedelta(months=index))
            end = start + relativedelta(months=1)
            start_dt = fields.Datetime.to_string(start)
            end_dt = fields.Datetime.to_string(end)
            applications = Applicant.search_count([
                ("create_date", ">=", start_dt),
                ("create_date", "<", end_dt),
            ])
            hires = Applicant.search_count(hired_domain + [
                ("write_date", ">=", start_dt),
                ("write_date", "<", end_dt),
            ])
            monthly.append({
                "label": start.strftime("%b"),
                "applications": applications,
                "hires": hires,
            })
        max_monthly = max([max(item["applications"], item["hires"]) for item in monthly] or [1])
        for item in monthly:
            item["applications_percent"] = round((item["applications"] / max_monthly) * 100.0, 1) if item["applications"] else 0.0
            item["hires_percent"] = round((item["hires"] / max_monthly) * 100.0, 1) if item["hires"] else 0.0

        request_states = []
        pending_requests = 0
        approved_requests = 0
        if self.env.registry.get("hr.recruitment.request"):
            Request = self.env["hr.recruitment.request"].sudo()
            labels = dict(Request._fields["state"].selection)
            request_groups = Request.read_group([], ["state"], ["state"])
            request_counts = {
                group.get("state"): group.get("state_count") or group.get("__count", 0)
                for group in request_groups
            }
            pending_requests = sum(
                request_counts.get(state, 0)
                for state in ("hr_approval", "hrm_approval", "md_approval")
            )
            approved_requests = request_counts.get("approved", 0)
            for state, label in labels.items():
                request_states.append({
                    "state": state,
                    "label": label,
                    "count": request_counts.get(state, 0),
                })

        recent_applicants = []
        for applicant in Applicant.search([], order="create_date desc", limit=8):
            recent_applicants.append({
                "id": applicant.id,
                "name": applicant.partner_name or applicant.name,
                "job": applicant.job_id.display_name or _("No Job"),
                "stage": applicant.stage_id.display_name or _("No Stage"),
                "created": fields.Date.to_string(fields.Date.to_date(applicant.create_date)),
                "hired": bool(applicant.stage_id.hired_stage or applicant.emp_id),
            })

        return {
            "cards": [
                {
                    "key": "applicants",
                    "label": _("Total Applicants"),
                    "value": total_applicants,
                    "icon": "fa-users",
                    "model": "hr.applicant",
                    "domain": [],
                },
                {
                    "key": "open_applicants",
                    "label": _("In Progress"),
                    "value": open_applicants,
                    "icon": "fa-hourglass-half",
                    "model": "hr.applicant",
                    "domain": open_applicant_domain,
                },
                {
                    "key": "hired",
                    "label": _("Hired"),
                    "value": hired_applicants,
                    "icon": "fa-check-circle",
                    "model": "hr.applicant",
                    "domain": hired_domain,
                },
                {
                    "key": "jobs",
                    "label": _("Open Positions"),
                    "value": published_jobs,
                    "icon": "fa-briefcase",
                    "model": "hr.job",
                    "domain": published_job_domain,
                },
                {
                    "key": "requests",
                    "label": _("Pending Requests"),
                    "value": pending_requests,
                    "icon": "fa-file-text-o",
                    "model": "hr.recruitment.request" if self.env.registry.get("hr.recruitment.request") else False,
                    "domain": [("state", "in", ["hr_approval", "hrm_approval", "md_approval"])],
                },
            ],
            "summary": {
                "active_jobs": active_jobs,
                "published_jobs": published_jobs,
                "month_applicants": month_applicants,
                "month_hires": month_hires,
                "conversion_rate": conversion_rate,
                "approved_requests": approved_requests,
            },
            "pipeline": pipeline,
            "top_jobs": top_jobs,
            "departments": departments,
            "monthly": monthly,
            "request_states": request_states,
            "recent_applicants": recent_applicants,
        }
