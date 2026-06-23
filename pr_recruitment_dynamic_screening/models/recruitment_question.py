# -*- coding: utf-8 -*-

import math

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


ANSWER_TYPES = [
    ("char", "Short Text"),
    ("text", "Long Text"),
    ("integer", "Whole Number"),
    ("decimal", "Decimal Number"),
    ("selection", "Selection"),
    ("many2one", "Related Record"),
    ("one2many", "Repeating Lines"),
    ("boolean", "Yes / No"),
    ("date", "Date"),
]

CRITERION_TYPES = [
    ("none", "No Automatic Screening"),
    ("number_min", "Number: Minimum"),
    ("number_max", "Number: Maximum"),
    ("number_range", "Number: Allowed Range"),
    ("number_equal", "Number: Must Equal"),
    ("text_equal", "Text: Must Equal"),
    ("option_allowed", "Selection / Record: Allowed Values"),
    ("option_min_sequence", "Selection / Record: Minimum Level"),
    ("line_count_min", "Repeating Lines: Minimum Entries"),
    ("line_count_max", "Repeating Lines: Maximum Entries"),
    ("line_count_range", "Repeating Lines: Allowed Range"),
    ("boolean_equal", "Yes / No: Required Answer"),
    ("date_min", "Date: On or After"),
    ("date_max", "Date: On or Before"),
    ("date_range", "Date: Allowed Range"),
]

RELATION_MODELS = [
    ("res.country", "Nationality / Country"),
    ("hr.recruitment.degree", "Education Degree"),
    ("hr.skill", "Skill / Language Skill"),
    ("res.lang", "Language"),
]

LINE_COLUMN_TYPES = [
    ("char", "Short Text"),
    ("text", "Long Text"),
    ("integer", "Whole Number"),
    ("decimal", "Decimal Number"),
    ("selection", "Selection"),
    ("many2one", "Related Record"),
    ("date", "Date"),
]


class RecruitmentQuestionOption(models.Model):
    _name = "pr.recruitment.question.option"
    _description = "Recruitment Question Option"
    _order = "sequence, id"

    question_id = fields.Many2one(
        "pr.recruitment.question", required=True, ondelete="cascade", index=True
    )
    name = fields.Char(string="Option", required=True, translate=True)
    sequence = fields.Integer(
        default=10,
        help="For minimum-level screening, larger sequence values are higher levels.",
    )
    active = fields.Boolean(default=True)
    screening_allowed = fields.Boolean(
        string="Allowed",
        help="Accept this value when the screening rule uses allowed values.",
    )
    screening_minimum = fields.Boolean(
        string="Minimum Level",
        help="Use this value as the minimum accepted ranked level.",
    )
    relation_model = fields.Selection(
        RELATION_MODELS,
        related="question_id.relation_model",
        store=True,
        readonly=True,
    )
    country_id = fields.Many2one("res.country", string="Country / Nationality")
    degree_id = fields.Many2one("hr.recruitment.degree", string="Education Degree")
    skill_id = fields.Many2one("hr.skill", string="Skill")
    language_id = fields.Many2one("res.lang", string="Language")
    source_request_option_id = fields.Many2one(
        "pr.recruitment.question.option",
        string="Source Request Option",
        readonly=True,
        copy=False,
        index=True,
        ondelete="set null",
    )

    _sql_constraints = [
        (
            "question_option_name_unique",
            "unique(question_id, name)",
            "An option may only appear once on the same question.",
        )
    ]

    @api.model_create_multi
    def create(self, vals_list):
        options = super().create(vals_list)
        minimum_options = options.filtered("screening_minimum")
        for option in minimum_options:
            option.question_id.option_ids.filtered(
                lambda sibling: sibling != option and sibling.screening_minimum
            ).with_context(skip_child_request_question_sync=True).write(
                {"screening_minimum": False}
            )
        if not self.env.context.get("skip_child_request_question_sync"):
            options.mapped("question_id")._sync_approved_request_questions()
        return options

    def write(self, values):
        if values.get("screening_minimum"):
            for option in self:
                option.question_id.option_ids.filtered(
                    lambda sibling: sibling != option and sibling.screening_minimum
                ).with_context(skip_child_request_question_sync=True).write(
                    {"screening_minimum": False}
                )
        result = super().write(values)
        if not self.env.context.get("skip_child_request_question_sync"):
            questions = self.mapped("question_id")
            questions._check_screening_configuration()
            questions._sync_approved_request_questions()
        return result

    def unlink(self):
        questions = self.mapped("question_id")
        result = super().unlink()
        if not self.env.context.get("skip_child_request_question_sync"):
            questions = questions.exists()
            questions._check_screening_configuration()
            questions._sync_approved_request_questions()
        return result

    @api.onchange("country_id", "degree_id", "skill_id", "language_id")
    def _onchange_related_record(self):
        for option in self:
            record = option._get_related_record()
            if record:
                option.name = record.display_name

    def _get_related_record(self):
        self.ensure_one()
        relation_model = self.question_id.relation_model
        return {
            "res.country": self.country_id,
            "hr.recruitment.degree": self.degree_id,
            "hr.skill": self.skill_id,
            "res.lang": self.language_id,
        }.get(relation_model, self.env["res.country"])

    @api.constrains(
        "question_id",
        "country_id",
        "degree_id",
        "skill_id",
        "language_id",
        "screening_allowed",
        "screening_minimum",
    )
    def _check_related_record(self):
        for option in self:
            question = option.question_id
            if len(question.option_ids.filtered("screening_minimum")) > 1:
                raise ValidationError(_("Only one available value can be the Minimum Level."))
            if not option.active and (
                option.screening_allowed or option.screening_minimum
            ):
                raise ValidationError(
                    _("An archived value cannot be used by an active screening rule.")
                )
            if option.question_id.answer_type != "many2one":
                continue
            record = option._get_related_record()
            if not record:
                raise ValidationError(_("Select a related Odoo record for every value."))
            selected_count = sum(
                bool(record)
                for record in (
                    option.country_id,
                    option.degree_id,
                    option.skill_id,
                    option.language_id,
                )
            )
            if selected_count != 1:
                raise ValidationError(_("Each related value must point to exactly one record."))


