from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestQiwaProcessor(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.applicant = cls.env["hr.applicant"].create({
            "name": "Qiwa Arabic Name Test",
            "partner_name": "BODOUR FELIMBAN",
        })
        cls.processor = cls.env["qiwa.contract.processor"].new({
            "applicant_id": cls.applicant.id,
        })

    def _get_saudi_country(self):
        return (
            self.env.ref("base.sa", raise_if_not_found=False)
            or self.env["res.country"].search([("code", "=", "SA")], limit=1)
            or self.env["res.country"].create({"name": "Saudi Arabia", "code": "SA"})
        )

    def test_arabic_label_value_is_not_discarded(self):
        self.assertEqual(
            self.processor._clean_label_value("بدور ممدوح احمد فليمبان"),
            "بدور ممدوح احمد فليمبان",
        )

    def test_applicant_name_replaces_unreliable_arabic_pdf_name(self):
        self.assertEqual(
            self.processor._resolve_employee_name("اں لم احمد ممدوح دور"),
            "BODOUR FELIMBAN",
        )

    def test_arabic_only_qiwa_contract_parses_with_applicant_name(self):
        text = """
1. .1
Contract number: 35247461
2. .2
Establishment Name: Petroraq Engineering Co. Ltd.
3. .3
Employee name: بدور ممدوح احمد فليمبان : العامل اسم
Nationality: Saudi
ID no.: 1114361767
4. .4
Occupation: Human Resources Clerk
"""

        data = self.processor._parse_qiwa_data(text)

        self.assertEqual(data["employee_name"], "BODOUR FELIMBAN")
        self.assertEqual(data["contract_number"], "35247461")
        self.assertEqual(data["iqama_no"], "1114361767")

    def test_saudi_employee_onboarding_is_completed_without_iqama_work_permit_tasks(self):
        employee = self.env["hr.employee"].create({
            "name": "Saudi Onboarding Employee",
            "country_id": self._get_saudi_country().id,
            "identification_id": "SAUDI-ONBOARD-001",
        })

        onboarding = self.env["hr.applicant.onboarding"].create({
            "name": employee.name,
            "employee_id": employee.id,
            "hire_type": "local",
        })

        self.assertEqual(onboarding.state, "completed")
        self.assertFalse(onboarding.onboarding_task_initialized)

        onboarding.action_start_onboarding_reminders()

        self.assertEqual(onboarding.state, "completed")
        task_types = set(onboarding.checklist_ids.mapped("task_type"))
        self.assertIn("national_id_copy", task_types)
        self.assertNotIn("iqama_copy", task_types)
        self.assertNotIn("iqama_transfer_completion", task_types)
        self.assertNotIn("work_permit_issuance", task_types)

    def test_saudi_employee_cannot_create_onboarding_iqama_or_work_permit_request(self):
        employee = self.env["hr.employee"].create({
            "name": "Saudi Onboarding Compliance Employee",
            "country_id": self._get_saudi_country().id,
            "identification_id": "SAUDI-ONBOARD-002",
        })
        onboarding = self.env["hr.applicant.onboarding"].create({
            "name": employee.name,
            "employee_id": employee.id,
            "hire_type": "local",
        })

        with self.assertRaises(ValidationError):
            self.env["hr.onboarding.compliance.request"].sudo().create({
                "onboarding_id": onboarding.id,
                "employee_id": employee.id,
                "employee_category": "saudi",
                "request_type": "work_permit_issuance",
            })
