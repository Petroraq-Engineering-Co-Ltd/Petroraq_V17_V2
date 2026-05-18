from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


CONTRACT_SIGNED_STAGE_KEYWORDS = (
    'contract signed',
    'signed contract',
    'signed offer',
    'accepted offer',
)


class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    qiwa_contract_processor_id = fields.Many2one(
        'qiwa.contract.processor',
        string='Qiwa Contract OCR',
        copy=False,
        readonly=True,
    )
    show_load_qiwa_contract = fields.Boolean(
        compute='_compute_show_load_qiwa_contract',
        string='Show Load Qiwa Contract',
    )

    def _get_qiwa_created_employee(self):
        self.ensure_one()
        employee = self.env['hr.employee']
        if self.qiwa_contract_processor_id.employee_id:
            return self.qiwa_contract_processor_id.employee_id
        if 'emp_id' in self._fields and self.emp_id:
            return self.emp_id
        if 'employee_id' in self._fields and self.employee_id:
            return self.employee_id
        if self.applicant_onboarding_id.employee_id:
            return self.applicant_onboarding_id.employee_id
        return employee

    def _stage_is_contract_signed(self):
        self.ensure_one()
        stage = self.stage_id
        if not stage:
            return False
        if stage.hired_stage:
            return True
        stage_name = (stage.name or '').casefold()
        return any(keyword in stage_name for keyword in CONTRACT_SIGNED_STAGE_KEYWORDS)

    @api.depends(
        'stage_id',
        'stage_id.hired_stage',
        'qiwa_contract_processor_id',
        'qiwa_contract_processor_id.employee_id',
        'applicant_onboarding_id',
        'applicant_onboarding_id.employee_id',
    )
    def _compute_show_load_qiwa_contract(self):
        for rec in self:
            rec.show_load_qiwa_contract = bool(
                rec.active
                and rec._stage_is_contract_signed()
                and not rec._get_qiwa_created_employee()
            )

    def action_load_qiwa_contract(self):
        self.ensure_one()
        view = self.env.ref('qiwa_contract_ocr.view_contract_ocr_wizard_form')
        return {
            'name': _('Load Qiwa Contract'),
            'type': 'ir.actions.act_window',
            'res_model': 'contract.ocr.wizard',
            'view_mode': 'form',
            'views': [(view.id, 'form')],
            'target': 'new',
            'context': {
                'default_applicant_id': self.id,
                'default_filename': self._get_qiwa_default_filename(),
            },
        }

    def create_employee_from_applicant(self):
        """Use Qiwa OCR instead of creating an empty employee from the applicant."""
        self.ensure_one()
        return self.action_load_qiwa_contract()

    def _get_qiwa_default_filename(self):
        self.ensure_one()
        candidate_name = self.partner_name or self.name or _('Applicant')
        return _('Qiwa Contract - %s.pdf') % candidate_name

    def action_open_qiwa_contract_processor(self):
        self.ensure_one()
        if not self.qiwa_contract_processor_id:
            raise UserError(_('No Qiwa contract has been loaded for this applicant yet.'))
        return self.qiwa_contract_processor_id.action_open_processor()

    @api.constrains('stage_id')
    def _check_stage_to_generate_onboarding(self):
        """
        Keep the recruitment stage sequence guard from pr_hr_recruitment, but
        stop creating a blank employee when the hired/contract-signed stage is
        reached. The Qiwa processor creates the employee after extracting the
        signed contract.
        """
        for rec in self:
            old_stage = rec.last_stage_id
            new_stage = rec.stage_id
            if old_stage and new_stage and new_stage.sequence != 0:
                next_stage = rec._get_next_recruitment_stage(from_stage=old_stage)
                if new_stage != next_stage:
                    raise ValidationError(
                        _('You can not go to this step directly, please forward the rules')
                    )
