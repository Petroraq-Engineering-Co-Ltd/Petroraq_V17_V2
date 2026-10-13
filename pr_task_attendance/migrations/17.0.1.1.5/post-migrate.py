import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    count = env["hr.task.attendance.day"]._repair_pre_enforcement_absences()
    _logger.info("Restored %s pre-enforcement ETM absence day(s).", count)
