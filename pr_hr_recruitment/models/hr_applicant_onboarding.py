from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class HrApplicantOnboarding(models.Model):
    _name = 'hr.applicant.onboarding'
    _description = 'HR Applicant Onboarding'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = "id"

    # region [Fields]

    name = fields.Char(string='Applicant Name', required=True)
    employee_id = fields.Many2one("hr.employee", string="Employee")
    applicant_id = fields.Many2one("hr.applicant", string="Applicant")
    work_permit_id = fields.Many2one("hr.work.permit", string="Work Permit", readonly=True)
    hire_type = fields.Selection(
        [('local', 'Local'), ('overseas', 'Overseas')],
        string='Hire Type', default="local", required=True,
    )
    checklist_ids = fields.One2many("hr.applicant.onboarding.checklist", "applicant_onboarding_id", string="Checklists")
    state = fields.Selection(
        [
            ('initialize', 'Initialized'),
            ('checklist', 'Checklist'),
            ('work_permit', 'Work Permit'),
            ('completed', 'Onboarded'),
        ],
        string='Status', default="initialize",
    )

    # endregion [Fields]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._mark_onboarded_after_employee_created()
        return records

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get("skip_onboarding_completion") and "employee_id" in vals:
            self._mark_onboarded_after_employee_created()
        return res

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

    def _mark_onboarded_after_employee_created(self):
        records = self.filtered(lambda rec: rec.employee_id and rec.state != "completed")
        if records:
            records.with_context(
                skip_onboarding_completion=True,
                skip_onboarding_auto_tasks=True,
            ).write({"state": "completed"})

    def _is_saudi_employee(self):
        self.ensure_one()
        return self._is_saudi_country(self.employee_id.country_id)

    def _is_saudi_applicant_or_employee(self):
        self.ensure_one()
        if self.employee_id and self._is_saudi_employee():
            return True
        applicant = self.applicant_id
        if applicant and hasattr(applicant, "_get_applicant_country"):
            return self._is_saudi_country(applicant._get_applicant_country())
        return False

    def generate_checklist(self):
        for rec in self:
            checklist_items = []
            # Generate checklist items based on hire type
            if rec._is_saudi_applicant_or_employee():
                checklist_items += [
                    (0, 0, {"checklist_item": "National ID Copy"}),
                    (0, 0, {"checklist_item": "Education Certificates"}),
                    (0, 0, {"checklist_item": "SCE Registration (if engineer)"}),
                    (0, 0, {"checklist_item": "GOSI Certificate"}),
                ]
            elif rec.hire_type == 'local':
                checklist_items += [
                    (0, 0, {"checklist_item": "Passport Copy"}),
                    (0, 0, {"checklist_item": "Iqama Copy"}),
                    (0, 0, {"checklist_item": "Education Certificates"}),
                    (0, 0, {"checklist_item": "SCE Registration (if engineer)"}),
                    (0, 0, {"checklist_item": "GOSI Certificate (if Saudi)"}),
                    (0, 0, {"checklist_item": "Transfer Request for Local"}),
                    (0, 0, {"checklist_item": "Previous Employer Release Letter (if transfer)"})
                ]
            elif rec.hire_type == 'overseas':
                checklist_items += [
                    (0, 0, {"checklist_item": "Passport Copy"}),
                    (0, 0, {"checklist_item": "Education Certificates"}),
                    (0, 0, {"checklist_item": "Work Permit"})
                ]
            if checklist_items:
                if rec.checklist_ids:
                    rec.checklist_ids.unlink()
                    rec.checklist_ids = checklist_items
                else:
                    rec.checklist_ids = checklist_items
            if rec.state != "completed":
                rec.state = "checklist"

    def action_generate_work_permit(self):
        self.ensure_one()
        if self._is_saudi_employee():
            raise UserError(_("Saudi employees do not require Iqama/Work Permit records."))
        view = self.env.ref("pr_hr_recruitment.hr_work_permit_form_view")
        return {
            'name': "Work Permit",
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'hr.work.permit',
            "views": [[view.id, "form"]],
            "context": {
                'default_applicant_onboarding_id': self.id,
                'default_employee_id': self.employee_id.id,
                'default_name': self.name,
                        },
            'target': 'current',
        }

    def open_applicant_id_view_form(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Applicant'),
            'res_model': 'hr.applicant',
            'view_type': 'form',
            'view_mode': 'form',
            'res_id': self.applicant_id.id,
        }

    def open_work_permit_id_view_form(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Work Permit'),
            'res_model': 'hr.work.permit',
            'view_type': 'form',
            'view_mode': 'form',
            'res_id': self.work_permit_id.id,
        }

    def unlink(self):
        if self.state != 'initialize':
            raise ValidationError("You Can Not Delete This Applicant Onboarding !!")
        return super().unlink()


class HrApplicantOnboardingChecklist(models.Model):
    _name = 'hr.applicant.onboarding.checklist'
    _description = 'HR Applicant Onboarding Checklist'

    applicant_onboarding_id = fields.Many2one("hr.applicant.onboarding", string="Application Onboarding")
    checklist_item = fields.Char(string='Checklist Item', required=True)
    is_completed = fields.Boolean(string='Completed', default=False)
    file_attachment = fields.Binary(string='Attachment', attachment=True, required=False)
    attachment_file_name = fields.Char(string='File Name', required=False)

    def action_preview_attachment(self):
        self.ensure_one()
        attachment = self.env["ir.attachment"].sudo().search([
            ("res_model", "=", self._name),
            ("res_id", "=", self.id),
            ("res_field", "=", "file_attachment"),
        ], limit=1)
        if not attachment:
            raise UserError(_("Please upload an attachment first."))
        return attachment.action_preview_inline()
