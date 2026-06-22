from odoo import Command
from odoo.tests.common import TransactionCase


class ScreeningCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Question = cls.env["pr.recruitment.question"]
        cls.Answer = cls.env["pr.recruitment.answer"]
        cls._name_sequence = 0
        cls.job = cls.env["hr.job"].create({"name": "Screening Test Job"})
        cls.other_job = cls.env["hr.job"].create(
            {"name": "Other Screening Test Job"}
        )

    @classmethod
    def unique_name(cls, prefix):
        cls._name_sequence += 1
        return "%s %s" % (prefix, cls._name_sequence)

    def make_question(
        self,
        answer_type="char",
        *,
        job=None,
        request_record=None,
        required=False,
        options=None,
        columns=None,
        relation_model=False,
        active=True,
    ):
        values = {
            "name": self.unique_name("Question"),
            "answer_type": answer_type,
            "required": required,
            "active": active,
            "criterion_type": "none",
        }
        if request_record:
            values["request_id"] = request_record.id
        else:
            values["job_id"] = (job or self.job).id
        if relation_model:
            values["relation_model"] = relation_model
        if answer_type in ("selection", "many2one"):
            values["option_ids"] = [
                Command.create(option_values)
                for option_values in (options or self.default_options(answer_type))
            ]
        if answer_type == "one2many":
            values["line_column_ids"] = [
                Command.create(column_values)
                for column_values in (columns or [{"name": "Value", "column_type": "char"}])
            ]
        return self.Question.create(values)

    def default_options(self, answer_type):
        if answer_type == "selection":
            return [
                {"name": self.unique_name("Low"), "sequence": 10},
                {"name": self.unique_name("High"), "sequence": 20},
            ]
        countries = self.env["res.country"].search([], limit=2)
        return [
            {
                "name": country.display_name,
                "sequence": index * 10,
                "country_id": country.id,
            }
            for index, country in enumerate(countries, start=1)
        ]

    def set_criterion(self, question, criterion_type, **values):
        write_values = dict(values, criterion_type=criterion_type)
        if criterion_type not in ("none", "line_count_max"):
            write_values.setdefault("required", True)
        question.write(write_values)
        return question

    def make_applicant(self, job=None, **values):
        applicant_values = {
            "name": self.unique_name("Applicant"),
            "partner_name": self.unique_name("Candidate"),
            "job_id": (job or self.job).id,
            "email_from": "%s@example.com" % self.unique_name("candidate").replace(" ", "").lower(),
            "partner_phone": "+966 50 000 0000",
        }
        applicant_values.update(values)
        return self.env["hr.applicant"].create(applicant_values)

    def make_answer(self, applicant, question, raw_value):
        values, error = question._prepare_answer(raw_value)
        self.assertFalse(error)
        values.update(
            {"applicant_id": applicant.id, "question_id": question.id}
        )
        return self.Answer.sudo().create(values)
