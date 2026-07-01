# -*- coding: utf-8 -*-

from odoo import _, fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    work_permit_count = fields.Integer(
        string="Work Permits",
        compute="_compute_work_permit_count",
    )

    def _compute_iqama_count(self):
        for employee in self:
            employee.iqama_count = self.env["hr.employee.iqama"].sudo().search_count([
                ("employee_id", "=", employee.id),
            ])

    def _compute_insurance_count(self):
        for employee in self:
            employee.insurance_count = self.env["hr.employee.medical.insurance"].sudo().search_count([
                ("employee_id", "=", employee.id),
            ])

    def _compute_work_permit_count(self):
        for employee in self:
            employee.work_permit_count = self.env["hr.work.permit"].sudo().search_count([
                ("employee_id", "=", employee.id),
            ])

    def _open_employee_compliance_request(self, request_type, title, extra_context=None):
        self.ensure_one()
        context = {
            "default_request_type": request_type,
            "default_employee_id": self.id,
            "default_company_id": self.company_id.id or self.env.company.id,
            "default_iqama_no": self.identification_id or False,
        }
        if request_type in ("iqama_new", "iqama_renewal"):
            context["default_iqama_profession"] = self.job_id.name or False
        if extra_context:
            context.update(extra_context)
        return {
            "type": "ir.actions.act_window",
            "name": title,
            "res_model": "pr.employee.service.request",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "current",
            "context": context,
        }

    def open_related_iqamas(self):
        self.ensure_one()
        iqamas = self.env["hr.employee.iqama"].sudo().search([
            ("employee_id", "=", self.id),
        ])
        if not iqamas:
            return self._open_employee_compliance_request(
                "iqama_new",
                _("New Iqama & Work Permit Request"),
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("%s Iqama & Work Permit") % self.name,
            "res_model": "hr.employee.iqama",
            "view_mode": "tree,form",
            "views": [
                [self.env.ref("pr_hr.hr_employee_iqama_view_tree").id, "tree"],
                [self.env.ref("pr_hr.hr_employee_iqama_view_form").id, "form"],
            ],
            "domain": [("employee_id", "=", self.id)],
            "context": {"default_employee_id": self.id},
        }

    def open_related_insurance(self):
        self.ensure_one()
        insurance = self.env["hr.employee.medical.insurance"].sudo().search([
            ("employee_id", "=", self.id),
        ])
        if not insurance:
            return self._open_employee_compliance_request(
                "medical_insurance_new",
                _("New Medical Insurance Request"),
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("%s Medical Insurance") % self.name,
            "res_model": "hr.employee.medical.insurance",
            "view_mode": "tree,form",
            "views": [
                [self.env.ref("pr_hr.hr_employee_medical_insurance_view_tree").id, "tree"],
                [self.env.ref("pr_hr.hr_employee_medical_insurance_view_form").id, "form"],
            ],
            "domain": [("employee_id", "=", self.id)],
            "context": {"default_employee_id": self.id},
        }

    def open_related_work_permits(self):
        """Compatibility redirect: Work Permit is managed by the Iqama flow."""
        return self.open_related_iqamas()
