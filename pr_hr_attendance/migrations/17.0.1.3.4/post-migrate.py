import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    count = env["attendance.sheet"]._repair_pre_enforcement_saturday_results()
    _logger.info("Restored %s pre-enforcement Saturday attendance sheet(s).", count)
