import logging

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    count = env["attendance.sheet"]._repair_non_etm_saturday_results()
    logging.getLogger(__name__).info("Rebuilt %s non-ETM Saturday attendance sheet(s).", count)
