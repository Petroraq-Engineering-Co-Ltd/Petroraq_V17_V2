# -*- coding: utf-8 -*-
"""Bug 3: gaps in the task list reference numbers.

The sequence used the "standard" implementation, i.e. a real PostgreSQL
sequence. A PostgreSQL sequence is NOT rolled back when the surrounding
transaction fails, so every save that was rejected by a validation burned
a number and left holes such as PEC-TL-2026-00004 -> PEC-TL-2026-00007.

Switching to "no_gap" allocates the number inside the transaction, so a
rejected save gives the number back.

The sequence record sits in a noupdate="1" data block, so a plain module
upgrade does not touch it - hence this migration. Because the "standard"
implementation keeps the counter in the PostgreSQL sequence and NOT in
ir_sequence.number_next, the counter is first re-seeded from the highest
reference that actually exists in the data, so numbering continues where
it left off instead of restarting.
"""
import logging
import re

_logger = logging.getLogger(__name__)

REF_RE = re.compile(r'^PEC-TL-(\d{4})-(\d+)$')


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        SELECT s.id
          FROM ir_sequence s
          JOIN ir_model_data d
            ON d.model = 'ir.sequence' AND d.res_id = s.id
         WHERE d.module = 'employee_task_management'
           AND d.name = 'seq_employee_task_list'
    """)
    row = cr.fetchone()
    if not row:
        _logger.warning(
            "employee_task_management: task list sequence not found, "
            "nothing to migrate.")
        return
    seq_id = row[0]

    # 1. Highest reference actually used, per year.
    cr.execute("SELECT name FROM employee_task_list WHERE name IS NOT NULL")
    highest_per_year = {}
    for (name,) in cr.fetchall():
        match = REF_RE.match(name or '')
        if not match:
            continue
        year, number = match.group(1), int(match.group(2))
        if number > highest_per_year.get(year, 0):
            highest_per_year[year] = number

    # 2. Re-seed the per-year date ranges of this sequence.
    cr.execute("""
        SELECT id, date_from
          FROM ir_sequence_date_range
         WHERE sequence_id = %s
    """, (seq_id,))
    for range_id, date_from in cr.fetchall():
        year = str(date_from.year)
        if year in highest_per_year:
            cr.execute(
                "UPDATE ir_sequence_date_range SET number_next = %s "
                "WHERE id = %s",
                (highest_per_year[year] + 1, range_id))
            _logger.info(
                "employee_task_management: sequence range %s re-seeded "
                "to %s", year, highest_per_year[year] + 1)

    # 3. Re-seed the parent counter too (used if no range matches).
    if highest_per_year:
        cr.execute(
            "UPDATE ir_sequence SET number_next = %s WHERE id = %s",
            (max(highest_per_year.values()) + 1, seq_id))

    # 4. Finally switch the implementation.
    cr.execute(
        "UPDATE ir_sequence SET implementation = 'no_gap' WHERE id = %s",
        (seq_id,))
    _logger.info(
        "employee_task_management: task list sequence switched to no_gap.")
