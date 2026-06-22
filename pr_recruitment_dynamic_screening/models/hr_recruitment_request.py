# -*- coding: utf-8 -*-

from odoo import _, Command, api, fields, models
from odoo.exceptions import ValidationError

from .hr_job import (
    EDUCATION_SCREENING_RULES,
    IQAMA_SCREENING_RULES,
    LOCATION_SCREENING_RULES,
    NATIONALITY_SCREENING_RULES,
    NUMERIC_SCREENING_RULES,
    validate_numeric_screening_configuration,
)


class HrRecruitmentRequest(models.Model):
    _inherit = "hr.recruitment.request"

    application_question_ids = fields.One2many(
        "pr.recruitment.question",
        "request_id",
        string="Application Questions",
        copy=True,
    )
    core_location_rule = fields.Selection(
        LOCATION_SCREENING_RULES,
        string="Location Rule",
        required=True,
        default="none",
        copy=True,
    )
    core_location_values = fields.Text(
        string="Allowed Location Terms",
        help="Enter one location or matching term per line.",
        copy=True,
    )
    core_nationality_rule = fields.Selection(
        NATIONALITY_SCREENING_RULES,
        string="Nationality Rule",
        required=True,
        default="none",
        copy=True,
    )
    core_nationality_ids = fields.Many2many(
        "res.country",
        "pr_request_core_nationality_rel",
        "request_id",
        "country_id",
        string="Selected Nationalities",
        help=(
            "Nationalities that are allowed or excluded according to the selected rule."
        ),
        copy=True,
    )
    core_education_rule = fields.Selection(
        EDUCATION_SCREENING_RULES,
        string="Education Rule",
        required=True,
        default="none",
        copy=True,
    )
    core_education_degree_ids = fields.Many2many(
        "hr.recruitment.degree",
        "pr_request_core_education_degree_rel",
        "request_id",
        "degree_id",
        string="Allowed Education Degrees",
        copy=True,
    )
    core_minimum_education_id = fields.Many2one(
        "hr.recruitment.degree",
        string="Minimum Education Degree",
        ondelete="restrict",
        copy=True,
    )
    core_experience_rule = fields.Selection(
        NUMERIC_SCREENING_RULES,
        string="Experience Rule",
        required=True,
        default="none",
        copy=True,
    )
    core_experience_minimum = fields.Float(
        string="Minimum Experience (Years)", copy=True
    )
    core_experience_maximum = fields.Float(
        string="Maximum Experience (Years)", copy=True
    )
    core_notice_period_rule = fields.Selection(
        NUMERIC_SCREENING_RULES,
        string="Notice Period Rule",
        required=True,
        default="none",
        copy=True,
    )
    core_notice_period_minimum = fields.Integer(
        string="Minimum Notice Period (Days)", copy=True
    )
    core_notice_period_maximum = fields.Integer(
        string="Maximum Notice Period (Days)", copy=True
    )
    core_salary_rule = fields.Selection(
        NUMERIC_SCREENING_RULES,
        string="Expected Salary Rule",
        required=True,
        default="none",
        copy=True,
    )
    core_salary_minimum = fields.Float(
        string="Minimum Expected Salary (SAR)", copy=True
    )
    core_salary_maximum = fields.Float(
        string="Maximum Expected Salary (SAR)", copy=True
    )
    core_iqama_rule = fields.Selection(
        IQAMA_SCREENING_RULES,
        string="National ID / Iqama Rule",
        required=True,
        default="none",
        copy=True,
    )

    _CORE_SCREENING_FIELDS = {
        "core_location_rule",
        "core_location_values",
        "core_nationality_rule",
        "core_nationality_ids",
        "core_education_rule",
        "core_education_degree_ids",
        "core_minimum_education_id",
        "core_experience_rule",
        "core_experience_minimum",
        "core_experience_maximum",
        "core_notice_period_rule",
        "core_notice_period_minimum",
        "core_notice_period_maximum",
        "core_salary_rule",
        "core_salary_minimum",
        "core_salary_maximum",
        "core_iqama_rule",
    }

    @api.constrains(*_CORE_SCREENING_FIELDS)
    def _check_core_screening_configuration(self):
        for request_record in self:
            terms = [
                line
                for line in (request_record.core_location_values or "").splitlines()
                if line.strip()
            ]
            if request_record.core_location_rule != "none" and not terms:
                raise ValidationError(
                    _("Enter at least one allowed location or matching term.")
                )
            if (
                request_record.core_nationality_rule in ("allowed", "excluded")
                and not request_record.core_nationality_ids
            ):
                raise ValidationError(
                    _("Select at least one nationality for the selected rule.")
                )
            if (
                request_record.core_education_rule == "allowed"
                and not request_record.core_education_degree_ids
            ):
                raise ValidationError(
                    _("Select at least one allowed education degree.")
                )
            if (
                request_record.core_education_rule == "minimum"
                and not request_record.core_minimum_education_id
            ):
                raise ValidationError(_("Select the minimum education degree."))
            validate_numeric_screening_configuration(
                request_record.core_experience_rule,
                request_record.core_experience_minimum,
                request_record.core_experience_maximum,
                _("Experience"),
            )
            validate_numeric_screening_configuration(
                request_record.core_notice_period_rule,
                request_record.core_notice_period_minimum,
                request_record.core_notice_period_maximum,
                _("Notice period"),
            )
            validate_numeric_screening_configuration(
                request_record.core_salary_rule,
                request_record.core_salary_minimum,
                request_record.core_salary_maximum,
                _("Expected salary"),
            )

    def write(self, values):
        result = super().write(values)
        if self._CORE_SCREENING_FIELDS.intersection(values):
            for request_record in self.filtered(
                lambda record: record.state in ("approved", "done")
            ):
                request_record._sync_core_screening_to_job()
        return result

    def _sync_core_screening_to_job(self, job=None):
        for request_record in self:
            target_job = job or request_record.job_id or request_record.created_job_id
            if not target_job:
                continue
            target_job.sudo().write(
                {
                    "core_location_rule": request_record.core_location_rule,
                    "core_location_values": request_record.core_location_values,
                    "core_nationality_rule": request_record.core_nationality_rule,
                    "core_nationality_ids": [
                        Command.set(request_record.core_nationality_ids.ids)
                    ],
                    "core_education_rule": request_record.core_education_rule,
                    "core_education_degree_ids": [
                        Command.set(request_record.core_education_degree_ids.ids)
                    ],
                    "core_minimum_education_id": (
                        request_record.core_minimum_education_id.id
                    ),
                    "core_experience_rule": request_record.core_experience_rule,
                    "core_experience_minimum": (
                        request_record.core_experience_minimum
                    ),
                    "core_experience_maximum": (
                        request_record.core_experience_maximum
                    ),
                    "core_notice_period_rule": (
                        request_record.core_notice_period_rule
                    ),
                    "core_notice_period_minimum": (
                        request_record.core_notice_period_minimum
                    ),
                    "core_notice_period_maximum": (
                        request_record.core_notice_period_maximum
                    ),
                    "core_salary_rule": request_record.core_salary_rule,
                    "core_salary_minimum": request_record.core_salary_minimum,
                    "core_salary_maximum": request_record.core_salary_maximum,
                    "core_iqama_rule": request_record.core_iqama_rule,
                }
            )
        return True

    def _publish_recruitment_job(self, job):
        result = super()._publish_recruitment_job(job)
        for request_record in self:
            request_record._sync_core_screening_to_job(job)
            request_record.application_question_ids.sudo().copy_to_job(job.sudo())
        return result

    def action_sync_application_questions(self):
        self.check_access_rights("read")
        for request_record in self:
            request_record.check_access_rule("read")
            job = request_record.job_id or request_record.created_job_id
            if job:
                request_record._sync_core_screening_to_job(job)
                request_record.application_question_ids.sudo().copy_to_job(job.sudo())
        return True
