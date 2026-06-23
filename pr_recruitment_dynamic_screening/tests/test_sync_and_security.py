from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import tagged

from .common import ScreeningCase


@tagged("post_install", "-at_install")
class TestRequestQuestionSynchronization(ScreeningCase):

    def make_request(self, requested_by=None, job=None, state="draft"):
        return self.env["hr.recruitment.request"].create(
            {
                "name": self.unique_name("REQ"),
                "requested_by_id": (requested_by or self.env.user).id,
                "requested_employees": 1,
                "job_id": (job or self.job).id,
                "state": state,
            }
        )

    def test_option_rename_preserves_historical_answer_reference(self):
        request_record = self.make_request()
        source = self.make_question("selection", request_record=request_record)
        source.copy_to_job(self.job)
        target = self.Question.search(
            [("job_id", "=", self.job.id), ("source_request_question_id", "=", source.id)]
        )
        source_option = source.option_ids[0]
        target_option = target.option_ids.filtered(
            lambda option: option.source_request_option_id == source_option
        )
        applicant = self.make_applicant()
        answer = self.Answer.sudo().create(
            {
                "applicant_id": applicant.id,
                "question_id": target.id,
                "raw_value": str(target_option.id),
                "option_id": target_option.id,
            }
        )

        target_option_id = target_option.id
        source_option.write({"name": "Renamed Source Option"})
        source.copy_to_job(self.job)
        self.assertEqual(target_option.id, target_option_id)
        self.assertEqual(target_option.name, "Renamed Source Option")
        self.assertEqual(answer.option_id, target_option)

    def test_option_rename_archives_stale_name_collision(self):
        request_record = self.make_request()
        source = self.make_question("selection", request_record=request_record)
        source.option_ids = [
            Command.create({"name": "Current"}),
            Command.create({"name": "Former"}),
        ]
        source.copy_to_job(self.job)
        target = self.Question.search(
            [("job_id", "=", self.job.id), ("source_request_question_id", "=", source.id)]
        )
        current_source = source.option_ids.filtered(
            lambda option: option.name == "Current"
        )
        former_source = source.option_ids.filtered(
            lambda option: option.name == "Former"
        )
        current_target = target.option_ids.filtered(
            lambda option: option.source_request_option_id == current_source
        )
        former_target = target.option_ids.filtered(
            lambda option: option.source_request_option_id == former_source
        )

        current_target_id = current_target.id
        former_source.unlink()
        current_source.write({"name": "Former"})
        source.copy_to_job(self.job)

        self.assertEqual(current_target.id, current_target_id)
        self.assertEqual(current_target.name, "Former")
        self.assertTrue(current_target.active)
        self.assertFalse(former_target.active)
        self.assertFalse(former_target.source_request_option_id)
        self.assertIn("Archived", former_target.name)

    def test_repeating_column_sync_preserves_cells_and_archives_incompatible_column(self):
        request_record = self.make_request()
        source = self.make_question(
            "one2many",
            request_record=request_record,
            columns=[
                {
                    "name": "Level",
                    "column_type": "selection",
                    "option_ids": [
                        Command.create({"name": "Junior"}),
                        Command.create({"name": "Senior"}),
                    ],
                },
                {"name": "Notes", "column_type": "char"},
            ],
        )
        source.copy_to_job(self.job)
        target = self.Question.search(
            [("job_id", "=", self.job.id), ("source_request_question_id", "=", source.id)]
        )
        source_column = source.line_column_ids.filtered(lambda column: column.name == "Level")
        target_column = target.line_column_ids.filtered(
            lambda column: column.source_request_column_id == source_column
        )
        source_option = source_column.option_ids[0]
        target_option = target_column.option_ids.filtered(
            lambda option: option.source_request_option_id == source_option
        )

        applicant = self.make_applicant()
        answer = self.Answer.sudo().create(
            {"applicant_id": applicant.id, "question_id": target.id}
        )
        answer_line = self.env["pr.recruitment.answer.line"].sudo().create(
            {"answer_id": answer.id}
        )
        cell = self.env["pr.recruitment.answer.cell"].sudo().create(
            {
                "line_id": answer_line.id,
                "column_id": target_column.id,
                "column_option_id": target_option.id,
                "raw_value": str(target_option.id),
            }
        )

        original_column_id = target_column.id
        original_option_id = target_option.id
        source_column.write({"name": "Renamed Level"})
        source_option.write({"name": "Renamed Junior"})
        source.copy_to_job(self.job)
        self.assertEqual(target_column.id, original_column_id)
        self.assertEqual(target_column.name, "Renamed Level")
        self.assertEqual(target_option.id, original_option_id)
        self.assertEqual(cell.column_id, target_column)
        self.assertEqual(cell.column_option_id, target_option)

        source_column.write({"column_type": "char"})
        source.copy_to_job(self.job)
        target.invalidate_recordset()
        old_column = self.env["pr.recruitment.question.column"].browse(
            original_column_id
        )
        replacement = target.line_column_ids.filtered(
            lambda column: column.source_request_column_id == source_column
        )
        self.assertFalse(old_column.active)
        self.assertFalse(old_column.source_request_column_id)
        self.assertEqual(cell.column_id, old_column)
        self.assertTrue(replacement.active)
        self.assertEqual(replacement.column_type, "char")
        self.assertNotEqual(replacement.id, old_column.id)

    def test_removed_source_column_is_archived_on_job(self):
        request_record = self.make_request()
        source = self.make_question(
            "one2many",
            request_record=request_record,
            columns=[
                {"name": "Keep", "column_type": "char"},
                {"name": "Remove", "column_type": "char"},
            ],
        )
        source.copy_to_job(self.job)
        target = self.Question.search(
            [("job_id", "=", self.job.id), ("source_request_question_id", "=", source.id)]
        )
        removed_source = source.line_column_ids.filtered(
            lambda column: column.name == "Remove"
        )
        removed_target = target.line_column_ids.filtered(
            lambda column: column.source_request_column_id == removed_source
        )
        removed_source.unlink()
        source.copy_to_job(self.job)
        self.assertFalse(removed_target.active)
        self.assertFalse(removed_target.source_request_column_id)

    def test_incompatible_answer_type_creates_new_live_question(self):
        request_record = self.make_request()
        source = self.make_question("char", request_record=request_record)
        source.copy_to_job(self.job)
        old_target = self.Question.search(
            [("job_id", "=", self.job.id), ("source_request_question_id", "=", source.id)]
        )
        self.make_answer(self.make_applicant(), old_target, "historical")

        source.write({"answer_type": "integer"})
        source.copy_to_job(self.job)
        new_target = self.Question.search(
            [("job_id", "=", self.job.id), ("source_request_question_id", "=", source.id)]
        )
        self.assertFalse(old_target.active)
        self.assertFalse(old_target.source_request_question_id)
        self.assertTrue(new_target.active)
        self.assertEqual(new_target.answer_type, "integer")
        self.assertNotEqual(new_target, old_target)

    def test_approved_request_changes_sync_automatically(self):
        request_record = self.make_request(state="approved")
        source = self.make_question("char", request_record=request_record)
        target = self.Question.search(
            [("job_id", "=", self.job.id), ("source_request_question_id", "=", source.id)]
        )
        self.assertTrue(target)
        source.write({"name": "Updated Approved Question"})
        self.assertEqual(target.name, "Updated Approved Question")

    def test_unanswered_selection_can_be_reconfigured_without_transient_failure(self):
        request_record = self.make_request()
        source = self.make_question("selection", request_record=request_record)
        source.copy_to_job(self.job)
        target = self.Question.search(
            [("job_id", "=", self.job.id), ("source_request_question_id", "=", source.id)]
        )

        source.write({"answer_type": "integer", "criterion_type": "none"})
        source.copy_to_job(self.job)

        self.assertEqual(target.answer_type, "integer")
        self.assertFalse(target.option_ids)
        self.assertTrue(target.active)

    def test_approved_request_core_field_rules_synchronize_to_job(self):
        request_record = self.make_request(state="approved")
        country = self.env["res.country"].search([], limit=1)
        degree = self.env["hr.recruitment.degree"].create(
            {"name": self.unique_name("Request Degree"), "sequence": 30}
        )

        request_record.write(
            {
                "core_location_rule": "contains",
                "core_location_values": "Jubail",
                "core_nationality_rule": "allowed",
                "core_nationality_ids": [Command.set(country.ids)],
                "core_education_rule": "minimum",
                "core_minimum_education_id": degree.id,
                "core_experience_rule": "minimum",
                "core_experience_minimum": 3,
                "core_notice_period_rule": "maximum",
                "core_notice_period_maximum": 45,
                "core_salary_rule": "maximum",
                "core_salary_maximum": 12000,
                "core_iqama_rule": "required",
            }
        )

        self.assertEqual(self.job.core_location_rule, "contains")
        self.assertEqual(self.job.core_location_values, "Jubail")
        self.assertEqual(self.job.core_nationality_ids, country)
        self.assertEqual(self.job.core_education_rule, "minimum")
        self.assertEqual(self.job.core_minimum_education_id, degree)
        self.assertEqual(self.job.core_experience_rule, "minimum")
        self.assertEqual(self.job.core_experience_minimum, 3)
        self.assertEqual(self.job.core_notice_period_rule, "maximum")
        self.assertEqual(self.job.core_notice_period_maximum, 45)
        self.assertEqual(self.job.core_salary_rule, "maximum")
        self.assertEqual(self.job.core_salary_maximum, 12000)
        self.assertEqual(self.job.core_iqama_rule, "required")


