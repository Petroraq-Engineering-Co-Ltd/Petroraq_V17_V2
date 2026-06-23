# -*- coding: utf-8 -*-

from dateutil.relativedelta import relativedelta

from odoo import _, models


def _next_from_date(lines):
    to_dates = lines.filtered("to_date").mapped("to_date")
    return max(to_dates) + relativedelta(days=1) if to_dates else False


class HrEmployeeIqama(models.Model):
    _inherit = "hr.employee.iqama"

    def action_renew(self):
        self.ensure_one()
        return self.employee_id._open_employee_compliance_request(
            "iqama_renewal",
            _("Iqama Renewal Request"),
            {
                "default_iqama_id": self.id,
                "default_iqama_no": self.identification_id,
                "default_place_of_issue": self.place_of_issue or False,
                "default_service_from_date": _next_from_date(self.iqama_line_ids),
                "default_service_expiry_date": self.expiry_date,
            },
        )


class HrEmployeeMedicalInsurance(models.Model):
    _inherit = "hr.employee.medical.insurance"

    def action_renew(self):
        self.ensure_one()
        return self.employee_id._open_employee_compliance_request(
            "medical_insurance_renewal",
            _("Medical Insurance Renewal Request"),
            {
                "default_insurance_id": self.id,
                "default_iqama_no": self.identification_id,
                "default_insurance_company": self.insurance_company,
                "default_insurance_category": self.insurance_category,
                "default_service_from_date": _next_from_date(self.insurance_line_ids),
                "default_service_expiry_date": self.expiry_date,
            },
        )
