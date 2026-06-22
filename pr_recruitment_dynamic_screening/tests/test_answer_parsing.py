from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .common import ScreeningCase


@tagged("post_install", "-at_install")
class TestAnswerParsing(ScreeningCase):

    def test_required_and_optional_text(self):
        optional = self.make_question("char")
        self.assertEqual(optional._prepare_answer(""), ({}, False))

        required = self.make_question("text", required=True)
        values, error = required._prepare_answer("  useful answer  ")
        self.assertFalse(error)
        self.assertEqual(values["value_text"], "useful answer")
        self.assertTrue(required._prepare_answer("")[1])
        self.assertTrue(required._prepare_answer("x" * 5001)[1])

    def test_integer_boundaries_and_invalid_values(self):
        question = self.make_question("integer")
        for raw_value, expected in (("0", 0), ("-12", -12), (str(2**31 - 1), 2**31 - 1)):
            with self.subTest(raw_value=raw_value):
                values, error = question._prepare_answer(raw_value)
                self.assertFalse(error)
                self.assertEqual(values["value_integer"], expected)
        for raw_value in ("1.2", "abc", str(2**31), str(-(2**31) - 1)):
            with self.subTest(raw_value=raw_value):
                self.assertTrue(question._prepare_answer(raw_value)[1])

    def test_decimal_rejects_non_finite_values(self):
        question = self.make_question("decimal")
        values, error = question._prepare_answer("-12.50")
        self.assertFalse(error)
        self.assertEqual(values["value_float"], -12.5)
        for raw_value in ("nan", "inf", "-inf", "not-a-number"):
            with self.subTest(raw_value=raw_value):
                self.assertTrue(question._prepare_answer(raw_value)[1])

    def test_boolean_and_date_validation(self):
        boolean = self.make_question("boolean")
        self.assertTrue(boolean._prepare_answer("yes")[0]["value_boolean"])
        self.assertFalse(boolean._prepare_answer("no")[0]["value_boolean"])
        self.assertTrue(boolean._prepare_answer("maybe")[1])

        date_question = self.make_question("date")
        values, error = date_question._prepare_answer("2026-06-21")
        self.assertFalse(error)
        self.assertEqual(str(values["value_date"]), "2026-06-21")
        self.assertTrue(date_question._prepare_answer("21/06/2026")[1])

    def test_selection_rejects_foreign_and_archived_options(self):
        question = self.make_question("selection")
        other = self.make_question("selection", job=self.other_job)
        accepted = question.option_ids[0]
        values, error = question._prepare_answer(str(accepted.id))
        self.assertFalse(error)
        self.assertEqual(values["option_id"], accepted.id)
        self.assertTrue(question._prepare_answer(str(other.option_ids[0].id))[1])
        accepted.write({"active": False})
        self.assertTrue(question._prepare_answer(str(accepted.id))[1])

    def test_many2one_allow_list_rejects_unlisted_records(self):
        question = self.make_question("many2one", relation_model="res.country")
        accepted = question.option_ids[0]
        values, error = question._prepare_answer(str(accepted.id))
        self.assertFalse(error)
        self.assertEqual(values["option_id"], accepted.id)
        self.assertTrue(question._prepare_answer("999999999")[1])

    def test_repeating_rows_validate_tokens_columns_and_limits(self):
        question = self.make_question(
            "one2many",
            required=True,
            columns=[
                {"name": "Employer", "column_type": "char", "required": True},
                {"name": "Years", "column_type": "integer"},
            ],
        )
        employer, years = question.line_column_ids
        post = {
            "pr_question_%s_rows" % question.id: "1,2,2,invalid",
            "pr_question_%s_1_column_%s" % (question.id, employer.id): "Petroraq",
            "pr_question_%s_1_column_%s" % (question.id, years.id): "3",
            "pr_question_%s_2_column_%s" % (question.id, employer.id): "",
            "pr_question_%s_2_column_%s" % (question.id, years.id): "",
        }
        payload, error = question.prepare_website_payload(post)
        self.assertFalse(error)
        self.assertEqual(len(payload["lines"]), 1)
        self.assertEqual(len(payload["lines"][0]["cells"]), 2)

        missing_required = dict(post)
        missing_required[
            "pr_question_%s_1_column_%s" % (question.id, employer.id)
        ] = ""
        self.assertTrue(question.prepare_website_payload(missing_required)[1])

        too_many = {"pr_question_%s_rows" % question.id: ",".join(map(str, range(1, 22)))}
        self.assertTrue(question.prepare_website_payload(too_many)[1])
        oversized = {"pr_question_%s_rows" % question.id: "1" * 201}
        self.assertTrue(question.prepare_website_payload(oversized)[1])

    def test_archived_repeating_columns_are_not_accepted(self):
        question = self.make_question(
            "one2many",
            columns=[
                {"name": "Current", "column_type": "char"},
                {"name": "Old", "column_type": "char"},
            ],
        )
        current, old = question.line_column_ids
        old.write({"active": False})
        post = {
            "pr_question_%s_rows" % question.id: "1",
            "pr_question_%s_1_column_%s" % (question.id, current.id): "kept",
            "pr_question_%s_1_column_%s" % (question.id, old.id): "forged",
        }
        payload, error = question.prepare_website_payload(post)
        self.assertFalse(error)
        self.assertEqual(
            [cell["column_id"] for cell in payload["lines"][0]["cells"]],
            [current.id],
        )

    def test_column_selection_rejects_other_column_option(self):
        question = self.make_question(
            "one2many",
            columns=[
                {
                    "name": "Level",
                    "column_type": "selection",
                    "option_ids": [
                        Command.create({"name": "Junior"}),
                        Command.create({"name": "Senior"}),
                    ],
                },
                {
                    "name": "Other",
                    "column_type": "selection",
                    "option_ids": [Command.create({"name": "Unrelated"})],
                },
            ],
        )
        level, other = question.line_column_ids
        self.assertFalse(level._prepare_cell(str(level.option_ids[0].id))[1])
        self.assertTrue(level._prepare_cell(str(other.option_ids[0].id))[1])

    def test_persisted_answers_reject_cross_question_and_cross_column_relations(self):
        first = self.make_question("selection")
        second = self.make_question("selection")
        applicant = self.make_applicant()
        with self.assertRaises(ValidationError):
            self.Answer.sudo().create(
                {
                    "applicant_id": applicant.id,
                    "question_id": first.id,
                    "option_id": second.option_ids[0].id,
                    "raw_value": str(second.option_ids[0].id),
                }
            )

        repeating = self.make_question(
            "one2many",
            columns=[
                {
                    "name": "First",
                    "column_type": "selection",
                    "option_ids": [Command.create({"name": "A"})],
                },
                {
                    "name": "Second",
                    "column_type": "selection",
                    "option_ids": [Command.create({"name": "B"})],
                },
            ],
        )
        answer = self.Answer.sudo().create(
            {"applicant_id": applicant.id, "question_id": repeating.id}
        )
        line = self.env["pr.recruitment.answer.line"].sudo().create(
            {"answer_id": answer.id}
        )
        first_column, second_column = repeating.line_column_ids
        with self.assertRaises(ValidationError):
            self.env["pr.recruitment.answer.cell"].sudo().create(
                {
                    "line_id": line.id,
                    "column_id": first_column.id,
                    "column_option_id": second_column.option_ids[0].id,
                }
            )
