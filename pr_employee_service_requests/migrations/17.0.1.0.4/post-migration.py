def migrate(cr, version):
    cr.execute(
        """
        UPDATE pr_employee_service_request
           SET moi_fee_amount = requested_amount
         WHERE request_type = 'iqama_renewal'
           AND COALESCE(moi_fee_amount, 0) = 0
           AND COALESCE(mol_fee_amount, 0) = 0
           AND COALESCE(requested_amount, 0) > 0
        """
    )
    cr.execute(
        """
        UPDATE pr_employee_service_request
           SET work_permit_expiry_date = service_expiry_date
         WHERE request_type IN ('iqama_new', 'iqama_renewal')
           AND work_permit_expiry_date IS NULL
        """
    )
