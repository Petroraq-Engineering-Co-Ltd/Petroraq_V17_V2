import base64
from datetime import date
from unittest.mock import patch

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