@tagged("post_install", "-at_install")
class TestQuestionSecurity(ScreeningCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        internal_group = cls.env.ref("base.group_user")
        recruitment_group = cls.env.ref(
            "hr_recruitment.group_hr_recruitment_user"
        )
        cls.owner_user = cls.env["res.users"].create(
            {
                "name": "Question Owner",
                "login": "screening.question.owner",
                "groups_id": [Command.set(internal_group.ids)],
            }
        )
        cls.other_user = cls.env["res.users"].create(
            {
                "name": "Other Requester",
                "login": "screening.other.requester",
                "groups_id": [Command.set(internal_group.ids)],
            }
        )
        cls.recruiter_user = cls.env["res.users"].create(
            {
                "name": "Recruitment User",
                "login": "screening.recruiter",
                "groups_id": [Command.set((internal_group | recruitment_group).ids)],
            }
        )

    def make_request_for(self, user, state="draft"):
        return self.env["hr.recruitment.request"].create(
            {
                "name": self.unique_name("SEC-REQ"),
                "requested_by_id": user.id,
                "requested_employees": 1,
                "job_id": self.job.id,
                "state": state,
            }
        )

    def test_requester_only_sees_questions_from_owned_requests(self):
        own_request = self.make_request_for(self.owner_user)
        other_request = self.make_request_for(self.other_user)
        own_question = self.make_question("char", request_record=own_request)
        other_question = self.make_question("char", request_record=other_request)

        visible = self.Question.with_user(self.owner_user).search(
            [("id", "in", (own_question | other_question).ids)]
        )
        self.assertEqual(visible, own_question)
        with self.assertRaises(AccessError):
            other_question.with_user(self.owner_user).check_access_rule("read")

    def test_recruiter_sees_all_request_and_job_questions(self):
        owner_request = self.make_request_for(self.owner_user)
        request_question = self.make_question("char", request_record=owner_request)
        job_question = self.make_question("char")
        visible = self.Question.with_user(self.recruiter_user).search(
            [("id", "in", (request_question | job_question).ids)]
        )
        self.assertEqual(set(visible.ids), set((request_question | job_question).ids))

    def test_owner_edit_on_approved_request_synchronizes_with_internal_privilege(self):
        request_record = self.make_request_for(self.owner_user, state="approved")
        source = self.make_question("char", request_record=request_record)
        target = self.Question.sudo().search(
            [("job_id", "=", self.job.id), ("source_request_question_id", "=", source.id)]
        )

        source.with_user(self.owner_user).write({"name": "Owner synchronized update"})

        self.assertEqual(target.name, "Owner synchronized update")
