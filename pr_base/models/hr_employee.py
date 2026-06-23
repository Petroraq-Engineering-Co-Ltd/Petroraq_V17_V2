# -*- coding: utf-8 -*-

import re

from odoo import api, models, _
from odoo.exceptions import ValidationError


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    def _pr_normalize_employee_id(self, value):
        return re.sub(r"[^0-9A-Z]", "", (value or "").upper())

    @api.constrains("identification_id", "active")
    def _check_identification_id_required_unique(self):
        for employee in self:
            if not employee.active:
                continue

            identification = employee._pr_normalize_employee_id(employee.identification_id)

            if not identification:
                raise ValidationError(_("Identification No is required for employees."))

            duplicate = self.search([
                ("id", "!=", employee.id),
                ("active", "=", True),
                ("identification_id", "!=", False),
            ]).filtered(
                lambda emp: emp._pr_normalize_employee_id(emp.identification_id) == identification
            )[:1]

            if duplicate:
                raise ValidationError(_(
                    "Identification No '%(id_no)s' is already used by employee '%(employee)s'."
                ) % {
                                          "id_no": employee.identification_id,
                                          "employee": duplicate.name,
                                      })
