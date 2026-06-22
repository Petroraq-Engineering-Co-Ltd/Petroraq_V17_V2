# -*- coding: utf-8 -*-

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    questions = env["pr.recruitment.question"].with_context(active_test=False).search([])
    for question in questions:
        if question.allowed_option_ids:
            question.allowed_option_ids.write({"screening_allowed": True})
        if question.minimum_option_id:
            question.minimum_option_id.write({"screening_minimum": True})

