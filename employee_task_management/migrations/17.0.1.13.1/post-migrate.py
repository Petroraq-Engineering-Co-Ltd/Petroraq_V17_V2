# -*- coding: utf-8 -*-
"""Backfill `needs_employee_planning` on lists already awaiting acceptance.

The flag became a STORED field in 17.0.1.13.1 (it used to be computed
live, which is what made the buttons flip the moment the employee added
his activities). Records already sitting in Pending Acceptance were
never stamped, so without this pass they would all read False and show
Accept / Request Modification even where the manager handed over a bare
list.

Best effort only: getting the flag wrong on an in-flight record shows
the wrong pair of buttons, which is recoverable. It must never block an
upgrade.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    try:
        env = api.Environment(cr, SUPERUSER_ID, {})
        pending = env['employee.task.list'].search([
            ('state', '=', 'pending_acceptance'),
        ])
        stamped = 0
        for rec in pending:
            value = rec._plan_is_incomplete()
            if rec.needs_employee_planning != value:
                rec.with_context(etm_workflow=True).write(
                    {'needs_employee_planning': value})
                stamped += 1
        _logger.info(
            "needs_employee_planning backfilled on %s of %s pending "
            "task list(s)", stamped, len(pending))
    except Exception:
        cr.rollback()
        _logger.exception(
            "needs_employee_planning backfill failed - lists already "
            "awaiting acceptance may show the wrong buttons until they "
            "move state again. Upgrade continues.")
