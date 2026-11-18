import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.attendance'].cron_finalize_daily_attendance_statuses()
    _logger.info('Refreshed attendance worked hours and daily statuses after pr_hr_custom upgrade.')

