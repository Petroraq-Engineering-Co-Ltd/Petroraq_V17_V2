import secrets
from datetime import timedelta

from odoo import api, fields, models


class PrWebsiteCaptchaChallenge(models.Model):
    _name = 'pr.website.captcha.challenge'
    _description = 'Website CAPTCHA Challenge'
    _order = 'expires_at desc'

    token = fields.Char(required=True, index=True, readonly=True)
    answer = fields.Integer(required=True, readonly=True)
    expires_at = fields.Datetime(required=True, index=True, readonly=True)

    _sql_constraints = [
        ('token_unique', 'unique(token)', 'CAPTCHA challenge tokens must be unique.'),
    ]

    @api.model
    def create_contact_challenge(self, ttl_seconds=600):
        now = fields.Datetime.now()
        self.sudo().search([('expires_at', '<', now)], limit=200).unlink()

        left = secrets.randbelow(90) + 10
        right = secrets.randbelow(90) + 10
        challenge = self.sudo().create({
            'token': secrets.token_urlsafe(32),
            'answer': left + right,
            'expires_at': now + timedelta(seconds=ttl_seconds),
        })
        return {
            'question': 'What is %s + %s?' % (left, right),
            'nonce': challenge.token,
        }

    @api.model
    def consume_contact_challenge(self, token, supplied_answer):
        """Atomically consume a challenge and return its validation result."""
        if not token:
            return 'missing'

        self.env.cr.execute(
            'SELECT id, answer, expires_at '
            'FROM pr_website_captcha_challenge '
            'WHERE token = %s '
            'FOR UPDATE',
            [token],
        )
        challenge = self.env.cr.fetchone()
        if not challenge:
            return 'missing'

        challenge_id, expected_answer, expires_at = challenge
        self.env.cr.execute(
            'DELETE FROM pr_website_captcha_challenge WHERE id = %s',
            [challenge_id],
        )

        if expires_at < fields.Datetime.now():
            return 'expired'
        if not supplied_answer.isdigit() or int(supplied_answer) != expected_answer:
            return 'incorrect'
        return 'valid'
