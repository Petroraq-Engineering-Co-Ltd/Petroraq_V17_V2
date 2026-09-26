from odoo import models, fields, api, _
from odoo.tools import date_utils
from odoo.osv import expression
from dateutil.relativedelta import relativedelta
from odoo.exceptions import ValidationError
import re
import json
import math
from random import randint
import logging
from datetime import datetime, timedelta
import pandas as pd


_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    """
    """
    # region [Initial]
    _inherit = 'hr.employee'
    # endregion [Initial]

    # region [Fields]

    compute_attendance = fields.Boolean(string="Check Attendance")

    allow_gosi_recovery = fields.Boolean(
        string="Allow GOSI",
        help="Only relevant for archived (terminated) employees. When enabled, this "
             "employee is still included in attendance sheet batch generation after "
             "being archived, so post-termination GOSI recovery can keep being "
             "processed for them.",
    )

    # endregion [Fields]

