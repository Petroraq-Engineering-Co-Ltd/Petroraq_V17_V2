import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    sheet_count = env[
        "attendance.sheet"
    ]._repair_non_etm_saturday_results()
    _logger.info(
        "Restored %s open non-ETM Saturday attendance sheet(s) from their "
        "configured working calendars.",
        sheet_count,
    )
