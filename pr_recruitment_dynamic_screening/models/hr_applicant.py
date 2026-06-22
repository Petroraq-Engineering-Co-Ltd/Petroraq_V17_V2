# -*- coding: utf-8 -*-

import math
import re

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class RecruitmentAnswer(models.Model):
    _name = "pr.recruitment.answer"
    _description = "Recruitment Application Answer"
    _order = "question_id"

    applicant_id = fields.Many2one("hr.applicant", required=True, ondelete="cascade", index=True)
    question_id = fields.Many2one(
        "pr.recruitment.question", required=True, ondelete="restrict", index=True
    )
    answer_type = fields.Selection(related="question_id.answer_type", readonly=True)
    option_id = fields.Many2one("pr.recruitment.question.option", ondelete="restrict")
    raw_value = fields.Text(readonly=True)
    value_text = fields.Text(readonly=True)
    value_integer = fields.Integer(readonly=True)
    value_float = fields.Float(readonly=True)
    value_boolean = fields.Boolean(readonly=True)
    value_date = fields.Date(readonly=True)
    line_ids = fields.One2many(
        "pr.recruitment.answer.line", "answer_id", string="Entries", readonly=True
    )
    display_value = fields.Char(compute="_compute_display_value")

    _sql_constraints = [
        (
            "applicant_question_unique",
            "unique(applicant_id, question_id)",
            "An applicant can only answer a question once.",
        )
    ]

    @api.constrains("applicant_id", "question_id", "option_id")
    def _check_answer_relations(self):
        for answer in self:
            if (
                answer.question_id.job_id
                and answer.applicant_id.job_id != answer.question_id.job_id
            ):
                raise ValidationError(
                    _("The screening answer must belong to the applicant's job position.")
                )
            if answer.option_id and answer.option_id.question_id != answer.question_id:
                raise ValidationError(
                    _("The selected answer value does not belong to this question.")
                )

    @api.depends(
        "question_id.answer_type",
        "option_id.name",
        "value_text",
        "value_integer",
        "value_float",
        "value_boolean",
        "value_date",
        "line_ids.display_value",
    )
    def _compute_display_value(self):
        for answer in self:
            answer_type = answer.question_id.answer_type
            if answer_type in ("char", "text"):
                answer.display_value = answer.value_text or ""
            elif answer_type == "integer":
                answer.display_value = str(answer.value_integer)
            elif answer_type == "decimal":
                answer.display_value = str(answer.value_float)
            elif answer_type in ("selection", "many2one"):
                answer.display_value = answer.option_id.name or ""
            elif answer_type == "one2many":
                answer.display_value = "; ".join(answer.line_ids.mapped("display_value")) or _("No entries")
            elif answer_type == "boolean":
                answer.display_value = _("Yes") if answer.value_boolean else _("No")
            elif answer_type == "date":
                answer.display_value = fields.Date.to_string(answer.value_date)
            else:
                answer.display_value = answer.raw_value or ""


class RecruitmentAnswerLine(models.Model):
    _name = "pr.recruitment.answer.line"
    _description = "Recruitment Repeating Answer Line"
    _order = "id"

    answer_id = fields.Many2one(
        "pr.recruitment.answer", required=True, ondelete="cascade", index=True
    )
    applicant_id = fields.Many2one(
        related="answer_id.applicant_id", store=True, index=True
    )
    cell_ids = fields.One2many(
        "pr.recruitment.answer.cell", "line_id", string="Values", readonly=True
    )
    display_value = fields.Char(compute="_compute_display_value")

    @api.depends("cell_ids.display_value", "cell_ids.column_id.name")
    def _compute_display_value(self):
        for line in self:
            line.display_value = ", ".join(
                "%s: %s" % (cell.column_id.name, cell.display_value)
                for cell in line.cell_ids
            )


