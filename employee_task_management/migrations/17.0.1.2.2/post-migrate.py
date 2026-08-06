# -*- coding: utf-8 -*-
"""The auto-apply scheduled action was renamed from
_cron_auto_apply_modification_requests() to _cron_auto_apply().

The ir.cron record lives in a noupdate="1" data block, so a normal
upgrade leaves it untouched - hence this migration.

NOTE ON THE TABLES: ir.cron uses _inherits = {'ir.actions.server': ...},
so the `code` column lives on ir_act_server, NOT on ir_cron. The join
goes ir_model_data -> ir_cron -> ir_cron.ir_actions_server_id.

This is cosmetic housekeeping only: the old method name is still aliased
in the model, so the cron keeps working whether or not this runs. It is
therefore wrapped so that a failure can never block an upgrade.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    try:
        cr.execute("""
            UPDATE ir_act_server s
               SET code = 'model._cron_auto_apply()'
              FROM ir_cron c
              JOIN ir_model_data d
                ON d.model = 'ir.cron' AND d.res_id = c.id
             WHERE d.module = 'employee_task_management'
               AND d.name = 'ir_cron_auto_apply_modification'
               AND s.id = c.ir_actions_server_id
        """)
        _logger.info(
            "employee_task_management: auto-apply cron repointed to "
            "_cron_auto_apply() (%s row(s))", cr.rowcount)
    except Exception:
        # Never let cosmetic housekeeping break an upgrade - the model
        # still exposes the old method name as an alias.
        cr.rollback()
        _logger.exception(
            "employee_task_management: could not repoint the auto-apply "
            "cron; it will keep calling the aliased method name.")
