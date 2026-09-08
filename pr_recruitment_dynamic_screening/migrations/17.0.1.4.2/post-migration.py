def migrate(cr, version):
    cr.execute(
        """
        UPDATE hr_applicant_refuse_reason AS reason
           SET template_id = template.res_id
          FROM ir_model_data AS reason_data,
               ir_model_data AS template
         WHERE reason_data.module = 'pr_recruitment_dynamic_screening'
           AND reason_data.name = 'refuse_reason_automatic_screening'
           AND reason_data.model = 'hr.applicant.refuse.reason'
           AND reason.id = reason_data.res_id
           AND template.module = 'pr_hr_recruitment'
           AND template.name = 'email_template_applicant_rejection'
           AND template.model = 'mail.template'
           AND reason.template_id IS NULL
        """
    )