class RecruitmentAnswerCell(models.Model):
    _name = "pr.recruitment.answer.cell"
    _description = "Recruitment Repeating Answer Cell"
    _order = "column_id"

    line_id = fields.Many2one(
        "pr.recruitment.answer.line", required=True, ondelete="cascade", index=True
    )
    column_id = fields.Many2one(
        "pr.recruitment.question.column", required=True, ondelete="restrict", index=True
    )
    column_option_id = fields.Many2one(
        "pr.recruitment.question.column.option", ondelete="restrict"
    )
    raw_value = fields.Text(readonly=True)
    value_text = fields.Text(readonly=True)
    value_integer = fields.Integer(readonly=True)
    value_float = fields.Float(readonly=True)
    value_date = fields.Date(readonly=True)
    display_value = fields.Char(compute="_compute_display_value")

    _sql_constraints = [
        (
            "line_column_unique",
            "unique(line_id, column_id)",
            "A repeating line can only contain a column once.",
        )
    ]

    @api.constrains("line_id", "column_id", "column_option_id")
    def _check_cell_relations(self):
        for cell in self:
            question = cell.line_id.answer_id.question_id
            if cell.column_id.question_id != question:
                raise ValidationError(
                    _("The repeating answer column does not belong to this question.")
                )
            if (
                cell.column_option_id
                and cell.column_option_id.column_id != cell.column_id
            ):
                raise ValidationError(
                    _("The selected repeating value does not belong to this column.")
                )

    @api.depends(
        "column_id.column_type",
        "column_option_id.name",
        "value_text",
        "value_integer",
        "value_float",
        "value_date",
    )
    def _compute_display_value(self):
        for cell in self:
            column_type = cell.column_id.column_type
            if column_type in ("char", "text"):
                cell.display_value = cell.value_text or ""
            elif column_type == "integer":
                cell.display_value = str(cell.value_integer)
            elif column_type == "decimal":
                cell.display_value = str(cell.value_float)
            elif column_type in ("selection", "many2one"):
                cell.display_value = cell.column_option_id.name or ""
            elif column_type == "date":
                cell.display_value = fields.Date.to_string(cell.value_date)
            else:
                cell.display_value = cell.raw_value or ""


