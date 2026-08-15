# -*- coding: utf-8 -*-
"""Recompute task-line progress under the new hours-weighted rule.

`employee.task.line.progress` is a stored value written by
`_recompute_progress_from_subtasks`, not a compute with depends - so an
existing record keeps whatever percentage the OLD equal-share rule left
behind until somebody happens to toggle one of its activities. Without
this pass, a task list in flight would keep showing e.g. 50% where the
new rule says 83.33%, and the manager would see two different numbers
for the same work depending on how recently it was touched.

Deliberately narrow: it writes `progress` ONLY. It does not touch
task_status or completion_date, so nothing that already reached a
terminal state gets rewritten and no delay history is disturbed.
Non-load-bearing, so a failure here must never block the upgrade.
"""
import logging

from odoo import api, SUPERUSER_ID
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    try:
        env = api.Environment(cr, SUPERUSER_ID, {})
        lines = env['employee.task.line'].search([
            ('subtask_ids', '!=', False),
        ])
        changed = 0
        for line in lines:
            new_progress = line._weighted_progress()
            if float_compare(new_progress, line.progress,
                             precision_digits=2) != 0:
                line.with_context(etm_workflow=True).write(
                    {'progress': new_progress})
                changed += 1
        _logger.info(
            "Hours-weighted progress: re-rated %s of %s task line(s)",
            changed, len(lines))
    except Exception:
        cr.rollback()
        _logger.exception(
            "Hours-weighted progress migration failed - existing records "
            "keep their old percentage until an activity is next toggled. "
            "Upgrade continues.")