class RecruitmentQuestionColumnOption(models.Model):
    _name = "pr.recruitment.question.column.option"
    _description = "Recruitment Repeating Column Option"
    _order = "sequence, id"

    column_id = fields.Many2one(
        "pr.recruitment.question.column", required=True, ondelete="cascade", index=True
    )
    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    relation_model = fields.Selection(
        RELATION_MODELS,
        related="column_id.relation_model",
        store=True,
        readonly=True,
    )
    country_id = fields.Many2one("res.country", string="Country / Nationality")
    degree_id = fields.Many2one("hr.recruitment.degree", string="Education Degree")
    skill_id = fields.Many2one("hr.skill", string="Skill")
    language_id = fields.Many2one("res.lang", string="Language")
    source_request_option_id = fields.Many2one(
        "pr.recruitment.question.column.option",
        string="Source Request Column Option",
        readonly=True,
        copy=False,
        index=True,
        ondelete="set null",
    )

    _sql_constraints = [
        (
            "column_option_name_unique",
            "unique(column_id, name)",
            "An option may only appear once in the same column.",
        )
    ]

    @api.model_create_multi
    def create(self, vals_list):
        options = super().create(vals_list)
        if not self.env.context.get("skip_child_request_question_sync"):
            options.mapped("column_id.question_id")._sync_approved_request_questions()
        return options

    def write(self, values):
        result = super().write(values)
        if not self.env.context.get("skip_child_request_question_sync"):
            columns = self.mapped("column_id")
            columns._check_column_options()
            columns.mapped("question_id")._sync_approved_request_questions()
        return result

    def unlink(self):
        columns = self.mapped("column_id")
        result = super().unlink()
        if not self.env.context.get("skip_child_request_question_sync"):
            columns = columns.exists()
            columns._check_column_options()
            columns.mapped("question_id")._sync_approved_request_questions()
        return result

    @api.onchange("country_id", "degree_id", "skill_id", "language_id")
    def _onchange_related_record(self):
        for option in self:
            record = option._get_related_record()
            if record:
                option.name = record.display_name

    def _get_related_record(self):
        self.ensure_one()
        relation_model = self.column_id.relation_model
        return {
            "res.country": self.country_id,
            "hr.recruitment.degree": self.degree_id,
            "hr.skill": self.skill_id,
            "res.lang": self.language_id,
        }.get(relation_model, self.env["res.country"])

    @api.constrains(
        "column_id",
        "country_id",
        "degree_id",
        "skill_id",
        "language_id",
    )
    def _check_related_record(self):
        for option in self:
            if not option.active:
                continue
            if option.column_id.column_type != "many2one":
                continue
            selected_count = sum(
                bool(value)
                for value in (
                    option.country_id,
                    option.degree_id,
                    option.skill_id,
                    option.language_id,
                )
            )
            if not option._get_related_record() or selected_count != 1:
                raise ValidationError(_("Select exactly one related Odoo record."))


