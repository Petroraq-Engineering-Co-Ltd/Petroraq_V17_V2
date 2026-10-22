import logging

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    count = env["hr.task.attendance.day"]._repair_non_etm_absences()
    logging.getLogger(__name__).info("Restored %s non-ETM task absence day(s).", count)
