from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestZatcaWarningCenter(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.partner_id.country_id = cls.env.ref("base.sa")
        cls.partner = cls.env["res.partner"].create({
            "name": "ZATCA Warning Center Customer",
            "company_type": "company",
            "country_id": cls.env.ref("base.sa").id,
            "vat": "300000000000003",
        })
        cls.invoice = cls.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": cls.partner.id,
        })
        cls.account_user = new_test_user(
            cls.env,
            login="zatca_warning_account_user",
            groups="account.group_account_invoice",
        )

    def test_response_warning_is_captured_once(self):
        payload = {
            "validationResults": {
                "warningMessages": [{
                    "code": "BR-TEST-001",
                    "message": "Customer address should be completed.",
                }],
            },
        }
        WarningCase = self.env["petroraq.zatca.warning.case"]
        first = WarningCase.capture_zatca_response(self.invoice, payload)
        second = WarningCase.capture_zatca_response(self.invoice, payload)
        self.assertEqual(len(first), 1)
        self.assertEqual(first, second)
        self.assertEqual(first.source, "zatca")
        self.assertEqual(first.state, "open")
        self.assertEqual(self.invoice.zatca_open_warning_count, 1)

    def test_account_user_can_capture_without_rule_configuration_access(self):
        case = self.env["petroraq.zatca.warning.case"].with_user(
            self.account_user
        ).capture_zatca_response(self.invoice, {
            "validationResults": {"warningMessages": [{
                "code": "BR-TEST-ACCOUNT-USER",
                "message": "A normal accounting user can submit this response.",
            }]},
        })
        self.assertTrue(case)
        values = case.with_user(self.account_user).read([
            "target_type", "recommended_action", "suggestion_origin",
        ])[0]
        self.assertEqual(values["suggestion_origin"], "builtin")
        self.assertTrue(values["recommended_action"])

    def test_draft_precheck_creates_customer_actionable_cases(self):
        action = self.invoice.action_run_zatca_precheck()
        self.assertEqual(action["res_model"], "petroraq.zatca.warning.case")
        cases = self.env["petroraq.zatca.warning.case"].search(action["domain"])
        self.assertTrue(cases)
        self.assertTrue(all(case.source == "precheck" for case in cases))
        self.assertTrue(all(case.rule_id.code == "PR-CUSTOMER-DATA" for case in cases))
        target_action = cases[0].action_open_target()
        self.assertEqual(target_action["res_model"], "res.partner")
        self.assertEqual(target_action["res_id"], self.partner.commercial_partner_id.id)

    def test_case_resolution_does_not_modify_invoice(self):
        case = self.env["petroraq.zatca.warning.case"].capture_zatca_response(
            self.invoice,
            {"validationResults": {"warningMessages": [{
                "code": "BR-TEST-IMMUTABLE",
                "message": "Investigate on the next invoice.",
            }]}},
        )
        original_state = self.invoice.state
        case.action_start()
        case.write({"resolution_note": "Customer master data corrected for future invoices."})
        case.action_resolve()
        self.assertEqual(case.state, "resolved")
        self.assertEqual(self.invoice.state, original_state)

    def test_builtin_customer_suggestion_is_actionable(self):
        case = self.env["petroraq.zatca.warning.case"].capture_zatca_response(
            self.invoice,
            {"validationResults": {"warningMessages": [{
                "code": "BR-TEST-CUSTOMER",
                "message": "Buyer postal address is incomplete.",
            }]}},
        )
        self.assertFalse(case.rule_id)
        self.assertEqual(case.suggestion_origin, "builtin")
        self.assertEqual(case.target_type, "customer")
        self.assertIn("customer", case.recommended_action.lower())
        self.assertEqual(case.action_open_target()["res_model"], "res.partner")

    def test_existing_invoice_audit_creates_actionable_cases(self):
        action = self.env["petroraq.zatca.invoice.audit.wizard"].create({
            "company_id": self.company.id,
            "include_draft": True,
        }).action_run_audit()
        self.assertEqual(action["res_model"], "petroraq.zatca.warning.case")
        case = self.env["petroraq.zatca.warning.case"].search([
            ("invoice_id", "=", self.invoice.id),
            ("source", "=", "audit"),
        ], limit=1)
        self.assertTrue(case)
        self.assertEqual(case.rule_id.code, "PR-CUSTOMER-DATA")

    def test_chatter_import_uses_xml_evidence_and_specific_rule(self):
        xml = b'''<?xml version="1.0"?><Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2" xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"><cbc:TaxCurrencyCode>SAR</cbc:TaxCurrencyCode><cac:TaxTotal><cbc:TaxAmount>15.00</cbc:TaxAmount><cac:TaxSubtotal/></cac:TaxTotal></Invoice>'''
        self.env["ir.attachment"].create({
            "name": "zatca-test.xml", "mimetype": "application/xml", "raw": xml,
            "res_model": "account.move", "res_id": self.invoice.id,
        })
        self.env["mail.message"].create({
            "model": "account.move", "res_id": self.invoice.id,
            "body": "<div>Accepted by ZATCA (with Warnings)<br/><b>[202] </b><b>BR-KSA-EN16931-09</b> : Only one tax total must be provided when tax currency code is provided.</div>",
        })
        case = self.env["petroraq.zatca.warning.case"].capture_zatca_chatter(self.invoice)
        self.assertEqual(case.code, "BR-KSA-EN16931-09")
        self.assertEqual(case.source, "chatter")
        self.assertTrue(case.xml_attachment_id)
        self.assertIn("found 1", case.xml_diagnosis)
        self.assertEqual(case.rule_id.code, "BR-KSA-EN16931-09")
