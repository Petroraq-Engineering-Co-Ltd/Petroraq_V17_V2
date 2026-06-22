# -*- coding: utf-8 -*-

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    reason = env.ref(
        "pr_recruitment_dynamic_screening.refuse_reason_automatic_screening",
        raise_if_not_found=False,
    )
    if not reason:
        return

    applicants = env["hr.applicant"].with_context(active_test=False).search(
        [("dynamic_screening_status", "=", "auto_refused")]
    )
    for applicant in applicants:
        values = {
            "active": False,
            "refuse_reason_id": reason.id,
            "date_closed": False,
        }
        applicant.write(values)
