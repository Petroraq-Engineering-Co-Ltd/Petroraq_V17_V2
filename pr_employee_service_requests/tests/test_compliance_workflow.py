import base64
from datetime import date
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import Form, TransactionCase


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

    def test_payment_voucher_status_accepts_rejected_vouchers(self):
        """Opening a request linked to a rejected CPV/BPV must not crash."""
        selection = dict(
            self.env["pr.employee.service.request"]
            ._fields["payment_voucher_state"]
            ._description_selection(self.env)
        )
        self.assertEqual(selection.get("reject"), "Rejected")

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

    def _post_generated_voucher(self, voucher, accounts_user, finance_user):
        """Drive a draft CPV or BPV generated from a payment request through posting."""
        voucher.with_user(accounts_user).action_submit()
        voucher.with_user(accounts_user).action_approve_remaining_lines()
        voucher.with_user(accounts_user).action_finance_approve()
        voucher.with_user(finance_user).action_post()

    def test_new_iqama_requires_approval_before_hr_issue(self):
        budget, cost_center, expense_account = self._create_budget_and_expense_account()
        cash_bank_account = self.env["account.account"].create({
            "name": "Compliance New Iqama Bank",
            "code": "PRCOMPIQBNK",
            "account_type": "asset_cash",
            "company_id": self.env.company.id,
        })
        manager_user = self._create_role_user("iqama.new.mgr", [])
        hr_sup_user = self._create_role_user("iqama.new.hrsup", ["pr_hr.group_hr_supervisor"])
        hr_mgr_user = self._create_role_user("iqama.new.hrmgr", ["pr_hr.group_hr_manager"])
        accounts_user = self._create_role_user("iqama.new.acc", ["account.group_account_manager"])
        finance_user = self._create_role_user("iqama.new.fin", ["pr_account.custom_group_accounting_manager"])
        md_user = self._create_role_user("iqama.new.md", ["pr_hr.group_hr_md"])

        manager_emp = self.env["hr.employee"].create({
            "name": "New Iqama Manager",
            "user_id": manager_user.id,
        })
        non_saudi_country = self._get_destination_country()
        employee = self.env["hr.employee"].create({
            "name": "New Iqama Employee",
            "parent_id": manager_emp.id,
            "country_id": non_saudi_country.id,
            "identification_id": "TEST-IQAMA-NEW-FIN-01",
        })

        attachment = self.env["ir.attachment"].create({
            "name": "new-iqama.pdf",
            "datas": base64.b64encode(b"new iqama"),
            "mimetype": "application/pdf",
        })
        request = self._create_request(
            "iqama_new",
            employee_id=employee.id,
            iqama_no=employee.identification_id,
            payment_responsibility="self",
            moi_fee_amount=400.0,
            mol_fee_amount=600.0,
            expense_bucket_id=budget.id,
            cost_center_id=cost_center.id,
            expense_account_id=expense_account.id,
            service_from_date=date(2099, 1, 1),
            service_to_date=date(2099, 12, 31),
            service_expiry_date=date(2099, 12, 31),
            work_permit_expiry_date=date(2099, 12, 31),
            place_of_issue="Riyadh",
            visa_number="TEST-WP-001",
            iqama_profession="Engineer",
            issue_date=date(2099, 1, 1),
            attachment_ids=[(6, 0, attachment.ids)],
        )

        self.assertEqual(request.payment_responsibility, "company")
        self.assertEqual(request.requested_amount, 1000.0)

        with patch.object(type(request), "_notify_users", autospec=True):
            request.action_submit()

        self.assertEqual(request.state, "employee_manager_approval")
        self.assertFalse(request.iqama_id)
        self.assertFalse(request.iqama_line_id)
        self.assertFalse(request.work_permit_id)

        with patch.object(type(request), "_notify_group", autospec=True):
            request.with_user(manager_user).action_employee_manager_approve()
            self.assertEqual(request.state, "hr_supervisor_approval")
            request.with_user(hr_sup_user).action_hr_supervisor_approve()
            self.assertEqual(request.state, "hr_manager_approval")
            request.with_user(hr_mgr_user).action_hr_manager_approve()

        self.assertEqual(request.state, "accounts_approval")
        self.assertEqual(request.approved_amount, 1000.0)
        self.assertTrue(request.with_user(accounts_user).is_current_user_financial_approver)

        with patch.object(type(request), "_notify_group", autospec=True):
            request.with_user(accounts_user).action_accounts_approve()

        self.assertEqual(request.state, "finance_approval")
        self.assertTrue(request.with_user(finance_user).is_current_user_financial_approver)

        with patch.object(type(request), "_notify_group", autospec=True):
            request.with_user(finance_user).action_finance_approve()

        self.assertEqual(request.state, "md_approval")
        with patch.object(type(self.env["pr.employee.payment.request"]), "_notify_accounts", autospec=True):
            request.with_user(md_user).action_md_approve()

        self.assertEqual(request.state, "payment_approval")
        self.assertEqual(request.approved_amount, 1000.0)
        self.assertTrue(request.payment_request_id)
        self.assertEqual(request.payment_request_id.state, "requested")
        self.assertEqual(request.payment_request_id.total_amount, 1000.0)
        self.assertEqual(request.payment_request_id.line_ids.mapped("amount"), [400.0, 600.0])
        self.assertFalse(request.iqama_id)

        with self.assertRaisesRegex(UserError, "Only paid employee service requests can be issued"):
            request.with_user(hr_mgr_user).action_issue()

        request.payment_request_id.with_user(accounts_user).write({
            "transfer_type": "bank",
            "pay_from_account_id": cash_bank_account.id,
        })
        request.payment_request_id.with_user(accounts_user).action_create_payment_voucher()
        self.assertTrue(request.bank_payment_id)
        self.assertEqual(request.payment_request_id.state, "voucher_created")
        self.assertEqual(request.bank_payment_id.bank_payment_line_ids.mapped("total_amount"), [400.0, 600.0])

        self._post_generated_voucher(request.bank_payment_id, accounts_user, finance_user)
        self.assertEqual(request.state, "paid")
        self.assertTrue(request.paid_date)

        request.with_user(hr_mgr_user).action_issue()

        self.assertEqual(request.state, "issued")
        self.assertTrue(request.iqama_id)
        self.assertTrue(request.iqama_line_id)
        self.assertTrue(request.work_permit_id)
        self.assertEqual(request.iqama_line_id.amount, 1000.0)
        self.assertEqual(request.iqama_line_id.payment_request_id, request.payment_request_id)
        self.assertEqual(request.iqama_line_id.bank_payment_id, request.bank_payment_id)
        self.assertEqual(request.work_permit_id.work_permit_fees, 1000.0)
        self.assertEqual(request.work_permit_id.payment_state, "paid")
        self.assertEqual(request.work_permit_id.bank_payment_id, request.bank_payment_id)
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

    def test_new_medical_insurance_requires_approval_before_hr_issue(self):
        budget, cost_center, expense_account = self._create_budget_and_expense_account()
        cash_bank_account = self.env["account.account"].create({
            "name": "Compliance New Insurance Bank",
            "code": "PRCOMPINSBNK",
            "account_type": "asset_cash",
            "company_id": self.env.company.id,
        })
        manager_user = self._create_role_user("ins.new.mgr", [])
        hr_sup_user = self._create_role_user("ins.new.hrsup", ["pr_hr.group_hr_supervisor"])
        hr_mgr_user = self._create_role_user("ins.new.hrmgr", ["pr_hr.group_hr_manager"])
        accounts_user = self._create_role_user("ins.new.acc", ["account.group_account_manager"])
        finance_user = self._create_role_user("ins.new.fin", ["pr_account.custom_group_accounting_manager"])
        md_user = self._create_role_user("ins.new.md", ["pr_hr.group_hr_md"])

        manager_emp = self.env["hr.employee"].create({
            "name": "New Insurance Manager",
            "user_id": manager_user.id,
        })
        employee = self.env["hr.employee"].create({
            "name": "New Insurance Employee",
            "parent_id": manager_emp.id,
            "identification_id": "TEST-INS-NEW-FIN-01",
        })
        attachment = self.env["ir.attachment"].create({
            "name": "new-insurance.pdf",
            "datas": base64.b64encode(b"new insurance"),
            "mimetype": "application/pdf",
        })
        request = self._create_request(
            "medical_insurance_new",
            employee_id=employee.id,
            iqama_no=employee.identification_id,
            payment_responsibility="self",
            requested_amount=500.0,
            expense_bucket_id=budget.id,
            cost_center_id=cost_center.id,
            expense_account_id=expense_account.id,
            service_from_date=date(2099, 1, 1),
            service_to_date=date(2099, 12, 31),
            service_expiry_date=date(2099, 12, 31),
            insurance_company="Test Insurance",
            insurance_category="A",
            attachment_ids=[(6, 0, attachment.ids)],
        )

        self.assertEqual(request.payment_responsibility, "company")

        with patch.object(type(request), "_notify_users", autospec=True):
            request.action_submit()

        self.assertEqual(request.state, "employee_manager_approval")
        self.assertFalse(request.insurance_id)
        self.assertFalse(request.insurance_line_id)

        with patch.object(type(request), "_notify_group", autospec=True):
            request.with_user(manager_user).action_employee_manager_approve()
            request.with_user(hr_sup_user).action_hr_supervisor_approve()
            request.with_user(hr_mgr_user).action_hr_manager_approve()

        self.assertEqual(request.state, "accounts_approval")
        self.assertEqual(request.approved_amount, 500.0)
        self.assertTrue(request.with_user(accounts_user).is_current_user_financial_approver)

        with patch.object(type(request), "_notify_group", autospec=True):
            request.with_user(accounts_user).action_accounts_approve()

        self.assertEqual(request.state, "finance_approval")
        self.assertTrue(request.with_user(finance_user).is_current_user_financial_approver)

        with patch.object(type(request), "_notify_group", autospec=True):
            request.with_user(finance_user).action_finance_approve()

        self.assertEqual(request.state, "md_approval")
        with patch.object(type(self.env["pr.employee.payment.request"]), "_notify_accounts", autospec=True):
            request.with_user(md_user).action_md_approve()

        self.assertEqual(request.state, "payment_approval")
        self.assertEqual(request.approved_amount, 500.0)
        self.assertTrue(request.payment_request_id)
        self.assertEqual(request.payment_request_id.total_amount, 500.0)
        self.assertEqual(request.payment_request_id.line_ids.mapped("amount"), [500.0])
        self.assertFalse(request.insurance_id)

        with self.assertRaisesRegex(UserError, "Only paid employee service requests can be issued"):
            request.with_user(hr_mgr_user).action_issue()

        request.payment_request_id.with_user(accounts_user).write({
            "transfer_type": "cash",
            "pay_from_account_id": cash_bank_account.id,
        })
        request.payment_request_id.with_user(accounts_user).action_create_payment_voucher()
        self.assertTrue(request.cash_payment_id)
        self.assertEqual(request.payment_request_id.state, "voucher_created")

        self._post_generated_voucher(request.cash_payment_id, accounts_user, finance_user)
        self.assertEqual(request.state, "paid")

        request.with_user(hr_mgr_user).action_issue()

        self.assertEqual(request.state, "issued")
        self.assertTrue(request.insurance_id)
        self.assertTrue(request.insurance_line_id)
        self.assertEqual(request.insurance_line_id.amount, 500.0)
        self.assertEqual(request.insurance_line_id.payment_request_id, request.payment_request_id)

    def test_new_compliance_requests_costing_validations_and_write_sync(self):
        budget, cost_center, expense_account = self._create_budget_and_expense_account()
        non_saudi = self._get_destination_country()
        employee = self.env["hr.employee"].create({
            "name": "Compliance Validation Employee",
            "country_id": non_saudi.id,
            "identification_id": "TEST-VAL-001",
        })
        attachment = self.env["ir.attachment"].create({
            "name": "val-doc.pdf",
            "datas": base64.b64encode(b"doc"),
            "mimetype": "application/pdf",
        })

        with self.assertRaises(ValidationError):
            self._create_request(
                "iqama_new",
                employee_id=employee.id,
                iqama_no=employee.identification_id,
                payment_responsibility="self",
            )
        with self.assertRaises(ValidationError):
            self._create_request(
                "medical_insurance_new",
                employee_id=employee.id,
                iqama_no=employee.identification_id,
                payment_responsibility="self",
            )

        iqama_req = self._create_request(
            "iqama_new",
            employee_id=employee.id,
            iqama_no=employee.identification_id,
            moi_fee_amount=200.0,
            mol_fee_amount=300.0,
            service_from_date=date(2099, 1, 1),
            service_to_date=date(2099, 12, 31),
            service_expiry_date=date(2099, 12, 31),
            work_permit_expiry_date=date(2099, 12, 31),
            iqama_profession="Engineer",
            issue_date=date(2099, 1, 1),
            expense_bucket_id=budget.id,
            cost_center_id=cost_center.id,
            expense_account_id=expense_account.id,
        )
        self.assertEqual(iqama_req.requested_amount, 500.0)
        iqama_req.write({"moi_fee_amount": 250.0})
        self.assertEqual(iqama_req.requested_amount, 550.0)

        with self.assertRaisesRegex(UserError, "supporting document"):
            iqama_req.action_submit()

        iqama_req.attachment_ids = [(6, 0, attachment.ids)]
        iqama_req.expense_bucket_id = False
        with self.assertRaisesRegex(UserError, "approved Budget"):
            iqama_req.action_submit()

        iqama_req.expense_bucket_id = budget.id
        iqama_req.cost_center_id = False
        with self.assertRaisesRegex(UserError, "Cost Center"):
            iqama_req.action_submit()

        iqama_req.cost_center_id = cost_center.id
        iqama_req.expense_account_id = False
        with self.assertRaisesRegex(UserError, "Employee / Expense Account"):
            iqama_req.action_submit()

        ins_req = self._create_request(
            "medical_insurance_new",
            employee_id=employee.id,
            iqama_no=employee.identification_id,
            requested_amount=400.0,
            service_from_date=date(2099, 1, 1),
            service_to_date=date(2099, 12, 31),
            service_expiry_date=date(2099, 12, 31),
            insurance_company="Test Insurance",
            insurance_category="A",
            expense_bucket_id=budget.id,
            cost_center_id=cost_center.id,
            expense_account_id=expense_account.id,
        )
        with self.assertRaisesRegex(UserError, "supporting document"):
            ins_req.action_submit()

    def test_form_view_approval_ui_for_new_compliance_requests(self):
        arch = self.env["pr.employee.service.request"].get_view(view_type="form")["arch"]
        doc = etree.fromstring(arch)
        approvals_pages = doc.xpath("//notebook/page[@string='Approvals']")
        self.assertEqual(len(approvals_pages), 1)
        self.assertFalse(approvals_pages[0].get("invisible"))
        for button_name in ("action_accounts_approve", "action_finance_approve"):
            buttons = doc.xpath(f"//header/button[@name='{button_name}']")
            self.assertEqual(len(buttons), 1)
            invisible_expr = buttons[0].get("invisible") or ""
            self.assertNotIn("iqama_new", invisible_expr)
            self.assertNotIn("medical_insurance_new", invisible_expr)
            self.assertIn("payment_responsibility == 'self'", invisible_expr)
            self.assertIn("exit_reentry_historical_company_paid", invisible_expr)
        payment_groups = doc.xpath("//group[@string='Payment']")
        self.assertEqual(len(payment_groups), 1)
        payment_group_inv = payment_groups[0].get("invisible") or ""
        self.assertNotIn("iqama_new", payment_group_inv)
        self.assertNotIn("medical_insurance_new", payment_group_inv)
        approved_fields = payment_groups[0].xpath(".//field[@name='approved_amount']")
        self.assertEqual(len(approved_fields), 1)
        self.assertIn("iqama_new", approved_fields[0].get("invisible") or "")
        self.assertIn("iqama_renewal", approved_fields[0].get("invisible") or "")
        iqama_group = doc.xpath("//group[contains(@string, 'Iqama')]")[0]
        for fname in ("moi_fee_amount", "mol_fee_amount", "requested_amount"):
            fnode = iqama_group.xpath(f".//field[@name='{fname}']")[0]
            finv = fnode.get("invisible") or ""
            self.assertIn("iqama_new", finv)
            self.assertIn("iqama_renewal", finv)
        ins_group = doc.xpath("//group[@string='Medical Insurance Details']")[0]
        ins_amount = ins_group.xpath(".//field[@name='requested_amount']")[0]
        self.assertEqual(ins_amount.get("invisible"), "payment_responsibility == 'self'")
        resp_field = doc.xpath("//field[@name='payment_responsibility']")[0]
        self.assertNotIn("iqama_new", resp_field.get("invisible") or "")
        self.assertNotIn("medical_insurance_new", resp_field.get("invisible") or "")

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

        with self.assertRaisesRegex(ValidationError, "Saudi employees"):
            self.env["pr.employee.service.request"].create({
                "request_type": "iqama_new",
                "employee_id": saudi_employee.id,
                "company_id": self.env.company.id,
                "iqama_no": saudi_employee.identification_id,
                "moi_fee_amount": 100.0,
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

    def test_renewal_submits_to_employee_manager(self):
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

        self.assertEqual(request.state, "employee_manager_approval")
        self.assertEqual(request.requested_amount, 100.0)
        self.assertEqual(request._get_payment_amount(), 100.0)
        self.assertFalse(request.hr_supervisor_approved_by_id)

    def _create_budget_and_expense_account(self, planned_amount=5000.0):
        today = date.today()
        plan = self.env["account.analytic.plan"].create({
            "name": "Compliance Workflow Test Plan",
        })
        cost_center = self.env["account.analytic.account"].create({
            "name": "Compliance Workflow Test Cost Center",
            "plan_id": plan.id,
        })
        budget = self.env["crossovered.budget"].create({
            "name": "Compliance Workflow Test Budget",
            "date_from": today,
            "date_to": date(2099, 12, 31),
            "state": "validate",
            "user_id": self.env.user.id,
            "expense_type": "opex",
        })
        self.env["crossovered.budget.lines"].create({
            "crossovered_budget_id": budget.id,
            "analytic_account_id": cost_center.id,
            "date_from": budget.date_from,
            "date_to": budget.date_to,
            "planned_amount": planned_amount,
        })
        expense_account = self.env["account.account"].create({
            "name": "Compliance Test Expense Account",
            "code": "PRCOMPEXP01",
            "account_type": "expense",
            "company_id": self.env.company.id,
        })
        return budget, cost_center, expense_account

    def _create_role_user(self, login, group_xmlids):
        internal_group = self.env.ref("base.group_user")
        group_ids = [internal_group.id]
        for xmlid in group_xmlids:
            group = self.env.ref(xmlid)
            group_ids.append(group.id)
        return self.env["res.users"].with_context(no_reset_password=True).create({
            "name": login,
            "login": login,
            "email": f"{login}@example.test",
            "groups_id": [(6, 0, group_ids)],
        })

    def test_md_approval_auto_creates_payment_request_on_iqama_renewal(self):
        today = date.today()
        budget, cost_center, expense_account = self._create_budget_and_expense_account()
        md_user = self._create_role_user("iqama.md.test", ["pr_hr.group_hr_md"])
        accounts_user = self._create_role_user("iqama.accounts.test", ["account.group_account_manager"])
        request = self._create_request(
            "iqama_renewal",
            state="md_approval",
            payment_responsibility="company",
            moi_fee_amount=40.0,
            mol_fee_amount=60.0,
            iqama_profession="Engineer",
            service_from_date=today,
            service_to_date=date(2099, 12, 31),
            service_expiry_date=date(2099, 12, 31),
            expense_bucket_id=budget.id,
            cost_center_id=cost_center.id,
            expense_account_id=expense_account.id,
        )

        request.with_user(md_user).action_md_approve()

        self.assertEqual(request.state, "payment_approval")
        self.assertEqual(request.md_approved_by_id, md_user)
        self.assertEqual(request.approved_amount, 100.0)
        self.assertTrue(request.payment_request_id)
        self.assertEqual(request.payment_request_id.state, "requested")
        self.assertEqual(request.payment_request_state, "requested")
        self.assertEqual(request.payment_request_id.total_amount, 100.0)
        self.assertEqual(request.payment_request_id.line_ids.mapped("amount"), [40.0, 60.0])
        self.assertFalse(request.cash_payment_id)
        self.assertFalse(request.bank_payment_id)
        with self.assertRaises(UserError):
            request.with_user(accounts_user).action_create_payment_request()

    def test_md_approval_auto_creates_payment_request_on_medical_insurance_renewal(self):
        today = date.today()
        budget, cost_center, expense_account = self._create_budget_and_expense_account()
        md_user = self._create_role_user("med.md.test", ["pr_hr.group_hr_md"])
        request = self._create_request(
            "medical_insurance_renewal",
            state="md_approval",
            payment_responsibility="company",
            requested_amount=500.0,
            insurance_company="Test Insurance",
            insurance_category="A",
            service_from_date=today,
            service_to_date=date(2099, 12, 31),
            service_expiry_date=date(2099, 12, 31),
            expense_bucket_id=budget.id,
            cost_center_id=cost_center.id,
            expense_account_id=expense_account.id,
        )

        request.with_user(md_user).action_md_approve()

        self.assertEqual(request.state, "payment_approval")
        self.assertEqual(request.md_approved_by_id, md_user)
        self.assertEqual(request.approved_amount, 500.0)
        self.assertTrue(request.payment_request_id)
        self.assertEqual(request.payment_request_id.state, "requested")
        self.assertEqual(request.payment_request_id.total_amount, 500.0)
        self.assertEqual(request.payment_request_id.line_ids.mapped("amount"), [500.0])
        self.assertFalse(request.cash_payment_id)
        self.assertFalse(request.bank_payment_id)

    def test_create_payment_request_button_visibility_and_legacy_fallback(self):
        accounts_user = self._create_role_user("legacy.accounts.test", ["account.group_account_manager"])
        arch = (
            self.env["pr.employee.service.request"]
            .with_user(accounts_user)
            .get_view(view_type="form")["arch"]
        )
        doc = etree.fromstring(arch)
        buttons = doc.xpath("//header/button[@name='action_create_payment_request']")
        self.assertEqual(len(buttons), 1)
        invisible_expr = buttons[0].get("invisible") or ""
        for required_token in ("payment_request_id", "cash_payment_id", "bank_payment_id"):
            self.assertIn(required_token, invisible_expr)

        today = date.today()
        budget, cost_center, expense_account = self._create_budget_and_expense_account()
        legacy_request = self._create_request(
            "iqama_renewal",
            state="payment_approval",
            payment_responsibility="company",
            moi_fee_amount=40.0,
            mol_fee_amount=60.0,
            approved_amount=100.0,
            iqama_profession="Engineer",
            service_from_date=today,
            service_to_date=date(2099, 12, 31),
            service_expiry_date=date(2099, 12, 31),
            expense_bucket_id=budget.id,
            cost_center_id=cost_center.id,
            expense_account_id=expense_account.id,
        )

        self.assertFalse(legacy_request.payment_request_id)
        action = legacy_request.with_user(accounts_user).action_create_payment_request()
        self.assertEqual(action["res_model"], "pr.employee.payment.request")
        self.assertTrue(legacy_request.payment_request_id)
        self.assertEqual(legacy_request.payment_request_id.state, "requested")
        self.assertEqual(legacy_request.payment_request_id.total_amount, 100.0)

    def test_dependent_fee_submits_as_company_paid_hr_request(self):
        relation = self.env["hr.employee.dependent.relation"].create({
            "name": "Dependent Fee Test Child",
        })
        request = self._create_request(
            "dependent_fee",
            dependent_relation_id=relation.id,
            requested_amount=750.0,
            payment_responsibility="company",
        )

        self.assertEqual(request.payment_responsibility, "company")
        request.action_submit()

        self.assertEqual(request.state, "employee_manager_approval")
        self.assertFalse(request.payment_request_id)

    def test_dependent_fee_duration_is_optional_selection(self):
        relation = self.env["hr.employee.dependent.relation"].create({
            "name": "Dependent Fee Duration Child",
        })
        request = self._create_request(
            "dependent_fee",
            dependent_relation_id=relation.id,
            dependent_fee_duration="6",
            requested_amount=500.0,
            payment_responsibility="company",
        )

        self.assertEqual(request.dependent_fee_duration, "6")

    def test_self_paid_dependent_fee_is_supported_for_record_keeping(self):
        relation = self.env.ref("pr_hr.employee_dependent_relationship_self")
        request = self._create_request(
            "dependent_fee",
            dependent_relation_id=relation.id,
            requested_amount=250.0,
            payment_responsibility="self",
        )

        self.assertEqual(request.payment_responsibility, "self")
        self.assertTrue(request._is_self_paid_request())
        self.assertFalse(request.payment_request_id)
        with self.assertRaises(UserError):
            request.action_create_payment_request()

    def test_dependent_fee_cannot_be_issued(self):
        relation = self.env["hr.employee.dependent.relation"].create({
            "name": "Dependent Fee Issue Test Child",
        })
        request = self._create_request(
            "dependent_fee",
            dependent_relation_id=relation.id,
            requested_amount=500.0,
            payment_responsibility="company",
        )
        request.state = "paid"
        with self.assertRaisesRegex(UserError, "Only paid employee service requests can be issued"):
            request.action_issue()

    def test_reimbursement_cannot_be_issued(self):
        request = self._create_request(
            "reimbursement",
            requested_amount=100.0,
        )
        request.state = "paid"
        with self.assertRaisesRegex(UserError, "Only paid employee service requests can be issued"):
            request.action_issue()

    def test_form_view_hides_issued_statusbar_for_non_issuable_types(self):
        arch = self.env["pr.employee.service.request"].get_view(view_type="form")["arch"]
        doc = etree.fromstring(arch)
        statusbars = doc.xpath("//header/field[@name='state'][@widget='statusbar']")
        self.assertEqual(len(statusbars), 2)
        with_issued = [
            sb for sb in statusbars
            if "issued" in (sb.get("statusbar_visible") or "").split(",")
        ]
        without_issued = [
            sb for sb in statusbars
            if "issued" not in (sb.get("statusbar_visible") or "").split(",")
        ]
        self.assertEqual(len(with_issued), 1)
        self.assertEqual(len(without_issued), 1)
        self.assertIn("not in", with_issued[0].get("invisible") or "")
        self.assertNotIn("not in", without_issued[0].get("invisible") or "")

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
        self.assertEqual(request.state, "employee_manager_approval")
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
        self.assertEqual(request.state, "md_approval")
        request.action_md_approve()

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
        self.assertEqual(request.state, "md_approval")
        request.action_md_approve()

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

        with patch.object(type(historical), "_notify_users", autospec=True):
            historical.action_submit()

        self.assertEqual(historical.state, "employee_manager_approval")
        self.assertEqual(historical.payment_responsibility, "company")
        self.assertEqual(historical.approved_amount, 0.0)
        self.assertFalse(historical.is_current_user_financial_approver)

        with self.assertRaises(UserError):
            historical.action_accounts_approve()
        with self.assertRaises(UserError):
            historical.action_finance_approve()

        with patch.object(type(historical), "_notify_group", autospec=True):
            historical.action_employee_manager_approve()
            self.assertEqual(historical.state, "hr_supervisor_approval")
            historical.action_hr_supervisor_approve()
            self.assertEqual(historical.state, "hr_manager_approval")
            historical.action_hr_manager_approve()

        self.assertEqual(historical.state, "md_approval")
        historical.action_md_approve()

        self.assertEqual(historical.state, "paid")
        self.assertEqual(historical.approved_amount, 0.0)
        self.assertFalse(historical.payment_request_id)
        self.assertFalse(historical.cash_payment_id)
        self.assertFalse(historical.bank_payment_id)

        historical.action_issue()

        self.assertEqual(historical.state, "issued")
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
            qiwa_renewal_reference="QIWA-RENEW-2099-001",
        )

        with patch.object(type(request), "_notify_group", autospec=True):
            request.action_submit()
        request.action_hr_manager_approve()
        self.assertEqual(request.state, "md_approval")
        request.action_md_approve()

        self.assertEqual(request.state, "issued")
        self.assertTrue(request.iqama_line_id)
        self.assertEqual(request.iqama_line_id.amount, 0.0)
        self.assertFalse(request.payment_request_id)
        self.assertFalse(request.bank_payment_id)

    def test_iqama_renewal_cannot_be_issued_without_qiwa_reference(self):
        request = self._create_request(
            "iqama_renewal",
            state="paid",
            iqama_profession="Engineer",
            issue_date=date(2099, 1, 1),
            service_expiry_date=date(2099, 12, 31),
            work_permit_expiry_date=date(2099, 12, 31),
        )

        with self.assertRaisesRegex(UserError, "Qiwa Renewal Reference"):
            request.action_issue()

        self.assertEqual(request.state, "paid")

    def test_full_sequential_approval_flow(self):
        """Test full sequence: Draft -> Employee Manager -> HR Supervisor -> HR Manager -> Accounts -> Finance -> MD -> Voucher Approval."""
        request = self._create_request(
            "reimbursement",
            reimbursement_type="food",
            requested_amount=150.0,
            expense_date=date(2099, 1, 1),
            payment_responsibility="company",
        )
        self.assertEqual(request.state, "draft")

        # 1. Submit -> employee_manager_approval
        with patch.object(type(request), "_notify_users", autospec=True):
            request.action_submit()
        self.assertEqual(request.state, "employee_manager_approval")

        # 2. Employee Manager Approve -> hr_supervisor_approval
        with patch.object(type(request), "_notify_group", autospec=True):
            request.action_employee_manager_approve()
        self.assertEqual(request.state, "hr_supervisor_approval")
        self.assertEqual(request.employee_manager_approved_by_id, self.env.user)

        # 3. HR Supervisor Approve -> hr_manager_approval
        with patch.object(type(request), "_notify_group", autospec=True):
            request.action_hr_supervisor_approve()
        self.assertEqual(request.state, "hr_manager_approval")
        self.assertEqual(request.hr_supervisor_approved_by_id, self.env.user)

        # 4. HR Manager Approve -> accounts_approval
        with patch.object(type(request), "_notify_group", autospec=True):
            request.action_hr_manager_approve()
        self.assertEqual(request.state, "accounts_approval")
        self.assertEqual(request.hr_manager_approved_by_id, self.env.user)
        self.assertEqual(request.approved_amount, 150.0)

        # 5. Accounts Approve -> finance_approval
        with (
            patch.object(type(request), "_check_before_accounts_approval", autospec=True),
            patch.object(type(request), "_notify_group", autospec=True),
        ):
            request.action_accounts_approve()
        self.assertEqual(request.state, "finance_approval")
        self.assertEqual(request.accounts_approved_by_id, self.env.user)

        # 6. Finance Approve -> md_approval
        with (
            patch.object(type(request), "_check_before_accounts_approval", autospec=True),
            patch.object(type(request), "_notify_group", autospec=True),
        ):
            request.action_finance_approve()
        self.assertEqual(request.state, "md_approval")
        self.assertEqual(request.finance_approved_by_id, self.env.user)

        # 7. MD Approve -> payment_approval
        with (
            patch.object(type(request), "_check_before_md_approval", autospec=True),
            patch.object(type(request), "_create_payment_request", autospec=True, return_value=self.env["pr.employee.payment.request"]),
            patch.object(type(request), "_notify_group", autospec=True),
        ):
            request.action_md_approve()
        self.assertEqual(request.state, "payment_approval")
        self.assertEqual(request.md_approved_by_id, self.env.user)

    def test_skip_level_md_approval_from_employee_manager(self):
        """MD can approve directly from employee_manager_approval in a single click."""
        request = self._create_request(
            "reimbursement",
            reimbursement_type="fuel",
            requested_amount=200.0,
            expense_date=date(2099, 1, 1),
            payment_responsibility="company",
        )
        with patch.object(type(request), "_notify_users", autospec=True):
            request.action_submit()
        self.assertEqual(request.state, "employee_manager_approval")

        # MD approves directly from employee_manager_approval
        with (
            patch.object(type(request), "_check_before_md_approval", autospec=True),
            patch.object(type(request), "_create_payment_request", autospec=True, return_value=self.env["pr.employee.payment.request"]),
        ):
            request.action_md_approve()

        self.assertEqual(request.state, "payment_approval")
        self.assertEqual(request.md_approved_by_id, self.env.user)
        self.assertFalse(request.hr_supervisor_approved_by_id)
        self.assertFalse(request.accounts_approved_by_id)
        self.assertFalse(request.finance_approved_by_id)

    def test_skip_level_finance_approval_from_hr_supervisor(self):
        """Finance can approve directly from hr_supervisor_approval, moving to md_approval."""
        request = self._create_request(
            "reimbursement",
            reimbursement_type="office",
            requested_amount=300.0,
            expense_date=date(2099, 1, 1),
            payment_responsibility="company",
        )
        with patch.object(type(request), "_notify_users", autospec=True):
            request.action_submit()
        request.action_employee_manager_approve()
        self.assertEqual(request.state, "hr_supervisor_approval")

        # Finance approves directly from hr_supervisor_approval
        with (
            patch.object(type(request), "_check_before_accounts_approval", autospec=True),
            patch.object(type(request), "_notify_group", autospec=True),
        ):
            request.action_finance_approve()

        self.assertEqual(request.state, "md_approval")
        self.assertEqual(request.finance_approved_by_id, self.env.user)
        self.assertFalse(request.hr_manager_approved_by_id)
        self.assertFalse(request.accounts_approved_by_id)

    def test_self_sponsored_skips_accounts_and_finance(self):
        """Self-sponsored requests skip Accounts and Finance, going from HR Manager to MD."""
        request = self._create_request(
            "dependent_fee",
            payment_responsibility="self",
            requested_amount=250.0,
        )
        with patch.object(type(request), "_notify_users", autospec=True):
            request.action_submit()
        self.assertEqual(request.state, "employee_manager_approval")

        request.action_employee_manager_approve()
        self.assertEqual(request.state, "hr_supervisor_approval")

        request.action_hr_supervisor_approve()
        self.assertEqual(request.state, "hr_manager_approval")

        # HR Manager approve on self-paid moves directly to md_approval (skipping accounts and finance)
        with patch.object(type(request), "_notify_group", autospec=True):
            request.action_hr_manager_approve()
        self.assertEqual(request.state, "md_approval")

        # MD approval on self-paid finalizes request without voucher creation
        with patch.object(type(request), "_check_before_md_approval", autospec=True):
            request.action_md_approve()
        self.assertEqual(request.state, "issued")
        self.assertEqual(request.approved_amount, 0.0)

    def test_pr_hr_groups_and_skip_level_safeguards(self):
        """Test approval using dedicated pr_hr groups and activity cleanup on skip-level approval."""
        internal_group = self.env.ref("base.group_user")
        hr_supervisor_group = self.env.ref("pr_hr.group_hr_supervisor", raise_if_not_found=False)
        if not hr_supervisor_group:
            hr_supervisor_group = self.env["res.groups"].create({
                "name": "HR Supervisor",
                "category_id": self.env.ref("base.module_category_human_resources_employees").id,
            })
        hr_manager_group = self.env.ref("pr_hr.group_hr_manager", raise_if_not_found=False)
        if not hr_manager_group:
            hr_manager_group = self.env["res.groups"].create({
                "name": "HR Manager",
                "category_id": self.env.ref("base.module_category_human_resources_employees").id,
            })
        hr_md_group = self.env.ref("pr_hr.group_hr_md", raise_if_not_found=False)
        if not hr_md_group:
            hr_md_group = self.env["res.groups"].create({
                "name": "Managing Director (HR)",
                "category_id": self.env.ref("base.module_category_human_resources_employees").id,
            })

        user_supervisor = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "PR HR Supervisor",
            "login": "pr.hr.supervisor.test",
            "email": "supervisor@test.com",
            "groups_id": [(6, 0, [internal_group.id, hr_supervisor_group.id])],
        })
        user_md = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "PR HR MD",
            "login": "pr.hr.md.test",
            "email": "md@test.com",
            "groups_id": [(6, 0, [internal_group.id, hr_md_group.id])],
        })

        request = self._create_request(
            "reimbursement",
            reimbursement_type="other",
            requested_amount=120.0,
            expense_date=date(2099, 1, 1),
            payment_responsibility="company",
        )
        with patch.object(type(request), "_notify_users", autospec=True):
            request.action_submit()
        self.assertEqual(request.state, "employee_manager_approval")

        # 1. Test HR Supervisor skip-level from employee_manager_approval
        with patch.object(type(request), "_notify_group", autospec=True):
            request.with_user(user_supervisor).action_hr_supervisor_approve()
        self.assertEqual(request.state, "hr_manager_approval")
        self.assertEqual(request.hr_supervisor_approved_by_id, user_supervisor)

        # 2. Test MD skip-level directly from hr_manager_approval
        with (
            patch.object(type(request), "_check_before_md_approval", autospec=True),
            patch.object(type(request), "_create_payment_request", autospec=True, return_value=self.env["pr.employee.payment.request"]),
        ):
            request.with_user(user_md).action_md_approve()
        self.assertEqual(request.state, "payment_approval")
        self.assertEqual(request.md_approved_by_id, user_md)

    def test_expense_account_sync_from_payment_request_line(self):
        """Updating expense account on payment request line syncs back to service request."""
        account_type = self.env.ref("account.data_account_type_expenses", raise_if_not_found=False)
        account_vals = {
            "name": "Test Expense Account",
            "code": "TEST_EXP_001",
            "company_id": self.env.company.id,
        }
        if account_type:
            account_vals["user_type_id"] = account_type.id
        elif "account_type" in self.env["account.account"]._fields:
            account_vals["account_type"] = "expense"
        test_account = self.env["account.account"].create(account_vals)

        request = self._create_request(
            "reimbursement",
            reimbursement_type="office",
            requested_amount=80.0,
            expense_date=date(2099, 1, 1),
            payment_responsibility="company",
        )
        payment_request = self.env["pr.employee.payment.request"].create({
            "service_request_id": request.id,
            "requested_user_id": self.env.user.id,
            "employee_id": self.employee.id,
            "company_id": self.env.company.id,
            "line_ids": [(0, 0, {
                "description": "Test Line",
                "amount": 80.0,
            })],
        })
        request.payment_request_id = payment_request.id
        self.assertFalse(request.expense_account_id)

        # Update expense account on line
        payment_request.line_ids[:1].write({"expense_account_id": test_account.id})
        self.assertEqual(request.expense_account_id, test_account)

    def _create_cost_center(self, name, plan=None):
        if plan is None:
            plan = self.env["account.analytic.plan"].create({"name": f"{name} Plan"})
        return self.env["account.analytic.account"].create({
            "name": name,
            "plan_id": plan.id,
        })

    def _create_budget(self, name, cost_centers, date_from=None, date_to=None):
        date_from = date_from or date.today()
        date_to = date_to or date(2099, 12, 31)
        budget = self.env["crossovered.budget"].create({
            "name": name,
            "date_from": date_from,
            "date_to": date_to,
            "state": "validate",
            "user_id": self.env.user.id,
            "expense_type": "opex",
        })
        for cost_center in cost_centers:
            self.env["crossovered.budget.lines"].create({
                "crossovered_budget_id": budget.id,
                "analytic_account_id": cost_center.id,
                "date_from": budget.date_from,
                "date_to": budget.date_to,
                "planned_amount": 5000.0,
            })
        return budget

    def test_budget_onchange_auto_selects_first_cost_center_on_service_request(self):
        plan = self.env["account.analytic.plan"].create({"name": "Budget Onchange Plan"})
        cc_emp = self._create_cost_center("CC Emp", plan)
        cc1 = self._create_cost_center("CC Single", plan)
        cc2_first = self._create_cost_center("CC Multi First", plan)
        cc2_second = self._create_cost_center("CC Multi Second", plan)
        cc3_first = self._create_cost_center("CC Emp Budget First", plan)
        cc_outside = self._create_cost_center("CC Outside", plan)

        employee = self.env["hr.employee"].create({
            "name": "Budget Onchange Employee",
            "identification_id": "TEST-BUDGET-ONCHANGE-001",
            "employee_cost_center_id": cc_emp.id,
        })
        budget_single = self._create_budget("Budget Single CC", [cc1])
        budget_multi = self._create_budget("Budget Multi CC", [cc2_first, cc2_second])
        budget_emp = self._create_budget("Budget Emp Multi CC", [cc3_first, cc_emp])
        budget_empty = self._create_budget("Budget Empty CC", [])

        employee_no_cc = self.env["hr.employee"].create({
            "name": "No Cost Center Employee",
            "identification_id": "TEST-NO-CC-001",
        })
        form = Form(
            self.env["pr.employee.service.request"].with_context(
                default_employee_id=False
            )
        )
        form.employee_id = employee
        self.assertEqual(form.cost_center_id, cc_emp)
        self.assertEqual(form.expense_bucket_id, budget_emp)
        self.assertEqual(set(form.allowed_cost_center_ids[:].ids), {cc3_first.id, cc_emp.id})

        form.expense_bucket_id = budget_single
        self.assertEqual(form.cost_center_id, cc1)
        self.assertEqual(form.allowed_cost_center_ids[:].ids, [cc1.id])

        form.expense_bucket_id = budget_multi
        self.assertEqual(form.cost_center_id, cc2_first)
        self.assertEqual(
            set(form.allowed_cost_center_ids[:].ids),
            {cc2_first.id, cc2_second.id},
        )
        self.assertNotIn(cc_outside.id, form.allowed_cost_center_ids[:].ids)

        form.cost_center_id = cc2_second
        self.assertEqual(form.expense_bucket_id, budget_multi)
        self.assertEqual(form.cost_center_id, cc2_second)

        form.expense_bucket_id = budget_empty
        self.assertFalse(form.cost_center_id)
        self.assertEqual(form.allowed_cost_center_ids[:].ids, [])

        form.expense_bucket_id = budget_multi
        self.assertEqual(form.cost_center_id, cc2_first)

        form.expense_bucket_id = self.env["crossovered.budget"]
        self.assertFalse(form.cost_center_id)
        self.assertEqual(form.allowed_cost_center_ids[:].ids, [])

        default_budget_form = Form(
            self.env["pr.employee.service.request"].with_context(
                default_employee_id=employee_no_cc.id,
                default_expense_bucket_id=budget_single.id,
            )
        )
        self.assertEqual(default_budget_form.cost_center_id, cc1)
        self.assertEqual(default_budget_form.allowed_cost_center_ids[:].ids, [cc1.id])

        hr_readonly_user = self._create_role_user(
            "budget.hr.readonly.test",
            [
                "pr_hr.group_hr_supervisor",
                "account.group_account_readonly",
                "analytic.group_analytic_accounting",
            ],
        )
        hr_form = Form(
            self.env["pr.employee.service.request"]
            .with_user(hr_readonly_user)
            .with_context(default_employee_id=False)
        )
        hr_form.expense_bucket_id = budget_multi
        self.assertEqual(hr_form.cost_center_id, cc2_first)
        self.assertEqual(
            set(hr_form.allowed_cost_center_ids[:].ids),
            {cc2_first.id, cc2_second.id},
        )

        basic_user = self._create_role_user("budget.basic.user.test", [])
        basic_record = (
            self.env["pr.employee.service.request"]
            .with_user(basic_user)
            .new({"employee_id": employee.id})
        )
        basic_record.expense_bucket_id = budget_multi.id
        basic_record._onchange_expense_bucket_id()
        self.assertEqual(basic_record.cost_center_id.id, cc2_first.id)
        self.assertEqual(
            set(basic_record.allowed_cost_center_ids.ids),
            {cc2_first.id, cc2_second.id},
        )
        basic_record.expense_bucket_id = False
        basic_record._onchange_expense_bucket_id()
        self.assertFalse(basic_record.cost_center_id)
        self.assertEqual(basic_record.allowed_cost_center_ids.ids, [])

    def test_budget_onchange_auto_selects_first_cost_center_on_compliance_wizards(self):
        today = date.today()
        plan = self.env["account.analytic.plan"].create({"name": "Wizard Onchange Plan"})
        cc_emp = self._create_cost_center("Wiz CC Emp", plan)
        cc1 = self._create_cost_center("Wiz CC Single", plan)
        cc2_first = self._create_cost_center("Wiz CC Multi First", plan)
        cc2_second = self._create_cost_center("Wiz CC Multi Second", plan)
        cc3_first = self._create_cost_center("Wiz CC Emp First", plan)

        employee = self.env["hr.employee"].create({
            "name": "Wizard Budget Employee",
            "identification_id": "TEST-WIZ-BUDGET-001",
            "employee_cost_center_id": cc_emp.id,
        })
        budget_single = self._create_budget("Wiz Budget Single", [cc1])
        budget_multi = self._create_budget("Wiz Budget Multi", [cc2_first, cc2_second])
        budget_emp = self._create_budget("Wiz Budget Emp", [cc3_first, cc_emp])
        budget_empty = self._create_budget("Wiz Budget Empty", [])

        iqama = self.env["hr.employee.iqama"].create({
            "name": "Wizard Test Iqama",
            "employee_id": employee.id,
            "identification_id": employee.identification_id,
            "expiry_date": date(2099, 12, 31),
            "state": "valid",
        })
        iqama_form = Form(
            self.env["hr.employee.iqama.line.add.wizard"].with_context(
                default_employee_id=employee.id,
                default_iqama_id=iqama.id,
                default_from_date=today,
            )
        )
        self.assertEqual(iqama_form.cost_center_id, cc_emp)
        self.assertEqual(iqama_form.expense_bucket_id, budget_emp)
        self.assertEqual(set(iqama_form.allowed_cost_center_ids[:].ids), {cc3_first.id, cc_emp.id})

        iqama_form.expense_bucket_id = budget_single
        self.assertEqual(iqama_form.cost_center_id, cc1)
        self.assertEqual(iqama_form.allowed_cost_center_ids[:].ids, [cc1.id])

        iqama_form.expense_bucket_id = budget_multi
        self.assertEqual(iqama_form.cost_center_id, cc2_first)
        self.assertEqual(
            set(iqama_form.allowed_cost_center_ids[:].ids),
            {cc2_first.id, cc2_second.id},
        )

        iqama_form.cost_center_id = cc2_second
        self.assertEqual(iqama_form.expense_bucket_id, budget_multi)
        self.assertEqual(iqama_form.cost_center_id, cc2_second)

        iqama_form.expense_bucket_id = budget_empty
        self.assertFalse(iqama_form.cost_center_id)
        self.assertEqual(iqama_form.allowed_cost_center_ids[:].ids, [])

        iqama_form.expense_bucket_id = budget_multi
        self.assertEqual(iqama_form.cost_center_id, cc2_first)

        iqama_form.expense_bucket_id = self.env["crossovered.budget"]
        self.assertFalse(iqama_form.cost_center_id)
        self.assertEqual(iqama_form.allowed_cost_center_ids[:].ids, [])

        insurance = self.env["hr.employee.medical.insurance"].create({
            "name": "Wizard Test Insurance",
            "employee_id": employee.id,
            "identification_id": employee.identification_id,
            "insurance_company": "Bupa",
            "insurance_category": "VIP",
            "expiry_date": date(2099, 12, 31),
            "state": "valid",
        })
        insurance_form = Form(
            self.env["hr.employee.medical.insurance.line.add.wizard"].with_context(
                default_employee_id=employee.id,
                default_insurance_id=insurance.id,
                default_from_date=today,
            )
        )
        self.assertEqual(insurance_form.cost_center_id, cc_emp)
        self.assertEqual(insurance_form.expense_bucket_id, budget_emp)
        self.assertEqual(
            set(insurance_form.allowed_cost_center_ids[:].ids),
            {cc3_first.id, cc_emp.id},
        )

        insurance_form.expense_bucket_id = budget_single
        self.assertEqual(insurance_form.cost_center_id, cc1)
        self.assertEqual(insurance_form.allowed_cost_center_ids[:].ids, [cc1.id])

        insurance_form.expense_bucket_id = budget_multi
        self.assertEqual(insurance_form.cost_center_id, cc2_first)
        self.assertEqual(
            set(insurance_form.allowed_cost_center_ids[:].ids),
            {cc2_first.id, cc2_second.id},
        )

        insurance_form.cost_center_id = cc2_second
        self.assertEqual(insurance_form.expense_bucket_id, budget_multi)
        self.assertEqual(insurance_form.cost_center_id, cc2_second)

        insurance_form.expense_bucket_id = budget_empty
        self.assertFalse(insurance_form.cost_center_id)
        self.assertEqual(insurance_form.allowed_cost_center_ids[:].ids, [])

        insurance_form.expense_bucket_id = budget_multi
        self.assertEqual(insurance_form.cost_center_id, cc2_first)

        insurance_form.expense_bucket_id = self.env["crossovered.budget"]
        self.assertFalse(insurance_form.cost_center_id)
        self.assertEqual(insurance_form.allowed_cost_center_ids[:].ids, [])

    def test_cost_center_domain_and_allowed_cost_centers_in_form_views(self):
        expected_domain = "expense_bucket_id and [('id', 'in', allowed_cost_center_ids)] or []"
        for model_name in (
            "pr.employee.service.request",
            "hr.employee.iqama.line.add.wizard",
            "hr.employee.medical.insurance.line.add.wizard",
        ):
            view_info = self.env[model_name].get_view(view_type="form")
            arch = etree.fromstring(view_info["arch"])
            allowed_nodes = arch.xpath("//field[@name='allowed_cost_center_ids']")
            self.assertTrue(allowed_nodes, f"{model_name} form is missing allowed_cost_center_ids")
            self.assertEqual(allowed_nodes[0].get("invisible"), "1")
            cost_center_nodes = arch.xpath("//field[@name='cost_center_id']")
            self.assertTrue(cost_center_nodes, f"{model_name} form is missing cost_center_id")
            self.assertEqual(cost_center_nodes[0].get("domain"), expected_domain)

    def test_submit_escalation_by_manager_access_rights(self):
        """Submitting checks the resolved Stage-1 manager's roles and routes
        directly to the highest applicable stage while leaving skipped audit fields blank."""
        scenarios = [
            ("regular_mgr", [], "company", "employee_manager_approval", False),
            ("hr_sup_mgr", ["pr_hr.group_hr_supervisor"], "company", "hr_supervisor_approval", False),
            ("hr_mgr_mgr", ["pr_hr.group_hr_manager"], "company", "hr_manager_approval", False),
            ("acc_mgr", ["account.group_account_manager"], "company", "accounts_approval", True),
            ("fin_mgr", ["pr_account.custom_group_accounting_manager"], "company", "finance_approval", True),
            ("md_mgr", ["pr_hr.group_hr_md"], "company", "md_approval", True),
            ("acc_self_mgr", ["account.group_account_manager"], "self", "employee_manager_approval", False),
            ("fin_self_mgr", ["pr_account.custom_group_accounting_manager"], "self", "employee_manager_approval", False),
            ("md_self_mgr", ["pr_hr.group_hr_md"], "self", "md_approval", False),
            (
                "fin_hrsup_self_mgr",
                ["pr_account.custom_group_accounting_manager", "pr_hr.group_hr_supervisor"],
                "self",
                "hr_supervisor_approval",
                False,
            ),
        ]
        SR = self.env["pr.employee.service.request"]
        self_relation = (
            self.env.ref("pr_hr.employee_dependent_relationship_self", raise_if_not_found=False)
            or self.env["hr.employee.dependent.relation"].search([], limit=1)
        )
        for idx, (tag, group_xmlids, resp, expected_state, expect_approved_amount) in enumerate(scenarios):
            emp_user = self._create_role_user(f"sub.esc.emp.{idx}", [])
            mgr_user = self._create_role_user(f"sub.esc.{tag}.{idx}", group_xmlids)
            mgr_emp = self.env["hr.employee"].create({
                "name": f"Escalation Manager {tag}",
                "user_id": mgr_user.id,
            })
            emp = self.env["hr.employee"].create({
                "name": f"Escalation Employee {tag}",
                "user_id": emp_user.id,
                "parent_id": mgr_emp.id,
            })
            if resp == "self":
                req = SR.with_user(emp_user).create({
                    "request_type": "dependent_fee",
                    "employee_id": emp.id,
                    "company_id": self.env.company.id,
                    "dependent_relation_id": self_relation.id,
                    "payment_responsibility": "self",
                    "requested_amount": 350.0,
                    "reason": f"Submit escalation self {tag}",
                })
            else:
                req = SR.with_user(emp_user).create({
                    "request_type": "reimbursement",
                    "reimbursement_type": "fuel",
                    "employee_id": emp.id,
                    "company_id": self.env.company.id,
                    "requested_amount": 350.0,
                    "expense_date": date(2099, 1, 1),
                    "payment_responsibility": "company",
                    "reason": f"Submit escalation company {tag}",
                })

            with patch.object(type(req), "_notify_users", autospec=True):
                req.with_user(emp_user).action_submit()

            with self.subTest(scenario=tag):
                self.assertEqual(req.state, expected_state)
                self.assertFalse(req.employee_manager_approved_by_id)
                self.assertFalse(req.hr_supervisor_approved_by_id)
                self.assertFalse(req.hr_manager_approved_by_id)
                self.assertFalse(req.accounts_approved_by_id)
                self.assertFalse(req.finance_approved_by_id)
                self.assertFalse(req.md_approved_by_id)
                if expect_approved_amount:
                    self.assertEqual(req.approved_amount, 350.0)
                else:
                    self.assertEqual(req.approved_amount, 0.0)
