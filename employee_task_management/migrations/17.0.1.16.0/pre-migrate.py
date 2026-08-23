# -*- coding: utf-8 -*-
"""Backfill blank task-line dates BEFORE they become required.

LOAD-BEARING - this one is deliberately NOT wrapped in a try/except.

Odoo does NOT crash when a NOT NULL constraint cannot be applied to a
column that still holds nulls: it logs a warning and carries on. The
column would then silently never get its constraint while the Python
side enforced it anyway, leaving the database and the model disagreeing
about what is valid. So if this cannot complete, it must fail loudly and
stop the upgrade rather than leave a half-migrated schema behind.

Nothing is deleted. Every blank is filled from the record's own data:
  * Start Date  <- End Date, else the list's Assign Date, else today
  * End Date    <- Start Date, else the list's Assign Date, else today
End Date additionally goes through GREATEST(start_date, ...) so filling
a blank can never produce a range that ends before it begins - an
inverted range would then be rejected by _check_working_date_range and
the record would be unusable.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        SELECT COUNT(*) FROM employee_task_line
         WHERE start_date IS NULL OR end_date IS NULL
    """)
    blanks = cr.fetchone()[0]
    _logger.info(
        "ETM 1.16.0: %s task line(s) have a blank Start or End Date",
        blanks)
    if not blanks:
        return

    # Start Date first, so the End Date fill below can lean on it.
    cr.execute("""
        UPDATE employee_task_line line
           SET start_date = COALESCE(
                   line.end_date,
                   tl.assign_date,
                   CURRENT_DATE)
          FROM employee_task_list tl
         WHERE tl.id = line.task_list_id
           AND line.start_date IS NULL
    """)
    _logger.info("ETM 1.16.0: filled %s blank Start Date(s)", cr.rowcount)

    cr.execute("""
        UPDATE employee_task_line line
           SET end_date = GREATEST(
                   line.start_date,
                   COALESCE(line.start_date, tl.assign_date, CURRENT_DATE))
          FROM employee_task_list tl
         WHERE tl.id = line.task_list_id
           AND line.end_date IS NULL
    """)
    _logger.info("ETM 1.16.0: filled %s blank End Date(s)", cr.rowcount)

    # Orphans: a task line whose task list has gone. The join above
    # cannot reach them, and a leftover null would silently block the
    # NOT NULL constraint.
    cr.execute("""
        UPDATE employee_task_line
           SET start_date = COALESCE(start_date, end_date, CURRENT_DATE),
               end_date = COALESCE(end_date, start_date, CURRENT_DATE)
         WHERE start_date IS NULL OR end_date IS NULL
    """)
    if cr.rowcount:
        _logger.warning(
            "ETM 1.16.0: filled %s orphan task line(s) with no task list",
            cr.rowcount)

    cr.execute("""
        SELECT COUNT(*) FROM employee_task_line
         WHERE start_date IS NULL OR end_date IS NULL
    """)
    remaining = cr.fetchone()[0]
    if remaining:
        raise Exception(
            "ETM 1.16.0: %s task line(s) still have a blank date after "
            "the backfill. Aborting so the NOT NULL constraint is not "
            "applied to a half-migrated table." % remaining)
