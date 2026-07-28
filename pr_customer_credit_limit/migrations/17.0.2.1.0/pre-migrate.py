def migrate(cr, version):
    """Consolidate legacy request classifications into the active workflow."""
    cr.execute(
        """
        UPDATE pr_customer_credit_limit_request
           SET request_type = 'revision'
         WHERE request_type IN ('increase', 'decrease', 'temporary')
        """
    )
