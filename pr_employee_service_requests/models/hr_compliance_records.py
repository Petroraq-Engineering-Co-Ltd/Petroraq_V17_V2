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
        work_permit = self.env["hr.work.permit"].sudo().search([
            ("employee_id", "=", self.employee_id.id),
        ], order="id desc", limit=1)
        next_from_date = _next_from_date(self.iqama_line_ids)
        return self.employee_id._open_employee_compliance_request(
            "iqama_renewal",
            _("Iqama & Work Permit Renewal Request"),
            {
                "default_iqama_id": self.id,
                "default_work_permit_id": work_permit.id if work_permit else False,
                "default_iqama_no": self.identification_id,
                "default_place_of_issue": self.place_of_issue or False,
                "default_service_from_date": next_from_date,
                "default_service_expiry_date": self.expiry_date,
                "default_visa_number": work_permit.visa_number if work_permit else False,
                "default_iqama_profession": work_permit.iqama_profession if work_permit else self.employee_id.job_id.name,
                "default_issue_date": next_from_date,
                "default_work_permit_expiry_date": (
                    work_permit.work_permit_expiry_date if work_permit else False
                ),
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


class HrWorkPermit(models.Model):
    _inherit = "hr.work.permit"

    def action_renew(self):
        self.ensure_one()
        iqama = self.env["hr.employee.iqama"].sudo().search([
            ("employee_id", "=", self.employee_id.id),
        ], order="id desc", limit=1)
        next_from_date = (
            iqama.expiry_date + relativedelta(days=1)
            if iqama and iqama.expiry_date
            else False
        )
        return self.employee_id._open_employee_compliance_request(
            "iqama_renewal",
            _("Iqama & Work Permit Renewal Request"),
            {
                "default_work_permit_id": self.id,
                "default_iqama_id": iqama.id if iqama else False,
                "default_iqama_no": iqama.identification_id if iqama else self.employee_id.identification_id,
                "default_visa_number": self.visa_number,
                "default_iqama_profession": self.iqama_profession,
                "default_issue_date": next_from_date,
                "default_service_from_date": next_from_date,
                "default_service_expiry_date": self.iqama_expiry_date,
                "default_work_permit_expiry_date": self.work_permit_expiry_date,
            },
        )
