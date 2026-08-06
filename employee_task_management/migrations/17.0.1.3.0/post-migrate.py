# -*- coding: utf-8 -*-
"""The auto-apply cron changed meaning: it no longer releases a task list
one working day after a manager ignored a modification request, it now
releases any waiting task list once the start date of its work arrives.

The method name (_cron_auto_apply) is unchanged, so this migration is
purely cosmetic - it relabels the scheduled action so the UI does not
still describe the old rule. The ir.cron record is in a noupdate="1"
block, so a normal upgrade would leave the old label in place.

ir.cron uses _inherits = {'ir.actions.server': 'ir_actions_server_id'},
so `name` lives on ir_act_server, NOT on ir_cron.
"""
import logging

_logger = logging.getLogger(__name__)

NEW_NAME = ('Employee Task Management: Auto-assign task lists whose '
            'start date has arrived')


def migrate(cr, version):
    if not version:
        return
    try:
        cr.execute("""
            UPDATE ir_act_server s
               SET name = %s
              FROM ir_cron c
              JOIN ir_model_data d
                ON d.model = 'ir.cron' AND d.res_id = c.id
             WHERE d.module = 'employee_task_management'
               AND d.name = 'ir_cron_auto_apply_modification'
               AND s.id = c.ir_actions_server_id
        """, (NEW_NAME,))
        _logger.info(
            "employee_task_management: auto-assign cron relabelled "
            "(%s row(s))", cr.rowcount)
    except Exception:
        # Cosmetic only - never let this block an upgrade.
        cr.rollback()
        _logger.exception(
            "employee_task_management: could not relabel the auto-assign "
            "cron; rename it from Scheduled Actions if needed.")
