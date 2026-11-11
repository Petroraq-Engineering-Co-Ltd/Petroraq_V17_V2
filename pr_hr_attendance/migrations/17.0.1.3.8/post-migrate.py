import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["hr.attendance"].cron_finalize_daily_attendance_statuses()
    _logger.info(
        "Recomputed stale sentinel worked_hours and finalized daily attendance statuses."
    )

