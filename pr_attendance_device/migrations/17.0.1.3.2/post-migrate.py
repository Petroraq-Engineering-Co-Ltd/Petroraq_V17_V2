import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    repaired_count = env['user.attendance']._repair_desynced_checkouts()
    _logger.info(
        'Repaired %s desynced biometric checkout record(s) from user.attendance.',
        repaired_count,
    )

