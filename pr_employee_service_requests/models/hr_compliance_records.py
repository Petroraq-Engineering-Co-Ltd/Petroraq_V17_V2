# -*- coding: utf-8 -*-

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .employee_service_request import _open_attachment_preview_action


def _next_from_date(lines):
    to_dates = lines.filtered("to_date").mapped("to_date")
    return max(to_dates) + relativedelta(days=1) if to_dates else False


def _record_attachments(record):
    record.ensure_one()
    return record.env["ir.attachment"].sudo().search([
        ("res_model", "=", record._name),
        ("res_id", "=", record.id),
    ])


class HrEmployeeIqama(models.Model):
    _inherit = "hr.employee.iqama"

    attachment_count = fields.Integer(string="Attachments", compute="_compute_attachment_count")

    @staticmethod
    def _is_saudi_country(country):
        return bool(
            country
            and (
                (country.code or "").upper() == "SA"
                or ("is_homeland" in country._fields and country.is_homeland)
                or (country.name or "").strip().casefold()
                in ("saudi", "saudi arabia", "kingdom of saudi arabia")
            )
        )

    @api.constrains("employee_id")
    def _check_not_saudi_employee(self):
        for rec in self:
            if rec._is_saudi_country(rec.employee_id.country_id):
                raise ValidationError(_("Saudi employees do not require Iqama/Work Permit records."))

    @api.depends("message_ids")
    def _compute_attachment_count(self):
        for rec in self:
            rec.attachment_count = len(_record_attachments(rec))

    def action_view_attachments(self):
        self.ensure_one()
        return _open_attachment_preview_action(
            self,
            _record_attachments(self),
            _("Attachments - %s") % self.display_name,
        )

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

    attachment_count = fields.Integer(string="Attachments", compute="_compute_attachment_count")

    @api.depends("message_ids")
    def _compute_attachment_count(self):
        for rec in self:
            rec.attachment_count = len(_record_attachments(rec))

    def action_view_attachments(self):
        self.ensure_one()
        return _open_attachment_preview_action(
            self,
            _record_attachments(self),
            _("Attachments - %s") % self.display_name,
        )

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

    attachment_count = fields.Integer(string="Attachments", compute="_compute_attachment_count")

    @api.depends("message_ids")
    def _compute_attachment_count(self):
        for rec in self:
            rec.attachment_count = len(_record_attachments(rec))

    def action_view_attachments(self):
        self.ensure_one()
        return _open_attachment_preview_action(
            self,
            _record_attachments(self),
            _("Attachments - %s") % self.display_name,
        )

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
