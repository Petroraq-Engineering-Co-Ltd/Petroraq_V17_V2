from datetime import date

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import tagged

from .common import ScreeningCase


@tagged("post_install", "-at_install")
class TestScreeningRules(ScreeningCase):

    def test_numeric_text_boolean_and_date_rules(self):
        applicant = self.make_applicant()

        integer = self.set_criterion(
            self.make_question("integer"), "number_min", criterion_number=5
        )
        self.assertTrue(integer._screening_failure(self.make_answer(applicant, integer, "4")))
        self.assertFalse(integer._screening_failure(self.make_answer(
            self.make_applicant(), integer, "5"
        )))

        decimal = self.set_criterion(
            self.make_question("decimal"), "number_equal", criterion_number=0.3
        )
        self.assertFalse(
            decimal._screening_failure(
                self.make_answer(self.make_applicant(), decimal, "0.3000000001")
            )
        )

        text = self.set_criterion(
            self.make_question("char"), "text_equal", criterion_text="Approved"
        )
        self.assertFalse(
            text._screening_failure(
                self.make_answer(self.make_applicant(), text, "  APPROVED  ")
            )
        )

        boolean = self.set_criterion(
            self.make_question("boolean"),
            "boolean_equal",
            criterion_boolean=False,
        )
        self.assertFalse(
            boolean._screening_failure(
                self.make_answer(self.make_applicant(), boolean, "no")
            )
        )

        minimum_date = self.set_criterion(
            self.make_question("date"),
            "date_min",
            criterion_date=date(2026, 1, 1),
        )
        self.assertTrue(
            minimum_date._screening_failure(
                self.make_answer(self.make_applicant(), minimum_date, "2025-12-31")
            )
        )

    def test_allowed_and_ranked_option_rules(self):
        allowed = self.make_question("selection")
        accepted, rejected = allowed.option_ids
        accepted.write({"screening_allowed": True})
        self.set_criterion(allowed, "option_allowed")
        self.assertFalse(
            allowed._screening_failure(
                self.make_answer(self.make_applicant(), allowed, str(accepted.id))
            )
        )
        self.assertTrue(
            allowed._screening_failure(
                self.make_answer(self.make_applicant(), allowed, str(rejected.id))
            )
        )

        ranked = self.make_question("selection")
        low, high = ranked.option_ids.sorted("sequence")
        high.write({"screening_minimum": True})
        self.set_criterion(ranked, "option_min_sequence")
        self.assertTrue(
            ranked._screening_failure(
                self.make_answer(self.make_applicant(), ranked, str(low.id))
            )
        )
        self.assertFalse(
            ranked._screening_failure(
                self.make_answer(self.make_applicant(), ranked, str(high.id))
            )
        )

    def test_line_count_rules(self):
        question = self.set_criterion(
            self.make_question("one2many"),
            "line_count_min",
            criterion_number=2,
        )
        applicant = self.make_applicant()
        answer = self.Answer.sudo().create(
            {"applicant_id": applicant.id, "question_id": question.id}
        )
        self.env["pr.recruitment.answer.line"].sudo().create(
            {"answer_id": answer.id}
        )
        self.assertTrue(question._screening_failure(answer))
        self.env["pr.recruitment.answer.line"].sudo().create(
            {"answer_id": answer.id}
        )
        self.assertFalse(question._screening_failure(answer))


