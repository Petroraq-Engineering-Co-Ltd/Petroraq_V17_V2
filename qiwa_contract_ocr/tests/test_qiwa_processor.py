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