class HrApplicant(models.Model):
    _inherit = "hr.applicant"

    dynamic_answer_ids = fields.One2many(
        "pr.recruitment.answer", "applicant_id", string="Screening Answers", readonly=True
    )
    dynamic_screening_status = fields.Selection(
        [
            ("not_screened", "Not Screened"),
            ("passed", "Passed"),
            ("auto_refused", "Automatically Refused"),
        ],
        default="not_screened",
        required=True,
        copy=False,
        tracking=True,
    )
    dynamic_screening_failure_reason = fields.Text(
        string="Automatic Refusal Reason", readonly=True, copy=False
    )
    dynamic_screened_on = fields.Datetime(readonly=True, copy=False)

    @api.model
    def get_recruitment_dashboard_data(self):
        data = super().get_recruitment_dashboard_data()
        Applicant = self.env["hr.applicant"].sudo().with_context(active_test=False)
        auto_refused_domain = [
            ("active", "=", False),
            ("dynamic_screening_status", "=", "auto_refused"),
        ]
        today = fields.Date.context_today(self)
        month_start = fields.Datetime.to_string(today.replace(day=1))
        auto_refused_total = Applicant.search_count(auto_refused_domain)
        auto_refused_month = Applicant.search_count(
            auto_refused_domain + [("dynamic_screened_on", ">=", month_start)]
        )

        refused_by_job = []
        job_groups = Applicant.read_group(
            auto_refused_domain + [("job_id", "!=", False)],
            ["job_id"],
            ["job_id"],
            orderby="job_id_count desc",
        )
        max_refused = max(
            [group.get("job_id_count") or group.get("__count", 0) for group in job_groups]
            or [1]
        )
        for group in job_groups:
            job_value = group.get("job_id")
            if not job_value:
                continue
            refused_count = group.get("job_id_count") or group.get("__count", 0)
            job_id, job_name = job_value
            applicant_count = Applicant.search_count([("job_id", "=", job_id)])
            refused_by_job.append(
                {
                    "id": job_id,
                    "name": job_name,
                    "count": refused_count,
                    "total": applicant_count,
                    "rate": round((refused_count / applicant_count) * 100.0, 1)
                    if applicant_count
                    else 0.0,
                    "percent": round((refused_count / max_refused) * 100.0, 1)
                    if refused_count
                    else 0.0,
                }
            )

        recent_auto_refused = []
        for applicant in Applicant.search(
            auto_refused_domain,
            order="dynamic_screened_on desc, id desc",
            limit=8,
        ):
            reason_lines = [
                line.strip()
                for line in (applicant.dynamic_screening_failure_reason or "").splitlines()
                if line.strip()
            ]
            recent_auto_refused.append(
                {
                    "id": applicant.id,
                    "name": applicant.partner_name or applicant.name,
                    "job": applicant.job_id.display_name or _("No Job"),
                    "reason": reason_lines[0] if reason_lines else _("Rule not recorded"),
                    "screened_on": fields.Datetime.to_string(
                        applicant.dynamic_screened_on
                    )
                    if applicant.dynamic_screened_on
                    else "",
                }
            )

        auto_refused_card = {
            "key": "auto_refused",
            "label": _("Auto Refused"),
            "value": auto_refused_total,
            "icon": "fa-ban",
            "model": "hr.applicant",
            "domain": auto_refused_domain,
            "context": {"active_test": False},
        }
        cards = data.setdefault("cards", [])
        cards.insert(min(3, len(cards)), auto_refused_card)
        data.setdefault("summary", {})["auto_refused_month"] = auto_refused_month
        data["auto_refused_by_job"] = refused_by_job
        data["recent_auto_refused"] = recent_auto_refused
        return data

    @api.model
    def _normalize_screening_email(self, email):
        return (email or "").strip().casefold()

    @api.model
    def _normalize_screening_phone(self, phone):
        normalized = re.sub(r"\D", "", phone or "")
        return normalized[2:] if normalized.startswith("00") else normalized

    @api.model
    def _lock_website_application_identity(self, job, email, phone):
        """Serialize matching public submissions to close the duplicate race window."""
        identity = "%s|%s|%s" % (
            job.id,
            self._normalize_screening_email(email),
            self._normalize_screening_phone(phone),
        )
        self.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [identity])

    @api.model
    def _find_duplicate_website_application(self, job, email, phone):
        normalized_email = self._normalize_screening_email(email)
        normalized_phone = self._normalize_screening_phone(phone)
        if not job or not normalized_email or not normalized_phone:
            return self.browse()
        candidates = self.sudo().with_context(active_test=False).search(
            [("job_id", "=", job.id), ("email_from", "=ilike", (email or "").strip())]
        )
        return candidates.filtered(
            lambda applicant: (
                self._normalize_screening_email(applicant.email_from)
                == normalized_email
                and self._normalize_screening_phone(applicant.partner_phone)
                == normalized_phone
            )
        )[:1]

    @api.model_create_multi
    def create(self, vals_list):
        applicants = super().create(vals_list)
        payload = self.env.context.get("pr_dynamic_recruitment_answers")
        should_screen_core_fields = self.env.context.get(
            "pr_screen_existing_application_fields"
        )
        if (payload or should_screen_core_fields) and len(applicants) == 1:
            applicants._record_dynamic_answers(payload or [])
        return applicants

    def _record_dynamic_answers(self, payload):
        self.ensure_one()
        Answer = self.env["pr.recruitment.answer"]
        job_questions = self.job_id.sudo().application_question_ids.filtered("active")
        question_by_id = {question.id: question for question in job_questions}
        for item in payload:
            question = question_by_id.get(item.get("question_id"))
            if not question:
                continue
            if question.answer_type == "one2many":
                answer = Answer.sudo().create(
                    {
                        "applicant_id": self.id,
                        "question_id": question.id,
                        "raw_value": _("%s entries") % len(item.get("lines", [])),
                    }
                )
                columns = {
                    column.id: column
                    for column in question.line_column_ids.filtered("active")
                }
                for source_line in item.get("lines", [])[:20]:
                    line = self.env["pr.recruitment.answer.line"].sudo().create(
                        {"answer_id": answer.id}
                    )
                    for source_cell in source_line.get("cells", []):
                        column = columns.get(source_cell.get("column_id"))
                        if not column:
                            continue
                        cell_values, error = column._prepare_cell(
                            source_cell.get("raw_value")
                        )
                        if error or not cell_values:
                            continue
                        cell_values.update(
                            {"line_id": line.id, "column_id": column.id}
                        )
                        self.env["pr.recruitment.answer.cell"].sudo().create(
                            cell_values
                        )
            else:
                values, error = question._prepare_answer(item.get("raw_value"))
                if error or not values:
                    continue
                values.update({"applicant_id": self.id, "question_id": question.id})
                Answer.sudo().create(values)
        self._evaluate_dynamic_screening()

    @api.model
    def _numeric_existing_field_failure(
        self, label, raw_value, rule, minimum, maximum, unit
    ):
        if rule == "none":
            return False
        try:
            numeric_value = float(str(raw_value or "").strip())
            if not math.isfinite(numeric_value) or numeric_value < 0:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            numeric_value = False

        if rule == "minimum":
            matches = numeric_value is not False and numeric_value >= minimum
            required = _("at least %s %s") % ("%g" % minimum, unit)
        elif rule == "maximum":
            matches = numeric_value is not False and numeric_value <= maximum
            required = _("no more than %s %s") % ("%g" % maximum, unit)
        else:
            matches = (
                numeric_value is not False and minimum <= numeric_value <= maximum
            )
            required = _("between %s and %s %s") % (
                "%g" % minimum,
                "%g" % maximum,
                unit,
            )
        if matches:
            return False
        return _("%s - received %s; required %s") % (
            label,
            (
                str(raw_value).strip()
                if raw_value not in (False, None, "")
                else _("Not provided")
            ),
            required,
        )

    def _existing_field_screening_failures(self):
        self.ensure_one()
        job = self.job_id
        failures = []

        if job.core_location_rule != "none":
            actual_location = " ".join((self.partner_location or "").split())
            normalized_location = actual_location.casefold()
            terms = job._core_location_terms()
            if job.core_location_rule == "exact":
                location_matches = normalized_location in terms
            else:
                location_matches = any(
                    term in normalized_location for term in terms
                )
            if not actual_location or not location_matches:
                failures.append(
                    _("Location - received %s; required %s")
                    % (
                        actual_location or _("Not provided"),
                        ", ".join(
                            line.strip()
                            for line in (job.core_location_values or "").splitlines()
                            if line.strip()
                        ),
                    )
                )

        if job.core_nationality_rule != "none":
            if job.core_nationality_rule == "allowed":
                nationality_matches = self.nationality_id in job.core_nationality_ids
                nationality_requirement = _("one of %s") % ", ".join(
                    job.core_nationality_ids.mapped("display_name")
                )
            else:
                nationality_matches = bool(
                    self.nationality_id
                    and self.nationality_id not in job.core_nationality_ids
                )
                nationality_requirement = _("any nationality except %s") % ", ".join(
                    job.core_nationality_ids.mapped("display_name")
                )
            if not nationality_matches:
                failures.append(
                    _("Nationality - received %s; required %s")
                    % (
                        self.nationality_id.display_name or _("Not provided"),
                        nationality_requirement,
                    )
                )

        if job.core_education_rule != "none":
            if job.core_education_rule == "allowed":
                education_matches = self.type_id in job.core_education_degree_ids
                required_education = ", ".join(
                    job.core_education_degree_ids.mapped("display_name")
                )
            else:
                minimum = job.core_minimum_education_id
                education_matches = bool(
                    self.type_id and self.type_id.sequence >= minimum.sequence
                )
                required_education = minimum.display_name
            if not education_matches:
                failures.append(
                    _("Education - received %s; required %s")
                    % (
                        self.type_id.display_name or _("Not provided"),
                        required_education,
                    )
                )

        experience_failure = self._numeric_existing_field_failure(
            _("Experience"),
            self.experience,
            job.core_experience_rule,
            job.core_experience_minimum,
            job.core_experience_maximum,
            _("years"),
        )
        if experience_failure:
            failures.append(experience_failure)

        notice_failure = self._numeric_existing_field_failure(
            _("Notice period"),
            self.notice_period,
            job.core_notice_period_rule,
            job.core_notice_period_minimum,
            job.core_notice_period_maximum,
            _("days"),
        )
        if notice_failure:
            failures.append(notice_failure)

        salary_failure = self._numeric_existing_field_failure(
            _("Expected salary"),
            self.salary_expected,
            job.core_salary_rule,
            job.core_salary_minimum,
            job.core_salary_maximum,
            _("SAR"),
        )
        if salary_failure:
            failures.append(salary_failure)

        if job.core_iqama_rule == "required":
            iqama_number = (self.national_id_iqama or "").strip()
            has_valid_iqama = (
                self.legally_required == "yes"
                and bool(re.fullmatch(r"\d{10}", iqama_number))
            )
            if not has_valid_iqama:
                if self.legally_required == "no":
                    received_iqama = _("No selected")
                elif not iqama_number:
                    received_iqama = _("Not provided")
                else:
                    received_iqama = _("Invalid number")
                failures.append(
                    _(
                        "National ID / Iqama - received %s; required Yes with a valid "
                        "10-digit number"
                    )
                    % received_iqama
                )
        return failures

    def _evaluate_dynamic_screening(self):
        for applicant in self:
            failures = applicant._existing_field_screening_failures()
            answers = {answer.question_id.id: answer for answer in applicant.dynamic_answer_ids}
            screening_questions = applicant.job_id.application_question_ids.filtered(
                lambda question: question.active and question.criterion_type != "none"
            )
            for question in screening_questions:
                answer = answers.get(question.id)
                if not answer:
                    if question.criterion_type == "line_count_max":
                        continue
                    failures.append(_("%s - no answer received") % question.name)
                    continue
                failure = question._screening_failure(answer)
                if failure:
                    failures.append(failure)

            previous_status = applicant.dynamic_screening_status
            previous_failure_reason = applicant.dynamic_screening_failure_reason or ""
            refusal_reason = self.env.ref(
                "pr_recruitment_dynamic_screening.refuse_reason_automatic_screening"
            )
            values = {"dynamic_screened_on": fields.Datetime.now()}
            if failures:
                failure_reason = "\n".join(failures)
                values.update(
                    {
                        "dynamic_screening_status": "auto_refused",
                        "dynamic_screening_failure_reason": failure_reason,
                    }
                )
                if (
                    applicant.active
                    or not applicant.refuse_reason_id
                    or applicant.refuse_reason_id == refusal_reason
                ):
                    values.update(
                        {
                            "active": False,
                            "refuse_reason_id": refusal_reason.id,
                            "date_closed": False,
                        }
                    )
            else:
                values.update(
                    {
                        "dynamic_screening_status": "passed",
                        "dynamic_screening_failure_reason": False,
                    }
                )
                if (
                    previous_status == "auto_refused"
                    and applicant.refuse_reason_id == refusal_reason
                ):
                    values.update(
                        {
                            "active": True,
                            "refuse_reason_id": False,
                            "date_closed": False,
                        }
                    )
            applicant.sudo().write(values)
            if failures and (
                previous_status != "auto_refused"
                or previous_failure_reason != failure_reason
            ):
                items = Markup().join(
                    Markup("<li>%s</li>") % escape(failure) for failure in failures
                )
                applicant.sudo().message_post(
                    body=Markup("<p>%s</p><ul>%s</ul>")
                    % (escape(_("Application automatically refused by screening rules.")), items)
                )
            elif not failures and previous_status == "auto_refused":
                applicant.sudo().message_post(
                    body=escape(
                        _(
                            "The application passed after its screening rules were "
                            "re-evaluated."
                        )
                    )
                )
        return True

    def action_rescreen_dynamic_answers(self):
        if not self.env.is_superuser() and not self.env.user.has_group(
            "hr_recruitment.group_hr_recruitment_user"
        ):
            raise AccessError(_("Only recruitment users can re-run applicant screening."))
        self.check_access_rights("write")
        self.check_access_rule("write")
        self._evaluate_dynamic_screening()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Screening complete"),
                "message": _("The selected application screening result was refreshed."),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }
