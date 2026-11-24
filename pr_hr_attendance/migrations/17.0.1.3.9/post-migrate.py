import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    count = env["hr.attendance"]._repair_scheduled_off_day_statuses()
    _logger.info(
        "Cleared the absence of %s attendance record(s) on scheduled off days.",
        count,
    )
