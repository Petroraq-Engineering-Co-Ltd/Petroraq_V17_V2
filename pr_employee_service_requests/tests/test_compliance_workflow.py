import base64
from datetime import date
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestEmployeeComplianceWorkflow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create({
            "name": "Compliance Workflow Employee",
            "identification_id": "TEST-IQAMA-001",
        })
        self_relation = cls.env.ref(
            "pr_hr.employee_dependent_relationship_self",
            raise_if_not_found=False,
        )
        if not self_relation:
            cls.env["hr.employee.dependent.relation"].create({"name": "Self"})

    def _create_request(self, request_type, **extra_vals):
        vals = {
            "request_type": request_type,
            "employee_id": self.employee.id,
            "company_id": self.env.company.id,
            "iqama_no": self.employee.identification_id,
            "reason": "Compliance record test",
        }
        vals.update(extra_vals)
        return self.env["pr.employee.service.request"].create(vals)

    def _get_destination_country(self):
        return (
            self.env.ref("base.us", raise_if_not_found=False)
            or self.env["res.country"].search([("code", "=", "US")], limit=1)
            or self.env["res.country"].create({"name": "United States", "code": "US"})
        )

    def _get_saudi_country(self):
        return (
            self.env.ref("base.sa", raise_if_not_found=False)
            or self.env["res.country"].search([("code", "=", "SA")], limit=1)
            or self.env["res.country"].create({"name": "Saudi Arabia", "code": "SA"})
        )

    def _create_open_contract(self, employee=None, date_start=date(2098, 1, 1), benefit_type="executive"):
        employee = employee or self.employee
        return self.env["hr.contract"].create({
            "name": "Exit Re-entry Entitlement Contract",
            "employee_id": employee.id,
            "company_id": self.env.company.id,
            "date_start": date_start,
            "joining_date": date_start,
            "contract_employment_type": "employment",
            "wage": 1.0,
            "state": "open",
            "exit_reentry_benefit_type": benefit_type,
        })

    def _create_saudi_employee(self):
        return self.env["hr.employee"].create({
            "name": "Saudi Compliance Employee",
            "identification_id": "SAUDI-NATIONAL-001",
            "country_id": self._get_saudi_country().id,
        })

    def test_new_iqama_creates_record_without_payment_or_approval(self):
        request = self._create_request(
            "iqama_new",
            service_from_date=date(2099, 1, 1),
            service_to_date=date(2099, 12, 31),
            service_expiry_date=date(2099, 12, 31),
            work_permit_expiry_date=date(2099, 12, 31),
            place_of_issue="Riyadh",
            visa_number="TEST-WP-001",
            iqama_profession="Engineer",
            issue_date=date(2099, 1, 1),
        )
        attachment = self.env["ir.attachment"].create({
            "name": "new-iqama.pdf",
            "datas": base64.b64encode(b"new iqama"),
            "mimetype": "application/pdf",
        })
        request.attachment_ids = [(6, 0, attachment.ids)]

        request.action_submit()

        self.assertEqual(request.state, "issued")
        self.assertTrue(request.iqama_id)
        self.assertTrue(request.iqama_line_id)
        self.assertTrue(request.work_permit_id)
        self.assertEqual(request.iqama_line_id.amount, 0.0)
        self.assertEqual(request.work_permit_id.work_permit_fees, 0.0)
        self.assertEqual(request.work_permit_id.payment_state, "draft")
        self.assertFalse(request.payment_request_id)
        self.assertFalse(request.bank_payment_id)
        copied_attachment = self.env["ir.attachment"].search([
            ("res_model", "=", request.iqama_id._name),
            ("res_id", "=", request.iqama_id.id),
            ("name", "=", attachment.name),
        ])
        self.assertTrue(copied_attachment)
        work_permit_attachment = self.env["ir.attachment"].search([
            ("res_model", "=", request.work_permit_id._name),
            ("res_id", "=", request.work_permit_id.id),
            ("name", "=", attachment.name),
        ])
        self.assertTrue(work_permit_attachment)

    def test_new_medical_insurance_creates_record_without_payment(self):
        request = self._create_request(
            "medical_insurance_new",
            service_from_date=date(2099, 1, 1),
            service_to_date=date(2099, 12, 31),
            service_expiry_date=date(2099, 12, 31),
            insurance_company="Test Insurance",
            insurance_category="A",
        )

        request.action_submit()

        self.assertEqual(request.state, "issued")
        self.assertTrue(request.insurance_id)
        self.assertTrue(request.insurance_line_id)
        self.assertEqual(request.insurance_line_id.amount, 0.0)
        self.assertFalse(request.payment_request_id)
        self.assertFalse(request.bank_payment_id)

    def test_work_permit_fallback_opens_combined_iqama_renewal(self):
        self.env["hr.employee.iqama"].create({
            "name": "Existing Iqama",
            "employee_id": self.employee.id,
            "identification_id": self.employee.identification_id,
            "expiry_date": date(2098, 12, 31),
            "state": "valid",
        })
        work_permit = self.env["hr.work.permit"].create({
            "name": "Existing Work Permit",
            "employee_id": self.employee.id,
            "visa_number": "TEST-WP-RENEW",
            "iqama_profession": "Engineer",
            "work_permit_fees": 0.0,
            "iqama_issuance_date": date(2098, 1, 1),
            "iqama_expiry_date": date(2098, 12, 31),
            "work_permit_expiry_date": date(2098, 12, 31),
            "state": "issued",
        })

        action = work_permit.action_renew()

        self.assertEqual(action["res_model"], "pr.employee.service.request")
        self.assertEqual(action["context"]["default_request_type"], "iqama_renewal")
        self.assertEqual(action["context"]["default_work_permit_id"], work_permit.id)
        self.assertEqual(action["context"]["default_service_from_date"], date(2099, 1, 1))

    def test_separate_work_permit_request_types_are_retired(self):
        request_types = dict(
            self.env["pr.employee.service.request"]._fields["request_type"].selection
        )
        self.assertNotIn("work_permit_new", request_types)
        self.assertNotIn("work_permit_renewal", request_types)

    def test_saudi_employee_cannot_create_iqama_or_exit_reentry_request(self):
        saudi_employee = self._create_saudi_employee()

        with self.assertRaises(ValidationError):
            self.env["pr.employee.service.request"].create({
                "request_type": "iqama_new",
                "employee_id": saudi_employee.id,
                "company_id": self.env.company.id,
                "iqama_no": saudi_employee.identification_id,
                "reason": "Saudi employees do not need Iqama",
            })

        with self.assertRaises(ValidationError):
            self.env["pr.employee.service.request"].create({
                "request_type": "exit_reentry",
                "employee_id": saudi_employee.id,
                "company_id": self.env.company.id,
                "reason": "Saudi employees do not need exit re-entry",
            })

    def test_saudi_employee_cannot_create_iqama_or_work_permit_record(self):
        saudi_employee = self._create_saudi_employee()

        with self.assertRaises(ValidationError):
            self.env["hr.employee.iqama"].create({
                "name": "Saudi Iqama",
                "employee_id": saudi_employee.id,
                "identification_id": saudi_employee.identification_id,
                "expiry_date": date(2099, 12, 31),
            })

        with self.assertRaises(ValidationError):
            self.env["hr.work.permit"].create({
                "name": "Saudi Work Permit",
                "employee_id": saudi_employee.id,
                "visa_number": "SAUDI-WP-001",
                "iqama_profession": "Engineer",
                "work_permit_fees": 0.0,
                "iqama_issuance_date": date(2099, 1, 1),
                "iqama_expiry_date": date(2099, 12, 31),
                "work_permit_expiry_date": date(2099, 12, 31),
            })

    def test_iqama_renewal_keeps_moi_and_mol_as_separate_payment_lines(self):
        request = self._create_request(
            "iqama_renewal",
            moi_fee_amount=40.0,
            mol_fee_amount=60.0,
        )

        payment_lines = request._prepare_payment_request_lines()

        self.assertEqual([line[2]["amount"] for line in payment_lines], [40.0, 60.0])
        self.assertEqual(request._get_payment_amount(), 100.0)

    def test_renewal_submits_directly_to_hr_manager(self):
        existing_iqama = self.env["hr.employee.iqama"].create({
            "name": "Existing Iqama",
            "employee_id": self.employee.id,
            "identification_id": self.employee.identification_id,
            "expiry_date": date(2098, 12, 31),
            "state": "valid",
        })
        request = self._create_request(
            "iqama_renewal",
            iqama_id=existing_iqama.id,
            moi_fee_amount=40.0,
            mol_fee_amount=60.0,
            service_from_date=date(2099, 1, 1),
            service_to_date=date(2099, 12, 31),
            service_expiry_date=date(2099, 12, 31),
        )

        with (
            patch.object(type(request), "_check_before_submit", autospec=True),
            patch.object(type(request), "_notify_group", autospec=True),
        ):
            request.action_submit()

        self.assertEqual(request.state, "hr_manager_approval")
        self.assertEqual(request.requested_amount, 100.0)
        self.assertEqual(request._get_payment_amount(), 100.0)
        self.assertFalse(request.hr_supervisor_approved_by_id)

    def test_md_approval_uses_automatic_renewal_bpv(self):
        request = self._create_request(
            "iqama_renewal",
            state="md_approval",
            moi_fee_amount=40.0,
            mol_fee_amount=60.0,
            iqama_profession="Engineer",
            service_expiry_date=date(2099, 12, 31),
        )

        with (
            patch.object(type(request), "_check_before_md_approval", autospec=True),
            patch.object(
                type(request),
                "_create_renewal_bpv",
                autospec=True,
                return_value=request,
            ) as create_bpv,
        ):
            request.action_md_approve()

        self.assertEqual(request.state, "payment_approval")
        self.assertEqual(request.md_approved_by_id, self.env.user)
        create_bpv.assert_called_once()

    def test_company_exit_reentry_without_current_contract_switches_to_self(self):
        country = self._get_destination_country()
        request = self._create_request(
            "exit_reentry",
            payment_responsibility="company",
            destination_country_id=country.id,
            travel_date=date(2099, 1, 1),
            return_date=date(2099, 1, 10),
        )

        with patch.object(type(request), "_notify_group", autospec=True):
            request.action_submit()

        self.assertEqual(request.payment_responsibility, "self")
        self.assertEqual(request.state, "hr_manager_approval")
        self.assertFalse(request.payment_request_id)

    def test_self_exit_reentry_approval_creates_no_payment_artifacts(self):
        country = self._get_destination_country()
        request = self._create_request(
            "exit_reentry",
            payment_responsibility="self",
            destination_country_id=country.id,
            travel_date=date(2099, 1, 1),
            return_date=date(2099, 1, 10),
        )

        with patch.object(type(request), "_notify_group", autospec=True):
            request.action_submit()
        request.action_hr_manager_approve()

        self.assertEqual(request.state, "paid")
        self.assertEqual(request.approved_amount, 0.0)
        self.assertFalse(request.payment_request_id)
        self.assertFalse(request.cash_payment_id)
        self.assertFalse(request.bank_payment_id)

        request.visa_number = "SELF-EXIT-001"
        request.action_issue()
        self.assertEqual(request.state, "issued")

    def test_multiple_entry_exit_reentry_is_always_self_paid(self):
        country = self._get_destination_country()
        request = self._create_request(
            "exit_reentry",
            payment_responsibility="company",
            exit_reentry_entry_type="multiple",
            destination_country_id=country.id,
            travel_date=date(2099, 1, 1),
            return_date=date(2099, 1, 10),
        )

        self.assertEqual(request.payment_responsibility, "self")

        with patch.object(type(request), "_notify_group", autospec=True):
            request.action_submit()
        request.action_hr_manager_approve()

        self.assertEqual(request.state, "paid")
        self.assertEqual(request.approved_amount, 0.0)
        self.assertFalse(request.payment_request_id)
        self.assertFalse(request.cash_payment_id)
        self.assertFalse(request.bank_payment_id)

    def test_historical_company_exit_reentry_consumes_entitlement_without_payment(self):
        self._create_open_contract(date_start=date(2098, 1, 1), benefit_type="executive")
        country = self._get_destination_country()
        historical = self._create_request(
            "exit_reentry",
            payment_responsibility="company",
            exit_reentry_entry_type="single",
            exit_reentry_historical_company_paid=True,
            request_date=date(2098, 12, 1),
            destination_country_id=country.id,
            travel_date=date(2098, 12, 15),
            return_date=date(2098, 12, 25),
            visa_number="OLD-COMPANY-EXIT-001",
            issue_date=date(2098, 12, 1),
        )

        historical.action_submit()

        self.assertEqual(historical.state, "issued")
        self.assertEqual(historical.payment_responsibility, "company")
        self.assertEqual(historical.approved_amount, 0.0)
        self.assertFalse(historical.payment_request_id)
        self.assertFalse(historical.cash_payment_id)
        self.assertFalse(historical.bank_payment_id)

        new_request = self._create_request(
            "exit_reentry",
            payment_responsibility="company",
            request_date=date(2099, 1, 1),
            destination_country_id=country.id,
            travel_date=date(2099, 1, 15),
            return_date=date(2099, 1, 25),
        )

        self.assertEqual(new_request.payment_responsibility, "self")
        self.assertIn("already used", new_request.exit_reentry_eligibility_message)

    def test_self_iqama_renewal_issues_without_payment(self):
        existing_iqama = self.env["hr.employee.iqama"].create({
            "name": "Existing Self Paid Iqama",
            "employee_id": self.employee.id,
            "identification_id": self.employee.identification_id,
            "expiry_date": date(2098, 12, 31),
            "state": "valid",
        })
        request = self._create_request(
            "iqama_renewal",
            payment_responsibility="self",
            iqama_id=existing_iqama.id,
            service_from_date=date(2099, 1, 1),
            service_to_date=date(2099, 12, 31),
            service_expiry_date=date(2099, 12, 31),
            work_permit_expiry_date=date(2099, 12, 31),
            iqama_profession="Engineer",
            issue_date=date(2099, 1, 1),
        )

        with patch.object(type(request), "_notify_group", autospec=True):
            request.action_submit()
        request.action_hr_manager_approve()

        self.assertEqual(request.state, "issued")
        self.assertTrue(request.iqama_line_id)
        self.assertEqual(request.iqama_line_id.amount, 0.0)
        self.assertFalse(request.payment_request_id)
        self.assertFalse(request.bank_payment_id)