class RecruitmentQuestionColumn(models.Model):
    _name = "pr.recruitment.question.column"
    _description = "Recruitment Repeating Question Column"
    _order = "sequence, id"

    question_id = fields.Many2one(
        "pr.recruitment.question", required=True, ondelete="cascade", index=True
    )
    name = fields.Char(string="Column Label", required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    column_type = fields.Selection(LINE_COLUMN_TYPES, required=True, default="char")
    relation_model = fields.Selection(RELATION_MODELS, string="Related Odoo Data")
    required = fields.Boolean(default=False)
    help_text = fields.Char(translate=True)
    option_ids = fields.One2many(
        "pr.recruitment.question.column.option", "column_id", copy=True
    )
    source_request_column_id = fields.Many2one(
        "pr.recruitment.question.column",
        string="Source Request Column",
        readonly=True,
        copy=False,
        index=True,
        ondelete="set null",
    )

    @api.model_create_multi
    def create(self, vals_list):
        columns = super().create(vals_list)
        if not self.env.context.get("skip_child_request_question_sync"):
            columns.mapped("question_id")._sync_approved_request_questions()
        return columns

    def write(self, values):
        protected_fields = {"column_type", "relation_model"} & set(values)
        if protected_fields:
            Cell = self.env["pr.recruitment.answer.cell"].sudo()
            for column in self:
                changed = any(
                    values.get(field_name) != column[field_name]
                    for field_name in protected_fields
                )
                if changed and Cell.search_count([("column_id", "=", column.id)]):
                    raise ValidationError(
                        _(
                            "The type of a repeating column cannot be changed after "
                            "applicant answers exist. Archive it and add a new column instead."
                        )
                    )
        result = super().write(values)
        if not self.env.context.get("skip_child_request_question_sync"):
            questions = self.mapped("question_id")
            questions._check_screening_configuration()
            questions._sync_approved_request_questions()
        return result

    def unlink(self):
        questions = self.mapped("question_id")
        result = super().unlink()
        if not self.env.context.get("skip_child_request_question_sync"):
            questions = questions.exists()
            questions._check_screening_configuration()
            questions._sync_approved_request_questions()
        return result

    @api.constrains("column_type", "relation_model", "option_ids")
    def _check_column_options(self):
        for column in self:
            if not column.active:
                continue
            active_options = column.option_ids.filtered("active")
            if column.column_type in ("selection", "many2one") and not active_options:
                raise ValidationError(_("A selection or related-record column needs at least one value."))
            if column.column_type == "many2one" and not column.relation_model:
                raise ValidationError(_("Select the related Odoo data source for the column."))
            if column.column_type == "many2one":
                for option in active_options:
                    selected_count = sum(
                        bool(value)
                        for value in (
                            option.country_id,
                            option.degree_id,
                            option.skill_id,
                            option.language_id,
                        )
                    )
                    if not option._get_related_record() or selected_count != 1:
                        raise ValidationError(
                            _("Every column value must match its selected Odoo data source.")
                        )

    def action_load_relation_values(self):
        self.check_access_rights("write")
        self.check_access_rule("write")
        field_by_model = {
            "res.country": "country_id",
            "hr.recruitment.degree": "degree_id",
            "hr.skill": "skill_id",
            "res.lang": "language_id",
        }
        for column in self:
            if column.column_type != "many2one" or not column.relation_model:
                raise ValidationError(_("Choose Related Record and its Odoo data source first."))
            relation_model = self.env[column.relation_model].sudo()
            domain = [("active", "=", True)] if "active" in relation_model._fields else []
            records = relation_model.search(domain, order="name, id", limit=2000)
            relation_field = field_by_model[column.relation_model]
            existing_ids = set(column.option_ids.mapped(relation_field).ids)
            next_sequence = max(column.option_ids.mapped("sequence") or [0]) + 10
            commands = []
            for record in records:
                if record.id in existing_ids:
                    continue
                commands.append(
                    (
                        0,
                        0,
                        {
                            "name": record.display_name,
                            "sequence": next_sequence,
                            relation_field: record.id,
                        },
                    )
                )
                next_sequence += 10
            if commands:
                column.write({"option_ids": commands})
        return True

    def _prepare_cell(self, raw_value):
        self.ensure_one()
        raw_value = (raw_value or "").strip()
        if not raw_value:
            if self.required:
                return {}, _("Please complete the %s column.") % self.name
            return {}, False
        values = {"raw_value": raw_value}
        try:
            if self.column_type in ("char", "text"):
                if len(raw_value) > 5000:
                    raise ValueError
                values["value_text"] = raw_value
            elif self.column_type == "integer":
                integer_value = int(raw_value)
                if not -(2**31) <= integer_value < 2**31:
                    raise ValueError
                values["value_integer"] = integer_value
            elif self.column_type == "decimal":
                float_value = float(raw_value)
                if not math.isfinite(float_value):
                    raise ValueError
                values["value_float"] = float_value
            elif self.column_type in ("selection", "many2one"):
                option_id = int(raw_value)
                option = self.option_ids.filtered(
                    lambda candidate: candidate.id == option_id and candidate.active
                )
                if not option:
                    raise ValueError
                values["column_option_id"] = option.id
            elif self.column_type == "date":
                values["value_date"] = fields.Date.to_date(raw_value)
        except (TypeError, ValueError, OverflowError):
            return {}, _("Please provide a valid value for %s.") % self.name
        return values, False


class RecruitmentQuestion(models.Model):
    _name = "pr.recruitment.question"
    _description = "Dynamic Recruitment Question"
    _order = "sequence, id"

    name = fields.Char(string="Question", required=True, translate=True)
    help_text = fields.Char(string="Help Text", translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    required = fields.Boolean(default=False)
    answer_type = fields.Selection(ANSWER_TYPES, required=True, default="char")
    relation_model = fields.Selection(
        RELATION_MODELS,
        string="Related Odoo Data",
        help="Only these approved public-safe models can be used on the website.",
    )
    line_column_ids = fields.One2many(
        "pr.recruitment.question.column",
        "question_id",
        string="Repeating Line Columns",
        copy=True,
    )
    job_id = fields.Many2one("hr.job", ondelete="cascade", index=True)
    request_id = fields.Many2one("hr.recruitment.request", ondelete="cascade", index=True)
    source_request_question_id = fields.Many2one(
        "pr.recruitment.question", readonly=True, ondelete="set null", copy=False
    )

    option_ids = fields.One2many(
        "pr.recruitment.question.option", "question_id", string="Selection Options", copy=True
    )
    criterion_type = fields.Selection(CRITERION_TYPES, required=True, default="none")
    criterion_number = fields.Float(string="Required Number")
    criterion_number_max = fields.Float(string="Maximum Required Number")
    criterion_text = fields.Char(string="Required Text")
    criterion_boolean = fields.Boolean(string="Required Answer")
    criterion_date = fields.Date(string="Required Date")
    criterion_date_max = fields.Date(string="Maximum Required Date")
    allowed_option_ids = fields.Many2many(
        "pr.recruitment.question.option",
        "pr_recruitment_question_allowed_option_rel",
        "question_id",
        "option_id",
        string="Allowed Options",
        domain="[('question_id', '=', id)]",
    )
    minimum_option_id = fields.Many2one(
        "pr.recruitment.question.option",
        string="Minimum Accepted Level",
        domain="[('question_id', '=', id)]",
        ondelete="set null",
    )
    hide_criterion_on_website = fields.Boolean(
        string="Hide Requirement from Applicant",
        default=True,
        help="Keep the automatic screening requirement internal instead of showing it below the question.",
    )
    website_criterion_hint = fields.Char(
        string="Applicant Requirement",
        compute="_compute_website_criterion_hint",
    )

    _sql_constraints = [
        (
            "one_question_owner",
            "CHECK((job_id IS NOT NULL AND request_id IS NULL) OR "
            "(job_id IS NULL AND request_id IS NOT NULL))",
            "A question must belong to either one job or one recruitment request.",
        )
    ]

    @api.model_create_multi
    def create(self, vals_list):
        questions = super(
            RecruitmentQuestion,
            self.with_context(skip_child_request_question_sync=True),
        ).create(vals_list)
        questions = questions.with_env(self.env)
        questions._sync_approved_request_questions()
        return questions

    def write(self, values):
        protected_fields = {"answer_type", "relation_model"} & set(values)
        if protected_fields:
            Answer = self.env["pr.recruitment.answer"].sudo()
            for question in self:
                changed = any(
                    values.get(field_name) != question[field_name]
                    for field_name in protected_fields
                )
                if changed and Answer.search_count([("question_id", "=", question.id)]):
                    raise ValidationError(
                        _(
                            "The answer type cannot be changed after applicant answers "
                            "exist. Archive this question and create a new one instead."
                        )
                    )
        result = super(
            RecruitmentQuestion,
            self.with_context(skip_child_request_question_sync=True),
        ).write(values)
        self._sync_approved_request_questions()
        return result

    def unlink(self):
        copied_questions = self.env["pr.recruitment.question"].sudo().search(
            [("source_request_question_id", "in", self.ids)]
        )
        if copied_questions:
            copied_questions.write({"active": False})
        return super().unlink()

    def _sync_approved_request_questions(self):
        if self.env.context.get("skip_request_question_sync"):
            return
        for question in self.filtered("request_id"):
            request_record = question.request_id
            if request_record.state not in ("approved", "done"):
                continue
            job = request_record.job_id or request_record.created_job_id
            if job:
                question.sudo().with_context(
                    skip_request_question_sync=True
                ).copy_to_job(job.sudo())

    @api.onchange("criterion_type")
    def _onchange_criterion_type(self):
        if self.criterion_type not in ("none", "line_count_max"):
            self.required = True

    @api.onchange("answer_type")
    def _onchange_answer_type(self):
        compatible = {
            "char": {"none", "text_equal"},
            "text": {"none", "text_equal"},
            "integer": {"none", "number_min", "number_max", "number_range", "number_equal"},
            "decimal": {"none", "number_min", "number_max", "number_range", "number_equal"},
            "selection": {"none", "option_allowed", "option_min_sequence"},
            "many2one": {"none", "option_allowed", "option_min_sequence"},
            "one2many": {"none", "line_count_min", "line_count_max", "line_count_range"},
            "boolean": {"none", "boolean_equal"},
            "date": {"none", "date_min", "date_max", "date_range"},
        }
        if self.criterion_type not in compatible.get(self.answer_type, {"none"}):
            self.criterion_type = "none"

    def action_load_relation_values(self):
        """Load missing records from the approved relation model as selectable values."""
        self.check_access_rights("write")
        self.check_access_rule("write")
        field_by_model = {
            "res.country": "country_id",
            "hr.recruitment.degree": "degree_id",
            "hr.skill": "skill_id",
            "res.lang": "language_id",
        }
        for question in self:
            if question.answer_type != "many2one" or not question.relation_model:
                raise ValidationError(_("Choose Related Record and its Odoo data source first."))
            relation_model = self.env[question.relation_model].sudo()
            domain = [("active", "=", True)] if "active" in relation_model._fields else []
            records = relation_model.search(domain, order="name, id", limit=2000)
            relation_field = field_by_model[question.relation_model]
            existing_ids = set(question.option_ids.mapped(relation_field).ids)
            next_sequence = max(question.option_ids.mapped("sequence") or [0]) + 10
            commands = []
            for record in records:
                if record.id in existing_ids:
                    continue
                commands.append(
                    (
                        0,
                        0,
                        {
                            "name": record.display_name,
                            "sequence": next_sequence,
                            relation_field: record.id,
                        },
                    )
                )
                next_sequence += 10
            if commands:
                question.write({"option_ids": commands})
        return True

    @api.depends(
        "criterion_type",
        "criterion_number",
        "criterion_number_max",
        "criterion_text",
        "criterion_boolean",
        "criterion_date",
        "criterion_date_max",
        "allowed_option_ids.name",
        "minimum_option_id.name",
        "option_ids.name",
        "option_ids.screening_allowed",
        "option_ids.screening_minimum",
        "hide_criterion_on_website",
    )
    def _compute_website_criterion_hint(self):
        for question in self:
            criterion = question.criterion_type
            hint = False
            number = "%g" % question.criterion_number
            if criterion == "number_min":
                hint = _("Minimum accepted: %s") % number
            elif criterion == "number_max":
                hint = _("Maximum accepted: %s") % number
            elif criterion == "number_range":
                hint = _("Accepted range: %s to %s") % (
                    number,
                    "%g" % question.criterion_number_max,
                )
            elif criterion == "number_equal":
                hint = _("Required value: %s") % number
            elif criterion == "text_equal":
                hint = _("Required answer: %s") % (question.criterion_text or "")
            elif criterion == "option_allowed":
                hint = _("Accepted answers: %s") % ", ".join(
                    question._get_allowed_screening_options().mapped("name")
                )
            elif criterion == "option_min_sequence":
                hint = _("Minimum accepted level: %s") % (
                    question._get_minimum_screening_option().name or ""
                )
            elif criterion == "line_count_min":
                hint = _("Provide at least %s entries") % number
            elif criterion == "line_count_max":
                hint = _("Provide no more than %s entries") % number
            elif criterion == "line_count_range":
                hint = _("Provide between %s and %s entries") % (
                    number,
                    "%g" % question.criterion_number_max,
                )
            elif criterion == "boolean_equal":
                hint = _("Required answer: %s") % (
                    _("Yes") if question.criterion_boolean else _("No")
                )
            elif criterion == "date_min":
                hint = _("Date must be on or after: %s") % (
                    fields.Date.to_string(question.criterion_date) or ""
                )
            elif criterion == "date_max":
                hint = _("Date must be on or before: %s") % (
                    fields.Date.to_string(question.criterion_date) or ""
                )
            elif criterion == "date_range":
                hint = _("Date must be between: %s and %s") % (
                    fields.Date.to_string(question.criterion_date) or "",
                    fields.Date.to_string(question.criterion_date_max) or "",
                )
            question.website_criterion_hint = (
                False if question.hide_criterion_on_website else hint
            )

    @api.constrains(
        "answer_type",
        "relation_model",
        "line_column_ids",
        "criterion_type",
        "required",
        "option_ids",
        "criterion_number",
        "criterion_number_max",
        "criterion_text",
        "criterion_boolean",
        "criterion_date",
        "criterion_date_max",
        "allowed_option_ids",
        "minimum_option_id",
    )
    def _check_screening_configuration(self):
        compatible = {
            "char": {"none", "text_equal"},
            "text": {"none", "text_equal"},
            "integer": {"none", "number_min", "number_max", "number_range", "number_equal"},
            "decimal": {"none", "number_min", "number_max", "number_range", "number_equal"},
            "selection": {"none", "option_allowed", "option_min_sequence"},
            "many2one": {"none", "option_allowed", "option_min_sequence"},
            "one2many": {"none", "line_count_min", "line_count_max", "line_count_range"},
            "boolean": {"none", "boolean_equal"},
            "date": {"none", "date_min", "date_max", "date_range"},
        }
        for question in self:
            if not question.active:
                continue
            if question.criterion_type not in compatible[question.answer_type]:
                raise ValidationError(_("The screening rule is not compatible with the answer type."))
            if (
                question.criterion_type not in ("none", "line_count_max")
                and not question.required
            ):
                raise ValidationError(_("A screening question must be required."))
            active_options = question.option_ids.filtered("active")
            active_columns = question.line_column_ids.filtered("active")
            if question.criterion_type in (
                "number_min",
                "number_max",
                "number_range",
                "number_equal",
                "line_count_min",
                "line_count_max",
                "line_count_range",
            ) and not math.isfinite(question.criterion_number):
                raise ValidationError(_("The screening threshold must be a finite number."))
            if question.criterion_type in (
                "number_range",
                "line_count_range",
            ) and not math.isfinite(question.criterion_number_max):
                raise ValidationError(_("The maximum screening threshold must be a finite number."))
            if question.answer_type in ("selection", "many2one") and not active_options:
                raise ValidationError(_("A selection or related-record question needs at least one value."))
            if question.answer_type == "many2one" and not question.relation_model:
                raise ValidationError(_("Select the related Odoo data source."))
            if question.answer_type == "one2many" and not active_columns:
                raise ValidationError(_("A repeating-lines question needs at least one column."))
            if (
                question.criterion_type in ("line_count_min", "line_count_max", "line_count_range")
                and question.criterion_number < 0
            ):
                raise ValidationError(_("The line-count threshold cannot be negative."))
            if (
                question.criterion_type == "line_count_range"
                and question.criterion_number_max < 0
            ):
                raise ValidationError(_("The line-count maximum cannot be negative."))
            if (
                question.criterion_type in ("line_count_min", "line_count_max", "line_count_range")
                and question.criterion_number != int(question.criterion_number)
            ):
                raise ValidationError(_("The line-count threshold must be a whole number."))
            if (
                question.criterion_type == "line_count_range"
                and question.criterion_number_max != int(question.criterion_number_max)
            ):
                raise ValidationError(_("The line-count maximum must be a whole number."))
            if (
                question.criterion_type in ("number_range", "line_count_range")
                and question.criterion_number > question.criterion_number_max
            ):
                raise ValidationError(_("The screening minimum cannot be greater than its maximum."))
            if question.answer_type == "many2one":
                for option in active_options:
                    record = option._get_related_record()
                    selected_count = sum(
                        bool(value)
                        for value in (
                            option.country_id,
                            option.degree_id,
                            option.skill_id,
                            option.language_id,
                        )
                    )
                    if not record or selected_count != 1:
                        raise ValidationError(
                            _("Every related value must match the selected Odoo data source.")
                        )
            if (
                question.criterion_type == "option_allowed"
                and not question._get_allowed_screening_options()
            ):
                raise ValidationError(_("Mark at least one available value as Allowed."))
            if (
                question.criterion_type == "option_min_sequence"
                and not question._get_minimum_screening_option()
            ):
                raise ValidationError(_("Mark one available value as the Minimum Level."))
            if len(question.option_ids.filtered("screening_minimum")) > 1:
                raise ValidationError(_("Only one available value can be the Minimum Level."))
            if question.criterion_type == "text_equal" and not question.criterion_text:
                raise ValidationError(_("Enter the required text answer."))
            if (
                question.criterion_type in ("date_min", "date_max", "date_range")
                and not question.criterion_date
            ):
                raise ValidationError(_("Enter the date used by the screening rule."))
            if question.criterion_type == "date_range" and not question.criterion_date_max:
                raise ValidationError(_("Enter the maximum date used by the screening rule."))
            if (
                question.criterion_type == "date_range"
                and question.criterion_date
                and question.criterion_date_max
                and question.criterion_date > question.criterion_date_max
            ):
                raise ValidationError(_("The screening start date cannot be after its end date."))
            foreign_options = question.allowed_option_ids.filtered(
                lambda option: option.question_id != question
            )
            if foreign_options or (
                question.minimum_option_id
                and question.minimum_option_id.question_id != question
            ):
                raise ValidationError(_("Screening options must belong to this question."))

    def _get_allowed_screening_options(self):
        self.ensure_one()
        marked = self.option_ids.filtered(
            lambda option: option.active and option.screening_allowed
        )
        return marked or self.allowed_option_ids.filtered("active")

    def _get_minimum_screening_option(self):
        self.ensure_one()
        marked = self.option_ids.filtered(
            lambda option: option.active and option.screening_minimum
        )[:1]
        return marked or self.minimum_option_id.filtered("active")

    def _prepare_answer(self, raw_value):
        """Return typed answer values and an error message, if any."""
        self.ensure_one()
        raw_value = (raw_value or "").strip()
        if not raw_value:
            if self.required:
                return {}, _("Please answer: %s") % self.name
            return {}, False

        values = {"raw_value": raw_value}
        try:
            if self.answer_type in ("char", "text"):
                if len(raw_value) > 5000:
                    raise ValueError
                values["value_text"] = raw_value
            elif self.answer_type == "integer":
                integer_value = int(raw_value)
                if not -(2**31) <= integer_value < 2**31:
                    raise ValueError
                values["value_integer"] = integer_value
            elif self.answer_type == "decimal":
                float_value = float(raw_value)
                if not math.isfinite(float_value):
                    raise ValueError
                values["value_float"] = float_value
            elif self.answer_type in ("selection", "many2one"):
                option_id = int(raw_value)
                option = self.option_ids.filtered(
                    lambda candidate: candidate.id == option_id and candidate.active
                )
                if not option:
                    raise ValueError
                values["option_id"] = option.id
            elif self.answer_type == "boolean":
                if raw_value not in ("yes", "no"):
                    raise ValueError
                values["value_boolean"] = raw_value == "yes"
            elif self.answer_type == "date":
                values["value_date"] = fields.Date.to_date(raw_value)
        except (TypeError, ValueError, OverflowError):
            return {}, _("Please provide a valid answer for: %s") % self.name
        return values, False

    def prepare_website_payload(self, post):
        """Validate one website answer and return context-safe source values."""
        self.ensure_one()
        if self.answer_type != "one2many":
            raw_value = post.get("pr_question_%s" % self.id, "")
            values, error = self._prepare_answer(raw_value)
            if error:
                return False, error
            if not values:
                return False, False
            return {"question_id": self.id, "raw_value": raw_value}, False

        token_value = post.get("pr_question_%s_rows" % self.id, "")
        if len(token_value) > 200:
            return False, _("A repeating question contains an invalid row list.")
        tokens = []
        for token in token_value.split(","):
            token = token.strip()
            if token.isdigit() and len(token) <= 6 and token not in tokens:
                tokens.append(token)
        if len(tokens) > 20:
            return False, _("A repeating question cannot contain more than 20 entries.")

        lines = []
        for token in tokens:
            raw_cells = {
                column.id: post.get(
                    "pr_question_%s_%s_column_%s" % (self.id, token, column.id),
                    "",
                )
                for column in self.line_column_ids.filtered("active")
            }
            if not any((value or "").strip() for value in raw_cells.values()):
                continue
            cells = []
            for column in self.line_column_ids.filtered("active"):
                raw_value = raw_cells[column.id]
                values, error = column._prepare_cell(raw_value)
                if error:
                    return False, _("%s: %s") % (self.name, error)
                if values:
                    cells.append(
                        {"column_id": column.id, "raw_value": raw_value}
                    )
            lines.append({"cells": cells})

        if self.required and not lines:
            return False, _("Please add at least one entry for: %s") % self.name
        return {
            "question_id": self.id,
            "answer_type": "one2many",
            "lines": lines,
        }, False

    def _screening_failure(self, answer):
        self.ensure_one()
        criterion = self.criterion_type
        if criterion == "none":
            return False

        failed = False
        expected = False
        actual = answer.display_value
        if criterion in ("number_min", "number_max", "number_range", "number_equal"):
            number = (
                answer.value_integer
                if self.answer_type == "integer"
                else answer.value_float
            )
            if criterion == "number_range":
                minimum = self.criterion_number
                maximum = self.criterion_number_max
                expected = _("between %s and %s") % ("%g" % minimum, "%g" % maximum)
                failed = (
                    float_compare(number, minimum, precision_digits=9) < 0
                    or float_compare(number, maximum, precision_digits=9) > 0
                )
            else:
                expected = self.criterion_number
                comparison = float_compare(number, expected, precision_digits=9)
                failed = {
                    "number_min": comparison < 0,
                    "number_max": comparison > 0,
                    "number_equal": comparison != 0,
                }[criterion]
        elif criterion == "text_equal":
            expected = self.criterion_text or ""
            failed = (answer.value_text or "").strip().casefold() != expected.strip().casefold()
        elif criterion == "option_allowed":
            allowed_options = self._get_allowed_screening_options()
            expected = ", ".join(allowed_options.mapped("name"))
            failed = answer.option_id not in allowed_options
        elif criterion == "option_min_sequence":
            minimum_option = self._get_minimum_screening_option()
            expected = minimum_option.name
            failed = (
                not answer.option_id.active
                or answer.option_id.sequence < minimum_option.sequence
            )
        elif criterion in ("line_count_min", "line_count_max", "line_count_range"):
            line_count = len(answer.line_ids)
            actual = line_count
            if criterion == "line_count_range":
                minimum = int(self.criterion_number)
                maximum = int(self.criterion_number_max)
                expected = _("between %s and %s entries") % (minimum, maximum)
                failed = line_count < minimum or line_count > maximum
            else:
                expected = int(self.criterion_number)
                failed = (
                    line_count < expected
                    if criterion == "line_count_min"
                    else line_count > expected
                )
        elif criterion == "boolean_equal":
            expected = _("Yes") if self.criterion_boolean else _("No")
            failed = answer.value_boolean != self.criterion_boolean
        elif criterion in ("date_min", "date_max", "date_range"):
            if criterion == "date_range":
                expected = _("between %s and %s") % (
                    fields.Date.to_string(self.criterion_date),
                    fields.Date.to_string(self.criterion_date_max),
                )
                failed = (
                    answer.value_date < self.criterion_date
                    or answer.value_date > self.criterion_date_max
                )
            else:
                expected = fields.Date.to_string(self.criterion_date)
                failed = (
                    answer.value_date < self.criterion_date
                    if criterion == "date_min"
                    else answer.value_date > self.criterion_date
                )

        if not failed:
            return False
        return _("%s - received %s; required %s") % (self.name, actual, expected)

    def copy_to_job(self, job):
        """Synchronize request questions without invalidating historical answers."""
        job.ensure_one()
        Question = self.env["pr.recruitment.question"]

        def option_values(source_option):
            return {
                "name": source_option.name,
                "sequence": source_option.sequence,
                "active": source_option.active,
                "screening_allowed": source_option.screening_allowed,
                "screening_minimum": source_option.screening_minimum,
                "country_id": source_option.country_id.id,
                "degree_id": source_option.degree_id.id,
                "skill_id": source_option.skill_id.id,
                "language_id": source_option.language_id.id,
                "source_request_option_id": source_option.id,
            }

        def column_option_values(source_option):
            return {
                "name": source_option.name,
                "sequence": source_option.sequence,
                "active": source_option.active,
                "country_id": source_option.country_id.id,
                "degree_id": source_option.degree_id.id,
                "skill_id": source_option.skill_id.id,
                "language_id": source_option.language_id.id,
                "source_request_option_id": source_option.id,
            }

        def option_commands(source_options, value_getter):
            return [(0, 0, value_getter(option)) for option in source_options]

        def column_values(source_column, include_options=False):
            values = {
                "name": source_column.name,
                "sequence": source_column.sequence,
                "active": source_column.active,
                "column_type": source_column.column_type,
                "relation_model": source_column.relation_model,
                "required": source_column.required,
                "help_text": source_column.help_text,
                "source_request_column_id": source_column.id,
            }
            if include_options:
                values["option_ids"] = option_commands(
                    source_column.option_ids
                    if source_column.column_type in ("selection", "many2one")
                    else self.env["pr.recruitment.question.column.option"],
                    column_option_values,
                )
            return values

        def sync_options(target_question, source_options):
            target_options = target_question.option_ids
            target_options.with_context(
                skip_child_request_question_sync=True
            ).write({"screening_allowed": False, "screening_minimum": False})
            by_source = {
                option.source_request_option_id.id: option
                for option in target_options
                if option.source_request_option_id
            }
            by_name = {option.name: option for option in target_options}
            matched = self.env["pr.recruitment.question.option"]
            result = {}
            for source_option in source_options:
                target_option = by_source.get(source_option.id) or by_name.get(
                    source_option.name
                )
                values = option_values(source_option)
                if target_option:
                    conflicts = (target_options - target_option).filtered(
                        lambda option: option.name == source_option.name
                    )
                    for conflict in conflicts:
                        conflict.with_context(
                            skip_child_request_question_sync=True
                        ).write(
                            {
                                "name": "%s (Archived %s)"
                                % (conflict.name, conflict.id),
                                "active": False,
                                "screening_allowed": False,
                                "screening_minimum": False,
                                "source_request_option_id": False,
                            }
                        )
                    target_option.with_context(
                        skip_child_request_question_sync=True
                    ).write(values)
                else:
                    values["question_id"] = target_question.id
                    target_option = self.env[
                        "pr.recruitment.question.option"
                    ].with_context(skip_child_request_question_sync=True).create(values)
                matched |= target_option
                result[source_option.id] = target_option.id
            (target_options - matched).with_context(
                skip_child_request_question_sync=True
            ).write(
                {
                    "active": False,
                    "screening_allowed": False,
                    "screening_minimum": False,
                    "source_request_option_id": False,
                }
            )
            return result

        def sync_column_options(target_column, source_options):
            target_options = target_column.option_ids
            by_source = {
                option.source_request_option_id.id: option
                for option in target_options
                if option.source_request_option_id
            }
            by_name = {option.name: option for option in target_options}
            matched = self.env["pr.recruitment.question.column.option"]
            for source_option in source_options:
                target_option = by_source.get(source_option.id) or by_name.get(
                    source_option.name
                )
                values = column_option_values(source_option)
                if target_option:
                    conflicts = (target_options - target_option).filtered(
                        lambda option: option.name == source_option.name
                    )
                    for conflict in conflicts:
                        conflict.with_context(
                            skip_child_request_question_sync=True
                        ).write(
                            {
                                "name": "%s (Archived %s)"
                                % (conflict.name, conflict.id),
                                "active": False,
                                "source_request_option_id": False,
                            }
                        )
                    target_option.with_context(
                        skip_child_request_question_sync=True
                    ).write(values)
                else:
                    values["column_id"] = target_column.id
                    target_option = self.env[
                        "pr.recruitment.question.column.option"
                    ].with_context(skip_child_request_question_sync=True).create(values)
                matched |= target_option
            (target_options - matched).with_context(
                skip_child_request_question_sync=True
            ).write({"active": False, "source_request_option_id": False})

        def sync_columns(target_question, source_columns):
            target_columns = target_question.line_column_ids
            by_source = {
                column.source_request_column_id.id: column
                for column in target_columns
                if column.source_request_column_id
            }
            by_name = {column.name: column for column in target_columns}
            matched = self.env["pr.recruitment.question.column"]
            Cell = self.env["pr.recruitment.answer.cell"].sudo()
            for source_column in source_columns:
                target_column = by_source.get(source_column.id) or by_name.get(
                    source_column.name
                )
                incompatible = target_column and (
                    target_column.column_type != source_column.column_type
                    or target_column.relation_model != source_column.relation_model
                )
                has_cells = bool(
                    target_column
                    and Cell.search_count([("column_id", "=", target_column.id)])
                )
                if incompatible and has_cells:
                    target_column.with_context(
                        skip_child_request_question_sync=True
                    ).write(
                        {"active": False, "source_request_column_id": False}
                    )
                    target_column = False
                if target_column:
                    if incompatible:
                        target_column.option_ids.with_context(
                            skip_child_request_question_sync=True
                        ).unlink()
                    target_column.with_context(
                        skip_child_request_question_sync=True
                    ).write(column_values(source_column))
                    sync_column_options(
                        target_column,
                        source_column.option_ids
                        if source_column.column_type in ("selection", "many2one")
                        else self.env["pr.recruitment.question.column.option"],
                    )
                else:
                    values = column_values(source_column, include_options=True)
                    values["question_id"] = target_question.id
                    target_column = self.env[
                        "pr.recruitment.question.column"
                    ].with_context(skip_child_request_question_sync=True).create(values)
                matched |= target_column
            (target_columns - matched).with_context(
                skip_child_request_question_sync=True
            ).write({"active": False, "source_request_column_id": False})

        for source in self:
            existing = Question.search(
                [
                    ("job_id", "=", job.id),
                    ("source_request_question_id", "=", source.id),
                ],
                limit=1,
            )
            source_options = (
                source.option_ids
                if source.answer_type in ("selection", "many2one")
                else self.env["pr.recruitment.question.option"]
            )
            new_option_commands = option_commands(source_options, option_values)
            new_column_commands = [
                (0, 0, column_values(column, include_options=True))
                for column in source.line_column_ids
            ]
            common_values = {
                "name": source.name,
                "help_text": source.help_text,
                "sequence": source.sequence,
                "active": source.active,
                "required": source.required,
                "criterion_number": source.criterion_number,
                "criterion_number_max": source.criterion_number_max,
                "criterion_text": source.criterion_text,
                "criterion_boolean": source.criterion_boolean,
                "criterion_date": source.criterion_date,
                "criterion_date_max": source.criterion_date_max,
                "hide_criterion_on_website": source.hide_criterion_on_website,
            }
            has_answers = False
            configuration_changed = False
            if existing:
                has_answers = bool(
                    self.env["pr.recruitment.answer"].sudo().search_count(
                        [("question_id", "=", existing.id)]
                    )
                )
                relation_changed = (
                    source.answer_type == "many2one"
                    and existing.relation_model != source.relation_model
                )
                configuration_changed = (
                    existing.answer_type != source.answer_type or relation_changed
                )
                if has_answers and configuration_changed:
                    existing.with_context(skip_request_question_sync=True).write(
                        {"active": False, "source_request_question_id": False}
                    )
                    existing = Question
            if existing:
                existing.with_context(skip_request_question_sync=True).write(
                    dict(common_values, criterion_type="none")
                )
                if not has_answers and configuration_changed:
                    existing.option_ids.with_context(
                        skip_child_request_question_sync=True
                    ).unlink()
                    existing.line_column_ids.with_context(
                        skip_child_request_question_sync=True
                    ).unlink()
                    existing.with_context(skip_request_question_sync=True).write(
                        {
                            "answer_type": source.answer_type,
                            "relation_model": source.relation_model,
                            "option_ids": new_option_commands,
                            "line_column_ids": new_column_commands,
                        }
                    )
                    option_map = {
                        option.source_request_option_id.id: option.id
                        for option in existing.option_ids
                        if option.source_request_option_id
                    }
                else:
                    option_map = sync_options(existing, source_options)
                    sync_columns(existing, source.line_column_ids)
                existing.with_context(skip_request_question_sync=True).write(
                    {
                        "criterion_type": source.criterion_type,
                        "allowed_option_ids": [
                            (
                                6,
                                0,
                                [
                                    option_map[option.id]
                                    for option in source.allowed_option_ids
                                    if option.id in option_map
                                ],
                            )
                        ],
                        "minimum_option_id": option_map.get(
                            source.minimum_option_id.id
                        ),
                    }
                )
                continue
            target = Question.create(
                dict(
                    common_values,
                    answer_type=source.answer_type,
                    relation_model=source.relation_model,
                    job_id=job.id,
                    source_request_question_id=source.id,
                    criterion_type="none",
                    option_ids=new_option_commands,
                    line_column_ids=new_column_commands,
                )
            )
            option_map = {
                option.source_request_option_id.id: option.id
                for option in target.option_ids
                if option.source_request_option_id
            }
            target.write(
                {
                    "criterion_type": source.criterion_type,
                    "allowed_option_ids": [
                        (
                            6,
                            0,
                            [
                                option_map[option.id]
                                for option in source.allowed_option_ids
                                if option.id in option_map
                            ],
                        )
                    ],
                    "minimum_option_id": option_map.get(source.minimum_option_id.id),
                }
            )
        return True
