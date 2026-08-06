# -*- coding: utf-8 -*-
"""Assign Date has been removed from the task lines (employee.task.line).
Only Start Date and End Date remain there; the Assign Date on the task
list header is untouched.

THIS MIGRATION IS LOAD-BEARING, do not wrap it in try/except.

Odoo never drops a column when a field is removed from a model. The old
`assign_date` column was declared required=True, so PostgreSQL still
holds a NOT NULL constraint on it - but Odoo no longer knows the field
exists and will stop supplying a value. Every future INSERT into
employee_task_line would then fail with:

    null value in column "assign_date" violates not-null constraint

Running as pre-migrate means the column is gone before Odoo re-inits the
table.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'employee_task_line'
           AND column_name = 'assign_date'
    """)
    if not cr.fetchone():
        _logger.info(
            "employee_task_management: employee_task_line.assign_date "
            "already gone, nothing to do.")
        return
    cr.execute(
        "ALTER TABLE employee_task_line DROP COLUMN assign_date")
    _logger.info(
        "employee_task_management: dropped employee_task_line.assign_date "
        "(and its NOT NULL constraint).")
