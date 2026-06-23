# -*- coding: utf-8 -*-

import math

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


LOCATION_SCREENING_RULES = [
    ("none", "No Location Screening"),
    ("exact", "Allow Exact Locations"),
    ("contains", "Location Contains Any Term"),
]

NATIONALITY_SCREENING_RULES = [
    ("none", "No Nationality Screening"),
    ("allowed", "Allow Selected Nationalities"),
    ("excluded", "Allow All Except Selected Nationalities"),
]

EDUCATION_SCREENING_RULES = [
    ("none", "No Education Screening"),
    ("allowed", "Allow Selected Degrees"),
    ("minimum", "Require Minimum Degree Level"),
]

NUMERIC_SCREENING_RULES = [
    ("none", "No Screening"),
    ("minimum", "Minimum Value"),
    ("maximum", "Maximum Value"),
    ("range", "Allowed Range"),
]

IQAMA_SCREENING_RULES = [
    ("none", "No National ID / Iqama Screening"),
    ("required", "Require Valid National ID / Iqama"),
]


def validate_numeric_screening_configuration(rule, minimum, maximum, label):
    if rule == "none":
        return
    relevant_values = []
    if rule in ("minimum", "range"):
        relevant_values.append(minimum)
    if rule in ("maximum", "range"):
        relevant_values.append(maximum)
    if any(not math.isfinite(value) or value < 0 for value in relevant_values):
        raise ValidationError(_("%s thresholds must be finite and non-negative.") % label)
    if rule == "range" and minimum > maximum:
        raise ValidationError(
            _("%s minimum cannot be greater than its maximum.") % label
        )


class HrJob(models.Model):
    _inherit = "hr.job"

    application_question_ids = fields.One2many(
        "pr.recruitment.question",
        "job_id",
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
        "pr_job_core_nationality_rel",
        "job_id",
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
        "pr_job_core_education_degree_rel",
        "job_id",
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

    @api.constrains(
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
    )
    def _check_core_screening_configuration(self):
        for job in self:
            if job.core_location_rule != "none" and not job._core_location_terms():
                raise ValidationError(
                    _("Enter at least one allowed location or matching term.")
                )
            if (
                job.core_nationality_rule in ("allowed", "excluded")
                and not job.core_nationality_ids
            ):
                raise ValidationError(
                    _("Select at least one nationality for the selected rule.")
                )
            if (
                job.core_education_rule == "allowed"
                and not job.core_education_degree_ids
            ):
                raise ValidationError(
                    _("Select at least one allowed education degree.")
                )
            if (
                job.core_education_rule == "minimum"
                and not job.core_minimum_education_id
            ):
                raise ValidationError(_("Select the minimum education degree."))
            validate_numeric_screening_configuration(
                job.core_experience_rule,
                job.core_experience_minimum,
                job.core_experience_maximum,
                _("Experience"),
            )
            validate_numeric_screening_configuration(
                job.core_notice_period_rule,
                job.core_notice_period_minimum,
                job.core_notice_period_maximum,
                _("Notice period"),
            )
            validate_numeric_screening_configuration(
                job.core_salary_rule,
                job.core_salary_minimum,
                job.core_salary_maximum,
                _("Expected salary"),
            )

    def _core_location_terms(self):
        self.ensure_one()
        return [
            " ".join(line.split()).casefold()
            for line in (self.core_location_values or "").splitlines()
            if line.strip()
        ]

    def _has_core_screening_rules(self):
        self.ensure_one()
        return any(
            rule != "none"
            for rule in (
                self.core_location_rule,
                self.core_nationality_rule,
                self.core_education_rule,
                self.core_experience_rule,
                self.core_notice_period_rule,
                self.core_salary_rule,
                self.core_iqama_rule,
            )
        )

    def prepare_dynamic_application_answers(self, post):
        self.ensure_one()
        prepared_answers = []
        for question in self.sudo().application_question_ids.filtered("active"):
            payload, error = question.prepare_website_payload(post)
            if error:
                return [], error
            if payload:
                prepared_answers.append(payload)
        return prepared_answers, False
