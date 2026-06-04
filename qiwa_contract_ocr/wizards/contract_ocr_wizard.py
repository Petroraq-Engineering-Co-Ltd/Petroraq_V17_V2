from odoo import _, fields, models
from odoo.exceptions import UserError


class ContractOcrWizard(models.TransientModel):
    _name = 'contract.ocr.wizard'
    _description = 'Upload Qiwa Contract for OCR'

    applicant_id = fields.Many2one('hr.applicant', string='Applicant', readonly=True)
    pdf_file = fields.Binary('Upload Qiwa PDF Contract')
    filename = fields.Char('Filename')

    def action_process_pdf(self):
        """Process uploaded PDF and create the employee/contract from Qiwa data."""
        self.ensure_one()
        if not self.pdf_file:
            raise UserError(_('Please upload a Qiwa PDF contract.'))

        processor = self.env['qiwa.contract.processor'].create({
            'name': self.filename or _('Qiwa Contract'),
            'applicant_id': self.applicant_id.id,
            'pdf_file': self.pdf_file,
            'filename': self.filename,
        })
        return processor.action_process_contract()
