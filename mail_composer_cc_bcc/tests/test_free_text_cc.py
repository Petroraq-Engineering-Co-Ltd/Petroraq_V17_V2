from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestFreeTextCc(TransactionCase):
    def test_free_text_cc_without_contacts(self):
        before = self.env["res.partner"].search_count([("email", "=", "cc-test@example.com")])
        wizard = self.env["mail.compose.message"].new({"email_cc_text": "cc-test@example.com; Other <other@example.com>"})
        result = wizard._get_additional_cc()
        self.assertIn("cc-test@example.com", result)
        self.assertIn("other@example.com", result)
        self.assertEqual(before, self.env["res.partner"].search_count([("email", "=", "cc-test@example.com")]))

    def test_invalid_cc_and_header_injection(self):
        for value in ("not-an-address", "valid@example.com\nBcc: hidden@example.com"):
            with self.assertRaises(ValidationError):
                self.env["mail.compose.message"].new({"email_cc_text": value})._get_additional_cc()

    def test_free_text_cc_has_smtp_envelopes(self):
        partner = self.env["res.partner"].create({"name": "Recipient", "email": "to@example.com"})
        mail = self.env["mail.mail"].create({
            "subject": "Envelope test", "body_html": "<p>Test</p>",
            "email_from": "sender@example.com", "recipient_ids": [(6, 0, partner.ids)],
            "email_cc": "first-cc@example.com, second-cc@example.com",
        }).with_context(is_from_composer=True)
        outgoing = mail._prepare_outgoing_list()
        recipients = mail.env.context["recipients"]
        self.assertIn("first-cc@example.com", recipients)
        self.assertIn("second-cc@example.com", recipients)
        self.assertEqual(len(outgoing), len(recipients))

    def test_comment_mode_does_not_pass_email_cc_to_message_post(self):
        wizard = self.env["mail.compose.message"].new({
            "composition_mode": "comment",
            "email_cc_text": "cc-test@example.com",
        })
        values = wizard._add_cc_bcc_to_mail_values({1: {"email_cc": "template@example.com"}})
        self.assertNotIn("email_cc", values[1])

    def test_mass_mail_keeps_free_text_email_cc(self):
        wizard = self.env["mail.compose.message"].new({
            "composition_mode": "mass_mail",
            "email_cc_text": "cc-test@example.com",
        })
        values = wizard._add_cc_bcc_to_mail_values({1: {}})
        self.assertEqual(values[1]["email_cc"], "cc-test@example.com")
