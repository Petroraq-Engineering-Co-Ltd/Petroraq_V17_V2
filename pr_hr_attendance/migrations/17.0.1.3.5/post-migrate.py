import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    attendance_count = env[
        "hr.attendance"
    ]._repair_etm_saturday_attendance_statuses()
    sheet_count = env[
        "attendance.sheet"
    ]._repair_etm_saturday_off_results()
    _logger.info(
        "Repaired %s Saturday attendance record(s) and %s open attendance sheet(s) "
        "under the ETM enforcement-date policy.",
        attendance_count,
        sheet_count,
    )