@tagged("post_install", "-at_install")
class TestApplicantScreeningLifecycle(ScreeningCase):

    def test_existing_location_nationality_and_minimum_education_rules(self):
        countries = self.env["res.country"].search([], limit=2)
        self.assertEqual(len(countries), 2)
        low_degree = self.env["hr.recruitment.degree"].create(
            {"name": self.unique_name("Diploma"), "sequence": 10}
        )
        high_degree = self.env["hr.recruitment.degree"].create(
            {"name": self.unique_name("Bachelor"), "sequence": 20}
        )
        self.job.write(
            {
                "core_location_rule": "contains",
                "core_location_values": "Jubail\nDammam",
                "core_nationality_rule": "allowed",
                "core_nationality_ids": [Command.set(countries[:1].ids)],
                "core_education_rule": "minimum",
                "core_minimum_education_id": high_degree.id,
            }
        )

        passing = self.make_applicant(
            partner_location="Al Jubail, Eastern Province",
            nationality_id=countries[0].id,
            type_id=high_degree.id,
        )
        passing._evaluate_dynamic_screening()
        self.assertEqual(passing.dynamic_screening_status, "passed")
        self.assertTrue(passing.active)

        failing = self.make_applicant(
            partner_location="Riyadh",
            nationality_id=countries[1].id,
            type_id=low_degree.id,
        )
        failing._evaluate_dynamic_screening()
        self.assertEqual(failing.dynamic_screening_status, "auto_refused")
        self.assertIn("Location", failing.dynamic_screening_failure_reason)
        self.assertIn("Nationality", failing.dynamic_screening_failure_reason)
        self.assertIn("Education", failing.dynamic_screening_failure_reason)

    def test_exact_location_and_allowed_education_are_case_insensitive(self):
        allowed_degree = self.env["hr.recruitment.degree"].create(
            {"name": self.unique_name("Allowed Degree"), "sequence": 1}
        )
        other_degree = self.env["hr.recruitment.degree"].create(
            {"name": self.unique_name("Other Degree"), "sequence": 99}
        )
        self.job.write(
            {
                "core_location_rule": "exact",
                "core_location_values": "Al Jubail",
                "core_education_rule": "allowed",
                "core_education_degree_ids": [Command.set(allowed_degree.ids)],
            }
        )
        passing = self.make_applicant(
            partner_location="  AL   JUBAIL ", type_id=allowed_degree.id
        )
        passing._evaluate_dynamic_screening()
        self.assertEqual(passing.dynamic_screening_status, "passed")

        failing = self.make_applicant(
            partner_location="Al Jubail", type_id=other_degree.id
        )
        failing._evaluate_dynamic_screening()
        self.assertEqual(failing.dynamic_screening_status, "auto_refused")
        self.assertIn("Education", failing.dynamic_screening_failure_reason)

    def test_nationality_exclusion_allows_everyone_except_selected(self):
        countries = self.env["res.country"].search([], limit=2)
        self.assertEqual(len(countries), 2)
        self.job.write(
            {
                "core_nationality_rule": "excluded",
                "core_nationality_ids": [Command.set(countries[:1].ids)],
            }
        )

        allowed = self.make_applicant(nationality_id=countries[1].id)
        excluded = self.make_applicant(nationality_id=countries[0].id)
        missing = self.make_applicant(nationality_id=False)
        (allowed | excluded | missing)._evaluate_dynamic_screening()

        self.assertEqual(allowed.dynamic_screening_status, "passed")
        self.assertEqual(excluded.dynamic_screening_status, "auto_refused")
        self.assertIn("except", excluded.dynamic_screening_failure_reason)
        self.assertEqual(missing.dynamic_screening_status, "auto_refused")
        self.assertIn("Not provided", missing.dynamic_screening_failure_reason)

    def test_core_only_context_evaluates_without_dynamic_questions(self):
        country = self.env["res.country"].search([], limit=1)
        self.job.write(
            {
                "core_nationality_rule": "allowed",
                "core_nationality_ids": [Command.set(country.ids)],
            }
        )
        applicant = self.env["hr.applicant"].with_context(
            pr_dynamic_recruitment_answers=[],
            pr_screen_existing_application_fields=True,
        ).create(
            {
                "name": "Core-only Candidate",
                "partner_name": "Core-only Candidate",
                "job_id": self.job.id,
                "nationality_id": False,
            }
        )
        self.assertEqual(applicant.dynamic_screening_status, "auto_refused")
        self.assertIn("Nationality", applicant.dynamic_screening_failure_reason)

    def test_experience_and_notice_period_numeric_rules(self):
        self.job.write(
            {
                "core_experience_rule": "minimum",
                "core_experience_minimum": 5.5,
                "core_notice_period_rule": "maximum",
                "core_notice_period_maximum": 30,
            }
        )
        passing = self.make_applicant(experience="5.5", notice_period="30")
        passing._evaluate_dynamic_screening()
        self.assertEqual(passing.dynamic_screening_status, "passed")

        failing = self.make_applicant(experience="4", notice_period="45")
        failing._evaluate_dynamic_screening()
        self.assertEqual(failing.dynamic_screening_status, "auto_refused")
        self.assertIn("Experience", failing.dynamic_screening_failure_reason)
        self.assertIn("Notice period", failing.dynamic_screening_failure_reason)

        malformed = self.make_applicant(experience="unknown", notice_period=False)
        malformed._evaluate_dynamic_screening()
        self.assertEqual(malformed.dynamic_screening_status, "auto_refused")
        self.assertIn("Not provided", malformed.dynamic_screening_failure_reason)

    def test_numeric_ranges_include_boundaries(self):
        self.job.write(
            {
                "core_experience_rule": "range",
                "core_experience_minimum": 2,
                "core_experience_maximum": 8,
                "core_notice_period_rule": "range",
                "core_notice_period_minimum": 0,
                "core_notice_period_maximum": 60,
            }
        )
        lower = self.make_applicant(experience="2", notice_period="0")
        upper = self.make_applicant(experience="8", notice_period="60")
        (lower | upper)._evaluate_dynamic_screening()
        self.assertEqual(lower.dynamic_screening_status, "passed")
        self.assertEqual(upper.dynamic_screening_status, "passed")

    def test_expected_salary_and_required_iqama_rules(self):
        self.job.write(
            {
                "core_salary_rule": "range",
                "core_salary_minimum": 5000,
                "core_salary_maximum": 9000,
                "core_iqama_rule": "required",
            }
        )
        passing = self.make_applicant(
            salary_expected=5000,
            legally_required="yes",
            national_id_iqama="1234567890",
        )
        no_iqama = self.make_applicant(
            salary_expected=7000,
            legally_required="no",
            national_id_iqama=False,
        )
        invalid_and_expensive = self.make_applicant(
            salary_expected=10000,
            legally_required="yes",
            national_id_iqama="123",
        )
        (passing | no_iqama | invalid_and_expensive)._evaluate_dynamic_screening()

        self.assertEqual(passing.dynamic_screening_status, "passed")
        self.assertEqual(no_iqama.dynamic_screening_status, "auto_refused")
        self.assertIn("No selected", no_iqama.dynamic_screening_failure_reason)
        self.assertEqual(
            invalid_and_expensive.dynamic_screening_status, "auto_refused"
        )
        self.assertIn(
            "Expected salary", invalid_and_expensive.dynamic_screening_failure_reason
        )
        self.assertIn(
            "Invalid number", invalid_and_expensive.dynamic_screening_failure_reason
        )

    def test_dashboard_exposes_auto_refusals_by_job(self):
        self.job.write({"core_iqama_rule": "required"})
        applicant = self.make_applicant(
            legally_required="no", national_id_iqama=False
        )
        applicant._evaluate_dynamic_screening()

        data = self.env["hr.applicant"].get_recruitment_dashboard_data()
        card = next(card for card in data["cards"] if card["key"] == "auto_refused")
        job_data = next(
            item for item in data["auto_refused_by_job"] if item["id"] == self.job.id
        )

        self.assertGreaterEqual(card["value"], 1)
        self.assertEqual(card["context"], {"active_test": False})
        self.assertEqual(job_data["count"], 1)
        self.assertEqual(data["recent_auto_refused"][0]["id"], applicant.id)

    def test_existing_field_rules_require_configuration_values(self):
        empty_job = self.env["hr.job"].create({"name": self.unique_name("Empty Job")})
        with self.assertRaises(ValidationError):
            empty_job.write({"core_location_rule": "contains"})

        other_job = self.env["hr.job"].create({"name": self.unique_name("Other Job")})
        with self.assertRaises(ValidationError):
            other_job.write({"core_nationality_rule": "allowed"})

        excluded_job = self.env["hr.job"].create(
            {"name": self.unique_name("Excluded Nationality Job")}
        )
        with self.assertRaises(ValidationError):
            excluded_job.write({"core_nationality_rule": "excluded"})

        degree_job = self.env["hr.job"].create({"name": self.unique_name("Degree Job")})
        with self.assertRaises(ValidationError):
            degree_job.write({"core_education_rule": "minimum"})

        range_job = self.env["hr.job"].create({"name": self.unique_name("Range Job")})
        with self.assertRaises(ValidationError):
            range_job.write(
                {
                    "core_experience_rule": "range",
                    "core_experience_minimum": 10,
                    "core_experience_maximum": 5,
                }
            )

        notice_job = self.env["hr.job"].create({"name": self.unique_name("Notice Job")})
        with self.assertRaises(ValidationError):
            notice_job.write(
                {
                    "core_notice_period_rule": "minimum",
                    "core_notice_period_minimum": -1,
                }
            )

        salary_job = self.env["hr.job"].create(
            {"name": self.unique_name("Salary Job")}
        )
        with self.assertRaises(ValidationError):
            salary_job.write(
                {
                    "core_salary_rule": "range",
                    "core_salary_minimum": 9000,
                    "core_salary_maximum": 5000,
                }
            )

    def test_public_payload_records_answers_and_auto_refuses(self):
        question = self.set_criterion(
            self.make_question("integer"), "number_min", criterion_number=5
        )
        payload, error = self.job.prepare_dynamic_application_answers(
            {"pr_question_%s" % question.id: "4"}
        )
        self.assertFalse(error)
        applicant = self.env["hr.applicant"].with_context(
            pr_dynamic_recruitment_answers=payload
        ).create(
            {
                "name": "Screened Candidate",
                "partner_name": "Screened Candidate",
                "job_id": self.job.id,
                "email_from": "screened@example.com",
                "partner_phone": "+966500000001",
            }
        )
        self.assertEqual(applicant.dynamic_screening_status, "auto_refused")
        self.assertFalse(applicant.active)
        self.assertEqual(len(applicant.dynamic_answer_ids), 1)
        self.assertEqual(applicant.refuse_reason_id, self.env.ref(
            "pr_recruitment_dynamic_screening.refuse_reason_automatic_screening"
        ))

        message_count = len(applicant.message_ids)
        applicant._evaluate_dynamic_screening()
        self.assertEqual(len(applicant.message_ids), message_count)

        question.write({"criterion_number": 1})
        action = applicant.action_rescreen_dynamic_answers()
        self.assertEqual(action["tag"], "display_notification")
        self.assertEqual(applicant.dynamic_screening_status, "passed")
        self.assertTrue(applicant.active)
        self.assertFalse(applicant.refuse_reason_id)

    def test_missing_required_screening_answer_fails_closed(self):
        self.set_criterion(
            self.make_question("char"), "text_equal", criterion_text="yes"
        )
        applicant = self.make_applicant()
        applicant._evaluate_dynamic_screening()
        self.assertEqual(applicant.dynamic_screening_status, "auto_refused")
        self.assertIn("no answer received", applicant.dynamic_screening_failure_reason)

    def test_manual_refusal_reason_is_not_overwritten_on_rescreen(self):
        self.set_criterion(
            self.make_question("char"), "text_equal", criterion_text="yes"
        )
        manual_reason = self.env["hr.applicant.refuse.reason"].create(
            {"name": "Manual screening decision"}
        )
        applicant = self.make_applicant(
            active=False, refuse_reason_id=manual_reason.id
        )
        applicant._evaluate_dynamic_screening()
        self.assertFalse(applicant.active)
        self.assertEqual(applicant.refuse_reason_id, manual_reason)

        applicant.write(
            {
                "dynamic_screening_status": "auto_refused",
                "refuse_reason_id": manual_reason.id,
            }
        )
        applicant._evaluate_dynamic_screening()
        self.assertFalse(applicant.active)
        self.assertEqual(applicant.refuse_reason_id, manual_reason)

    def test_optional_maximum_lines_treats_no_answer_as_zero(self):
        question = self.set_criterion(
            self.make_question("one2many"),
            "line_count_max",
            criterion_number=2,
            required=False,
        )
        applicant = self.make_applicant()
        applicant._evaluate_dynamic_screening()
        self.assertEqual(applicant.dynamic_screening_status, "passed")
        self.assertNotIn(question.name, applicant.dynamic_screening_failure_reason or "")

    def test_public_user_cannot_invoke_rescreen_action_by_rpc(self):
        applicant = self.make_applicant()
        with self.assertRaises(AccessError):
            applicant.with_user(self.env.ref("base.public_user")).action_rescreen_dynamic_answers()

    def test_repeating_answers_create_only_active_cells(self):
        question = self.make_question(
            "one2many",
            required=True,
            columns=[
                {"name": "Employer", "column_type": "char", "required": True},
                {"name": "Legacy", "column_type": "char"},
            ],
        )
        employer, legacy = question.line_column_ids
        legacy.write({"active": False})
        post = {
            "pr_question_%s_rows" % question.id: "1",
            "pr_question_%s_1_column_%s" % (question.id, employer.id): "Petroraq",
            "pr_question_%s_1_column_%s" % (question.id, legacy.id): "forged",
        }
        payload, error = self.job.prepare_dynamic_application_answers(post)
        self.assertFalse(error)
        applicant = self.env["hr.applicant"].with_context(
            pr_dynamic_recruitment_answers=payload
        ).create({"name": "Repeating Candidate", "job_id": self.job.id})
        answer = applicant.dynamic_answer_ids
        self.assertEqual(len(answer.line_ids), 1)
        self.assertEqual(answer.line_ids.cell_ids.column_id, employer)

    def test_payload_for_another_job_is_ignored(self):
        foreign_question = self.make_question("char", job=self.other_job)
        applicant = self.make_applicant()
        applicant._record_dynamic_answers(
            [{"question_id": foreign_question.id, "raw_value": "forged"}]
        )
        self.assertFalse(applicant.dynamic_answer_ids)

    def test_duplicate_application_normalizes_email_and_phone(self):
        existing = self.make_applicant(
            email_from="Candidate@Example.COM",
            partner_phone="+966 (50) 123-4567",
        )
        duplicate = self.env["hr.applicant"]._find_duplicate_website_application(
            self.job, " candidate@example.com ", "00966 50 123 4567"
        )
        self.assertEqual(duplicate, existing)
        self.assertFalse(
            self.env["hr.applicant"]._find_duplicate_website_application(
                self.other_job, "candidate@example.com", "+966501234567"
            )
        )


