def migrate(cr, version):
    cr.execute(
        """
        UPDATE pr_employee_service_request
           SET request_type = CASE request_type
               WHEN 'work_permit_new' THEN 'iqama_new'
               WHEN 'work_permit_renewal' THEN 'iqama_renewal'
               ELSE request_type
           END
         WHERE request_type IN ('work_permit_new', 'work_permit_renewal')
        """
    )
