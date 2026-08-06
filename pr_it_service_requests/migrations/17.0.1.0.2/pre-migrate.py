import logging


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Allow multiple approvers to share an approval sequence.

    Removing an entry from ``_sql_constraints`` does not reliably remove the
    existing PostgreSQL constraint on an upgraded database, so drop both old
    sequence-uniqueness constraints explicitly.
    """
    constraints = (
        ("pr_it_request_type_approver", "it_type_approver_sequence_unique"),
        ("pr_it_service_request_approver", "it_request_approver_sequence_unique"),
    )
    for table, constraint in constraints:
        cr.execute(
            'ALTER TABLE "%s" DROP CONSTRAINT IF EXISTS "%s"' % (table, constraint)
        )
        _logger.info("Dropped obsolete IT approval constraint %s on %s", constraint, table)