@tagged("post_install", "-at_install")
class TestConfigurationIntegrity(ScreeningCase):

    def test_incompatible_rule_and_fractional_line_count_are_rejected(self):
        question = self.make_question("char")
        with self.assertRaises(ValidationError):
            question.write({"criterion_type": "number_min", "required": True})

        repeating = self.make_question("one2many")
        with self.assertRaises(ValidationError):
            repeating.write(
                {
                    "criterion_type": "line_count_min",
                    "criterion_number": 1.5,
                    "required": True,
                }
            )

        with self.assertRaises(ValidationError):
            repeating.write(
                {
                    "criterion_type": "line_count_min",
                    "criterion_number": float("inf"),
                    "required": True,
                }
            )

    def test_last_active_option_and_column_cannot_be_archived(self):
        question = self.make_question("selection")
        question.option_ids[0].write({"active": False})
        with self.assertRaises(ValidationError):
            question.option_ids.filtered("active").write({"active": False})

        repeating = self.make_question("one2many")
        with self.assertRaises(ValidationError):
            repeating.line_column_ids.write({"active": False})

    def test_switching_minimum_option_is_atomic(self):
        question = self.make_question("selection")
        first, second = question.option_ids
        first.write({"screening_minimum": True})
        second.write({"screening_minimum": True})
        self.assertFalse(first.screening_minimum)
        self.assertTrue(second.screening_minimum)

    def test_answered_question_and_column_types_are_immutable(self):
        question = self.make_question("char")
        applicant = self.make_applicant()
        self.make_answer(applicant, question, "answer")
        with self.assertRaises(ValidationError):
            question.write({"answer_type": "integer"})

        repeating = self.make_question(
            "one2many",
            columns=[{"name": "Value", "column_type": "char"}],
        )
        answer = self.Answer.sudo().create(
            {"applicant_id": applicant.id, "question_id": repeating.id}
        )
        line = self.env["pr.recruitment.answer.line"].sudo().create(
            {"answer_id": answer.id}
        )
        column = repeating.line_column_ids
        self.env["pr.recruitment.answer.cell"].sudo().create(
            {
                "line_id": line.id,
                "column_id": column.id,
                "raw_value": "value",
                "value_text": "value",
            }
        )
        with self.assertRaises(ValidationError):
            column.write({"column_type": "integer"})
