# -*- coding: utf-8 -*-

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    requests = env["hr.recruitment.request"].search(
        [("state", "in", ("approved", "done"))]
    )
    requests.action_sync_application_questions()

